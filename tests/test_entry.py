import os
import socket
import sys
from pathlib import Path

import pytest

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
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
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
    if os.name == "nt":
        expected = str(tmp_path / "appdata" / "NexaDesk")
    else:
        expected = str(tmp_path / ".config" / "NexaDesk")
    assert captured["env"] == expected


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
    monkeypatch.setattr(entry, "_server_healthy_retry", lambda *a, **k: False)
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: True)  # post-spawn verification
    killed = []
    monkeypatch.setattr(entry, "_kill_stale_server", lambda port: killed.append(port) or True)

    class P:
        pid = 555

        def __init__(self, *a, **k):
            pass

        def poll(self):
            return None

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    pid = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert pid == "555"
    assert killed == [8745]


def test_spawn_kills_child_that_exits_immediately(monkeypatch):
    # A dead/half-started child must be detected and reported as a failed
    # spawn instead of being reported as success.
    monkeypatch.setattr(entry, "_port_open", lambda *a: False)

    class P:
        pid = 999

        def __init__(self, *a, **k):
            pass

        def poll(self):
            return 1  # child already dead

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    result = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert result is None


def test_spawn_terminates_child_that_never_becomes_healthy(monkeypatch):
    # Child stays alive but never answers its health check: terminate it and
    # report failure instead of leaving a zombie.
    monkeypatch.setattr(entry, "_port_open", lambda *a: False)
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: False)
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    calls = {"n": 0}

    def fake_time():
        calls["n"] += 1
        return 0.0 if calls["n"] == 1 else 100.0  # first call starts loop, second exits

    monkeypatch.setattr(entry.time, "time", fake_time)
    terminated = []

    class P:
        pid = 999

        def __init__(self, *a, **k):
            pass

        def poll(self):
            return None

        def terminate(self):
            terminated.append(True)

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    result = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert result is None
    assert terminated


def test_spawn_returns_pid_when_child_becomes_healthy(monkeypatch):
    monkeypatch.setattr(entry, "_port_open", lambda *a: False)
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: True)
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)

    class P:
        pid = 555

        def __init__(self, *a, **k):
            pass

        def poll(self):
            return None

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    result = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert result == "555"


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


def test_server_healthy_falls_back_to_secrets_api_key(tmp_path, monkeypatch):
    # B15: the probe must send the same credential the tool client resolves
    # (live .token file first, then the persisted screen_control_api_key -
    # see core.bootstrap.default_client_factory). Without the fallback a
    # server that authenticates via the persisted key while .token is
    # missing gets judged dead, so we kill and respawn a usable server.
    import json
    import urllib.error

    monkeypatch.setattr(entry, "config_dir", lambda: tmp_path)
    (tmp_path / "secrets.json").write_text(
        json.dumps({"screen_control_api_key": "KEY123"})
    )

    def fake_urlopen(req, *args, **kwargs):
        if req.get_header("X-auth-token") != "KEY123":
            raise urllib.error.HTTPError("http://x", 401, "no", None, None)

        class R:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R()

    monkeypatch.setattr(entry.urllib.request, "urlopen", fake_urlopen)
    assert entry._server_healthy("127.0.0.1", 8745) is True


def test_server_healthy_prefers_live_token_over_secrets_key(tmp_path, monkeypatch):
    # Mirror of test_client_factory_prefers_live_token_over_stale_secrets:
    # a stale cached key must never override the live .token file.
    import json
    import urllib.error

    monkeypatch.setattr(entry, "config_dir", lambda: tmp_path)
    (tmp_path / ".token").write_text("LIVE_TOKEN")
    (tmp_path / "secrets.json").write_text(
        json.dumps({"screen_control_api_key": "STALE_KEY"})
    )
    sent = {}

    def fake_urlopen(req, *args, **kwargs):
        sent["token"] = req.get_header("X-auth-token")
        if sent["token"] != "LIVE_TOKEN":
            raise urllib.error.HTTPError("http://x", 401, "no", None, None)

        class R:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return R()

    monkeypatch.setattr(entry.urllib.request, "urlopen", fake_urlopen)
    assert entry._server_healthy("127.0.0.1", 8745) is True
    assert sent["token"] == "LIVE_TOKEN"


