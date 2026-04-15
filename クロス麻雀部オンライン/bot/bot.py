import asyncio
import logging

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database.connection import init_db, close_db
from database import queries

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)-5s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("bot")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)
scheduler = AsyncIOScheduler(timezone="Asia/Tokyo")


@bot.event
async def on_ready():
    log.info("Bot起動: %s (ID: %s)", bot.user.name, bot.user.id)

    await init_db(config.DB_PATH)

    await bot.load_extension("cogs.matching")
    await bot.load_extension("cogs.group")
    await bot.load_extension("cogs.result")
    await bot.load_extension("cogs.ranking")

    # 2部制の募集ジョブ登録
    matching_cog = bot.get_cog("MatchingCog")
    if matching_cog:
        # 1部: 20:00 JST
        scheduler.add_job(
            matching_cog.start_recruitment,
            "cron",
            hour=config.MATCH_PART1_HOUR,
            minute=0,
            id="recruitment_part1",
            replace_existing=True,
            kwargs={"part": 1},
        )
        # 2部: 0:00 JST
        scheduler.add_job(
            matching_cog.start_recruitment,
            "cron",
            hour=config.MATCH_PART2_HOUR,
            minute=0,
            id="recruitment_part2",
            replace_existing=True,
            kwargs={"part": 2},
        )

    # 再起動時の募集復元
    if matching_cog:
        from services.timeutil import is_active
        from cogs.matching import _load_state
        state = _load_state()
        if state:
            try:
                ch = bot.get_channel(state["channel_id"])
                if ch:
                    matching_cog.recruitment_message = await ch.fetch_message(state["message_id"])
                    matching_cog.current_part = state.get("part", matching_cog._detect_current_part())
                    log.info("募集メッセージを復元: %s（%d部）", state["message_id"], matching_cog.current_part)
            except Exception:
                log.warning("募集メッセージの復元に失敗")
                matching_cog.recruitment_message = None

        if matching_cog.recruitment_message is None and is_active():
            part = matching_cog._detect_current_part()
            log.info("稼働時間内のため募集を自動開始（%d部）", part)
            await matching_cog.start_recruitment(part=part)

    # 自動締めジョブ（4:00 JST）
    scheduler.add_job(
        daily_close,
        "cron",
        hour=config.ACTIVE_END_HOUR,
        minute=0,
        id="daily_close",
        replace_existing=True,
    )
    scheduler.start()

    # スラッシュコマンド同期
    guild = discord.Object(id=config.GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    log.info("スラッシュコマンド同期完了")


async def daily_close():
    """4:00 JSTに実行: 本日のサマリーを送信して受付停止"""
    log.info("デイリークローズ開始")

    # マッチング停止
    matching_cog = bot.get_cog("MatchingCog")
    if matching_cog:
        matching_cog.queue.clear()
        if matching_cog.recruitment_message:
            try:
                await matching_cog.recruitment_message.delete()
            except (discord.NotFound, discord.HTTPException):
                pass
            matching_cog.recruitment_message = None
        from cogs.matching import _clear_state
        _clear_state()

    # アクティブなグループを解散
    group_cog = bot.get_cog("GroupCog")
    if group_cog:
        for match_id in list(group_cog.active_matches.keys()):
            await group_cog._disband_match(match_id)

    # 本日のサマリーを #ランキング に投稿
    from services.timeutil import now_jst
    today = now_jst()
    start = today.replace(hour=0, minute=0, second=0).isoformat()
    end = today.replace(hour=23, minute=59, second=59).isoformat()
    ranking = await queries.get_ranking(start, end)

    channel = bot.get_channel(config.RANKING_CHANNEL_ID)
    if channel and ranking:
        lines = []
        for i, row in enumerate(ranking, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(i, f" {i}")
            lines.append(
                f"{medal}  **{row['display_name']}**　"
                f"対戦数: {row['game_count']}　"
                f"平均順位: {row['avg_rank']}"
            )
        embed = discord.Embed(
            title=f"📊 本日の結果（{today.strftime('%Y/%m/%d')}）",
            description="\n".join(lines) if lines else "本日の対戦はありませんでした。",
            color=discord.Color.blue(),
        )
        await channel.send(embed=embed)
    elif channel:
        embed = discord.Embed(
            title=f"📊 本日の結果（{today.strftime('%Y/%m/%d')}）",
            description="本日の対戦はありませんでした。",
            color=discord.Color.greyple(),
        )
        await channel.send(embed=embed)

    log.info("デイリークローズ完了")


@bot.event
async def on_close():
    scheduler.shutdown(wait=False)
    await close_db()


def main():
    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
