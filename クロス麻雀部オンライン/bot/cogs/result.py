import logging
import re
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


class ResultThreadCreateView(discord.ui.View):
    """#対戦結果に常設する、成績スレッドを手動作成するためのボタン"""

    def __init__(self, cog: "ResultCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="📸 成績スレッドを作成",
        style=discord.ButtonStyle.primary,
        custom_id="create_result_thread",
    )
    async def create(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_create_result_thread(interaction)


class ResultCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ocr = OCRService()
        self.pending_results: dict[int, ResultData] = {}

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(ResultThreadCreateView(self))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        # 対戦結果チャンネル本体、または対戦結果チャンネル配下のスレッド
        is_result_channel = message.channel.id == config.RESULT_CHANNEL_ID
        is_result_thread = (
            isinstance(message.channel, discord.Thread)
            and message.channel.parent_id == config.RESULT_CHANNEL_ID
        )
        if not (is_result_channel or is_result_thread):
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
            score_str = f"  {p.score}" if p.score else ""
            point_str = f"  ({p.point:+.1f})" if p.point else ""
            lines.append(f"**{p.rank}位**: {p.player_name}{score_str}{point_str}")

        embed = discord.Embed(
            title="📊 対戦結果を認識しました",
            description="\n".join(lines),
            color=discord.Color.blue(),
        )
        embed.set_footer(text="この結果で確定しますか？")

        # スレッド内なら通知抑制
        silent = is_result_thread
        msg = await message.reply(embed=embed, view=ConfirmView(self, 0), silent=silent)
        # 結果スレッドの場合、スレッド名から match_id を推測して紐付け
        if is_result_thread:
            m = re.match(r"対戦卓-(\d+)", message.channel.name or "")
            if m:
                result.match_id = int(m.group(1))
        self.pending_results[msg.id] = result
        msg_view = ConfirmView(self, msg.id)
        await msg.edit(view=msg_view)

    async def handle_confirm(self, interaction: discord.Interaction, message_id: int) -> None:
        result = self.pending_results.get(message_id)
        if result is None:
            await interaction.response.send_message("この結果は既に処理済みです。", ephemeral=True)
            return

        # match_idが不明な場合は新規作成
        match_id = result.match_id
        match_type = len(result.players)
        if not match_id:
            match_id = await queries.create_match(match_type)
            log.info("match_id 不明のため新規作成: %d", match_id)

        # DB保存
        for p in result.players:
            # discord_id が不明なので、プレイヤー名をIDとして扱う
            discord_id_key = str(p.discord_id) if p.discord_id else f"ocr:{p.player_name}"
            member_id = await queries.upsert_member(discord_id_key, p.player_name)
            await queries.add_match_player(match_id, member_id)
            await queries.save_match_result(
                match_id, member_id, p.rank, p.score, p.point
            )

        await queries.update_match_status(match_id, "finished")

        del self.pending_results[message_id]

        # 確定ボタン付きメッセージを「記録済み」表示に書き換え（ボタン削除）
        lines = []
        for p in result.players:
            score_str = f"  {p.score}" if p.score else ""
            point_str = f"  ({p.point:+.1f})" if p.point else ""
            lines.append(f"**{p.rank}位**: {p.player_name}{score_str}{point_str}")
        confirmed_embed = discord.Embed(
            title=f"✅ 記録済み (match_id={match_id})",
            description="\n".join(lines),
            color=discord.Color.green(),
        )
        confirmed_embed.set_footer(text="修正は https://mj.kyoten-hub.com/成績修正 から")
        try:
            await interaction.response.edit_message(embed=confirmed_embed, view=None)
        except discord.HTTPException:
            try:
                await interaction.message.edit(embed=confirmed_embed, view=None)
            except discord.HTTPException:
                pass
            try:
                await interaction.response.send_message(
                    f"✅ 結果を記録しました。（match_id={match_id}）", ephemeral=True
                )
            except discord.HTTPException:
                pass

        log.info("成績記録: match_id=%s players=%d", match_id, len(result.players))

    async def handle_edit(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "手動で結果を入力してください。\n\n"
            "```\n/result @user1 1 @user2 2 @user3 3 @user4 4\n```",
            ephemeral=True,
        )

    async def handle_create_result_thread(self, interaction: discord.Interaction) -> None:
        """手動で成績提出用スレッドを作成"""
        result_channel = self.bot.get_channel(config.RESULT_CHANNEL_ID)
        if result_channel is None:
            await interaction.response.send_message(
                "対戦結果チャンネルが見つかりません。", ephemeral=True
            )
            return

        # match_id を新規採番（実対戦との紐付けなしの手動エントリ）
        match_id = await queries.create_match(4)  # 仮で4人戦として作成、後で修正可
        thread_name = f"対戦卓-{match_id:03d} 結果"
        try:
            thread = await result_channel.create_thread(
                name=thread_name,
                type=discord.ChannelType.public_thread,
            )
        except discord.HTTPException as e:
            await interaction.response.send_message(
                f"スレッド作成に失敗しました: {e}", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"📸 {thread_name}",
            description=(
                "対戦結果をここに投稿してください。\n\n"
                "・雀魂の終局画面スクショ → 自動で認識\n"
                "・認識結果に「確定」ボタンで記録\n"
                "・誤認識時は `/result` コマンドで手動入力\n"
                "・修正は [成績修正ページ](https://mj.kyoten-hub.com) から"
            ),
            color=discord.Color.blue(),
        )
        await thread.send(content=f"<@{interaction.user.id}>", embed=embed, silent=True)

        await interaction.response.send_message(
            f"✅ {thread.mention} を作成しました。", ephemeral=True
        )
        log.info("手動スレッド作成: match_id=%d user=%s", match_id, interaction.user.id)

    @app_commands.command(
        name="setup_result_panel", description="[管理者] #対戦結果に成績スレッド作成ボタンを設置します"
    )
    @app_commands.checks.has_permissions(administrator=True)
    async def setup_result_panel(self, interaction: discord.Interaction):
        result_channel = self.bot.get_channel(config.RESULT_CHANNEL_ID)
        if result_channel is None:
            await interaction.response.send_message(
                "対戦結果チャンネルが見つかりません。", ephemeral=True
            )
            return

        embed = discord.Embed(
            title="📸 対戦結果の投稿",
            description=(
                "対戦終了後、下のボタンで個別のスレッドを作成してください。\n"
                "スレッド内に雀魂の終局スクショを投稿すると自動で順位を認識します。"
            ),
            color=discord.Color.blue(),
        )
        await result_channel.send(embed=embed, view=ResultThreadCreateView(self))
        await interaction.response.send_message("✅ 設置しました。", ephemeral=True)

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
