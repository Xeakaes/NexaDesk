"""Chat file attachments: images become data-URIs, text files are inlined."""

from __future__ import annotations

import base64
import io
from dataclasses import dataclass
from pathlib import Path

MAX_TEXT_BYTES = 200 * 1024
# B34: bound both the file size (read_bytes loads the whole file) and the
# decoded dimensions (a 100MP screenshot would blow up the request payload).
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_IMAGE_DIM = 2048
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
TEXT_SUFFIXES = {".txt", ".md", ".py", ".json", ".csv", ".log", ".yml", ".yaml", ".toml", ".ini", ".cfg", ".sh", ".js", ".ts", ".html", ".css"}


class AttachmentError(ValueError):
    pass


@dataclass
class Attachment:
    name: str
    kind: str  # "image" | "text"
    data_uri: str | None = None
    content: str | None = None


def _encode_image(path: Path) -> str:
    """Load, downscale if needed, and encode as a PNG data-URI."""
    from PIL import Image

    with Image.open(path) as img:
        img.load()
        if max(img.size) > MAX_IMAGE_DIM:
            img.thumbnail((MAX_IMAGE_DIM, MAX_IMAGE_DIM))
        buf = io.BytesIO()
        # Always re-encode as PNG: after a thumbnail the source format's
        # compression settings no longer apply, and PNG is universally
        # decodable by vision providers.
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}"


def load_attachment(path: Path) -> Attachment:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        if path.stat().st_size > MAX_IMAGE_BYTES:
            raise AttachmentError(
                f"{path.name}: image too large (max {MAX_IMAGE_BYTES // (1024 * 1024)}MB)"
            )
        try:
            data_uri = _encode_image(path)
        except Exception as exc:  # noqa: BLE001 — any decode failure is user-facing
            raise AttachmentError(f"{path.name}: cannot read image ({exc})") from exc
        return Attachment(
            name=path.name,
            kind="image",
            data_uri=data_uri,
        )
    if suffix in TEXT_SUFFIXES:
        if path.stat().st_size > MAX_TEXT_BYTES:
            raise AttachmentError(f"{path.name}: text file too large (max 200KB)")
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise AttachmentError(f"{path.name}: not valid UTF-8 text") from exc
        return Attachment(name=path.name, kind="text", content=content)
    raise AttachmentError(f"{path.name}: unsupported file type ({suffix or 'no extension'})")


def build_user_payload(text: str, attachments: list[Attachment]) -> tuple[str, list[str]]:
    """Return (final_prompt_text, image_data_uris) for the user turn."""
    images = [a.data_uri for a in attachments if a.kind == "image" and a.data_uri]
    parts = [text] if text else []
    for att in attachments:
        if att.kind == "text" and att.content is not None:
            parts.append(f"--- {att.name} ---\n{att.content}")
    return "\n\n".join(parts), images
