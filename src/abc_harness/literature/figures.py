"""Figures of a paper: what the HTML lists, and the facts about an image the harness needs.

The model sees a figure as an image; the harness only needs its format and
size, to send it to the API and to estimate its token cost. Both come from the
file header, so no imaging library is needed.
"""

from __future__ import annotations

import math
import re
import struct
from dataclasses import asdict, dataclass, field
from typing import Any

# Image formats the Claude API accepts, keyed by their file signature.
SIGNATURES = {b"\x89PNG\r\n\x1a\n": "image/png", b"\xff\xd8\xff": "image/jpeg", b"GIF87a": "image/gif",
              b"GIF89a": "image/gif"}  # fmt: skip
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif", "image/webp": "webp"}
# The API scales an image down until its long edge fits, and charges about width * height / 750 tokens.
MAX_EDGE = 1568
TOKENS_PER_PIXEL = 1 / 750
UNKNOWN_IMAGE_TOKENS = 1600
FIGURE_LABEL = re.compile(r"^\s*(Figure|Fig\.)\s*(\d+[a-z]?)", re.IGNORECASE)


@dataclass
class Figure:
    """One figure as the paper's HTML lists it. `label` is how the paper names it, e.g. "Figure 1"."""

    label: str
    caption: str
    images: list[str] = field(default_factory=list)  # absolute image URLs, one per panel
    line: int = 0  # the caption's line in the saved full text

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def label_from_caption(caption: str, index: int) -> str:
    match = FIGURE_LABEL.match(caption)
    return f"Figure {match.group(2)}" if match else f"Figure (unnumbered {index})"


def slug(label: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")


def media_type(data: bytes) -> str | None:
    """The API media type of an image, or None for formats the API refuses (SVG, PDF, ...)."""
    for signature, kind in SIGNATURES.items():
        if data.startswith(signature):
            return kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def image_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from the header of a PNG, GIF, or JPEG; None if unknown."""
    kind = media_type(data)
    if kind == "image/png" and len(data) >= 24:
        return struct.unpack(">II", data[16:24])
    if kind == "image/gif" and len(data) >= 10:
        return struct.unpack("<HH", data[6:10])
    if kind == "image/jpeg":
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            length = struct.unpack(">H", data[i + 2 : i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                height, width = struct.unpack(">HH", data[i + 5 : i + 9])
                return width, height
            i += 2 + length
    return None


def image_tokens(data: bytes) -> int:
    size = image_size(data)
    if size is None:
        return UNKNOWN_IMAGE_TOKENS
    width, height = size
    scale = min(1.0, MAX_EDGE / max(width, height, 1))
    return math.ceil(width * scale * height * scale * TOKENS_PER_PIXEL)
