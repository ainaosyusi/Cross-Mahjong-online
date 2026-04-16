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
            log.warning("Vision API クライアント初期化失敗: %s", e)

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
        # 全単語を座標つきで収集
        words = []
        for page in annotation.pages:
            for block in page.blocks:
                for paragraph in block.paragraphs:
                    for word in paragraph.words:
                        text = "".join(sym.text for sym in word.symbols).strip()
                        if not text:
                            continue
                        xs = [v.x for v in word.bounding_box.vertices]
                        ys = [v.y for v in word.bounding_box.vertices]
                        words.append({
                            "text": text,
                            "cx": sum(xs) / 4,
                            "cy": sum(ys) / 4,
                            "top": min(ys),
                            "bottom": max(ys),
                            "left": min(xs),
                            "right": max(xs),
                            "height": max(ys) - min(ys),
                        })

        if not words:
            return None

        # デバッグログ
        log.info("=== OCR検出テキスト一覧 ===")
        for w in sorted(words, key=lambda w: (w["cy"], w["cx"])):
            log.info("  [y=%d x=%d] %r", int(w["cy"]), int(w["cx"]), w["text"])

        # 順位ラベル 1位/2位/3位/4位 を検出
        rank_anchors: dict[int, dict] = {}
        for w in words:
            m = re.match(r"^([1-4])位$", w["text"])
            if m:
                r = int(m.group(1))
                if r not in rank_anchors:
                    rank_anchors[r] = w

        # 単独の "1"〜"4" のみで「位」が別単語の場合もケア
        if len(rank_anchors) < 4:
            for w in words:
                if w["text"] in ("1", "2", "3", "4"):
                    r = int(w["text"])
                    # 近くに "位" があるか
                    for w2 in words:
                        if w2["text"] == "位" and abs(w2["cy"] - w["cy"]) < w["height"] and 0 < w2["left"] - w["right"] < 30:
                            if r not in rank_anchors:
                                rank_anchors[r] = w
                            break

        log.info("検出した順位ラベル: %s", sorted(rank_anchors.keys()))

        if len(rank_anchors) < 3:
            log.warning("順位ラベルが3つ未満")
            return None

        # 各行の高さを推定（順位ラベル間の縦距離から）
        ys_sorted = sorted(rank_anchors.values(), key=lambda w: w["cy"])
        if len(ys_sorted) >= 2:
            gaps = [ys_sorted[i+1]["cy"] - ys_sorted[i]["cy"] for i in range(len(ys_sorted) - 1)]
            avg_gap = sum(gaps) / len(gaps)
        else:
            avg_gap = 80
        # 行のY許容は隣接順位間隔の 0.4 倍
        y_tolerance = max(20, avg_gap * 0.4)
        log.info("Y許容=%d (avg_gap=%d)", int(y_tolerance), int(avg_gap))

        # 各順位について行を抽出
        players = []
        for rank in sorted(rank_anchors.keys()):
            anchor = rank_anchors[rank]
            row_y = anchor["cy"]

            row_words = []
            for w in words:
                if abs(w["cy"] - row_y) > y_tolerance:
                    continue
                if w["left"] < anchor["left"] - 10:
                    continue
                # 順位ラベル自身と "位" 単体を除外
                if re.match(r"^[1-4]位?$", w["text"]):
                    continue
                row_words.append(w)

            row_words.sort(key=lambda w: w["cx"])

            # テキストを結合してパース
            row_text_raw = [w["text"] for w in row_words]
            log.info("行%d 生データ: %s", rank, row_text_raw)

            # スコア（3〜6桁の整数）とポイント（+/-と小数）を検出
            score = 0
            point = 0.0
            name_parts = []

            # 先にポイント（小数）を左から探す
            point_idx = -1
            for i, w in enumerate(row_words):
                t = w["text"].replace(",", "").replace(" ", "").replace("+", "+").replace("−", "-").replace("－", "-")
                # ポイント候補: 符号付き/なしの小数
                if re.fullmatch(r"[+\-]?\d+\.\d+", t):
                    try:
                        point = float(t)
                        point_idx = i
                        break
                    except ValueError:
                        pass

            # スコア（ポイントより前の3〜6桁整数）を探す
            score_idx = -1
            for i, w in enumerate(row_words):
                if point_idx >= 0 and i >= point_idx:
                    break
                t = w["text"].replace(",", "").replace(" ", "")
                if re.fullmatch(r"-?\d{3,6}", t):
                    # プレイヤー名に含まれる数字ではないよう、十分大きい値のみ
                    try:
                        v = int(t)
                        if abs(v) >= 100:  # 100点以上をスコアと見なす
                            score = v
                            score_idx = i
                            break
                    except ValueError:
                        pass

            # 名前候補 = スコアより前の非数字テキスト
            for i, w in enumerate(row_words):
                if score_idx >= 0 and i >= score_idx:
                    break
                t = w["text"]
                # 明らかに名前でないものを除外
                if t in ("自家", "家", "白", "自", "0", "PT"):
                    continue
                if re.fullmatch(r"[×x]\s*\d+", t):  # "x0" のようなカウンタ
                    continue
                if re.fullmatch(r"[+\-]?\d+", t):  # 単なる整数
                    continue
                if re.fullmatch(r"PT|pt", t):
                    continue
                # 末尾の ":" "：" を除去
                t = t.rstrip(":：").strip()
                if t:
                    name_parts.append(t)

            player_name = "".join(name_parts) if name_parts else f"Player{rank}"

            log.info("行%d 解析結果: 名前=%r スコア=%d ポイント=%.1f", rank, player_name, score, point)

            players.append(PlayerResult(
                player_name=player_name,
                rank=rank,
                score=score,
                point=point,
            ))

        if len(players) < 3:
            return None

        log.info("OCR認識成功: %d人", len(players))
        return ResultData(match_id=None, players=players)