def test_kill_stale_server_kills_port_owner(monkeypatch):
    # A leftover dev server (`python -m vendor.sc_server.server`) holding the
    # port is ours: the cmdline identity check must recognize it and kill it.
    import signal
    import types

    if os.name == "nt":
        out = (
            "  TCP    127.0.0.1:8745         0.0.0.0:0              LISTENING       4242\n"
        )
    else:
        out = (
            'LISTEN 0 128 127.0.0.1:8745 0.0.0.0:* '
            'users:(("python3",pid=4242,fd=3))\n'
        )
    monkeypatch.setattr(
        entry.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout=out, returncode=0),
    )
    monkeypatch.setattr(
        entry,
        "_read_cmdline",
        lambda pid: "python3 -m vendor.sc_server.server --port 8745",
    )
    killed = []
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    monkeypatch.setattr(entry, "_pid_alive", lambda pid: False)
    assert entry._kill_stale_server(8745) is True
    assert killed == [(4242, signal.SIGTERM)]


@pytest.mark.skipif(os.name == "nt", reason="mocks the Linux ss output; the Windows netstat path has its own test below")
def test_kill_stale_server_falls_back_to_pattern(monkeypatch):
    import signal
    import types

    calls = []

    def fake_run(cmd, **k):
        calls.append(cmd)
        if cmd[0] == "ss":
            return types.SimpleNamespace(stdout="", returncode=1)
        return types.SimpleNamespace(stdout="4242\n", returncode=0)

    monkeypatch.setattr(entry.subprocess, "run", fake_run)
    monkeypatch.setattr(
        entry,
        "_read_cmdline",
        lambda pid: "python /app/NexaDesk --serve-screen-control --port 8745",
    )
    killed = []
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    monkeypatch.setattr(entry, "_pid_alive", lambda pid: False)
    assert entry._kill_stale_server(8745) is True
    assert killed == [(4242, signal.SIGTERM)]
    assert [c[0] for c in calls] == ["ss", "pgrep"]


@pytest.mark.skipif(os.name == "nt", reason="mocks the Linux ss output; the Windows netstat path has its own test below")
def test_kill_stale_server_refuses_foreign_port_owner(monkeypatch):
    # An unrelated app (e.g. nginx) on the port must never be killed; the
    # function reports the conflict instead.
    import types

    ss_out = (
        'LISTEN 0 128 127.0.0.1:8745 0.0.0.0:* '
        'users:(("nginx",pid=9999,fd=3))\n'
    )
    monkeypatch.setattr(
        entry.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout=ss_out, returncode=0),
    )
    monkeypatch.setattr(entry, "_read_cmdline", lambda pid: "nginx: master process")
    killed = []
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    assert entry._kill_stale_server(8745) is False
    assert killed == []


@pytest.mark.skipif(os.name == "nt", reason="mocks the Linux ss output; the Windows netstat path has its own test below")
def test_kill_stale_server_kills_only_our_pids(monkeypatch):
    import signal
    import types

    ss_out = (
        'LISTEN 0 128 127.0.0.1:8745 0.0.0.0:* '
        'users:(("nginx",pid=1111,fd=3),("python3",pid=4242,fd=4))\n'
    )
    monkeypatch.setattr(
        entry.subprocess,
        "run",
        lambda *a, **k: types.SimpleNamespace(stdout=ss_out, returncode=0),
    )
    cmdlines = {1111: "nginx: master process", 4242: "python3 -m vendor.sc_server.server"}
    monkeypatch.setattr(entry, "_read_cmdline", lambda pid: cmdlines.get(pid, ""))
    killed = []
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    monkeypatch.setattr(entry, "_pid_alive", lambda pid: False)
    assert entry._kill_stale_server(8745) is True
    assert killed == [(4242, signal.SIGTERM)]


