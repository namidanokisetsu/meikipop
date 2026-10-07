"""Keep recognized context and lookup offsets together through the OCR pipeline."""
from dataclasses import dataclass
import math
from meikipop.language.profiles import get_profile


@dataclass(frozen=True)
class ContextHit:
    query: str
    text: str
    start: int
    end: int
    language: str = "ja"

    @property
    def sentence(self):
        return sentence_at(self.text, self.start, self.end, self.language)


def sentence_at(text, start, end=None, language="ja"):
    """Return visible sentence and word span; never invent text outside OCR."""
    return get_profile(language).sentence_span(text, start, end)


def _in_character_gap(box, neighbour, point, vertical):
    if neighbour is None:
        return False
    if vertical:
        a = (box.center_y, box.height, box.center_x, box.width)
        b = (neighbour.center_y, neighbour.height, neighbour.center_x, neighbour.width)
        along, across = point[1], point[0]
    else:
        a = (box.center_x, box.width, box.center_y, box.height)
        b = (neighbour.center_x, neighbour.width, neighbour.center_y, neighbour.height)
        along, across = point
    direction = 1 if b[0] > a[0] else -1
    near, far = a[0] + direction * a[1] / 2, b[0] - direction * b[1] / 2
    gap, distance = direction * (far - near), direction * (along - near)
    # Fill the nearer half of a small gap on the same reading line.
    return (0 < gap <= min(a[1], b[1]) / 2 and 0 <= distance <= gap / 2
            and max(a[2] - a[3] / 2, b[2] - b[3] / 2) <= across
            <= min(a[2] + a[3] / 2, b[2] + b[3] / 2))


def hit_paragraphs(paragraphs, point, language="ja"):
    """Use source offsets (including spaces), with interpolation for OCR word boxes."""
    x, y = point
    unspaced = get_profile(language).word_mode == "unspaced"
    for paragraph in paragraphs or ():
        offset = 0
        for index, word in enumerate(paragraph.words):
            # OCR engines can normalize spaces; align against their actual full text.
            start = word.source_start if word.source_start is not None else paragraph.full_text.find(word.text, offset)
            if start < offset or not paragraph.full_text.startswith(word.text, start):
                continue
            offset = start + len(word.text)
            box = word.box
            if not box or not word.text:
                continue
            left, top = box.center_x - box.width / 2, box.center_y - box.height / 2
            inside = left <= x <= left + box.width and top <= y <= top + box.height
            neighbours = (paragraph.words[index - 1] if index else None,
                          paragraph.words[index + 1] if index + 1 < len(paragraph.words) else None)
            if not inside and not (unspaced and any(
                    _in_character_gap(box, other.box, point, paragraph.is_vertical)
                    for other in neighbours if other is not None)):
                continue
            if unspaced:
                fraction = ((y - top) / box.height if paragraph.is_vertical and box.height else
                            (x - left) / box.width if box.width else 0)
                start += min(len(word.text) - 1, max(0, int(fraction * len(word.text))))
                query = paragraph.full_text[start:]
                end = start + 1
            else:
                query = word.text.strip(".,!?;:()[]{}\"“”")
                start += word.text.find(query)
                end = start + len(query)
            if query:
                return ContextHit(query, paragraph.full_text, start, end, language)
    return None


def paddle_lines(results, language="tr"):
    """Rejoin Paddle's ASCII/symbol fragments using original Unicode word spans.

    PaddleX 3.7 get_word_info classifies Turkish accents as symbol runs, so its
    text_word entries are fragments, not lexical words. text_word_boxes contains
    one Nx4 pixel array per recognized line, in the original input image space.
    https://github.com/PaddlePaddle/PaddleX/blob/release/3.7/paddlex/inference/models/text_recognition/processors.py
    """
    for result in results or ():
        lines = ((text, zip(fragments, boxes)) for text, fragments, boxes in
                 zip(result.get("rec_texts", ()), result.get("text_word", ()), result.get("text_word_boxes", ())))
        yield from fragment_lines(lines, language)


