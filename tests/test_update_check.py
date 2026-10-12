import json

from core.update_check import fetch_latest_tag, is_newer, should_check, record_check


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload


class _Session:
    def __init__(self, resp=None, exc=None):
        self._resp = resp
        self._exc = exc
        self.urls = []

    def get(self, url, timeout=None):
        self.urls.append(url)
        if self._exc:
            raise self._exc
        return self._resp


def test_is_newer_parses_v_tags():
    assert is_newer("v0.2.1", "0.2.0")
    assert is_newer("v0.3.0", "v0.2.9")
    assert not is_newer("v0.2.0", "0.2.0")
    assert not is_newer("v0.1.9", "0.2.0")


def test_is_newer_is_offline_safe_on_garbage():
    assert not is_newer("not-a-version", "0.2.0")
    assert not is_newer("", "0.2.0")


def test_fetch_latest_tag_returns_tag():
    s = _Session(resp=_Resp({"tag_name": "v0.2.1"}))
    assert fetch_latest_tag(session=s) == "v0.2.1"
    assert "api.github.com/repos/Xeakaes/NexaDesk/releases/latest" in s.urls[0]


def test_fetch_latest_tag_returns_none_on_http_error():
    s = _Session(resp=_Resp({}, status=403))
    assert fetch_latest_tag(session=s) is None


def test_fetch_latest_tag_returns_none_on_network_error():
    import requests

    s = _Session(exc=requests.ConnectionError("offline"))
    assert fetch_latest_tag(session=s) is None


def test_should_check_daily_gate(tmp_path):
    state = tmp_path / "update_check.json"
    assert should_check(state) is True
    record_check(state)
    assert should_check(state) is False
    data = json.loads(state.read_text())
    assert "last_check" in data


def test_should_check_ignores_corrupt_state(tmp_path):
    state = tmp_path / "update_check.json"
    state.write_text("{corrupt")
    assert should_check(state) is True
