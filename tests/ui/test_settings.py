from pathlib import Path

from ui.settings import merge_permissions


def test_merge_permissions_overrides_defaults():
    merged = merge_permissions({"*": "ask"}, "allow", {"screenshot": "deny"})
    assert merged["*"] == "allow"
    assert merged["screenshot"] == "deny"


def test_settings_window_load_and_save(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"provider": {"type": "ollama", "url": "", "model": "x"},'
        ' "screen_control": {"enabled": true, "host": "127.0.0.1", "port": 8745},'
        ' "permissions": {"*": "ask"}, "avatar": "base"}'
    )
    secrets = tmp_path / "secrets.json"
    secrets.write_text('{"screen_control_api_key": "k", "api_key": ""}')
    ui_json = tmp_path / "ui.json"
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    assert win._provider_type.currentText() == "ollama"
    assert win._provider_url.text() == ""
    win._provider_url.setText("http://localhost:11434")
    win.save()
    import json

    data = json.loads(settings.read_text())
    assert data["provider"]["url"] == "http://localhost:11434"
    win.hide()
    win.deleteLater()


def test_settings_host_rejects_non_loopback(tmp_path):
    # The docs promise "listens on 127.0.0.1 only"; a typed 0.0.0.0/lan-ip
    # must be clamped back to loopback, not silently exposed to the LAN.
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._sc_host.setText("0.0.0.0")
    win.save()
    import json

    data = json.loads(settings.read_text())
    assert data["screen_control"]["host"] == "127.0.0.1"
    win.hide()
    win.deleteLater()


