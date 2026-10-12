"""Image-generation client for the F2 avatar pack flow (OpenAI-compatible)."""

import base64
import io
import json

import pytest
import requests
from PIL import Image

from core.providers.image_gen import (
    ImageGenClient,
    ImageGenError,
    decode_image_response,
    is_image_model,
)


@pytest.fixture(autouse=True)
def _telemetry_off(monkeypatch):
    monkeypatch.setenv("NEXADESK_TELEMETRY", "off")


def _png_bytes(color=(255, 0, 0, 255)):
    buf = io.BytesIO()
    Image.new("RGBA", (8, 8), color).save(buf, "PNG")
    return buf.getvalue()


class FakeResponse:
    def __init__(self, payload=None, status_code=200, content=b""):
        self._payload = payload
        self.status_code = status_code
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


class FakeSession:
    """Scripted session: each request pops the next response or exception."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def _next(self):
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def post(self, url, **kw):
        self.calls.append({"method": "post", "url": url, **kw})
        return self._next()

    def get(self, url, **kw):
        self.calls.append({"method": "get", "url": url, **kw})
        return self._next()


def test_is_image_model_markers():
    assert is_image_model("gpt-image-1")
    assert is_image_model("black-forest-labs/flux-1-dev")
    assert is_image_model("dall-e-3")
    assert not is_image_model("llama-3.3-70b-versatile")


def test_generate_with_photo_uses_edits_multipart(tmp_path):
    png = _png_bytes()
    photo = tmp_path / "ref.png"
    photo.write_bytes(png)
    session = FakeSession([
        FakeResponse({"data": [{"b64_json": base64.b64encode(png).decode()}]})
    ])
    client = ImageGenClient("http://api/v1", "key", session=session)

    out = client.generate("gpt-image-1", "a prompt", photo=photo)

    assert out == png
    call = session.calls[0]
    assert call["url"] == "http://api/v1/images/edits"
    assert call["headers"]["Authorization"] == "Bearer key"
    assert call["data"]["model"] == "gpt-image-1"
    assert call["data"]["prompt"] == "a prompt"
    assert call["data"]["size"] == "1024x1024"
    assert call["data"]["n"] == "1"
    assert "image" in call["files"]


def test_generate_without_photo_posts_generations_json():
    png = _png_bytes()
    session = FakeSession([
        FakeResponse({"data": [{"b64_json": base64.b64encode(png).decode()}]})
    ])
    client = ImageGenClient("http://api/v1", "key", session=session)

    out = client.generate("gpt-image-1", "a prompt")

    assert out == png
    call = session.calls[0]
    assert call["url"] == "http://api/v1/images/generations"
    assert call["json"] == {
        "model": "gpt-image-1",
        "prompt": "a prompt",
        "size": "1024x1024",
        "n": 1,
    }
    assert call["headers"]["Authorization"] == "Bearer key"


def test_generate_falls_back_to_generations_when_edits_404(tmp_path):
    png = _png_bytes()
    photo = tmp_path / "ref.png"
    photo.write_bytes(png)
    session = FakeSession([
        FakeResponse({"error": "no edits"}, status_code=404),
        FakeResponse({"data": [{"url": "http://cdn/img.png"}]}),
        FakeResponse(content=png),
    ])
    client = ImageGenClient("http://api/v1", "key", session=session)

    out = client.generate("gpt-image-1", "a prompt", photo=photo)

    assert out == png
    assert session.calls[0]["url"].endswith("/images/edits")
    assert session.calls[1]["url"].endswith("/images/generations")
    assert session.calls[2]["method"] == "get"
    assert session.calls[2]["url"] == "http://cdn/img.png"


def test_generate_both_endpoints_fail_raises(tmp_path):
    photo = tmp_path / "ref.png"
    photo.write_bytes(_png_bytes())
    session = FakeSession([
        requests.HTTPError("404"),
        FakeResponse({"error": "rate limited"}, status_code=429),
    ])
    client = ImageGenClient("http://api/v1", "key", session=session)

    with pytest.raises(ImageGenError) as excinfo:
        client.generate("gpt-image-1", "a prompt", photo=photo)

    assert excinfo.value.status_code == 429


def test_decode_image_response_rejects_unknown_shape():
    with pytest.raises(ImageGenError):
        decode_image_response({})
    with pytest.raises(ImageGenError):
        decode_image_response({"data": []})
