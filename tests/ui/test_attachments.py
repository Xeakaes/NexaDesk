import base64

import pytest

from ui.attachments import (
    AttachmentError,
    build_user_payload,
    load_attachment,
)


def test_load_image_returns_data_uri(tmp_path):
    p = tmp_path / "shot.png"
    p.write_bytes(b"\x89PNG fake")
    att = load_attachment(p)
    assert att.kind == "image"
    assert att.data_uri.startswith("data:image/png;base64,")
    raw = base64.b64decode(att.data_uri.split(",", 1)[1])
    assert raw == b"\x89PNG fake"


def test_load_text_returns_content(tmp_path):
    p = tmp_path / "note.md"
    p.write_text("# başlık\niçerik", encoding="utf-8")
    att = load_attachment(p)
    assert att.kind == "text"
    assert "başlık" in att.content


def test_unsupported_extension_raises(tmp_path):
    p = tmp_path / "app.exe"
    p.write_bytes(b"MZ")
    with pytest.raises(AttachmentError):
        load_attachment(p)


def test_oversized_text_raises(tmp_path):
    p = tmp_path / "big.txt"
    p.write_text("x" * (200 * 1024 + 1), encoding="utf-8")
    with pytest.raises(AttachmentError):
        load_attachment(p)


def test_payload_inlines_text_and_collects_images(tmp_path):
    txt = tmp_path / "code.py"
    txt.write_text("print('hi')", encoding="utf-8")
    img = tmp_path / "a.jpg"
    img.write_bytes(b"\xff\xd8fake")
    atts = [load_attachment(txt), load_attachment(img)]
    text, images = build_user_payload("şuna bak", atts)
    assert "code.py" in text and "print('hi')" in text
    assert "şuna bak" in text
    assert len(images) == 1 and images[0].startswith("data:image/jpeg;base64,")


def test_payload_without_attachments_is_plain():
    text, images = build_user_payload("selam", [])
    assert text == "selam"
    assert images == []
