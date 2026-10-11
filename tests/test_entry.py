import os
import socket
import sys
from pathlib import Path

from app_entry import entry


def test_version_flag_prints(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    monkeypatch.setattr(entry, "_version_file", lambda: tmp_path / "_version.txt")
    assert entry.main(["--version"]) == 0
    assert "0.0.0" in capsys.readouterr().out


def test_version_reads_bundled_file(capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("APP_VERSION", raising=False)
    (tmp_path / "_version.txt").write_text("9.9.9-test")
    monkeypatch.setattr(entry, "_version_file", lambda: tmp_path / "_version.txt")
    assert entry.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "9.9.9-test"


def test_version_env_wins(capsys, monkeypatch, tmp_path):
    monkeypatch.setenv("APP_VERSION", "1.2.3")
    (tmp_path / "_version.txt").write_text("9.9.9")
    monkeypatch.setattr(entry, "_version_file", lambda: tmp_path / "_version.txt")
    assert entry.main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == "1.2.3"


def test_serve_sets_data_dir_env(monkeypatch, tmp_path):
    monkeypatch.delenv("SCREEN_CONTROL_DATA_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "b"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        __import__("core.paths", fromlist=["Path"]).Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    captured = {}

    def fake_server_main():
        captured["env"] = os.environ.get("SCREEN_CONTROL_DATA_DIR")

    import vendor.sc_server.server as sm

    monkeypatch.setattr(sm, "main", fake_server_main)
    entry.serve_screen_control(["--serve-screen-control"])
    assert captured["env"] == str(tmp_path / ".config" / "NexaDesk")


def test_spawn_disabled_settings(monkeypatch):
    called = []
    monkeypatch.setattr(entry.subprocess, "Popen", lambda *a, **k: called.append(a))
    assert entry.maybe_spawn_server({"screen_control": {"enabled": False}}) is None
    assert called == []


def test_spawn_skipped_when_port_open(monkeypatch):
    class FakeSock:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(entry.socket, "create_connection", lambda *a, **k: FakeSock())
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: True)
    popped = []
    monkeypatch.setattr(entry.subprocess, "Popen", lambda *a, **k: popped.append(a))
    assert entry.maybe_spawn_server({"screen_control": {"enabled": True}}) is None
    assert popped == []


def test_spawn_replaces_unhealthy_server(monkeypatch):
    # Port is held by a stale/broken server: health check fails, so we kill it
    # and spawn a fresh one.
    probes = {"n": 0}

    def port_open(*a):
        probes["n"] += 1
        return probes["n"] <= 1  # listening on first probe, freed after the kill

    monkeypatch.setattr(entry, "_port_open", port_open)
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: False)
    killed = []
    monkeypatch.setattr(entry, "_kill_stale_server", lambda port: killed.append(port))

    class P:
        pid = 555

        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    pid = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert pid == "555"
    assert killed == [8745]


def test_server_healthy_true_on_200(monkeypatch):
    class R:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(entry.urllib.request, "urlopen", lambda *a, **k: R())
    assert entry._server_healthy("127.0.0.1", 8745) is True


def test_server_healthy_false_on_401(monkeypatch):
    # A server that answers but rejects the token the app will use (e.g. a
    # leftover dev server with its own session token) cannot serve any tool
    # call - it must be replaced, not reused.
    import urllib.error

    def raise401(*a, **k):
        raise urllib.error.HTTPError("http://x", 401, "no", None, None)

    monkeypatch.setattr(entry.urllib.request, "urlopen", raise401)
    assert entry._server_healthy("127.0.0.1", 8745) is False


def test_server_healthy_false_on_500(monkeypatch):
    import urllib.error

    def raise500(*a, **k):
        raise urllib.error.HTTPError("http://x", 500, "err", None, None)

    monkeypatch.setattr(entry.urllib.request, "urlopen", raise500)
    assert entry._server_healthy("127.0.0.1", 8745) is False


def test_server_healthy_false_on_dead_socket(monkeypatch):
    import urllib.error

    def raise_urlerror(*a, **k):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr(entry.urllib.request, "urlopen", raise_urlerror)
    assert entry._server_healthy("127.0.0.1", 8745) is False


def test_spawn_frozen_passes_host_port(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("closed")

    monkeypatch.setattr(entry.socket, "create_connection", boom)
    captured = {}

    class P:
        pid = 4242

        def __init__(self, *a, **k):
            captured["args"] = a
            captured["kwargs"] = k

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        __import__("core.paths", fromlist=["Path"]).Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    pid = entry.maybe_spawn_server(
        {"screen_control": {"enabled": True, "host": "0.0.0.0", "port": 9001}}
    )
    assert pid == "4242"
    cmd = captured["args"][0]
    assert "--serve-screen-control" in cmd
    assert "--host" in cmd and "0.0.0.0" in cmd
    assert "--port" in cmd and "9001" in cmd
    from core.paths import config_dir

    assert captured["kwargs"]["env"]["SCREEN_CONTROL_DATA_DIR"] == str(config_dir())


def test_spawn_dev_uses_module_invocation(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("closed")

    monkeypatch.setattr(entry.socket, "create_connection", boom)
    captured = {}

    class P:
        pid = 777

        def __init__(self, *a, **k):
            captured["args"] = a
            captured["kwargs"] = k

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    pid = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert pid == "777"
    cmd = captured["args"][0]
    assert "-m" in cmd and "vendor.sc_server.server" in cmd
    assert "--port" in cmd and "8745" in cmd
    assert "--serve-screen-control" not in cmd