def test_settings_host_accepts_loopback_aliases(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._sc_host.setText("localhost")
    win.save()
    import json

    data = json.loads(settings.read_text())
    assert data["screen_control"]["host"] == "localhost"
    win.hide()
    win.deleteLater()


def test_github_provider_shows_experimental_warning(tmp_path):
    # The GitHub provider uses an unofficial Copilot endpoint; selecting it
    # must surface a visible "experimental, unofficial API" warning so the
    # account-restriction risk is the user's informed choice.
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    assert win._provider_warning.isHidden()  # default provider is ollama
    win._provider_type.setCurrentText("github")
    assert not win._provider_warning.isHidden()
    low = win._provider_warning.text().lower()
    assert "unofficial" in low or "resmi olmayan" in low
    win._provider_type.setCurrentText("ollama")
    assert win._provider_warning.isHidden()
    win.hide()
    win.deleteLater()


def test_readme_labels_github_as_unofficial():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    readme = (root / "README.md").read_text(encoding="utf-8")
    # Every mention of the GitHub provider in the README must carry the
    # unofficial/experimental caveat.
    lines = [ln for ln in readme.splitlines() if "GitHub Copilot" in ln]
    assert lines, "README must mention GitHub Copilot somewhere"
    for ln in lines:
        low = ln.lower()
        assert (
            "experimental" in low
            or "unofficial" in low
            or "deneysel" in low
            or "resmi olmayan" in low
        ), f"README line must label GitHub Copilot as experimental/unofficial: {ln}"


def test_settings_persona_roundtrip(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    assert win._persona.toPlainText() == ""
    win._persona.setPlainText("Sen kısa cevap veren bir asistansın.")
    win.save()
    import json

    data = json.loads(settings.read_text())
    assert data["agent"]["persona"] == "Sen kısa cevap veren bir asistansın."
    # unrelated agent keys survive
    assert data["agent"].get("max_tool_calls", 10) >= 1
    win2 = SettingsWindow(settings, secrets, ui_json)
    win2.load()
    assert win2._persona.toPlainText() == "Sen kısa cevap veren bir asistansın."
    win.hide()
    win.deleteLater()
    win2.hide()
    win2.deleteLater()


def test_settings_has_five_titled_tabs(tmp_path):
    from PySide6.QtWidgets import QApplication, QTabWidget

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    tabs = win.findChild(QTabWidget)
    assert tabs is not None
    assert tabs.count() == 5
    titles = {tabs.tabText(i) for i in range(tabs.count())}
    assert titles == {"Genel", "Sağlayıcı", "Ekran kontrolü", "İzinler", "Avatar"}
    win.hide()
    win.deleteLater()


def _make_settings_files(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(
        '{"provider": {"type": "ollama", "url": "", "model": "x"},'
        ' "screen_control": {"enabled": true, "host": "127.0.0.1", "port": 8745},'
        ' "permissions": {"*": "ask"}, "avatar": "base"}'
    )
    secrets = tmp_path / "secrets.json"
    secrets.write_text('{"screen_control_api_key": "k", "api_key": ""}')
    ui_json = tmp_path / "ui.json"
    return settings, secrets, ui_json


def test_delete_pack_removes_dir_and_refreshes(tmp_path, monkeypatch):
    import json

    from PySide6.QtWidgets import QApplication, QMessageBox

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)

    # Fake an avatars root with a deletable pack and the built-in base.
    # _delete_pack uses user_avatars_dir() -> config_dir()/avatars.
    cfg = tmp_path / "cfg"
    avatars = cfg / "avatars"
    pack = avatars / "teto"
    (pack / "frames").mkdir(parents=True)
    (pack / "manifest.json").write_text(json.dumps({"name": "teto", "states": {}}))
    base = avatars / "base"
    (base / "frames").mkdir(parents=True)
    (base / "manifest.json").write_text(json.dumps({"name": "base", "states": {}}))

    # Empty bundle so _list_avatars does not pick up real on-disk packs.
    bundle = tmp_path / "bundle_assets"
    (bundle / "avatars").mkdir(parents=True)
    monkeypatch.setattr("core.paths.assets_dir", lambda: bundle)
    monkeypatch.setattr("core.paths.config_dir", lambda: cfg)
    monkeypatch.setattr(
        QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes)
    )

    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    # Point the combo at the pack we want to delete.
    idx = win._avatar.findText("teto")
    assert idx >= 0, f"teto not in combo: {win._avatar.count()}"
    win._avatar.setCurrentIndex(idx)
    win._delete_pack()
    assert not pack.exists()
    assert base.exists()  # built-in never deleted
    # Combo no longer lists the deleted pack.
    assert win._avatar.findText("teto") == -1
    win.hide()
    win.deleteLater()


def test_delete_pack_refuses_base(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    avatars = tmp_path / "avatars"
    base = avatars / "base"
    (base / "frames").mkdir(parents=True)
    (base / "manifest.json").write_text('{"name": "base", "states": {}}')

    monkeypatch.setattr("core.paths.assets_dir", lambda: tmp_path)

    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._avatar.setCurrentIndex(win._avatar.findText("base"))
    win._delete_pack()
    assert base.exists()  # still there
    win.hide()
    win.deleteLater()


def test_build_pack_runs_on_background_thread(tmp_path, monkeypatch):
    """_build_pack must not block: it starts a background thread and disables the button."""
    import threading

    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)

    cfg = tmp_path / "cfg"
    bundle = tmp_path / "bundle_assets"
    (bundle / "avatars").mkdir(parents=True)
    monkeypatch.setattr("core.paths.assets_dir", lambda: bundle)
    monkeypatch.setattr("core.paths.config_dir", lambda: cfg)

    # A slow stub so we can observe the in-flight state.
    started = threading.Event()
    release = threading.Event()

    def slow_build(src, out, name):
        started.set()
        release.wait(timeout=5)
        (out / "frames").mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text('{"name": "%s", "states": {}}' % name)

    monkeypatch.setattr("ui.settings.build_pack", slow_build)

    from PIL import Image

    src = tmp_path / "photo.png"
    img = Image.new("RGB", (64, 64), (255, 255, 255))
    for x in range(20, 44):
        for y in range(20, 44):
            img.putpixel((x, y), (200, 30, 30))
    img.save(src)

    win = SettingsWindow(settings, secrets, ui_json)
    win._pack_path.setText(str(src))
    win._pack_name.setText("worker")
    win._build_pack()  # should return immediately (thread started)
    # Button is disabled while the worker runs.
    assert not win._pack_build.isEnabled()
    assert started.wait(timeout=2), "build_pack never started on the thread"
    release.set()
    # Join the worker thread before pumping events. The worker is a plain
    # threading.Thread (no QThread teardown race), so delivering the queued
    # completion signal afterwards is safe.
    assert win._pack_worker.wait(5000), "worker thread did not finish"
    # Let the queued completion slot run.
    for _ in range(50):
        app.processEvents()
        if win._pack_build.isEnabled():
            break
        threading.Event().wait(0.05)
    assert win._pack_build.isEnabled(), "button not re-enabled after build"
    assert (cfg / "avatars" / "worker" / "manifest.json").is_file()
    win.hide()
    win.deleteLater()


def test_model_field_is_editable_dropdown(tmp_path):
    from PySide6.QtWidgets import QApplication, QComboBox

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    assert isinstance(win._provider_model, QComboBox)
    assert win._provider_model.isEditable()
    win.hide()
    win.deleteLater()


def test_fetch_models_populates_dropdown_and_keeps_current(tmp_path, monkeypatch):
    import threading

    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    secrets.write_text('{"screen_control_api_key": "k", "groq_api_key": "gsk_x"}')

    class StubProvider:
        def list_models(self):
            return ["m/zeta", "m/alpha"]

    monkeypatch.setattr(
        "core.providers.create_provider", lambda *a, **k: StubProvider()
    )

    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._provider_type.setCurrentText("groq")
    win._provider_model.setCurrentText("typed-by-user")
    win._fetch_models()
    assert win._model_worker is not None
    assert win._model_worker.wait(5000), "model fetch worker did not finish"
    for _ in range(50):
        app.processEvents()
        if win._btn_refresh_models.isEnabled():
            break
        threading.Event().wait(0.05)
    items = [win._provider_model.itemText(i) for i in range(win._provider_model.count())]
    # Ordering/sorting is the provider's job (covered in provider tests);
    # the UI inserts whatever the catalog returns.
    assert items == ["m/zeta", "m/alpha"]
    # The user's value survives the catalog refresh.
    assert win._provider_model.currentText() == "typed-by-user"
    assert win._btn_refresh_models.isEnabled()
    win.hide()
    win.deleteLater()


def test_fetch_models_failure_reenables_button(tmp_path, monkeypatch):
    import threading

    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)

    class BoomProvider:
        def list_models(self):
            raise RuntimeError("nope")

    monkeypatch.setattr(
        "core.providers.create_provider", lambda *a, **k: BoomProvider()
    )

    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._fetch_models()
    assert win._model_worker.wait(5000)
    for _ in range(50):
        app.processEvents()
        if win._btn_refresh_models.isEnabled():
            break
        threading.Event().wait(0.05)
    assert win._btn_refresh_models.isEnabled()
    win.hide()
    win.deleteLater()


