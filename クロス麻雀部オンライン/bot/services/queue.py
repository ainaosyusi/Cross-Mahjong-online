import logging
import random

log = logging.getLogger("queue")


class QueueService:
    def __init__(self):
        self._queue_4: set[int] = set()     # 4人戦のみ
        self._queue_3: set[int] = set()     # 3人戦のみ
        self._queue_both: set[int] = set()  # 両方

    def add(self, user_id: int, entry_type: str) -> None:
        self.remove(user_id)
        if entry_type == "4":
            self._queue_4.add(user_id)
        elif entry_type == "3":
            self._queue_3.add(user_id)
        elif entry_type == "both":
            self._queue_both.add(user_id)
        log.info("キュー追加: user=%s type=%s", user_id, entry_type)

    def remove(self, user_id: int) -> None:
        self._queue_4.discard(user_id)
        self._queue_3.discard(user_id)
        self._queue_both.discard(user_id)

    def remove_users(self, user_ids: list[int]) -> None:
        for uid in user_ids:
            self.remove(uid)

    def get_queue_4(self) -> list[int]:
        return list(self._queue_4 | self._queue_both)

    def get_queue_3(self) -> list[int]:
        return list(self._queue_3 | self._queue_both)

    def count_4(self) -> int:
        return len(self._queue_4) + len(self._queue_both)

    def count_3(self) -> int:
        return len(self._queue_3) + len(self._queue_both)

    def clear(self) -> None:
        self._queue_4.clear()
        self._queue_3.clear()
        self._queue_both.clear()
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
            selected = random.sample(candidates, 4)
            self.remove_users(selected)
            log.info("4人戦マッチング成立: %s", selected)
            return selected
        return None

    def try_match_3(self) -> list[int] | None:
        candidates = self.get_queue_3()
        if len(candidates) >= 3:
            selected = random.sample(candidates, 3)
            self.remove_users(selected)
            log.info("3人戦マッチング成立: %s", selected)
            return selected
        return None
