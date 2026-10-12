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


def _read_cmdline(pid: int) -> str:
    """Best-effort command line of a process (cross-platform)."""
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["wmic", "process", "where", f"processid={pid}", "get", "commandline"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        return out.stdout
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
        return raw.replace(b"\x00", b" ").decode("utf-8", "replace")
    except OSError:
        pass
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return out.stdout


_SERVER_CMDLINE_MARKERS = (
    "serve-screen-control",
    "vendor.sc_server.server",
    "vendor/sc_server/server.py",
)


def _is_our_server(pid: int) -> bool:
    cmdline = _read_cmdline(pid)
    return any(marker in cmdline for marker in _SERVER_CMDLINE_MARKERS)


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        return True  # best effort; no safe liveness probe without extra deps
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _port_owner_pids(port: int) -> list[int]:
    """PIDs listening on the port (any binary holding it)."""
    if os.name == "nt":
        try:
            out = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        pids = set()
        for line in out.stdout.splitlines():
            if "LISTENING" not in line:
                continue
            parts = line.split()
            if len(parts) < 5 or not parts[1].endswith(f":{port}"):
                continue
            if parts[-1].isdigit():
                pids.add(int(parts[-1]))
        return sorted(p for p in pids if p != os.getpid())
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
    if os.name == "nt":
        return []
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


def _kill_stale_server(port: int) -> bool:
    """Terminate leftover NexaDesk screen-control servers holding the port.

    Only PIDs whose cmdline identifies them as the NexaDesk screen-control
    server are killed; an unrelated application on the port is never touched.
    Returns True when the port was freed (best effort), False when the holder
    is not ours and the caller must surface the conflict instead of spawning.
    """
    port_pids = _port_owner_pids(port)
    ours = [pid for pid in port_pids if _is_our_server(pid)]
    if not ours:
        ours = [pid for pid in _pattern_pids(port) if _is_our_server(pid)]
    if not ours:
        return False
    sigkill = getattr(signal, "SIGKILL", signal.SIGTERM)
    for sig in (signal.SIGTERM, sigkill):
        alive = []
        for pid in ours:
            try:
                os.kill(pid, sig)
                alive.append(pid)
            except OSError:
                pass
        if sig == signal.SIGTERM:
            time.sleep(0.4)
            ours = [pid for pid in alive if _pid_alive(pid)]
            if not ours:
                return True
    return True


def _server_healthy_retry(
    host: str, port: int, attempts: int = 3, delay_s: float = 0.3
) -> bool:
    """Probe the server several times before declaring it dead.

    A single 1s probe can misjudge a busy-but-alive server and needlessly
    kill/replace it.
    """
    for i in range(attempts):
        if _server_healthy(host, port):
            return True
        if i < attempts - 1:
            time.sleep(delay_s)
    return False


def maybe_spawn_server(settings: dict, exe_path: str | None = None) -> str | None:
    sc = settings.get("screen_control") or {}
    if not sc.get("enabled"):
        return None
    host = sc.get("host", "127.0.0.1")
    if host not in ("127.0.0.1", "localhost"):
        host = "127.0.0.1"  # defense in depth: hand-edited settings must not expose the LAN
    port = int(sc.get("port", 8745))
    listening = _port_open(host, port)
    if listening:
        if _server_healthy_retry(host, port):
            return None  # healthy server already running — reuse it
        # Something holds the port but fails its endpoints. Replace it only
        # when the holder is a leftover NexaDesk server; a foreign app on the
        # port must never be killed.
        if not _kill_stale_server(port):
            print(
                f"[nexadesk] port {port} is used by another application; "
                "screen-control server not started",
                file=sys.stderr,
            )
            return None
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
    # Verify the child actually came up: a dead or half-started server must
    # not be reported as a successful spawn (the caller would then keep
    # retrying broken tool calls with no visible reason).
    deadline = time.time() + 5.0
    while time.time() < deadline:
        rc = proc.poll()
        if rc is not None:
            print(
                f"[nexadesk] screen-control server exited with code {rc}",
                file=sys.stderr,
            )
            return None
        if _server_healthy(host, port):
            return str(proc.pid)
        time.sleep(0.2)
    try:
        proc.terminate()
    except OSError:
        pass
    print(
        "[nexadesk] screen-control server failed to become healthy; terminated",
        file=sys.stderr,
    )
    return None


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