def test_save_uses_combo_current_text(tmp_path):
    import json

    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._provider_model.setCurrentText("my-hand-typed-model")
    win.save()
    data = json.loads(settings.read_text())
    assert data["provider"]["model"] == "my-hand-typed-model"
    win.hide()
    win.deleteLater()


def test_provider_type_change_resets_url_to_preset(tmp_path, monkeypatch):
    # B18: a custom URL from the previous provider must not survive a type
    # change — saving would send the new provider's key to that old host.
    import json

    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    monkeypatch.setattr(win, "_fetch_models", lambda: None)  # keep it offline
    win.load()
    win._provider_type.setCurrentText("openai_compatible")
    win._provider_url.setText("https://proxy.example.com/v1")  # user's proxy
    win._provider_type.setCurrentText("groq")
    assert win._provider_url.text() == "https://api.groq.com/openai/v1"
    win.save()
    data = json.loads(settings.read_text())
    assert data["provider"]["url"] == "https://api.groq.com/openai/v1"
    win.hide()
    win.deleteLater()


def test_stale_model_list_worker_cannot_apply_results(tmp_path, monkeypatch):
    # B23: a slow catalog fetch started for the previous provider type must
    # not refill the dropdown after the user has already switched again.
    from PySide6.QtWidgets import QApplication

    import ui.settings as sw
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)

    workers = []

    class FakeWorker:
        def __init__(self, s, k):
            self.signals = sw._ModelListSignals()
            workers.append(self)

        def start(self):
            pass

        def wait(self, ms=5000):
            return True

    monkeypatch.setattr(sw, "_ModelListWorker", FakeWorker)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._provider_type.setCurrentText("github")  # fetch #1 (models + ai)
    win._provider_type.setCurrentText("groq")    # fetch #2 (models + ai)
    # Each type change starts two workers: the provider catalog and the F2
    # AI image-model catalog. Provider workers are [0] and [2].
    assert len(workers) == 4
    # Fetch #1 finishes late, after the user already moved on to groq.
    workers[0].signals.finished.emit(["stale-model"])
    assert win._provider_model.findText("stale-model") == -1
    # The current fetch still applies.
    workers[2].signals.finished.emit(["fresh-model"])
    assert win._provider_model.findText("fresh-model") >= 0
    win.hide()
    win.deleteLater()


