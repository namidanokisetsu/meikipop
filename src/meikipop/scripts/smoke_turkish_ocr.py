"""Actual-model local OCR smoke, with networking blocked throughout inference."""
import socket
from time import perf_counter
from unittest.mock import patch


def main():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    from meikipop.ocr.turkish_paddle import LocalOCR, hit_word
    from meikipop.scripts.turkish import print_json

    image = Image.new("RGB", (850, 100), "white")
    text = "Bugün çocuklar kitap okuyor."
    ImageDraw.Draw(image).text((15, 20), text, font=ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 32), fill="black")
    with patch.object(socket.socket, "connect", side_effect=AssertionError("Runtime network access")), \
            patch.object(socket, "create_connection", side_effect=AssertionError("Runtime network access")):
        ocr = LocalOCR()
        result = ocr.engine.predict(np.array(image)[:, :, ::-1].copy())[0]
        assert result["rec_texts"] == [text], result["rec_texts"]
        words, boxes = result["text_word"][0], result["text_word_boxes"][0]
        index = words.index("kitap")
        left, top, right, bottom = boxes[index]
        hit = hit_word(result, ((left + right) / 2, (top + bottom) / 2))
        assert hit == (text, text.index("kitap")), hit
        assert hit_word(result, (840, 90)) is None
        pixels = np.array(image)[:, :, ::-1].copy()
        started = perf_counter()
        assert ocr.lookup_point(pixels, ((left + right) / 2, (top + bottom) / 2)) == hit
        recognition_ms = (perf_counter() - started) * 1000
        started = perf_counter()
        offset = 0
        for word, (left, top, right, bottom) in zip(words, boxes):
            offset = text.index(word, offset)
            cached = ocr.lookup_point(pixels, ((left + right) / 2, (top + bottom) / 2))
            assert cached == (text, offset), cached
            offset += len(word)
        cached_hover_ms = (perf_counter() - started) * 1000 / len(words)
    print_json({"offline": True, "text": text, "target": "kitap", "offset": hit[1],
                "recognition_ms": round(recognition_ms, 2), "cached_hover_ms": round(cached_hover_ms, 2)})


if __name__ == "__main__":
    main()
