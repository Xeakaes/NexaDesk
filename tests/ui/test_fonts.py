from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "assets" / "fonts"


def test_nunito_static_files_bundled():
    for name in ("Nunito-Regular.ttf", "Nunito-Bold.ttf", "OFL.txt"):
        p = ASSETS / name
        assert p.is_file(), name
    assert (ASSETS / "Nunito-Regular.ttf").stat().st_size > 50_000
    assert (ASSETS / "Nunito-Bold.ttf").stat().st_size > 50_000
    assert "SIL OPEN FONT LICENSE" in (ASSETS / "OFL.txt").read_text()


def test_load_fonts_registers_nunito_family():
    from PySide6.QtWidgets import QApplication

    from ui.fonts import load_fonts

    app = QApplication.instance() or QApplication([])
    font_id = load_fonts(app)
    assert font_id != -1
    from PySide6.QtGui import QFontDatabase

    families = QFontDatabase.applicationFontFamilies(font_id)
    assert "Nunito" in families


def test_load_fonts_missing_file_returns_minus_one(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import ui.fonts

    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(ui.fonts, "REGULAR_PATH", tmp_path / "nope.ttf")
    assert ui.fonts.load_fonts(app) == -1


def test_bubble_uses_app_font_not_hardcoded_sans():
    # B75: BubbleWindow overrode the transcript font with a hard-coded
    # QFont("Sans Serif", 10), defeating load_fonts()/the theme font.
    import inspect

    from ui.bubble import BubbleWindow

    src = inspect.getsource(BubbleWindow.__init__)
    assert 'QFont("Sans Serif"' not in src