def test_avatar_ai_model_round_trip(tmp_path):
    import json

    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._ai_model.setCurrentText("gpt-image-1")
    win.save()
    data = json.loads(settings.read_text())
    assert data["avatar_ai"]["model"] == "gpt-image-1"
    win2 = SettingsWindow(settings, secrets, ui_json)
    win2.load()
    assert win2._ai_model.currentText() == "gpt-image-1"
    win.hide()
    win.deleteLater()
    win2.hide()
    win2.deleteLater()


def test_ai_model_dropdown_filters_to_image_models(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._ai_fetch_gen = 1
    win._on_ai_models_loaded(["gpt-image-1", "llama-3.3-70b", "dall-e-3"], 1)
    items = [win._ai_model.itemText(i) for i in range(win._ai_model.count())]
    assert items == ["gpt-image-1", "dall-e-3"]
    win.hide()
    win.deleteLater()


def test_ai_model_fetch_generation_guard(tmp_path, monkeypatch):
    import ui.settings as sw
    from PySide6.QtWidgets import QApplication
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)

    workers = []

    class FakeWorker:
        def __init__(self, s, k):
            self.signals = sw._ModelListSignals()
            workers.append(self)

        def start(self):
            pass

        def wait(self, ms=5000):
            return True

    monkeypatch.setattr(sw, "_ModelListWorker", FakeWorker)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._fetch_ai_models()  # fetch #1
    win._fetch_ai_models()  # fetch #2
    assert len(workers) == 2
    # A stale fetch (superseded provider) must not refill the AI dropdown.
    workers[0].signals.finished.emit(["stale-image-model"])
    assert win._ai_model.findText("stale-image-model") == -1
    workers[1].signals.finished.emit(["fresh-image-model"])
    assert win._ai_model.findText("fresh-image-model") >= 0
    win.hide()
    win.deleteLater()


def test_ai_generate_gated_on_model_and_photo(tmp_path):
    from PySide6.QtWidgets import QApplication

    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    win._pack_path.setText("/tmp/photo.png")
    win._pack_name.setText("photo")
    win._ai_model.setCurrentText("")
    assert not win._ai_generate.isEnabled()
    win._ai_model.setCurrentText("gpt-image-1")
    assert win._ai_generate.isEnabled()
    win._pack_path.setText("")
    assert not win._ai_generate.isEnabled()
    win.hide()
    win.deleteLater()


