import os
from dotenv import load_dotenv

load_dotenv()

# Discord
DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
GUILD_ID: int = int(os.getenv("GUILD_ID", "0"))
MATCHING_CHANNEL_ID: int = int(os.getenv("MATCHING_CHANNEL_ID", "0"))
RESULT_CHANNEL_ID: int = int(os.getenv("RESULT_CHANNEL_ID", "0"))
RANKING_CHANNEL_ID: int = int(os.getenv("RANKING_CHANNEL_ID", "0"))
ANNOUNCE_CHANNEL_ID: int = int(os.getenv("ANNOUNCE_CHANNEL_ID", "0"))

# 稼働時間（JST）
ACTIVE_START_HOUR: int = 20   # 20:00 開始
ACTIVE_END_HOUR: int = 4      # 4:00 終了
TZ_JST = "Asia/Tokyo"

# Matching（2部制）
MATCH_PART1_HOUR: int = 20    # 1部: 20:00 開始
MATCH_PART2_HOUR: int = 0     # 2部: 0:00 開始
MATCH_TYPE_3: int = 3
MATCH_TYPE_4: int = 4

# OCR
OCR_CONFIDENCE_THRESHOLD: float = 0.7

# Database
DB_PATH: str = os.path.join(os.path.dirname(__file__), "data", "mahjong.db")

# Group
WITHDRAW_TIMEOUT: int = 60

# Web Dashboard
WEB_PORT: int = int(os.getenv("WEB_PORT", "8080"))
