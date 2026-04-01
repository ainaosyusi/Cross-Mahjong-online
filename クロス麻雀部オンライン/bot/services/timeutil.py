from datetime import datetime
from zoneinfo import ZoneInfo

import config

_jst = ZoneInfo(config.TZ_JST)


def now_jst() -> datetime:
    return datetime.now(_jst)


def is_active() -> bool:
    """23:00〜翌6:00 の間は True"""
    hour = now_jst().hour
    # 23時以降 or 6時より前
    return hour >= config.ACTIVE_START_HOUR or hour < config.ACTIVE_END_HOUR


INACTIVE_MESSAGE = "⏳ 受付時間外です（23:00〜6:00）"
