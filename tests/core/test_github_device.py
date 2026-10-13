"""GitHub OAuth device-flow client (official gh CLI app)."""

import time

import pytest

from core.auth.github_device import (
    CLIENT_ID,
    SCOPES,
    DeviceCode,
    GitHubDeviceError,
    poll_for_token,
    request_device_code,
)


class FakeResponse:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {"Content-Type": "application/json"}

    def json(self):
        return self._payload

    @property
    def text(self):
        from urllib.parse import urlencode

        return urlencode(self._payload)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def post(self, url, **kw):
        self.calls.append({"url": url, **kw})
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


DEVICE_RESPONSE = {
    "device_code": "dev123",
    "user_code": "ABCD-1234",
    "verification_uri": "https://github.com/login/device",
    "interval": 5,
    "expires_in": 900,
}


def test_request_device_code_posts_client_and_scopes():
    session = FakeSession([FakeResponse(DEVICE_RESPONSE)])

    code = request_device_code(session=session)

    assert isinstance(code, DeviceCode)
    assert code.device_code == "dev123"
    assert code.user_code == "ABCD-1234"
    assert code.verification_uri == "https://github.com/login/device"
    assert code.interval == 5.0
    assert code.expires_in == 900.0
    call = session.calls[0]
    assert call["url"] == "https://github.com/login/device/code"
    assert call["data"]["client_id"] == CLIENT_ID == "Iv1.b507a08c78f299fb"
    assert call["data"]["scope"] == SCOPES == "repo read:org gist workflow"


def test_request_device_code_accepts_form_encoded_response():
    session = FakeSession([FakeResponse(DEVICE_RESPONSE)])
    session.script.clear()
    session.script.append(
        type(
            "R",
            (),
            {
                "_payload": DEVICE_RESPONSE,
                "status_code": 200,
                "headers": {"Content-Type": "application/x-www-form-urlencoded"},
                "json": lambda self: (_ for _ in ()).throw(ValueError("no json")),
                "text": (
                    "device_code=dev123&user_code=ABCD-1234"
                    "&verification_uri=https%3A%2F%2Fgithub.com%2Flogin%2Fdevice"
                    "&interval=5&expires_in=900"
                ),
                "raise_for_status": lambda self: None,
            },
        )()
    )

    code = request_device_code(session=session)

    assert code.device_code == "dev123"
    assert code.user_code == "ABCD-1234"
    assert code.verification_uri == "https://github.com/login/device"


def test_poll_returns_token_after_pending():
    session = FakeSession([
        FakeResponse({"error": "authorization_pending"}),
        FakeResponse({"access_token": "gho_abc", "token_type": "bearer"}),
    ])
    sleeps = []

    token = poll_for_token(
        DeviceCode("dev123", "ABCD-1234", "https://github.com/login/device", 5, 900),
        session=session,
        sleep=sleeps.append,
    )

    assert token == "gho_abc"
    assert sleeps == [5.0]
    assert session.calls[1]["data"]["grant_type"] == (
        "urn:ietf:params:oauth:grant-type:device_code"
    )
    assert session.calls[1]["data"]["device_code"] == "dev123"
    assert session.calls[1]["data"]["client_id"] == CLIENT_ID


def test_poll_raises_on_access_denied():
    session = FakeSession([FakeResponse({"error": "access_denied"})])

    with pytest.raises(GitHubDeviceError, match="denied"):
        poll_for_token(
            DeviceCode("dev123", "ABCD-1234", "u", 5, 900),
            session=session,
            sleep=lambda s: None,
        )


def test_poll_raises_on_expired_token():
    session = FakeSession([FakeResponse({"error": "expired_token"})])

    with pytest.raises(GitHubDeviceError, match="expired"):
        poll_for_token(
            DeviceCode("dev123", "ABCD-1234", "u", 5, 900),
            session=session,
            sleep=lambda s: None,
        )


def test_poll_raises_on_deadline():
    session = FakeSession([FakeResponse({"error": "authorization_pending"})])
    now = time.monotonic()
    ticks = iter([now, now + 10, now + 20])

    with pytest.raises(GitHubDeviceError, match="timed out"):
        poll_for_token(
            DeviceCode("dev123", "ABCD-1234", "u", 5, 900),
            session=session,
            sleep=lambda s: None,
            deadline_s=5,
            _now=lambda: next(ticks),
        )