def test_kill_stale_server_windows_netstat_pids(monkeypatch):
    import types

    monkeypatch.setattr(entry.os, "name", "nt")
    netstat_out = (
        "  TCP    127.0.0.1:8745         0.0.0.0:0              LISTENING       4242\n"
    )

    def fake_run(cmd, **k):
        return types.SimpleNamespace(stdout=netstat_out, returncode=0)

    monkeypatch.setattr(entry.subprocess, "run", fake_run)
    monkeypatch.setattr(
        entry,
        "_read_cmdline",
        lambda pid: "NexaDesk.exe --serve-screen-control --port 8745",
    )
    killed = []
    monkeypatch.setattr(entry.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    assert entry._kill_stale_server(8745) is True
    assert killed[0][0] == 4242


def test_spawn_refuses_when_port_held_by_foreign_app(monkeypatch):
    # Port open + unhealthy, but the holder is not ours: do not kill, do not
    # spawn — the user gets their app's port back and a clear log line.
    monkeypatch.setattr(entry, "_port_open", lambda *a: True)
    monkeypatch.setattr(entry, "_server_healthy_retry", lambda *a, **k: False)
    monkeypatch.setattr(entry, "_kill_stale_server", lambda port: False)
    popped = []
    monkeypatch.setattr(entry.subprocess, "Popen", lambda *a, **k: popped.append(a))
    result = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert result is None
    assert popped == []


def test_server_healthy_retried_before_declaring_dead(monkeypatch):
    # A single 1s probe can misjudge a busy-but-alive server; retry before
    # deciding to replace it. Here the server comes up healthy on probe 3 →
    # it must be reused, never killed.
    probes = {"n": 0}

    def healthy(host, port):
        probes["n"] += 1
        return probes["n"] >= 3

    monkeypatch.setattr(entry, "_port_open", lambda *a: True)
    monkeypatch.setattr(entry, "_server_healthy", healthy)
    killed = []
    monkeypatch.setattr(entry, "_kill_stale_server", lambda port: killed.append(port))
    popped = []
    monkeypatch.setattr(entry.subprocess, "Popen", lambda *a, **k: popped.append(a))
    result = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert result is None
    assert probes["n"] == 3
    assert killed == []
    assert popped == []


def test_spawn_frozen_passes_host_port(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("closed")

    monkeypatch.setattr(entry.socket, "create_connection", boom)
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: True)
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    captured = {}

    class P:
        pid = 4242

        def __init__(self, *a, **k):
            captured["args"] = a
            captured["kwargs"] = k

        def poll(self):
            return None

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.setattr(
        __import__("core.paths", fromlist=["Path"]).Path,
        "home",
        classmethod(lambda cls: tmp_path),
    )
    pid = entry.maybe_spawn_server(
        {"screen_control": {"enabled": True, "host": "127.0.0.1", "port": 9001}}
    )
    assert pid == "4242"
    cmd = captured["args"][0]
    assert "--serve-screen-control" in cmd
    assert "--host" in cmd and "127.0.0.1" in cmd
    assert "--port" in cmd and "9001" in cmd
    from core.paths import config_dir

    assert captured["kwargs"]["env"]["SCREEN_CONTROL_DATA_DIR"] == str(config_dir())


def test_spawn_dev_uses_module_invocation(monkeypatch, tmp_path):
    def boom(*a, **k):
        raise OSError("closed")

    monkeypatch.setattr(entry.socket, "create_connection", boom)
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: True)
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    captured = {}

    class P:
        pid = 777

        def __init__(self, *a, **k):
            captured["args"] = a
            captured["kwargs"] = k

        def poll(self):
            return None

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    pid = entry.maybe_spawn_server({"screen_control": {"enabled": True, "port": 8745}})
    assert pid == "777"
    cmd = captured["args"][0]
    assert "-m" in cmd and "vendor.sc_server.server" in cmd
    assert "--port" in cmd and "8745" in cmd
    assert "--serve-screen-control" not in cmd


def test_spawn_clamps_non_loopback_host(monkeypatch, tmp_path):
    # Defense in depth: even if settings.json was hand-edited to 0.0.0.0,
    # the spawned server must only ever bind loopback.
    def boom(*a, **k):
        raise OSError("closed")

    monkeypatch.setattr(entry.socket, "create_connection", boom)
    monkeypatch.setattr(entry, "_server_healthy", lambda *a: True)
    monkeypatch.setattr(entry.time, "sleep", lambda s: None)
    captured = {}

    class P:
        pid = 4242

        def __init__(self, *a, **k):
            captured["args"] = a

        def poll(self):
            return None

    monkeypatch.setattr(entry.subprocess, "Popen", P)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    entry.maybe_spawn_server(
        {"screen_control": {"enabled": True, "host": "0.0.0.0", "port": 8745}}
    )
    cmd = captured["args"][0]
    host_idx = cmd.index("--host")
    assert cmd[host_idx + 1] == "127.0.0.1"
