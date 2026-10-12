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


def test_schedule_check_does_not_record_before_fetch(tmp_path, monkeypatch):
    # B44: recording before the fetch starts means a failed (offline) fetch
    # burns the daily gate. The record must happen only AFTER a successful
    # fetch, inside the worker.
    import ui.update as upd

    state = tmp_path / "update_check.json"
    monkeypatch.setattr(upd, "update_state_path", lambda: state)
    monkeypatch.setattr(upd, "update_check_enabled", lambda p: True)

    calls = {"fetch": 0}

    class SlowWorker:
        def __init__(self, current, session=None, state_path=None):
            self.signals = upd._UpdateSignals()
            self._current = current

        def start(self):
            # fetch still in flight: nothing recorded yet
            calls["fetch"] += 1
            assert not state.exists(), "record_check must not run before fetch"

    monkeypatch.setattr(upd, "UpdateCheckWorker", SlowWorker)
    upd.schedule_update_check(tmp_path / "s.json", "0.1.0", lambda tag: None)
    assert calls["fetch"] == 1


def test_worker_records_check_only_on_success(tmp_path, monkeypatch):
    import ui.update as upd

    state = tmp_path / "update_check.json"
    # success path: worker records after fetching a tag
    worker = upd.UpdateCheckWorker(
        "0.1.0", session=_FakeSession(tag="v9.9.9"), state_path=state
    )
    worker._run()
    assert state.exists(), "successful fetch must record the check"
    # failure path: no record — the daily gate stays open
    state.unlink()
    worker2 = upd.UpdateCheckWorker(
        "0.1.0", session=_FakeSession(tag=None), state_path=state
    )
    worker2._run()
    assert not state.exists(), "failed fetch must NOT burn the daily gate"


class _FakeSession:
    def __init__(self, tag):
        self._tag = tag

    def get(self, url, timeout=None):
        tag = self._tag
        status = 200 if tag else 500

        class R:
            status_code = status

            def json(self):
                return {"tag_name": tag} if tag else {}

        return R()
