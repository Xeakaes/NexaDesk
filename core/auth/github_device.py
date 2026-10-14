"""GitHub OAuth device-authorization flow using the official gh CLI app.

Token types: the resulting ``gho_`` access token works anywhere a classic
PAT would for API calls, including the Copilot token exchange in
``core/providers/github.py``. The client id is GitHub CLI's public OAuth
application identifier — not a secret.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from urllib.parse import parse_qs

import requests

CLIENT_ID = "Iv1.b507a08c78f299fb"
SCOPES = "repo read:org gist workflow"
_DEVICE_CODE_URL = "https://github.com/login/device/code"
_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
_GRANT_TYPE = "urn:ietf:params:oauth:grant-type:device_code"


class GitHubDeviceError(Exception):
    """Device-flow step failed (network, denial, expiry, or deadline).

    B87: ``code`` is a stable token the UI maps to a localized message —
    matching on the English exception text breaks under non-English locales.
    """

    def __init__(self, message: str, code: str = "generic") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class DeviceCode:
    device_code: str
    user_code: str
    verification_uri: str
    interval: float
    expires_in: float


def _response_payload(resp: requests.Response) -> dict:
    """GitHub answers device endpoints as JSON or form-encoded."""
    ctype = (resp.headers.get("Content-Type") or "").lower()
    if "json" in ctype:
        data = resp.json()
        return data if isinstance(data, dict) else {}
    parsed = parse_qs(resp.text, keep_blank_values=True)
    return {k: v[0] for k, v in parsed.items() if v}


def request_device_code(session: requests.Session | None = None) -> DeviceCode:
    """Start the device flow; returns the code the user must enter."""
    sess = session or requests.Session()
    resp = sess.post(
        _DEVICE_CODE_URL,
        data={"client_id": CLIENT_ID, "scope": SCOPES},
        headers={"Accept": "application/json"},
        timeout=30.0,
    )
    if resp.status_code >= 400:
        raise GitHubDeviceError(
            f"device code request failed (HTTP {resp.status_code})",
            code="network",
        )
    data = _response_payload(resp)
    try:
        return DeviceCode(
            device_code=data["device_code"],
            user_code=data["user_code"],
            verification_uri=data.get("verification_uri")
            or data.get("verification_uri_complete")
            or "https://github.com/login/device",
            interval=float(data.get("interval", 5)),
            expires_in=float(data.get("expires_in", 900)),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise GitHubDeviceError(
            "device code request returned a malformed response",
            code="network",
        ) from exc


def poll_for_token(
    code: DeviceCode,
    *,
    session: requests.Session | None = None,
    sleep=time.sleep,
    deadline_s: float | None = None,
    _now=time.monotonic,
) -> str:
    """Poll until the user authorizes; returns the ``gho_`` access token."""
    sess = session or requests.Session()
    interval = code.interval
    deadline = _now() + (deadline_s if deadline_s is not None else code.expires_in)
    while True:
        if _now() >= deadline:
            raise GitHubDeviceError(
                "sign-in timed out — start again", code="expired_token"
            )
        resp = sess.post(
            _ACCESS_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "device_code": code.device_code,
                "grant_type": _GRANT_TYPE,
            },
            headers={"Accept": "application/json"},
            timeout=30.0,
        )
        if resp.status_code >= 400:
            raise GitHubDeviceError(
                f"token poll failed (HTTP {resp.status_code})",
                code="network",
            )
        data = _response_payload(resp)
        token = data.get("access_token")
        if token:
            return str(token)
        error = data.get("error", "")
        if error in ("authorization_pending",):
            sleep(interval)
            continue
        if error == "slow_down":
            interval += 5
            sleep(interval)
            continue
        if error == "access_denied":
            raise GitHubDeviceError(
                "access denied in the browser", code="access_denied"
            )
        if error == "expired_token":
            raise GitHubDeviceError(
                "the code expired — start again", code="expired_token"
            )
        raise GitHubDeviceError(
            error or "unexpected token poll response", code="generic"
        )
