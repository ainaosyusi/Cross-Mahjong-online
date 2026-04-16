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

    アプローチ: スコア（3〜6桁整数）の位置を基準に順位を決定。
    名前は各スコアと同じ行の非数字テキストから構築。
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

            return self._parse(annotation, response.full_text_annotation)

        except Exception:
            log.exception("画像認識中にエラー")
            return None

    def _parse(self, annotation, _unused=None) -> ResultData | None:
        # 全単語を座標つきで収集
        words = []
        img_width = 0
        img_height = 0
        for page in annotation.pages:
            img_width = max(img_width, page.width)
            img_height = max(img_height, page.height)
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
                            "width": max(xs) - min(xs),
                            "height": max(ys) - min(ys),
                        })

        if not words:
            return None

        # 画像サイズ推定（ページ情報がない場合は単語の範囲から）
        if img_width == 0:
            img_width = max(w["right"] for w in words)
        if img_height == 0:
            img_height = max(w["bottom"] for w in words)

        log.info("画像サイズ: %dx%d 単語数=%d", img_width, img_height, len(words))

        # 1. スコア候補を抽出: 3〜6桁の整数で、画像の右半分以降、かつ文字が大きい（他の数字と区別）
        score_candidates = []
        right_threshold = img_width * 0.3  # 左30%は除外
        for w in words:
            t = w["text"].replace(",", "").replace(" ", "")
            if not re.fullmatch(r"-?\d{3,6}", t):
                continue
            if w["left"] < right_threshold:
                continue
            try:
                v = int(t)
            except ValueError:
                continue
            # 0点や小さすぎる数字（確率表示など）を除外
            if abs(v) < 100:
                continue
            score_candidates.append({**w, "value": v})

        log.info("スコア候補: %s", [(c["value"], int(c["cy"])) for c in score_candidates])

        # スコアは大きい文字サイズのはず → height で上位4つに絞る
        if len(score_candidates) > 4:
            score_candidates.sort(key=lambda w: -w["height"])
            # 高さが比較的大きいもの上位8件に絞ってから、Y順に並べ変え
            score_candidates = score_candidates[:8]

        # Y座標でソートして上から1位～
        score_candidates.sort(key=lambda w: w["cy"])

        # 重複除去: Y座標が近すぎるもの（同じスコアが二重に検出されるケース）
        filtered = []
        for c in score_candidates:
            if filtered and abs(c["cy"] - filtered[-1]["cy"]) < 30:
                continue
            filtered.append(c)
        score_candidates = filtered[:4]

        if len(score_candidates) < 3:
            log.warning("スコア候補が3つ未満: %d個", len(score_candidates))
            return None

        # 各スコアの行の高さ（次のスコアまでの距離の半分）
        if len(score_candidates) >= 2:
            gaps = [score_candidates[i+1]["cy"] - score_candidates[i]["cy"]
                    for i in range(len(score_candidates) - 1)]
            avg_gap = sum(gaps) / len(gaps)
        else:
            avg_gap = 200
        y_tolerance = avg_gap * 0.6  # 行間の60%までを「同じ行」とみなす
        log.info("平均行間=%d Y許容=%d", int(avg_gap), int(y_tolerance))

        players = []
        for rank, score_word in enumerate(score_candidates, start=1):
            row_y = score_word["cy"]

            # 同じ行の単語を収集
            row_words = [
                w for w in words
                if abs(w["cy"] - row_y) <= y_tolerance
            ]
            row_words.sort(key=lambda w: w["cx"])

            # プレイヤー名候補: スコアの左400px以内、かつ非数字テキスト
            # 雀魂のレイアウト: 名前はスコアより上にある
            NAME_MAX_DISTANCE = 400
            name_parts = []
            for w in row_words:
                # スコア以降（右側）は名前ではない
                if w["left"] >= score_word["left"] - 5:
                    continue
                # スコアから遠すぎる（UI要素など）は除外
                distance = score_word["left"] - w["right"]
                if distance > NAME_MAX_DISTANCE:
                    continue
                # スコアより下のテキストは除外（段位マーク、画面下のUI等）
                if w["top"] >= score_word["cy"]:
                    continue
                t = w["text"].strip().rstrip(":：")
                if not t:
                    continue
                # 数字・記号のみ除外
                if re.fullmatch(r"[\d\-+\.,%():：]+", t):
                    continue
                if t in ("位", "自家", "家", "自", "白", "PT", "pt", "RT", "自宅"):
                    continue
                if re.fullmatch(r"[×x]\s*\d+", t):
                    continue
                if re.fullmatch(r"[1-4]", t):
                    continue
                # 1文字の漢字で麻雀用語は除外
                if len(t) == 1 and t in "東西南北中発白萬筒索發家位戰戦":
                    continue
                # 時刻表示（HH:MM）除外
                if re.fullmatch(r"\d{1,2}:\d{2}", t):
                    continue
                # 丸囲み数字（①②③⑦等）やURLの断片は除外
                if re.fullmatch(r"[①-⑳]", t):
                    continue
                name_parts.append((w["cx"], t))

            # X座標でソートして結合
            name_parts.sort()
            player_name = "".join(t for _, t in name_parts) if name_parts else f"Player{rank}"

            # ポイント: スコアより右、符号付き小数
            point = 0.0
            for w in row_words:
                if w["left"] < score_word["right"]:
                    continue
                t = (w["text"].replace(",", "").replace(" ", "")
                     .replace("−", "-").replace("－", "-"))
                if re.fullmatch(r"[+\-]?\d+\.\d+", t):
                    try:
                        point = float(t)
                        break
                    except ValueError:
                        pass

            log.info("%d位: 名前=%r スコア=%d ポイント=%.1f",
                     rank, player_name, score_word["value"], point)

            players.append(PlayerResult(
                player_name=player_name,
                rank=rank,
                score=score_word["value"],
                point=point,
            ))

        if len(players) < 3:
            return None

        log.info("OCR認識成功: %d人", len(players))
        return ResultData(match_id=None, players=players)
