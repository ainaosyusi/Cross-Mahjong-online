import logging

import aiosqlite

from database.models import CREATE_TABLES_SQL

log = logging.getLogger("database")

_db: aiosqlite.Connection | None = None


async def init_db(db_path: str) -> None:
    global _db
    _db = await aiosqlite.connect(db_path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA foreign_keys=ON")

    for sql in CREATE_TABLES_SQL:
        await _db.execute(sql)
    await _db.commit()
    log.info("DB初期化完了: %s", db_path)


async def get_db() -> aiosqlite.Connection:
    if _db is None:
        raise RuntimeError("DB未初期化")
    return _db


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None
        log.info("DB接続を閉じました")
