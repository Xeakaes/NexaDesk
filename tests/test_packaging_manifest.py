"""Packaging contract tests: OCR and runtime deps must ship in the bundle.

rapidocr_onnxruntime is imported lazily inside vendor/sc_server/server.py,
so PyInstaller cannot discover it statically — the spec must collect it
explicitly, or packaged builds serve "OCR engine not installed".
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


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
