"""Packaging manifests must declare what the shipped binary needs (B30, B31)."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NFPM = ROOT / "packaging" / "nfpm.yaml"
NOTICE = ROOT / "NOTICE"


def test_nfpm_declares_qt_runtime_depends():
    # B30: a bare PyInstaller binary on a minimal Debian/Ubuntu fails with
    # "Could not load the Qt platform plugin xcb" unless the system Qt
    # runtime libraries are present — the deb must pull them in.
    text = NFPM.read_text(encoding="utf-8")
    assert "depends:" in text
    for pkg in (
        "libxkbcommon0",
        "libgl1",
        "libegl1",
        "libdbus-1-3",
        "libfontconfig1",
        "libxcb-cursor0",
        "libxcb-xkb1",
        "libx11-xcb1",
    ):
        assert pkg in text, f"deb depends must list {pkg}"
