"""Compact progress for downloads with a known or unknown size."""


def content_length(response):
    try:
        return max(0, int(getattr(response, "headers", {}).get("Content-Length", 0)))
    except (TypeError, ValueError):
        return 0


def download_progress(label, received, size):
    amount = f"{min(100, received * 100 // size)}%" if size else f"{received // (1024 * 1024)} MB"
    return f"Downloading {label} · {amount}"
