"""OpenAI-compatible image-generation client for the F2 avatar pack flow.

Speaks two wire formats, in order of preference:

- ``POST {base}/images/edits``  — multipart with the reference photo, so the
  model can keep the character's identity (photo reference).
- ``POST {base}/images/generations`` — JSON text-only fallback for providers
  that do not ship the edits endpoint.

Responses are accepted in either common shape: ``data[0].b64_json`` (bytes)
or ``data[0].url`` (downloaded). Failures raise :class:`ImageGenError` with
the HTTP status of the last attempt when available.
"""

from __future__ import annotations

import base64
from pathlib import Path

import requests

from core.agent.telemetry import log_event

IMAGE_MODEL_MARKERS: tuple[str, ...] = (
    "gpt-image",
    "dall-e",
    "dall_e",
    "flux",
    "imagen",
    "seedream",
    "stable-diffusion",
    "sd3",
    "image",
)


def is_image_model(model_id: str) -> bool:
    """True when a catalog model id looks like an image-generation model."""
    lowered = model_id.lower()
    return any(marker in lowered for marker in IMAGE_MODEL_MARKERS)


class ImageGenError(Exception):
    """Image generation failed (network, HTTP, or unexpected payload)."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def decode_image_response(payload: object, *, session: requests.Session | None = None) -> bytes:
    """Extract image bytes from an images-endpoint JSON payload.

    Accepts ``{"data": [{"b64_json": ...}]}`` and ``{"data": [{"url": ...}]}``;
    an ``{"error": ...}`` body (some local servers, e.g. LM Studio, return
    HTTP 200 with an error payload for unsupported endpoints) surfaces the
    provider message; anything else raises :class:`ImageGenError`.
    """
    if not isinstance(payload, dict):
        raise ImageGenError("unexpected image response payload")
    provider_error = payload.get("error")
    if provider_error is not None:
        if isinstance(provider_error, dict):
            provider_error = provider_error.get("message") or provider_error.get("code")
        raise ImageGenError(f"provider error: {provider_error}")
    data = payload.get("data")
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ImageGenError("unexpected image response payload")
    item = data[0]
    b64 = item.get("b64_json")
    if b64:
        return base64.b64decode(b64)
    url = item.get("url")
    if url:
        sess = session or requests
        resp = sess.get(url, timeout=120.0)
        resp.raise_for_status()
        return resp.content
    raise ImageGenError("unexpected image response payload")


class ImageGenClient:
    """Generates one image per call against an OpenAI-compatible provider."""

    def __init__(
        self,
        base_url: str,
        api_key: str,
        timeout_s: float = 120.0,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_s = timeout_s
        self._session = session or requests.Session()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}"}

    def generate(self, model: str, prompt: str, photo: Path | None = None) -> bytes:
        """Generate one image; ``photo`` enables the edits (reference) path."""
        if photo is not None:
            try:
                resp = self._post_edits(model, prompt, photo)
            except requests.RequestException:
                resp = None
            if resp is not None:
                if resp.status_code == 200:
                    log_event("image_gen", model=model, endpoint="edits", ok=True)
                    return decode_image_response(resp.json(), session=self._session)
                log_event(
                    "image_gen", model=model, endpoint="edits", ok=False,
                    status=resp.status_code,
                )
        try:
            resp = self._post_generations(model, prompt)
        except requests.RequestException as exc:
            log_event("image_gen", model=model, endpoint="generations", ok=False)
            raise ImageGenError(f"image generation request failed: {exc}") from exc
        if resp.status_code != 200:
            log_event(
                "image_gen", model=model, endpoint="generations", ok=False,
                status=resp.status_code,
            )
            raise ImageGenError(
                f"image generation failed with HTTP {resp.status_code}",
                status_code=resp.status_code,
            )
        log_event("image_gen", model=model, endpoint="generations", ok=True)
        try:
            return decode_image_response(resp.json(), session=self._session)
        except ValueError as exc:
            raise ImageGenError("image generation returned invalid JSON") from exc

    def _post_edits(self, model: str, prompt: str, photo: Path):
        photo_bytes = photo.read_bytes()
        return self._session.post(
            f"{self.base_url}/images/edits",
            headers=self._headers(),
            data={"model": model, "prompt": prompt, "size": "1024x1024", "n": "1"},
            files={"image": (photo.name, photo_bytes, "image/png")},
            timeout=self.timeout_s,
        )

    def _post_generations(self, model: str, prompt: str):
        return self._session.post(
            f"{self.base_url}/images/generations",
            headers=self._headers(),
            json={"model": model, "prompt": prompt, "size": "1024x1024", "n": 1},
            timeout=self.timeout_s,
        )
