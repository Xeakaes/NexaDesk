"""Packaging contract tests: OCR and runtime deps must ship in the bundle.

rapidocr_onnxruntime is imported lazily inside vendor/sc_server/server.py,
so PyInstaller cannot discover it statically — the spec must collect it
explicitly, or packaged builds serve "OCR engine not installed".
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Requirement name -> import name in the PyInstaller spec text.
_REQ_TO_IMPORT = {
    "requests": "requests",
    "pillow": "PIL",
    "flask": "flask",
    "mss": "mss",
    "pyautogui": "pyautogui",
    "numpy": "numpy",
    "pyvda": "pyvda",
    "evdev": "evdev",
    "rapidocr_onnxruntime": "rapidocr_onnxruntime",
}

# Not shipped in the app bundle on purpose.
_DEV_ONLY = {"pytest", "pyinstaller"}

# Bundled by PyInstaller's own hooks; no spec entry needed.
_AUTO_HOOKED = {"pyside6"}


def _parse_requirements(path: Path) -> list[str]:
    names = []
    for line in path.read_text().splitlines():
        line = line.split(";", 1)[0].strip()
        if not line or line.startswith("#"):
            continue
        names.append(re.split(r"[><=~!\[]", line, maxsplit=1)[0].strip().lower())
    return names


def test_requirements_packaging_includes_ocr_engine():
    text = (ROOT / "requirements-packaging.txt").read_text()
    assert "rapidocr" in text, "rapidocr_onnxruntime must be a packaging dependency"


def test_spec_collects_ocr_engine_and_onnxruntime():
    text = (ROOT / "packaging" / "nexadesk.spec").read_text()
    assert 'collect_all("rapidocr_onnxruntime")' in text
    assert 'collect_all("onnxruntime")' in text


def test_linux_build_smoke_checks_bundled_ocr():
    text = (ROOT / "packaging" / "build_linux.sh").read_text()
    assert "rapidocr" in text, "build must verify the OCR engine is bundled"


def test_every_runtime_requirement_is_bundled():
    """Every non-dev requirement must appear in the packaging spec.

    Add new runtime deps to _REQ_TO_IMPORT (or _DEV_ONLY) so this contract
    stays honest when requirements change.
    """
    spec = (ROOT / "packaging" / "nexadesk.spec").read_text()
    runtime = _parse_requirements(ROOT / "requirements.txt") + _parse_requirements(
        ROOT / "requirements-packaging.txt"
    )
    for req in dict.fromkeys(runtime):
        if req in _DEV_ONLY or req in _AUTO_HOOKED:
            continue
        import_name = _REQ_TO_IMPORT[req]
        assert import_name in spec, (
            f"{req} ({import_name}) is not bundled: add it to the spec "
            f"hiddenimports/collect_all or to _DEV_ONLY"
        )


# Documented asset name -> file that must produce that exact name.
_ASSET_NAMES = [
    ("NexaDesk_<version>_amd64.deb", "packaging/build_linux.sh"),
    ("NexaDesk_<version>_linux_amd64.tar.gz", "packaging/build_linux.sh"),
    ("NexaDesk_<version>_windows_x64.zip", ".github/workflows/release.yml"),
]


def test_readme_asset_names_match_packaging_outputs():
    """README download names must match what the packaging actually emits."""
    readme = (ROOT / "README.md").read_text()
    for name, producer in _ASSET_NAMES:
        assert name in readme, f"README must document the asset {name}"
        produced = (ROOT / producer).read_text()
        candidates = (
            name.replace("<version>", "${APP_VERSION}"),
            name.replace("<version>", "${env:APP_VERSION}"),
        )
        assert any(c in produced for c in candidates), (
            f"{producer} must emit {name}; found none of {candidates}"
        )
