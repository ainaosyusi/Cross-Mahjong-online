import asyncio
import logging

import discord
from discord.ext import commands
from apscheduler.schedulers.asyncio import AsyncIOScheduler

import config
from database.connection import init_db, close_db

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

    # 定時募集ジョブ登録
    matching_cog = bot.get_cog("MatchingCog")
    if matching_cog:
        scheduler.add_job(
            matching_cog.start_recruitment,
            "cron",
            hour=config.MATCH_START_HOUR,
            minute=config.MATCH_START_MINUTE,
            id="daily_recruitment",
            replace_existing=True,
        )
    scheduler.start()

    # スラッシュコマンド同期
    guild = discord.Object(id=config.GUILD_ID)
    bot.tree.copy_global_to(guild=guild)
    await bot.tree.sync(guild=guild)
    log.info("スラッシュコマンド同期完了")


@bot.event
async def on_close():
    scheduler.shutdown(wait=False)
    await close_db()


def main():
    bot.run(config.DISCORD_TOKEN)


if __name__ == "__main__":
    main()