def fragment_lines(lines, language="tr"):
    """Reassemble source words from (line_text, [(fragment, pixel_box), ...])."""
    for text, fragments in lines:
        positioned, offset = [], 0
        for fragment, box in fragments:
            if not isinstance(fragment, str) or not fragment:
                continue
            start = text.find(fragment, offset)
            if start < 0:
                continue
            offset = start + len(fragment)
            try:
                left, top, right, bottom = map(float, box)
            except (ValueError, TypeError):
                continue
            if not all(map(math.isfinite, (left, top, right, bottom))) or right <= left or bottom <= top:
                continue
            positioned.append((start, offset, (left, top, right, bottom)))
        words = []
        for start, end in get_profile(language).word_spans(text):
            parts = []
            covered = start
            for first, last, (left, top, right, bottom) in positioned:
                a, b = max(start, first), min(end, last)
                if a >= b:
                    continue
                if a > covered:
                    break
                covered = max(covered, b)
                # A fragment may include punctuation beside an accented letter.
                span = right - left
                parts.append((left + span * (a - first) / (last - first), top,
                              left + span * (b - first) / (last - first), bottom))
            if parts and covered >= end:
                words.append((text[start:end], start, end, _bounds(parts)))
        if words:
            yield text, words


def _bounds(boxes):
    return (min(box[0] for box in boxes), min(box[1] for box in boxes),
            max(box[2] for box in boxes), max(box[3] for box in boxes))


def _paddle_groups(lines):
    """Join close, aligned wrapped lines without crossing columns or large gaps."""
    lines = [(text, words, _bounds([word[3] for word in words])) for text, words in lines]
    groups = []
    for line in sorted(lines, key=lambda row: (row[2][1], row[2][0])):
        left, top, right, bottom = line[2]
        candidates = []
        for group in groups:
            previous = group[-1][2]
            pleft, ptop, pright, pbottom = previous
            height, prior_height = bottom - top, pbottom - ptop
            overlap = min(right, pright) - max(left, pleft)
            if (0.65 <= height / prior_height <= 1.55
                    and top - ptop >= 0.6 * min(height, prior_height)
                    and -0.2 * min(height, prior_height) <= top - pbottom <= 1.1 * max(height, prior_height)
                    and overlap >= 0.5 * min(right - left, pright - pleft)
                    and abs(left - pleft) <= max(2 * height, 0.25 * max(right - left, pright - pleft))):
                candidates.append((abs(top - pbottom) + abs(left - pleft), group))
        if candidates:
            min(candidates, key=lambda pair: pair[0])[1].append(line)
        else:
            groups.append([line])
    return groups


def paddle_paragraphs(results, width, height):
    """Adapt pixel-space fragments into normalized words and visible paragraphs."""
    if width <= 0 or height <= 0:
        raise ValueError("OCR image dimensions must be positive.")
    paragraphs = []
    for result in results or ():
        lines = ((text, zip(fragments, boxes)) for text, fragments, boxes in
                 zip(result.get("rec_texts", ()), result.get("text_word", ()), result.get("text_word_boxes", ())))
        paragraphs.extend(fragment_paragraphs(lines, width, height))
    return paragraphs


def fragment_paragraphs(lines, width, height, language="tr"):
    """Normalize local OCR word/symbol fragments with complete source offsets."""
    from .interface import BoundingBox, Paragraph, Word
    if width <= 0 or height <= 0:
        raise ValueError("OCR image dimensions must be positive.")

    def normalized(box):
        left, top, right, bottom = box
        return BoundingBox((left + right) / (2 * width), (top + bottom) / (2 * height),
                           (right - left) / width, (bottom - top) / height)

    paragraphs = []
    for group in _paddle_groups(fragment_lines(lines, language)):
        items = []
        line_offset = 0
        for text, words, _ in group:
            for index, (word, start, end, box) in enumerate(words):
                next_start = words[index + 1][1] if index + 1 < len(words) else len(text)
                items.append(Word(word, text[end:next_start], normalized(box), line_offset + start))
            line_offset += len(text) + 1
        text = "\n".join(line[0] for line in group)
        paragraphs.append(Paragraph(text, items, normalized(_bounds([line[2] for line in group])), False))
    return paragraphs
