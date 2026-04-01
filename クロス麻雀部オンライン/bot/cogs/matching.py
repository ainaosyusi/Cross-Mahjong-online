import logging

import discord
from discord import app_commands
from discord.ext import commands

import config
from database import queries
from services.queue import QueueService

log = logging.getLogger("matching")


class MatchingView(discord.ui.View):
    def __init__(self, cog: "MatchingCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="4人戦に参加", style=discord.ButtonStyle.primary, custom_id="join_4")
    async def join_4(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_join(interaction, "4")

    @discord.ui.button(label="3人戦に参加", style=discord.ButtonStyle.primary, custom_id="join_3")
    async def join_3(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_join(interaction, "3")

    @discord.ui.button(label="両方に参加", style=discord.ButtonStyle.success, custom_id="join_both")
    async def join_both(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_join(interaction, "both")

    @discord.ui.button(label="参加取消", style=discord.ButtonStyle.secondary, custom_id="cancel")
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.handle_cancel(interaction)


class MatchingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.queue = QueueService()
        self.recruitment_message: discord.Message | None = None

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(MatchingView(self))

    async def start_recruitment(self) -> None:
        channel = self.bot.get_channel(config.MATCHING_CHANNEL_ID)
        if channel is None:
            log.error("マッチングチャンネルが見つかりません: %s", config.MATCHING_CHANNEL_ID)
            return

        self.queue.clear()
        embed = self._build_embed()
        view = MatchingView(self)
        self.recruitment_message = await channel.send(embed=embed, view=view)
        log.info("募集開始")

    async def handle_join(self, interaction: discord.Interaction, entry_type: str) -> None:
        user = interaction.user
        if self.queue.is_in_queue(user.id):
            self.queue.remove(user.id)

        self.queue.add(user.id, entry_type)
        await queries.upsert_member(str(user.id), user.display_name)

        labels = {"4": "4人戦", "3": "3人戦", "both": "両方"}
        await interaction.response.send_message(
            f"{labels[entry_type]}に参加登録しました。", ephemeral=True
        )
        await self._update_display()
        await self._try_match(interaction.channel)

    async def handle_cancel(self, interaction: discord.Interaction) -> None:
        user = interaction.user
        if not self.queue.is_in_queue(user.id):
            await interaction.response.send_message("参加登録されていません。", ephemeral=True)
            return

        self.queue.remove(user.id)
        await interaction.response.send_message("参加を取り消しました。", ephemeral=True)
        await self._update_display()

    async def _try_match(self, channel) -> None:
        # 4人戦優先
        selected = self.queue.try_match_4()
        if selected:
            group_cog = self.bot.get_cog("GroupCog")
            if group_cog:
                await group_cog.create_match_group(selected, config.MATCH_TYPE_4)
            await self._update_display()
            await self._try_match(channel)
            return

        # 3人戦
        selected = self.queue.try_match_3()
        if selected:
            group_cog = self.bot.get_cog("GroupCog")
            if group_cog:
                await group_cog.create_match_group(selected, config.MATCH_TYPE_3)
            await self._update_display()
            await self._try_match(channel)

    async def _update_display(self) -> None:
        if self.recruitment_message is None:
            return
        try:
            embed = self._build_embed()
            await self.recruitment_message.edit(embed=embed)
        except discord.NotFound:
            self.recruitment_message = None

    def _build_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="🀄 本日の麻雀部 開催中！",
            color=discord.Color.green(),
        )
        embed.add_field(
            name="待機状況",
            value=(
                f"4人戦：**{self.queue.count_4()}人** 待機中\n"
                f"3人戦：**{self.queue.count_3()}人** 待機中"
            ),
            inline=False,
        )
        return embed

    @app_commands.command(name="start_matching", description="手動で募集を開始します")
    @app_commands.checks.has_permissions(administrator=True)
    async def start_matching_command(self, interaction: discord.Interaction):
        await interaction.response.send_message("募集を開始します。", ephemeral=True)
        await self.start_recruitment()

    @app_commands.command(name="stop_matching", description="募集を停止します")
    @app_commands.checks.has_permissions(administrator=True)
    async def stop_matching_command(self, interaction: discord.Interaction):
        self.queue.clear()
        if self.recruitment_message:
            try:
                embed = discord.Embed(
                    title="🀄 本日の募集は終了しました",
                    color=discord.Color.greyple(),
                )
                await self.recruitment_message.edit(embed=embed, view=None)
            except discord.NotFound:
                pass
            self.recruitment_message = None
        await interaction.response.send_message("募集を停止しました。", ephemeral=True)
        log.info("募集停止")


async def setup(bot: commands.Bot):
    await bot.add_cog(MatchingCog(bot))
