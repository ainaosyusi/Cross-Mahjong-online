import logging

log = logging.getLogger("queue")


class QueueService:
    def __init__(self):
        self._queue_4: list[int] = []     # 4人戦のみ（参加順）
        self._queue_3: list[int] = []     # 3人戦のみ（参加順）
        self._queue_both: list[int] = []  # 両方（参加順）
        self._names: dict[int, str] = {}  # user_id → 表示名

    def add(self, user_id: int, entry_type: str, display_name: str = "") -> None:
        self.remove(user_id)
        if entry_type == "4":
            self._queue_4.append(user_id)
        elif entry_type == "3":
            self._queue_3.append(user_id)
        elif entry_type == "both":
            self._queue_both.append(user_id)
        if display_name:
            self._names[user_id] = display_name
        log.info("キュー追加: user=%s (%s) type=%s", user_id, display_name, entry_type)

    def remove(self, user_id: int) -> None:
        if user_id in self._queue_4:
            self._queue_4.remove(user_id)
        if user_id in self._queue_3:
            self._queue_3.remove(user_id)
        if user_id in self._queue_both:
            self._queue_both.remove(user_id)
        self._names.pop(user_id, None)

    def remove_users(self, user_ids: list[int]) -> None:
        for uid in user_ids:
            self.remove(uid)

    def get_queue_4(self) -> list[int]:
        """4人戦候補（参加順）"""
        return self._queue_4 + self._queue_both

    def get_queue_3(self) -> list[int]:
        """3人戦候補（参加順）"""
        return self._queue_3 + self._queue_both

    def get_name(self, user_id: int) -> str:
        return self._names.get(user_id, str(user_id))

    def get_all_names(self) -> dict[int, str]:
        """全待機者のID→表示名"""
        return dict(self._names)

    def count_4(self) -> int:
        return len(self._queue_4) + len(self._queue_both)

    def count_3(self) -> int:
        return len(self._queue_3) + len(self._queue_both)

    def clear(self) -> None:
        self._queue_4.clear()
        self._queue_3.clear()
        self._queue_both.clear()
        self._names.clear()
        log.info("キューをクリアしました")

    def is_in_queue(self, user_id: int) -> bool:
        return (
            user_id in self._queue_4
            or user_id in self._queue_3
            or user_id in self._queue_both
        )

    def try_match_4(self) -> list[int] | None:
        candidates = self.get_queue_4()
        if len(candidates) >= 4:
            selected = candidates[:4]  # 早い者順
            self.remove_users(selected)
            log.info("4人戦マッチング成立: %s", selected)
            return selected
        return None

    def try_match_3(self) -> list[int] | None:
        candidates = self.get_queue_3()
        if len(candidates) >= 3:
            selected = candidates[:3]  # 早い者順
            self.remove_users(selected)
            log.info("3人戦マッチング成立: %s", selected)
            return selected
        return None
