import importlib
import sys


def test_sdk_importable_from_vendor():
    mod = importlib.import_module("vendor.sc_server.sdk")
    assert hasattr(mod, "ScreenControl")


def test_vendor_packages_renamed():
    sc_core_backends = importlib.import_module("vendor.sc_server.sc_core.backends")
    assert sc_core_backends.__name__ == "vendor.sc_server.sc_core.backends"
    import core

    assert not hasattr(core, "backends")


def test_server_module_importable():
    pytest_importorskip = __import__("pytest").importorskip
    pytest_importorskip("flask")
    mod = importlib.import_module("vendor.sc_server.server")
    assert hasattr(mod, "main")


def test_server_token_dir_uses_env(monkeypatch, tmp_path):
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    # force fresh module so env is read at import time
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    mod = importlib.import_module("vendor.sc_server.server")
    assert str(tmp_path) in mod.SESSION_TOKEN_FILE
    assert str(tmp_path) in mod.APIKEYS_FILE


def test_server_import_does_not_write_token(monkeypatch, tmp_path):
    # A racing second spawn imports this module before knowing it cannot
    # bind; an import-time token write would clobber the LIVE server's
    # token and 401 every subsequent tool call.
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    (tmp_path / ".token").write_text("LIVE_TOKEN")
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    importlib.import_module("vendor.sc_server.server")
    assert (tmp_path / ".token").read_text() == "LIVE_TOKEN"


def test_write_session_token_is_secure(monkeypatch, tmp_path):
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    mod = importlib.import_module("vendor.sc_server.server")
    mod._write_session_token()
    p = tmp_path / ".token"
    assert p.read_text() == mod.SESSION_TOKEN
    if __import__("os").name == "posix":
        assert (p.stat().st_mode & 0o777) == 0o600


