import logging
from dataclasses import dataclass

import cv2
import numpy as np

log = logging.getLogger("ocr")


@dataclass
class PlayerResult:
    player_name: str
    rank: int
    discord_id: int | None = None
    score: int = 0
    point: float = 0.0


@dataclass
class ResultData:
    match_id: int | None
    players: list[PlayerResult]


class OCRService:
    """
    雀魂の結果画面から順位とプレイヤー名を認識する。

    Phase 1: 最小構成（順位 + プレイヤー名のみ）
    - テンプレートマッチングで結果画面を検出
    - 各行のプレイヤー名と順位を OCR で読み取り

    TODO: Phase 2 でスコア・ポイントの読み取りを追加
    """

    def recognize(self, image_bytes: bytes) -> ResultData | None:
        try:
            arr = np.frombuffer(image_bytes, dtype=np.uint8)
            image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if image is None:
                log.warning("画像のデコードに失敗")
                return None

            result = self._try_recognize(image)
            return result

        except Exception:
            log.exception("画像認識中にエラー")
            return None

    def _try_recognize(self, image: np.ndarray) -> ResultData | None:
        """
        雀魂の結果画面を認識する。

        現在は簡易実装（プレースホルダー）。
        実際のテンプレートマッチング・OCR は雀魂の結果画面の
        サンプル画像を元にチューニングが必要。
        """
        # TODO: 実際の認識ロジックを実装
        # 1. グレースケール変換・前処理
        # 2. テンプレートマッチングで結果画面を検出
        # 3. 各行を切り出して順位・名前を OCR
        #
        # 現時点では None を返し、手動入力にフォールバックする
        log.info("画像認識: 未実装のため手動入力にフォールバック")
        return None
