"""First-run setup flow: missing API key must guide to Settings, not crash."""

from __future__ import annotations

import json

from core.providers.base import ProviderError
from ui.setup import UnconfiguredProvider, is_missing_key_error, reload_provider


def _write_fresh_install(tmp_path, with_key: bool = False):
    """Settings template as shipped (provider=groq) with or without an API key."""
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "provider": {"type": "groq", "model": "qwen/qwen3.8-27b"},
                "screen_control": {"enabled": False},
                "permissions": {"*": "ask"},
                "avatar": "base",
            }
        )
    )
    secrets = tmp_path / "secrets.json"
    secrets.write_text(json.dumps({"groq_api_key": "gsk_test"} if with_key else {}))
    secrets.chmod(0o600)
    return settings, secrets


def _make_runtime(tmp_path):
    from core.bootstrap import build_runtime

    settings, secrets = _write_fresh_install(tmp_path, with_key=False)
    try:
        build_runtime(settings_path=settings, secrets_path=secrets)
    except ProviderError as exc:
        assert is_missing_key_error(exc)
        runtime, _bus, _sess = build_runtime(
            settings_path=settings, secrets_path=secrets,
            provider=UnconfiguredProvider(),
        )
        return runtime, settings, secrets
    raise AssertionError("expected missing_api_key on fresh install")


def test_is_missing_key_error():
    assert is_missing_key_error(
        ProviderError("x", error_code="missing_api_key")
    )
    assert not is_missing_key_error(ProviderError("x", error_code="other"))
    assert not is_missing_key_error(ValueError("x"))


def test_reload_provider_installs_real_provider(tmp_path):
    runtime, settings, secrets = _make_runtime(tmp_path)
    assert isinstance(runtime._provider, UnconfiguredProvider)
    # User configures the model in Settings and saves.
    secrets.write_text(json.dumps({"groq_api_key": "gsk_test"}))
    assert reload_provider(runtime, settings, secrets) is True
    assert not isinstance(runtime._provider, UnconfiguredProvider)
    assert runtime._provider.supports_tools is True


def test_reload_provider_keeps_placeholder_when_still_incomplete(tmp_path):
    runtime, settings, secrets = _make_runtime(tmp_path)
    # Saved without entering a key -> placeholder must stay.
    assert reload_provider(runtime, settings, secrets) is False
    assert isinstance(runtime._provider, UnconfiguredProvider)


class _NoopGuideBox:
    """Stand-in for QMessageBox so the deferred guidance dialog never blocks."""

    class Icon:
        Information = 1

    class StandardButton:
        Ok = 1

    def __init__(self, parent=None):
        self.title = ""
        self.text = ""

    def setIcon(self, *_a):
        pass

    def setWindowTitle(self, title):
        self.title = title

    def setText(self, text):
        self.text = text

    def setStandardButtons(self, *_a):
        pass

    def exec(self):
        pass