def test_save_api_keys_is_private(monkeypatch, tmp_path):
    __import__("pytest").importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    for name in [m for m in list(sys.modules) if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    mod = importlib.import_module("vendor.sc_server.server")
    mod._api_key_names["a" * 64] = "test-key"
    mod._save_api_keys()
    p = tmp_path / ".apikeys"
    assert p.exists()
    if __import__("os").name == "posix":
        assert (p.stat().st_mode & 0o777) == 0o600


def test_default_client_factory_uses_vendor(monkeypatch):
    import core.bootstrap as b

    src = __import__("pathlib").Path(b.__file__).read_text()
    assert "/home/xeakaes/screen-control" not in src
    assert "vendor.sc_server.sdk" in src


def _load_fake_server(tmp_path, monkeypatch):
    """Fresh server module bound to the fake backend + isolated data dir."""
    pytest = __import__("pytest")
    pytest.importorskip("flask")
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SCREEN_CONTROL_BACKEND", "fake")
    # get_backend() caches a process-wide singleton — an earlier test may
    # have created the REAL platform backend; reset so the env is honored.
    import vendor.sc_server.sc_core.backends as backends_mod

    monkeypatch.setattr(backends_mod, "_backend_singleton", None)
    for name in [m for m in list(sys.modules)
                 if m.startswith("vendor.sc_server.server")]:
        del sys.modules[name]
    mod = importlib.import_module("vendor.sc_server.server")
    monkeypatch.setattr(mod, "_is_valid_token", lambda token: bool(token))
    return mod


def test_key_error_releases_held_keys(tmp_path, monkeypatch):
    # B12: a failed input batch means the client's paired key_up may never
    # arrive — the server must lift everything now, not after the watchdog.
    mod = _load_fake_server(tmp_path, monkeypatch)
    fake = mod._b()
    client = mod.app.test_client()
    hdr = {"X-Auth-Token": "t"}
    resp = client.post("/api/key", json={"action": "down", "key": "ctrl"}, headers=hdr)
    assert resp.status_code == 200
    assert "ctrl" in client.get("/api/held", headers=hdr).get_json()["keys"]

    def boom(*a, **k):
        raise RuntimeError("device gone")

    monkeypatch.setattr(fake, "key_press", boom)
    resp = client.post("/api/key", json={"action": "press", "key": "a"}, headers=hdr)
    assert resp.status_code == 500
    assert client.get("/api/held", headers=hdr).get_json()["keys"] == []


def test_mouse_error_releases_held_buttons(tmp_path, monkeypatch):
    mod = _load_fake_server(tmp_path, monkeypatch)
    fake = mod._b()
    client = mod.app.test_client()
    hdr = {"X-Auth-Token": "t"}
    resp = client.post("/api/mouse", json={"action": "down", "button": "left"}, headers=hdr)
    assert resp.status_code == 200
    assert "left" in client.get("/api/held", headers=hdr).get_json()["buttons"]

    def boom(*a, **k):
        raise RuntimeError("device gone")

    monkeypatch.setattr(fake, "mouse_move", boom)
    resp = client.post("/api/mouse", json={"action": "move", "x": 1, "y": 2}, headers=hdr)
    assert resp.status_code == 500
    assert client.get("/api/held", headers=hdr).get_json()["buttons"] == []


def test_shutdown_releases_held_keys(tmp_path, monkeypatch):
    # B12: process exit with a key still down leaves it stuck at the OS
    # level forever (the watchdog dies with the process).
    mod = _load_fake_server(tmp_path, monkeypatch)
    fake = mod._b()
    fake.key_down("ctrl")
    assert "ctrl" in fake.held_state()["keys"]

    class FakeServer:
        def serve_forever(self):
            raise KeyboardInterrupt

    import werkzeug.serving

    monkeypatch.setattr(
        werkzeug.serving, "make_server", lambda *a, **k: FakeServer()
    )
    monkeypatch.setattr("sys.argv", ["sc_server"])
    try:
        mod.main()
    except KeyboardInterrupt:
        pass
    assert fake.held_state()["keys"] == []


def test_monitor_for_point_picks_containing_monitor():
    from vendor.sc_server.sc_core.backends import monitor_for_point

    monitors = [
        {"id": 1, "left": 0, "top": 0, "width": 1920, "height": 1080,
         "is_primary": True},
        {"id": 2, "left": 1920, "top": 0, "width": 2560, "height": 1440},
    ]
    assert monitor_for_point(monitors, 100, 100) == 1
    assert monitor_for_point(monitors, 2000, 10) == 2
    # Outside every rect → primary fallback.
    assert monitor_for_point(monitors, -50, -50) == 1


def test_screenshot_resolves_monitor_for_window(tmp_path, monkeypatch):
    # B26: ?hwnd= targets the monitor that contains the window, not always 1.
    mod = _load_fake_server(tmp_path, monkeypatch)
    fake = mod._b()
    monkeypatch.setattr(fake, "monitor_for_window", lambda hwnd: 2)
    client = mod.app.test_client()
    resp = client.get("/api/screenshot?hwnd=5", headers={"X-Auth-Token": "t"})
    assert resp.status_code == 200
    shots = [c for c in fake.calls if c[0] == "screenshot_jpeg"]
    assert shots and shots[-1][1][0] == 2


def test_ocr_resolves_monitor_for_window(tmp_path, monkeypatch):
    mod = _load_fake_server(tmp_path, monkeypatch)
    fake = mod._b()
    monkeypatch.setattr(fake, "monitor_for_window", lambda hwnd: 2)
    client = mod.app.test_client()
    # Engine may be absent (503) — the capture call is what we assert.
    client.post("/api/ocr", json={"hwnd": 5}, headers={"X-Auth-Token": "t"})
    shots = [c for c in fake.calls if c[0] == "screenshot"]
    assert shots, "ocr must capture through the resolved monitor"
    last = shots[-1]
    assert last[1][0] == 2 or last[2].get("monitor") == 2


def test_sdk_local_token_fallback_reads_data_dir(tmp_path, monkeypatch):
    # B69: the server writes .token to $SCREEN_CONTROL_DATA_DIR (spawned
    # with config_dir()), so the SDK fallback must read there — never
    # vendor/sc_server/.token, which only exists in a source-tree server run.
    import vendor.sc_server.sdk as sdk

    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    (tmp_path / ".token").write_text("tok123\n", encoding="utf-8")
    client = sdk.ScreenControl.__new__(sdk.ScreenControl)
    assert client._load_local_token() == "tok123"


def test_ocr_body_region_rejects_bad_values(tmp_path, monkeypatch):
    # B49: POST /api/ocr body region must be validated like the GET query
    # parameter — zero/negative/huge regions must not reach the capture.
    import vendor.sc_server.server as srv

    client = srv.app.test_client()
    # no auth needed? check token — use the session token from env or set one
    srv.SESSION_TOKEN = "testtoken"
    headers = {"X-Auth-Token": "testtoken", "Content-Type": "application/json"}
    for bad in ([0, 0, 0, 0], [0, 0, -10, 10], [0, 0, 99999, 99999], [0, 0, 10]):
        resp = client.post("/api/ocr", json={"region": bad}, headers=headers)
        assert resp.status_code == 400, f"region {bad} should be rejected"
        assert b"region" in resp.data.lower() or b"error" in resp.data.lower()
