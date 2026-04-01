import logging
from dataclasses import dataclass

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import queries
from services.ocr import OCRService
from services.timeutil import is_active, INACTIVE_MESSAGE

log = logging.getLogger("result")


@dataclass
class PlayerResult:
    discord_id: int | None
    player_name: str
    rank: int
    score: int = 0
    point: float = 0.0


@dataclass
class ResultData:
    match_id: int | None
    players: list[PlayerResult]


class ConfirmView(discord.ui.View):
    def __init__(self, cog: "ResultCog", message_id: int):
        super().__init__(timeout=300)
        self.cog = cog
        self.message_id = message_id

    @discord.ui.button(label="確定", style=discord.ButtonStyle.success, custom_id="confirm_result")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_confirm(interaction, self.message_id)

    @discord.ui.button(label="修正する", style=discord.ButtonStyle.secondary, custom_id="edit_result")
    async def edit(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_edit(interaction)


class ResultCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ocr = OCRService()
        self.pending_results: dict[int, ResultData] = {}

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return
        if message.channel.id != config.RESULT_CHANNEL_ID:
            return
        if not message.attachments:
            return
        if not is_active():
            await message.reply(INACTIVE_MESSAGE)
            return

        # 画像のみ処理
        image_attachment = None
        for att in message.attachments:
            if att.content_type and att.content_type.startswith("image/"):
                image_attachment = att
                break

        if image_attachment is None:
            return

        image_bytes = await image_attachment.read()
        result = self.ocr.recognize(image_bytes)

        if result is None:
            embed = discord.Embed(
                title="⚠️ 画像の認識に失敗しました",
                description=(
                    "手動で結果を入力してください。\n\n"
                    "```\n/result @user1 1 @user2 2 @user3 3 @user4 4\n```"
                ),
                color=discord.Color.orange(),
            )
            await message.reply(embed=embed)
            return

        # 認識結果表示
        lines = []
        for p in result.players:
            lines.append(f"**{p.rank}位**: {p.player_name}")

        embed = discord.Embed(
            title="📊 対戦結果を認識しました",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="この結果で確定しますか？")

        msg = await message.reply(embed=embed, view=ConfirmView(self, 0))
        # message_id を使って pending に保存
        self.pending_results[msg.id] = result
        # View の message_id を更新
        msg_view = ConfirmView(self, msg.id)
        await msg.edit(view=msg_view)

    async def handle_confirm(self, interaction: discord.Interaction, message_id: int) -> None:
        result = self.pending_results.get(message_id)
        if result is None:
            await interaction.response.send_message("この結果は既に処理済みです。", ephemeral=True)
            return

        # DB保存
        for p in result.players:
            if p.discord_id:
                member_id = await queries.upsert_member(str(p.discord_id), p.player_name)
            else:
                member_id = await queries.upsert_member(p.player_name, p.player_name)

            if result.match_id:
                await queries.save_match_result(
                    result.match_id, member_id, p.rank, p.score, p.point
                )

        if result.match_id:
            await queries.update_match_status(result.match_id, "finished")

        del self.pending_results[message_id]

        await interaction.response.send_message("✅ 結果を記録しました。")
        log.info("成績記録: match_id=%s players=%d", result.match_id, len(result.players))

    async def handle_edit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "手動で結果を入力してください。\n\n"
            "```\n/result @user1 1 @user2 2 @user3 3 @user4 4\n```",
            ephemeral=True,
        )

    @app_commands.command(name="result", description="対戦結果を手動入力します")
    @app_commands.describe(
        player1="1位のプレイヤー", player2="2位のプレイヤー",
        player3="3位のプレイヤー", player4="4位のプレイヤー（3人戦の場合は省略）",
    )
    async def result_command(
        self,
        interaction: discord.Interaction,
        player1: discord.Member,
        player2: discord.Member,
        player3: discord.Member,
        player4: discord.Member | None = None,
    ):
        if not is_active():
            await interaction.response.send_message(INACTIVE_MESSAGE, ephemeral=True)
            return
        players = [
            (player1, 1),
            (player2, 2),
            (player3, 3),
        ]
        if player4:
            players.append((player4, 4))

        match_type = 4 if player4 else 3

        # 対戦レコード作成
        match_id = await queries.create_match(match_type)

        for member, rank in players:
            member_id = await queries.upsert_member(str(member.id), member.display_name)
            await queries.add_match_player(match_id, member_id)
            await queries.save_match_result(match_id, member_id, rank)

        await queries.update_match_status(match_id, "finished")

        lines = []
        for member, rank in players:
            lines.append(f"**{rank}位**: {member.display_name}")

        embed = discord.Embed(
            title="✅ 対戦結果を記録しました",
            description="\n".join(lines),
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed)
        log.info("手動成績記録: match_id=%d", match_id)


async def setup(bot: commands.Bot):
    await bot.add_cog(ResultCog(bot))
