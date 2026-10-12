"""Chat file attachments: images become data-URIs, text files are inlined."""

from __future__ import annotations

import base64
import mimetypes
from dataclasses import dataclass
from pathlib import Path

MAX_TEXT_BYTES = 200 * 1024
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


def load_attachment(path: Path) -> Attachment:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        data = path.read_bytes()
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        return Attachment(
            name=path.name,
            kind="image",
            data_uri=f"data:{mime};base64,{base64.b64encode(data).decode()}",
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