def _make_avatar_app(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    import ui.avatar_app as aa
    from ui.history import HistoryStore

    app = QApplication.instance() or QApplication([])
    settings, secrets = _write_fresh_install(tmp_path, with_key=False)
    monkeypatch.setattr("core.bootstrap.DEFAULT_SETTINGS", settings)
    monkeypatch.setattr("core.bootstrap.DEFAULT_SECRETS", secrets)
    monkeypatch.setattr(aa, "SETTINGS_PATH", settings)
    monkeypatch.setattr(aa, "SECRETS_PATH", secrets)
    monkeypatch.setattr(aa, "default_db_path", lambda: tmp_path / "h.db")
    monkeypatch.setattr(aa, "HistoryStore", lambda p: HistoryStore(tmp_path / "h.db"))
    monkeypatch.setattr(aa, "QMessageBox", _NoopGuideBox)
    ui = aa.App()
    # Flush the deferred guidance dialog INSIDE the test so its QTimer cannot
    # fire during later tests' processEvents (would hang the suite on exec()).
    app.processEvents()
    return app, ui, settings, secrets


def test_avatar_app_boots_placeholder_when_key_missing(tmp_path, monkeypatch):
    app, ui, _settings, _secrets = _make_avatar_app(tmp_path, monkeypatch)
    assert ui._needs_provider_setup is True
    assert isinstance(ui.runtime._provider, UnconfiguredProvider)
    ui.close()


def test_avatar_app_settings_saved_swaps_provider(tmp_path, monkeypatch):
    app, ui, _settings, secrets = _make_avatar_app(tmp_path, monkeypatch)
    secrets.write_text(json.dumps({"groq_api_key": "gsk_test"}))
    ui._on_settings_saved()
    assert ui._needs_provider_setup is False
    assert not isinstance(ui.runtime._provider, UnconfiguredProvider)
    ui.close()


def test_avatar_app_settings_saved_applies_screen_control(tmp_path, monkeypatch):
    # B29: enabling screen_control in Settings must reach the live runtime's
    # tool registry without an app restart (the template ships it disabled).
    app, ui, settings, _secrets = _make_avatar_app(tmp_path, monkeypatch)
    assert ui.runtime.registry.get("screenshot") is None
    cfg = json.loads(settings.read_text())
    cfg["screen_control"] = {"enabled": True, "host": "127.0.0.1", "port": 8745}
    settings.write_text(json.dumps(cfg))
    ui._on_settings_saved()
    assert ui.runtime.registry.get("screenshot") is not None
    ui.close()


def test_avatar_app_settings_saved_applies_provider_change(tmp_path, monkeypatch):
    # B24: once the app is configured, later saves (model/type change) must
    # hot-swap the provider too — not only the first-run setup transition.
    app, ui, settings, secrets = _make_avatar_app(tmp_path, monkeypatch)
    secrets.write_text(json.dumps({"groq_api_key": "gsk_test"}))
    ui._on_settings_saved()
    assert ui._needs_provider_setup is False
    first = ui.runtime._provider
    cfg = json.loads(settings.read_text())
    cfg["provider"]["model"] = "second-model"
    settings.write_text(json.dumps(cfg))
    ui._on_settings_saved()
    assert ui.runtime._provider is not first
    assert ui.runtime._provider.model == "second-model"
    ui.close()


def test_guide_dialog_opens_provider_settings(tmp_path, monkeypatch):
    app, ui, _settings, _secrets = _make_avatar_app(tmp_path, monkeypatch)

    import ui.avatar_app as aa

    class FakeBox:
        class Icon:
            Information = 1

        class StandardButton:
            Ok = 1

        instances = []

        def __init__(self, parent=None):
            self.title = ""
            self.text = ""
            self.exec_count = 0
            FakeBox.instances.append(self)

        def setIcon(self, *_a):
            pass

        def setWindowTitle(self, title):
            self.title = title

        def setText(self, text):
            self.text = text

        def setStandardButtons(self, *_a):
            pass

        def exec(self):
            self.exec_count += 1

    opened = []
    monkeypatch.setattr(aa, "QMessageBox", FakeBox)
    monkeypatch.setattr(ui, "_open_provider_settings", lambda: opened.append(True))
    ui._guide_provider_setup()
    assert len(FakeBox.instances) == 1
    assert FakeBox.instances[0].exec_count == 1
    assert FakeBox.instances[0].title == "Model Ayarı Gerekli"
    assert "Ayarlar" in FakeBox.instances[0].text
    assert opened == [True]
    ui.close()


def test_settings_save_emits_saved(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"provider": {"type": "groq", "model": "m"},'
        ' "screen_control": {"enabled": false},'
        ' "permissions": {"*": "ask"}, "avatar": "base"}'
    )
    secrets = tmp_path / "secrets.json"
    secrets.write_text("{}")
    ui_json = tmp_path / "ui.json"
    win = SettingsWindow(settings, secrets, ui_json)
    fired = []
    win.saved.connect(lambda: fired.append(True))
    win._provider_key.setText("gsk_saved")
    win.save()
    assert fired == [True]
    assert json.loads(secrets.read_text())["groq_api_key"] == "gsk_saved"
    win.hide()
    win.deleteLater()
