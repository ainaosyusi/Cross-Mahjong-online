import logging
import re
from dataclasses import dataclass

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
    雀魂の結果画面を Google Cloud Vision API で認識する。

    認識する情報:
    - 順位（1〜4位）
    - プレイヤー名
    - 素点
    - ポイント（ウマ込み）
    """

    def __init__(self):
        self._client = None
        self._available = False
        try:
            from google.cloud import vision
            self._client = vision.ImageAnnotatorClient()
            self._available = True
            log.info("Google Cloud Vision クライアント初期化完了")
        except Exception as e:
            log.warning("Vision API クライアント初期化失敗（手動入力にフォールバック）: %s", e)

    def recognize(self, image_bytes: bytes) -> ResultData | None:
        if not self._available:
            return None

        try:
            from google.cloud import vision
            image = vision.Image(content=image_bytes)
            response = self._client.document_text_detection(image=image)

            if response.error.message:
                log.warning("Vision API エラー: %s", response.error.message)
                return None

            annotation = response.full_text_annotation
            if not annotation or not annotation.pages:
                log.warning("テキストが検出されませんでした")
                return None

            return self._parse(annotation)

        except Exception:
            log.exception("画像認識中にエラー")
            return None

    def _parse(self, annotation) -> ResultData | None:
        """
        Vision API の結果から順位・名前・スコアを抽出する。

        雀魂の終局画面のレイアウト（各プレイヤー行）:
          [1位] [アバター] プレイヤー名   49100  +39.1
        """
        # 全単語を収集（位置情報付き）
        words = []
        for page in annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        text = "".join(sym.text for sym in word.symbols)
                        xs = [v.x for v in word.bounding_box.vertices]
                        ys = [v.y for v in word.bounding_box.vertices]
                        words.append({
                            "text": text,
                            "x": sum(xs) / len(xs),
                            "y": sum(ys) / len(ys),
                            "left": min(xs),
                            "right": max(xs),
                        })

        if not words:
            return None

        # 順位ラベル（1位、2位、3位、4位）を検出
        rank_words = {}
        for w in words:
            for rank in (1, 2, 3, 4):
                if f"{rank}位" in w["text"] or w["text"] == str(rank):
                    # "1位" 単体、もしくは "1" に続く "位" のパターンもケア
                    rank_words.setdefault(rank, w)

        # 見つからない場合は正規表現で探す
        if len(rank_words) < 4:
            for w in words:
                m = re.match(r"([1-4])位$", w["text"])
                if m:
                    r = int(m.group(1))
                    rank_words.setdefault(r, w)

        if len(rank_words) < 3:
            log.warning("順位ラベルが検出できませんでした: %s", list(rank_words.keys()))
            return None

        # 各順位の行をまとめる
        players = []
        sorted_ranks = sorted(rank_words.keys())
        for rank in sorted_ranks:
            anchor = rank_words[rank]
            row_y = anchor["y"]

            # 同じ行にある単語を収集（Y座標が近い & 順位ラベルより右）
            y_tolerance = 40  # 行の高さ許容
            row_words = [
                w for w in words
                if abs(w["y"] - row_y) < y_tolerance and w["left"] >= anchor["left"] - 5
            ]
            # 同じ順位ラベルは除外
            row_words = [w for w in row_words if w is not anchor and not re.match(r"^[1-4]位?$", w["text"])]
            # X座標でソート
            row_words.sort(key=lambda w: w["x"])

            # スコア（5桁の数字、例: 49100）を見つける
            score = 0
            point = 0.0
            name_candidates = []

            for w in row_words:
                t = w["text"].replace(",", "").replace(" ", "")
                # スコア判定: 3〜6桁の整数
                if re.match(r"^-?\d{3,6}$", t) and score == 0:
                    try:
                        score = int(t)
                        continue
                    except ValueError:
                        pass
                # ポイント判定: +/-付きの小数
                m = re.match(r"^([+-])?(\d+(?:\.\d+)?)$", t)
                if m and "." in t:
                    sign = -1 if m.group(1) == "-" else 1
                    try:
                        point = sign * float(m.group(2))
                        continue
                    except ValueError:
                        pass
                # 残りは名前候補（数字・記号のみは除外）
                if t and not re.match(r"^[\d\-+\.,%PT位家白自]+$", t):
                    name_candidates.append(t)

            player_name = "".join(name_candidates) if name_candidates else f"Player{rank}"

            players.append(PlayerResult(
                player_name=player_name,
                rank=rank,
                score=score,
                point=point,
            ))

        # 4人分揃わない場合も、3人分揃っていれば3人戦として扱う
        if len(players) < 3:
            log.warning("プレイヤーが3人未満: %d人", len(players))
            return None

        log.info("OCR認識成功: %d人", len(players))
        for p in players:
            log.info("  %d位 %s 素点=%d ポイント=%.1f", p.rank, p.player_name, p.score, p.point)

        return ResultData(match_id=None, players=players)
