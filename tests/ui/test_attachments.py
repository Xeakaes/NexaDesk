import base64

import pytest

from ui.attachments import (
    AttachmentError,
    build_user_payload,
    load_attachment,
)


def _real_png(tmp_path, name="shot.png", size=(32, 32)):
    from PIL import Image

    p = tmp_path / name
    Image.new("RGB", size, (200, 30, 30)).save(p)
    return p


def test_load_image_returns_data_uri(tmp_path):
    p = _real_png(tmp_path)
    att = load_attachment(p)
    assert att.kind == "image"
    assert att.data_uri.startswith("data:image/png;base64,")


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
    img = _real_png(tmp_path, name="a.png")
    atts = [load_attachment(txt), load_attachment(img)]
    text, images = build_user_payload("şuna bak", atts)
    assert "code.py" in text and "print('hi')" in text
    assert "şuna bak" in text
    assert len(images) == 1 and images[0].startswith("data:image/png;base64,")


def test_payload_without_attachments_is_plain():
    text, images = build_user_payload("selam", [])
    assert text == "selam"
    assert images == []


def test_load_image_rejects_oversize_file(tmp_path):
    # B34: an image over the size cap must be rejected up front, not
    # read fully into memory and base64-encoded.
    from ui.attachments import AttachmentError, MAX_IMAGE_BYTES, load_attachment

    p = tmp_path / "huge.png"
    # sparse-ish: write more than the cap without real image content
    with open(p, "wb") as f:
        f.truncate(MAX_IMAGE_BYTES + 1)
    with pytest.raises(AttachmentError, match="too large"):
        load_attachment(p)


def test_load_image_downscales_large_dimensions(tmp_path):
    # B34: a huge-dimension image is downscaled to max 2048px before encoding.
    from PIL import Image

    from ui.attachments import MAX_IMAGE_DIM, load_attachment

    p = tmp_path / "big.png"
    Image.new("RGB", (4000, 1000), (10, 20, 30)).save(p)
    att = load_attachment(p)
    assert att.kind == "image"
    # decode and check dimensions
    import base64 as _b64
    import io as _io

    raw = _b64.b64decode(att.data_uri.split(",", 1)[1])
    img = Image.open(_io.BytesIO(raw))
    assert max(img.size) <= MAX_IMAGE_DIM