def test_ai_generate_success_reuses_pack_built_slot(tmp_path, monkeypatch):
    import json
    import threading

    from PySide6.QtWidgets import QApplication

    import ui.settings as sw
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    cfg = tmp_path / "cfg"
    bundle = tmp_path / "bundle_assets"
    (bundle / "avatars").mkdir(parents=True)
    monkeypatch.setattr("core.paths.assets_dir", lambda: bundle)
    monkeypatch.setattr("core.paths.config_dir", lambda: cfg)

    def fake_build(photo, out, name, generate, *, progress=None, cancelled=None):
        out.mkdir(parents=True, exist_ok=True)
        (out / "manifest.json").write_text(json.dumps({"name": name, "states": {}}))
        for state, i, n in [("idle", 1, 5), ("thinking", 2, 5), ("working", 3, 5),
                            ("speaking", 4, 5), ("error", 5, 5)]:
            if progress:
                progress(state, i, n)
        return out

    monkeypatch.setattr(sw, "build_ai_pack", fake_build)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"fake")
    win._pack_path.setText(str(photo))
    win._pack_name.setText("Ai Hero")
    win._ai_model.setCurrentText("gpt-image-1")
    win._start_ai_pack()
    assert win._ai_worker is not None
    assert win._ai_worker.wait(5000)
    for _ in range(50):
        app.processEvents()
        if win._avatar.findText("ai_hero") >= 0:
            break
        threading.Event().wait(0.05)
    assert win._avatar.findText("ai_hero") >= 0
    from ui.i18n import i18n

    assert win._status.text() == i18n.t("settings.ai_success", name="ai_hero")
    win.hide()
    win.deleteLater()


def test_ai_generate_cancel_removes_partial_and_reenables(tmp_path, monkeypatch):
    import threading

    from PySide6.QtWidgets import QApplication

    import ui.settings as sw
    from ui.avatar.ai_pack import AiPackCancelled
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    cfg = tmp_path / "cfg"
    bundle = tmp_path / "bundle_assets"
    (bundle / "avatars").mkdir(parents=True)
    monkeypatch.setattr("core.paths.assets_dir", lambda: bundle)
    monkeypatch.setattr("core.paths.config_dir", lambda: cfg)

    gate = threading.Event()
    started = threading.Event()

    def blocking_build(photo, out, name, generate, *, progress=None, cancelled=None):
        started.set()
        gate.wait(5)
        raise AiPackCancelled()

    monkeypatch.setattr(sw, "build_ai_pack", blocking_build)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"fake")
    win._pack_path.setText(str(photo))
    win._pack_name.setText("cxl")
    win._ai_model.setCurrentText("gpt-image-1")
    win._start_ai_pack()
    assert started.wait(5)
    win._ai_worker.cancel()
    gate.set()
    assert win._ai_worker.wait(5000)
    for _ in range(50):
        app.processEvents()
        if win._ai_generate.isEnabled():
            break
        threading.Event().wait(0.05)
    assert win._ai_generate.isEnabled()
    assert not (cfg / "avatars" / "cxl").exists()
    win.hide()
    win.deleteLater()


def test_ai_generate_failure_shows_status(tmp_path, monkeypatch):
    import threading

    from PySide6.QtWidgets import QApplication

    import ui.settings as sw
    from core.providers.image_gen import ImageGenError
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    cfg = tmp_path / "cfg"
    bundle = tmp_path / "bundle_assets"
    (bundle / "avatars").mkdir(parents=True)
    monkeypatch.setattr("core.paths.assets_dir", lambda: bundle)
    monkeypatch.setattr("core.paths.config_dir", lambda: cfg)

    def failing_build(photo, out, name, generate, *, progress=None, cancelled=None):
        raise ImageGenError("429 rate limited", status_code=429)

    monkeypatch.setattr(sw, "build_ai_pack", failing_build)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"fake")
    win._pack_path.setText(str(photo))
    win._pack_name.setText("boom")
    win._ai_model.setCurrentText("gpt-image-1")
    win._start_ai_pack()
    assert win._ai_worker.wait(5000)
    for _ in range(50):
        app.processEvents()
        if "429" in win._status.text():
            break
        threading.Event().wait(0.05)
    assert "429" in win._status.text()
    assert win._ai_generate.isEnabled()
    win.hide()
    win.deleteLater()


