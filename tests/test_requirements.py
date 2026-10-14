"""B76: dependency manifests must not leak test deps into runtime nor duplicate pins."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_pyautogui_is_windows_only():
    # pyautogui is only imported by the Windows screen-control backend;
    # installing it unconditionally pulls X libs on Linux for nothing.
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    pack = (ROOT / "requirements-packaging.txt").read_text(encoding="utf-8")
    for text in (req, pack):
        for line in text.splitlines():
            if line.startswith("pyautogui"):
                assert 'sys_platform == "win32"' in line, line


def test_no_duplicate_and_no_test_deps_in_runtime():
    # pytest belongs to the packaging/dev manifest, not the runtime one the
    # release bundle installs from; flask/Pillow/requests must not appear twice.
    req_lines = [
        l.strip() for l in (ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
        if l.strip() and not l.strip().startswith("#")
    ]
    assert len(req_lines) == len(set(req_lines)), req_lines
    assert not any(l.startswith("pytest") for l in req_lines), req_lines


def test_no_duplicate_pins_across_manifests():
    # flask/Pillow/requests were pinned in both files — keep runtime pins in
    # requirements.txt only, packaging extras in the packaging manifest.
    def pins(path):
        out = {}
        for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "; " in line and "sys_platform" in line:
                continue
            name = line.split(">=")[0].split("==")[0].strip().lower()
            out[name] = line
        return out

    runtime = pins("requirements.txt")
    packaging = pins("requirements-packaging.txt")
    # no same-name pin in both (platform-marked lines already skipped above)
    overlap = set(runtime) & set(packaging)
    # numpy/mss etc. are packaging-only; PySide6/requests etc. runtime-only.
    assert not overlap, f"duplicated pins: {overlap}"
