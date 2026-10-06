"""Bounded crop growth for a recognized paragraph clipped by capture edges."""


def expanded_crop(frame, point):
    x, y = frame.point(*point)
    paragraph = next((p for p in frame.paragraphs if any(
        w.box and abs(x - w.box.center_x) <= w.box.width / 2
        and abs(y - w.box.center_y) <= w.box.height / 2 for w in p.words)), None)
    if paragraph is None:
        return None
    boxes = [w.box for w in paragraph.words if w.box]
    left, top, width, height = frame.request.crop
    gx, gy, gw, gh = frame.request.geometry
    px, py = frame.pixel_size or (width, height)
    mx, my = 6 / px, 6 / py
    edges = (any(b.center_x - b.width / 2 <= mx for b in boxes),
             any(b.center_y - b.height / 2 <= my for b in boxes),
             any(b.center_x + b.width / 2 >= 1 - mx for b in boxes),
             any(b.center_y + b.height / 2 >= 1 - my for b in boxes))
    a = max(gx, left - width // 2) if edges[0] else left
    b = max(gy, top - height // 2) if edges[1] else top
    c = min(gx + gw, left + width + width // 2) if edges[2] else left + width
    d = min(gy + gh, top + height + height // 2) if edges[3] else top + height
    # Include the next line when a clipped reading axis may wrap.
    if edges[2] and not paragraph.is_vertical:
        d = min(gy + gh, max(d, top + height + height // 2))
    if edges[3] and paragraph.is_vertical:
        a = max(gx, min(a, left - width // 2))
    crop = (a, b, c - a, d - b)
    return crop if crop != frame.request.crop else None
