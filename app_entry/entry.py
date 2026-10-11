"""Main executable entry: --serve-screen-control, self-spawn, --version dispatch."""

from __future__ import annotations

import os
import re
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Bootstrap: allow running as a plain script (python app_entry/entry.py)
# where sys.path[0] is the file's directory, not the repo root.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from core.paths import bundle_root, config_dir, is_frozen, repo_root


def _version_file() -> Path:
    return bundle_root() / "_version.txt"


def _bundled_version() -> str | None:
    p = _version_file()
    if p.exists():
        v = p.read_text(encoding="utf-8").strip()
        if v:
            return v
    return None


def serve_screen_control(argv: list[str] | None = None) -> int:
    os.environ.setdefault("SCREEN_CONTROL_DATA_DIR", str(config_dir()))
    from vendor.sc_server.server import main as server_main

    rest = argv if argv is not None else sys.argv[1:]
    rest = [a for a in rest if a != "--serve-screen-control"]
    sys.argv = ["screen-control-server", *rest]
    server_main()
    return 0


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.3):
            return True
    except OSError:
        return False


def _screen_control_token() -> str | None:
    try:
        p = config_dir() / ".token"
        if p.exists():
            return p.read_text(encoding="utf-8").strip() or None
    except OSError:
        pass
    return None


def _server_healthy(host: str, port: int) -> bool:
    """True only when the server accepts the token the app will actually use.

    Three failure modes are all unusable and must trigger a replace:
    - a stale server that 500s on its capture endpoints (reinstall/bad
      shutdown), and
    - a server that answers but rejects our credentials (401) - e.g. a
      leftover dev server holding the port with its own session token; every
      tool call would 401, so reusing it silently breaks the app.
    Only an authenticated 200 counts as healthy.
    """
    req = urllib.request.Request(
        f"http://{host}:{port}/api/info",
        headers={"X-Auth-Token": _screen_control_token() or ""},
    )
    try:
        with urllib.request.urlopen(req, timeout=1.0) as resp:
            return resp.status == 200
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def _port_owner_pids(port: int) -> list[int]:
    """PIDs listening on the port, via ss (matches any binary holding it)."""
    try:
        out = subprocess.run(
            ["ss", "-lptnH", f"sport = :{port}"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    pids = {int(p) for p in re.findall(r"pid=(\d+)", out.stdout)}
    return sorted(p for p in pids if p != os.getpid())


def _pattern_pids(port: int) -> list[int]:
    """PIDs of leftover frozen spawns (cmdline fallback when ss is missing)."""
    pattern = rf"serve-screen-control.*--port[= ]{port}\b"
    try:
        out = subprocess.run(
            ["pgrep", "-f", pattern],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [
        int(p)
        for p in out.stdout.split()
        if p.isdigit() and int(p) != os.getpid()
    ]


def _kill_stale_server(port: int) -> None:
    """Best-effort terminate whatever holds the screen-control port.

    Kills by port owner (ss) first so a leftover dev server
    (`python -m vendor.sc_server.server`, which has no
    `--serve-screen-control` in its cmdline) is replaced too; falls back to
    the spawn cmdline pattern when ss is unavailable. Called only after the
    health check already rejected the server, so anything on the port is
    unusable by definition.
    """
    pids = _port_owner_pids(port) or _pattern_pids(port)
    for sig in (signal.SIGTERM, signal.SIGKILL):
        alive = []
        for pid in pids:
            try:
                os.kill(pid, sig)
                alive.append(pid)
            except OSError:
                pass
        if sig is signal.SIGTERM:
            time.sleep(0.4)
            pids = [
                pid
                for pid in alive
                if os.path.exists(f"/proc/{pid}")
            ]
            if not pids:
                return


def maybe_spawn_server(settings: dict, exe_path: str | None = None) -> str | None:
    sc = settings.get("screen_control") or {}
    if not sc.get("enabled"):
        return None
    host = sc.get("host", "127.0.0.1")
    port = int(sc.get("port", 8745))
    listening = _port_open(host, port)
    if listening:
        if _server_healthy(host, port):
            return None  # healthy server already running — reuse it
        # Something holds the port but fails its endpoints (stale server from
        # a previous run). Replace it, otherwise screenshot/OCR keep 500ing.
        _kill_stale_server(port)
        for _ in range(20):
            if not _port_open(host, port):
                break
            time.sleep(0.1)

    env = {**os.environ, "SCREEN_CONTROL_DATA_DIR": str(config_dir())}
    if is_frozen():
        cmd = [
            exe_path or sys.executable,
            "--serve-screen-control",
            "--host",
            host,
            "--port",
            str(port),
        ]
        kwargs: dict = {}
    else:
        cmd = [
            sys.executable,
            "-m",
            "vendor.sc_server.server",
            "--host",
            host,
            "--port",
            str(port),
        ]
        kwargs = {"cwd": str(repo_root())}
    try:
        proc = subprocess.Popen(
            cmd,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            **kwargs,
        )
    except OSError:
        return None
    return str(proc.pid)


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--serve-screen-control" in args:
        return serve_screen_control(args)
    if "--version" in args:
        import core

        print(
            os.environ.get("APP_VERSION")
            or _bundled_version()
            or getattr(core, "__version__", "0.0.0")
        )
        return 0
    from ui.app import main as ui_main

    return ui_main()


if __name__ == "__main__":
    sys.exit(main())