def test_ai_generate_locked_while_worker_running(tmp_path, monkeypatch):
    # Review Important #2: textChanged (or a catalog refresh) during a run
    # must not re-enable the AI Generate button — no second concurrent worker.
    import threading

    from PySide6.QtWidgets import QApplication

    import ui.settings as sw
    from ui.avatar.ai_pack import AiPackCancelled
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    cfg = tmp_path / "cfg"
    bundle = tmp_path / "bundle_assets"
    (bundle / "avatars").mkdir(parents=True)
    monkeypatch.setattr("core.paths.assets_dir", lambda: bundle)
    monkeypatch.setattr("core.paths.config_dir", lambda: cfg)

    gate = threading.Event()
    started = threading.Event()

    def blocking_build(photo, out, name, generate, *, progress=None, cancelled=None):
        started.set()
        gate.wait(5)
        raise AiPackCancelled()

    monkeypatch.setattr(sw, "build_ai_pack", blocking_build)
    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"fake")
    win._pack_path.setText(str(photo))
    win._pack_name.setText("lock")
    win._ai_model.setCurrentText("gpt-image-1")
    win._start_ai_pack()
    assert started.wait(5)
    # A catalog refresh restores the model text mid-run; the button must
    # stay locked.
    win._on_ai_models_loaded(["gpt-image-1"], win._ai_fetch_gen)
    assert not win._ai_generate.isEnabled()
    other = tmp_path / "photo2.png"
    other.write_bytes(b"fake2")
    win._pack_path.setText(str(other))  # textChanged mid-run
    assert not win._ai_generate.isEnabled()
    gate.set()
    assert win._ai_worker.wait(5000)
    for _ in range(50):
        app.processEvents()
        if win._ai_generate.isEnabled():
            break
        threading.Event().wait(0.05)
    # Terminal state unlocks again.
    assert win._ai_generate.isEnabled()
    win.hide()
    win.deleteLater()


def test_ai_privacy_hint_label_present(tmp_path):
    # Review Important #3: the plan requires a privacy hint row on the avatar
    # tab — photo/prompts go only to the selected provider.
    from PySide6.QtWidgets import QApplication, QLabel

    from ui.i18n import i18n
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    win = SettingsWindow(settings, secrets, ui_json)
    assert isinstance(win._ai_privacy, QLabel)
    assert win._ai_privacy.text() == i18n.t("settings.ai_privacy")
    win.hide()
    win.deleteLater()


def test_start_ai_pack_fails_fast_on_existing_name(tmp_path, monkeypatch):
    # Critical #1 UI side: an existing pack name must surface pack_exists
    # immediately, without starting a generation worker.
    from PySide6.QtWidgets import QApplication

    from ui.i18n import i18n
    from ui.settings import SettingsWindow

    app = QApplication.instance() or QApplication([])
    settings, secrets, ui_json = _make_settings_files(tmp_path)
    cfg = tmp_path / "cfg"
    bundle = tmp_path / "bundle_assets"
    (bundle / "avatars").mkdir(parents=True)
    monkeypatch.setattr("core.paths.assets_dir", lambda: bundle)
    monkeypatch.setattr("core.paths.config_dir", lambda: cfg)
    existing = cfg / "avatars" / "taken"
    existing.mkdir(parents=True)

    win = SettingsWindow(settings, secrets, ui_json)
    win.load()
    photo = tmp_path / "photo.png"
    photo.write_bytes(b"fake")
    win._pack_path.setText(str(photo))
    win._pack_name.setText("taken")
    win._ai_model.setCurrentText("gpt-image-1")
    win._start_ai_pack()
    assert getattr(win, "_ai_worker", None) is None
    assert win._status.text() == i18n.t("settings.pack_exists", name="taken")
    win.hide()
    win.deleteLater()
