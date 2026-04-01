import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands

from database import queries
from services.timeutil import is_active, INACTIVE_MESSAGE

log = logging.getLogger("ranking")


class PeriodView(discord.ui.View):
    def __init__(self, cog: "RankingCog"):
        super().__init__(timeout=300)
        self.cog = cog

    @discord.ui.button(label="通算", style=discord.ButtonStyle.primary)
    async def all_time(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_ranking(interaction, "all")

    @discord.ui.button(label="今月", style=discord.ButtonStyle.secondary)
    async def this_month(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_ranking(interaction, "monthly")

    @discord.ui.button(label="先月", style=discord.ButtonStyle.secondary)
    async def last_month(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_ranking(interaction, "last_month")


class RankingCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="ranking", description="ランキングを表示します")
    @app_commands.describe(period="期間（monthly: 今月 / all: 通算）")
    @app_commands.choices(period=[
        app_commands.Choice(name="今月", value="monthly"),
        app_commands.Choice(name="通算", value="all"),
    ])
    async def ranking_command(
        self, interaction: discord.Interaction, period: str = "monthly"
    ):
        if not is_active():
            await interaction.response.send_message(INACTIVE_MESSAGE, ephemeral=True)
            return
        await self.show_ranking(interaction, period)

    async def show_ranking(self, interaction: discord.Interaction, period: str) -> None:
        start_date, end_date, title_period = self._get_date_range(period)
        rows = await queries.get_ranking(start_date, end_date)

        if not rows:
            embed = discord.Embed(
                title=f"🏆 {title_period}ランキング",
                description="まだ対戦データがありません。",
                color=discord.Color.greyple(),
            )
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, view=PeriodView(self))
            else:
                await interaction.response.send_message(embed=embed, view=PeriodView(self))
            return

        lines = []
        for i, row in enumerate(rows, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f" {i}")
            lines.append(
                f"{medal}  **{row['display_name']}**　"
                f"対戦数: {row['game_count']}　"
                f"平均順位: {row['avg_rank']}　"
                f"トップ率: {row['top_rate']}%"
            )

        embed = discord.Embed(
            title=f"🏆 {title_period}ランキング",
            description="\n".join(lines),
            color=discord.Color.gold(),
        )

        if interaction.response.is_done():
            await interaction.followup.send(embed=embed, view=PeriodView(self))
        else:
            await interaction.response.send_message(embed=embed, view=PeriodView(self))

    @app_commands.command(name="mystats", description="自分の成績を表示します")
    async def mystats_command(self, interaction: discord.Interaction):
        if not is_active():
            await interaction.response.send_message(INACTIVE_MESSAGE, ephemeral=True)
            return
        stats = await queries.get_player_stats(str(interaction.user.id))

        if stats is None:
            await interaction.response.send_message(
                "まだ対戦データがありません。", ephemeral=True
            )
            return

        embed = discord.Embed(
            title=f"📊 {interaction.user.display_name} の成績",
            color=discord.Color.blue(),
        )
        embed.add_field(name="対戦数", value=str(stats["game_count"]), inline=True)
        embed.add_field(name="平均順位", value=str(stats["avg_rank"]), inline=True)
        embed.add_field(name="総合得点", value=str(stats["total_point"]), inline=True)
        embed.add_field(name="トップ率", value=f"{stats['top_rate']}%", inline=True)
        embed.add_field(name="連対率", value=f"{stats['rentai_rate']}%", inline=True)

        await interaction.response.send_message(embed=embed)

    @staticmethod
    def _get_date_range(period: str) -> tuple[str | None, str | None, str]:
        now = datetime.utcnow()
        if period == "monthly":
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            title = f"{now.year}年{now.month}月"
            return start.isoformat(), None, title
        elif period == "last_month":
            first_this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_month_end = first_this_month
            last_month_start = (first_this_month - timedelta(days=1)).replace(day=1)
            m = last_month_start.month
            y = last_month_start.year
            return last_month_start.isoformat(), last_month_end.isoformat(), f"{y}年{m}月"
        else:
            return None, None, "通算"


async def setup(bot: commands.Bot):
    await bot.add_cog(RankingCog(bot))
