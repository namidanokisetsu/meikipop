"""Archive-owned dictionary images, isolated from file and network resources."""
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re

IMAGE_URI = re.compile(r"meikipop-image:/([a-z]{2,3}(?:-[a-z0-9]{2,8})*-[0-9a-f]{64})/([0-9a-f]{64}\.png)")
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".avif", ".bmp"}


def assets_ready(metadata, directory, pack):
    if metadata.get("media_version") != "1" or metadata.get("image_failures", "0") != "0":
        return False
    try:
        filenames = json.loads(metadata["image_files"])
    except (KeyError, ValueError, TypeError):
        return False
    return (isinstance(filenames, list) and len(filenames) == int(metadata.get("images", 0))
            and all(isinstance(name, str) and re.fullmatch(r"[0-9a-f]{64}\.png", name)
                    and resolve_image(directory, f"meikipop-image:/{pack}/{name}") for name in filenames))


def resolve_image(directory, uri):
    match = IMAGE_URI.fullmatch(str(uri))
    if not match:
        return None
    root = Path(directory).resolve()
    candidate = (root / (match[1] + ".assets") / match[2]).resolve()
    return candidate if candidate.is_relative_to(root) and candidate.is_file() else None


class ArchiveImages:
    def __init__(self, archive, staging, pack, cancelled=None):
        self.archive, self.staging, self.pack = archive, Path(staging), pack
        self.imported = {}
        self.requested = set()
        self.cancelled = cancelled

    def prepare(self, node):
        if isinstance(node, list):
            for child in node:
                self.prepare(child)
        elif isinstance(node, dict):
            if node.get("tag") == "img" or node.get("type") == "image":
                self._image(node)
            self.prepare(node.get("content"))

    def _image(self, node):
        if self.cancelled and self.cancelled():
            raise InterruptedError("Dictionary import cancelled.")
        source = node.get("path")
        if not isinstance(source, str):
            return
        path = PurePosixPath(source)
        if (path.is_absolute() or ".." in path.parts or "\\" in source or ":" in source
                or path.suffix.lower() not in IMAGE_SUFFIXES):
            return
        self.requested.add(source)
        if source not in self.imported:
            from PIL import Image
            try:
                info = self.archive.getinfo(source)
                if info.file_size > 20 * 1024 * 1024:
                    return
                with Image.open(io.BytesIO(self.archive.read(source))) as image:
                    if image.width * image.height > 40_000_000:
                        return
                    image.thumbnail((1280, 4096))
                    filename = hashlib.sha256(source.encode("utf-8")).hexdigest() + ".png"
                    image.convert("RGBA").save(self.staging / filename)
                    self.imported[source] = (filename, image.width, image.height)
            except (OSError, ValueError, KeyError, Image.DecompressionBombError):
                return
        filename, width, height = self.imported[source]
        node["path"] = f"meikipop-image:/{self.pack}/{filename}"
        node["width"], node["height"] = width, height
