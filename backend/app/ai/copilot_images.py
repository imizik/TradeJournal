"""Images the copilot can see (docs/copilot-lab.md § The copilot can see).

Two kinds reach the model: a screenshot the owner shares from the panel or the
phone's share sheet, and the chart image saved with a pre-trade plan, which the
trade review attaches. Either is decoded to pixels and re-encoded here, so no
metadata (EXIF, GPS, colour profiles, comments) survives and the model never
sees more than a 1568-pixel longest side, the size it reads at full detail.

PyAV (already the transcriber's dependency) does the decoding, scaling and JPEG
encoding; there is no Pillow. A shared screenshot is stored under a random id in
private storage beside the plan captures for 24 hours at most, and deleted as
soon as the turn that sent it ends.
"""
from __future__ import annotations

import base64
import io
import time
import uuid
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from app.engine import captures

ACCEPTED = captures.IMAGE_TYPES  # PNG, JPEG, WebP, by their first bytes
MAX_IN = 8_000_000
MAX_PIXELS = 50_000_000  # a decompression bomb is refused before it is decoded
LONGEST = 1568
JPEG_QSCALE = 3  # ffmpeg's MJPEG scale, about quality 85
MAX_PER_TURN = 2
TTL_S = 24 * 3600
ID = r"^[0-9a-f]{32}$"
_FORMAT = {"image/png": "png_pipe", "image/jpeg": "jpeg_pipe", "image/webp": "webp_pipe"}


class ImageError(ValueError):
    """An image this app cannot use; the message says why."""


@dataclass(frozen=True)
class Image:
    jpeg: bytes
    width: int
    height: int


def _fit(width: int, height: int) -> tuple[int, int]:
    scale = min(1.0, LONGEST / max(width, height))
    return max(1, round(width * scale)), max(1, round(height * scale))


def encode_rgb(pixels) -> Image:
    """An RGB array (height x width x 3, uint8) as a JPEG no larger than ``LONGEST`` on its longest side."""
    import av
    frame = av.VideoFrame.from_ndarray(pixels, format="rgb24")
    width, height = _fit(frame.width, frame.height)
    frame = frame.reformat(width=width, height=height, format="yuvj420p", interpolation="AREA")
    codec = av.CodecContext.create("mjpeg", "w")
    codec.width, codec.height, codec.pix_fmt, codec.time_base = width, height, "yuvj420p", Fraction(1, 1)
    codec.options = {"qmin": str(JPEG_QSCALE), "qmax": str(JPEG_QSCALE), "flags": "+bitexact"}
    jpeg = b"".join(bytes(p) for p in codec.encode(frame)) + b"".join(bytes(p) for p in codec.encode(None))
    return Image(jpeg, width, height)


def process(data: bytes) -> Image:
    """An upload as the model will see it: type checked by its first bytes, size capped, decoded, flattened onto white,
    scaled down and re-encoded. Raises ImageError."""
    import av
    import numpy as np
    if not data:
        raise ImageError("The image is empty.")
    if len(data) > MAX_IN:
        raise ImageError("The image is larger than 8 MB.")
    kind = captures._media_type(data[:16], ACCEPTED)
    if kind is None:
        raise ImageError("The image must be PNG, JPEG or WebP.")
    try:
        with av.open(io.BytesIO(data), format=_FORMAT[kind]) as container:
            stream = container.streams.video[0]
            if (stream.width or 0) * (stream.height or 0) > MAX_PIXELS:
                raise ImageError("The image has too many pixels.")
            frame = next(container.decode(stream))
    except ImageError:
        raise
    except Exception:  # noqa: BLE001 - any decoder failure is an unreadable upload
        raise ImageError("The image could not be read.") from None
    if frame.width * frame.height > MAX_PIXELS:
        raise ImageError("The image has too many pixels.")
    rgba = frame.to_ndarray(format="rgba").astype(np.float32)
    alpha = rgba[..., 3:4] / 255.0
    rgb = (rgba[..., :3] * alpha + 255.0 * (1.0 - alpha)).round().astype(np.uint8)
    return encode_rgb(np.ascontiguousarray(rgb))


def block(jpeg: bytes) -> dict:
    """The Messages API image content block for a processed image."""
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                        "data": base64.b64encode(jpeg).decode("ascii")}}


def mcp_block(image_block: dict) -> dict:
    """The same image as an MCP tool-result block (the Agent SDK's plan backend)."""
    return {"type": "image", "data": image_block["source"]["data"], "mimeType": image_block["source"]["media_type"]}


def size_of(image_block: dict) -> int:
    """The JPEG's size in bytes, from its base64."""
    data = image_block["source"]["data"]
    return len(data) * 3 // 4 - data[-2:].count("=")


# --------------------------------------------------------------------------- shared screenshots

def _root() -> Path:
    return captures.storage_root() / "copilot-images"


def _path(image_id: str) -> Path:
    if len(image_id) != 32 or any(c not in "0123456789abcdef" for c in image_id):
        raise ImageError("That image id is not readable.")
    return _root() / f"{image_id}.jpg"


def purge(now: float | None = None) -> int:
    """Delete shared screenshots older than a day; returns how many."""
    now = time.time() if now is None else now
    gone = 0
    for path in _root().glob("*.jpg") if _root().is_dir() else []:
        try:
            if now - path.stat().st_mtime > TTL_S:
                path.unlink()
                gone += 1
        except FileNotFoundError:
            pass
    return gone


def store(data: bytes) -> dict:
    """Process and keep one shared screenshot: ``{id, width, height, bytes}``. Raises ImageError."""
    image = process(data)
    purge()
    image_id = uuid.uuid4().hex
    captures._write(_path(image_id), image.jpeg)
    return {"id": image_id, "width": image.width, "height": image.height, "bytes": len(image.jpeg)}


def load(image_id: str) -> bytes:
    """A stored screenshot's JPEG; ImageError when it was never stored, was used, or is older than a day."""
    path = _path(image_id)
    try:
        if time.time() - path.stat().st_mtime > TTL_S:
            path.unlink(missing_ok=True)
            raise ImageError("That screenshot has expired; attach it again.")
        return path.read_bytes()
    except FileNotFoundError:
        raise ImageError("That screenshot is no longer stored; attach it again.") from None


def delete(image_id: str) -> None:
    try:
        _path(image_id).unlink(missing_ok=True)
    except (ImageError, OSError):
        pass

