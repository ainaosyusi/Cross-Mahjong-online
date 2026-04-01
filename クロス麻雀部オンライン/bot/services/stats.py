from database import queries


class StatsService:
    @staticmethod
    async def get_ranking(
        start_date: str | None = None, end_date: str | None = None
    ) -> list[dict]:
        return await queries.get_ranking(start_date, end_date)

    @staticmethod
    async def get_player_stats(
        discord_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict | None:
        return await queries.get_player_stats(discord_id, start_date, end_date)
