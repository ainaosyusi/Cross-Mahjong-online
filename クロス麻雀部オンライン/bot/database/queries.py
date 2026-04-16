from datetime import datetime

from database.connection import get_db


async def upsert_member(discord_id: str, display_name: str) -> int:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO members (discord_id, display_name)
        VALUES (?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET display_name = excluded.display_name
        """,
        (discord_id, display_name),
    )
    await db.commit()
    async with db.execute(
        "SELECT id FROM members WHERE discord_id = ?", (discord_id,)
    ) as cur:
        row = await cur.fetchone()
        return row["id"]


async def create_match(match_type: int) -> int:
    db = await get_db()
    async with db.execute(
        "INSERT INTO matches (match_type, status) VALUES (?, 'playing')",
        (match_type,),
    ) as cur:
        match_id = cur.lastrowid
    await db.commit()
    return match_id


async def update_match_channel_ids(
    match_id: int, thread_id: str, voice_channel_id: str
) -> None:
    db = await get_db()
    await db.execute(
        "UPDATE matches SET thread_id = ?, voice_channel_id = ? WHERE id = ?",
        (thread_id, voice_channel_id, match_id),
    )
    await db.commit()


async def add_match_player(match_id: int, member_id: int) -> None:
    db = await get_db()
    await db.execute(
        "INSERT OR IGNORE INTO match_players (match_id, member_id) VALUES (?, ?)",
        (match_id, member_id),
    )
    await db.commit()


async def remove_match_player(match_id: int, member_id: int) -> None:
    db = await get_db()
    await db.execute(
        "DELETE FROM match_players WHERE match_id = ? AND member_id = ?",
        (match_id, member_id),
    )
    await db.commit()


async def update_match_status(match_id: int, status: str) -> None:
    db = await get_db()
    finished_at = datetime.utcnow().isoformat() if status in ("finished", "disbanded") else None
    await db.execute(
        "UPDATE matches SET status = ?, finished_at = COALESCE(?, finished_at) WHERE id = ?",
        (status, finished_at, match_id),
    )
    await db.commit()


async def save_match_result(
    match_id: int, member_id: int, rank: int, score: int = 0, point: float = 0.0
) -> None:
    db = await get_db()
    await db.execute(
        """
        INSERT INTO match_results (match_id, member_id, rank, score, point)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(match_id, member_id) DO UPDATE SET
            rank = excluded.rank, score = excluded.score, point = excluded.point
        """,
        (match_id, member_id, rank, score, point),
    )
    await db.commit()


async def get_match_by_thread(thread_id: str) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM matches WHERE thread_id = ?", (thread_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_match_players(match_id: int) -> list[dict]:
    db = await get_db()
    async with db.execute(
        """
        SELECT mp.*, m.discord_id, m.display_name
        FROM match_players mp
        JOIN members m ON m.id = mp.member_id
        WHERE mp.match_id = ?
        """,
        (match_id,),
    ) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def get_member_by_discord_id(discord_id: str) -> dict | None:
    db = await get_db()
    async with db.execute(
        "SELECT * FROM members WHERE discord_id = ?", (discord_id,)
    ) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_ranking(start_date: str | None = None, end_date: str | None = None) -> list[dict]:
    db = await get_db()
    conditions = ["mt.status = 'finished'"]
    params = []
    if start_date:
        conditions.append("mt.finished_at >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("mt.finished_at < ?")
        params.append(end_date)
    where = " AND ".join(conditions)

    sql = f"""
        SELECT
            m.discord_id,
            m.display_name,
            COUNT(*) AS game_count,
            ROUND(AVG(r.rank), 2) AS avg_rank,
            ROUND(SUM(r.point), 1) AS total_point,
            ROUND(AVG(r.point), 1) AS avg_point,
            SUM(r.score) AS total_score,
            ROUND(AVG(r.score), 0) AS avg_score,
            MAX(r.score) AS max_score,
            ROUND(SUM(CASE WHEN r.rank = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS top_rate,
            ROUND(SUM(CASE WHEN r.rank <= 2 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rentai_rate,
            ROUND(SUM(CASE WHEN r.rank = 4 THEN 0 ELSE 1 END) * 100.0 / COUNT(*), 1) AS last_avoid_rate
        FROM match_results r
        JOIN members m ON m.id = r.member_id
        JOIN matches mt ON mt.id = r.match_id
        WHERE {where}
        GROUP BY m.id
        ORDER BY total_point DESC
    """
    async with db.execute(sql, params) as cur:
        return [dict(row) for row in await cur.fetchall()]


async def get_player_stats(
    discord_id: str, start_date: str | None = None, end_date: str | None = None
) -> dict | None:
    db = await get_db()
    conditions = ["mt.status = 'finished'", "m.discord_id = ?"]
    params: list = [discord_id]
    if start_date:
        conditions.append("mt.finished_at >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("mt.finished_at < ?")
        params.append(end_date)
    where = " AND ".join(conditions)

    sql = f"""
        SELECT
            m.discord_id,
            m.display_name,
            COUNT(*) AS game_count,
            ROUND(AVG(r.rank), 2) AS avg_rank,
            ROUND(SUM(r.point), 1) AS total_point,
            ROUND(AVG(r.point), 1) AS avg_point,
            SUM(r.score) AS total_score,
            ROUND(AVG(r.score), 0) AS avg_score,
            MAX(r.score) AS max_score,
            ROUND(SUM(CASE WHEN r.rank = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS top_rate,
            ROUND(SUM(CASE WHEN r.rank <= 2 THEN 1 ELSE 0 END) * 100.0 / COUNT(*), 1) AS rentai_rate,
            ROUND(SUM(CASE WHEN r.rank = 4 THEN 0 ELSE 1 END) * 100.0 / COUNT(*), 1) AS last_avoid_rate
        FROM match_results r
        JOIN members m ON m.id = r.member_id
        JOIN matches mt ON mt.id = r.match_id
        WHERE {where}
        GROUP BY m.id
    """
    async with db.execute(sql, params) as cur:
        row = await cur.fetchone()
        return dict(row) if row else None
