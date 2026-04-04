from datetime import datetime
from zoneinfo import ZoneInfo

import config

_jst = ZoneInfo(config.TZ_JST)


def now_jst() -> datetime:
    return datetime.now(_jst)


def is_active() -> bool:
    """20:00〜翌4:00 の間は True"""
    hour = now_jst().hour
    # 20時以降 or 4時より前
    return hour >= config.ACTIVE_START_HOUR or hour < config.ACTIVE_END_HOUR


INACTIVE_MESSAGE = "⏳ 受付時間外です（1部 20:00〜24:00 / 2部 0:00〜4:00）"
