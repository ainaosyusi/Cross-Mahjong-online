CREATE_TABLES_SQL = [
    """
    CREATE TABLE IF NOT EXISTS members (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        discord_id    TEXT    UNIQUE NOT NULL,
        display_name  TEXT    NOT NULL,
        created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS matches (
        id               INTEGER PRIMARY KEY AUTOINCREMENT,
        match_type       INTEGER NOT NULL,
        status           TEXT    NOT NULL DEFAULT 'waiting',
        thread_id        TEXT,
        voice_channel_id TEXT,
        created_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        finished_at      DATETIME
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_players (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id   INTEGER NOT NULL REFERENCES matches(id),
        member_id  INTEGER NOT NULL REFERENCES members(id),
        joined_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(match_id, member_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS match_results (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id   INTEGER NOT NULL REFERENCES matches(id),
        member_id  INTEGER NOT NULL REFERENCES members(id),
        rank       INTEGER NOT NULL,
        score      INTEGER NOT NULL DEFAULT 0,
        point      REAL    NOT NULL DEFAULT 0.0,
        created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(match_id, member_id)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_members_discord_id ON members(discord_id)",
    "CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(status)",
    "CREATE INDEX IF NOT EXISTS idx_matches_created_at ON matches(created_at)",
    "CREATE INDEX IF NOT EXISTS idx_match_results_member_id ON match_results(member_id)",
    "CREATE INDEX IF NOT EXISTS idx_match_results_member_date ON match_results(member_id, created_at)",
]
