"""Settings window v2: general (lang/theme/mode), provider, screen, perms, packs."""

from __future__ import annotations

import json
import os
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ui.avatar.pack import PackError, build_pack, delete_pack, sanitize_pack_name
from ui.i18n import i18n, language_bridge
from ui.paths import SECRETS_PATH, SETTINGS_PATH, ui_json_path
from ui.prefs import THEMES, load_prefs, save_prefs, UiPrefs

PROVIDER_TYPES = [
    "ollama",
    "openai_compatible",
    "github",
    "nvidia",
    "groq",
    "google",
    "deepseek",
    "mistral",
    "xai",
    "together",
    "openrouter",
    "nararouter",
]
PERMISSION_LEVELS = ["allow", "ask", "deny"]
KNOWN_TOOLS = [
    "screenshot",
    "ocr_screen",
    "mouse",
    "keyboard",
    "list_windows",
    "focus_window",
]
PROVIDER_KEY_SECRETS = {
    "openai_compatible": "api_key",
    "github": "github_api_key",
    "nvidia": "nvidia_api_key",
    "groq": "groq_api_key",
    "google": "google_api_key",
    "deepseek": "deepseek_api_key",
    "mistral": "mistral_api_key",
    "xai": "xai_api_key",
    "together": "together_api_key",
    "openrouter": "openrouter_api_key",
    "nararouter": "nararouter_api_key",
}


class _PackSignals(QObject):
    """Signal carrier living on the UI thread; safe to emit from any thread."""

    succeeded = Signal(str)  # pack name
    failed = Signal(str, str)  # name, error kind ("exists" | "bad_image" | "error")


class _PackBuildWorker:
    """Runs build_pack on a plain thread and reports via Qt signals.

    A plain ``threading.Thread`` (not ``QThread``) is used deliberately: the
    PySide6 ``QThread`` teardown + queued-signal delivery race segfaults on
    some CI runners. The signals live on a separate ``QObject`` whose thread
    affinity is the UI thread, so emitting from the worker thread is queued
    safely and no Qt object is destroyed mid-delivery.
    """

    def __init__(self, src: Path, out: Path, name: str, parent=None) -> None:
        del parent  # kept for API compat; a plain thread has no Qt parent
        self.signals = _PackSignals()
        self._src = src
        self._out = out
        self._name = name
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wait(self, ms: int = 5000) -> bool:
        """Join the worker thread; True if it finished within the timeout."""
        self._thread.join(timeout=ms / 1000.0)
        return not self._thread.is_alive()

    def _run(self) -> None:
        try:
            build_pack(self._src, self._out, self._name)
        except PackError as exc:
            kind = "exists" if "exists" in str(exc) else "bad_image"
            self.signals.failed.emit(self._name, kind)
        except Exception:
            self.signals.failed.emit(self._name, "error")
        else:
            self.signals.succeeded.emit(self._name)


class _ModelListSignals(QObject):
    """Signal carrier living on the UI thread; safe to emit from any thread."""

    finished = Signal(list)  # model ids
    failed = Signal()


class _ModelListWorker:
    """Fetches the provider's model catalog on a plain background thread.

    Same pattern as _PackBuildWorker: a plain threading.Thread (no QThread
    teardown race) emitting through a UI-thread-affine QObject, so the
    Settings window never blocks on a network round-trip.
    """

    def __init__(self, settings: dict, secrets: dict) -> None:
        self.signals = _ModelListSignals()
        self._settings = settings
        self._secrets = secrets
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wait(self, ms: int = 5000) -> bool:
        """Join the worker thread; True if it finished within the timeout."""
        self._thread.join(timeout=ms / 1000.0)
        return not self._thread.is_alive()

    def _run(self) -> None:
        try:
            from core.providers import create_provider

            provider = create_provider(self._settings, self._secrets)
            models = provider.list_models()
        except Exception:  # noqa: BLE001 — bad key/network: keep the dropdown usable
            self.signals.failed.emit()
        else:
            self.signals.finished.emit(list(models))


def merge_permissions(existing: dict, default: str, per_tool: dict) -> dict:
    merged = dict(existing)
    merged["*"] = default
    merged.update(per_tool)
    return merged


class SettingsWindow(QWidget):
    language_changed = Signal(str)
    theme_changed = Signal(str)
    saved = Signal()

    def __init__(
        self,
        settings_path: Path | None = None,
        secrets_path: Path | None = None,
        ui_json: Path | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("settings_win")
        self.setMinimumWidth(460)
        self._settings_path = settings_path or SETTINGS_PATH
        self._secrets_path = secrets_path or SECRETS_PATH
        self._ui_json = ui_json or ui_json_path()
        self.setAttribute(Qt.WidgetAttribute.WA_QuitOnClose, False)

        # --- general section ---
        self._lang = QComboBox(self)
        self._lang.addItems(["tr", "en"])
        self._theme = QComboBox(self)
        self._theme.addItems(list(THEMES))
        self._mode = QComboBox(self)
        self._mode.addItems(["gui", "avatar"])
        general_form = QFormLayout()
        self._lbl_lang = QLabel(self)
        self._lbl_theme = QLabel(self)
        self._lbl_mode = QLabel(self)
        general_form.addRow(self._lbl_lang, self._lang)
        general_form.addRow(self._lbl_theme, self._theme)
        general_form.addRow(self._lbl_mode, self._mode)
        self._persona = QPlainTextEdit(self)
        self._persona.setPlaceholderText(i18n.t("settings.persona_hint"))
        self._persona.setMinimumHeight(72)
        self._lbl_persona = QLabel(self)
        general_form.addRow(self._lbl_persona, self._persona)
        general_box = QGroupBox(self)
        general_box.setLayout(general_form)

        # --- provider section ---
        self._provider_type = QComboBox(self)
        self._provider_type.addItems(PROVIDER_TYPES)
        self._provider_url = QLineEdit(self)
        # Editable dropdown: picks from the provider catalog, still accepts a
        # hand-typed model id when the catalog fetch fails or lacks it.
        self._provider_model = QComboBox(self)
        self._provider_model.setEditable(True)
        self._btn_refresh_models = QPushButton(self)
        model_row = QWidget(self)
        model_layout = QHBoxLayout(model_row)
        model_layout.setContentsMargins(0, 0, 0, 0)
        model_layout.addWidget(self._provider_model, 1)
        model_layout.addWidget(self._btn_refresh_models)
        self._provider_key = QLineEdit(self)
        self._provider_key.setEchoMode(QLineEdit.EchoMode.Password)
        provider_form = QFormLayout()
        self._lbl_provider_type = QLabel(self)
        self._lbl_provider_url = QLabel(self)
        self._lbl_provider_model = QLabel(self)
        self._lbl_provider_key = QLabel(self)
        provider_form.addRow(self._lbl_provider_type, self._provider_type)
        provider_form.addRow(self._lbl_provider_url, self._provider_url)
        provider_form.addRow(self._lbl_provider_model, model_row)
        provider_form.addRow(self._lbl_provider_key, self._provider_key)
        provider_box = QGroupBox(self)
        provider_box.setLayout(provider_form)
        self._model_worker: _ModelListWorker | None = None
        self._btn_refresh_models.clicked.connect(self._fetch_models)
        self._provider_type.currentTextChanged.connect(self._on_provider_type_changed)

        # --- screen control section ---
        self._sc_host = QLineEdit(self)
        self._sc_port = QSpinBox(self)
        self._sc_port.setRange(1, 65535)
        self._sc_key = QLineEdit(self)
        self._sc_key.setEchoMode(QLineEdit.EchoMode.Password)
        sc_form = QFormLayout()
        self._lbl_sc_host = QLabel(self)
        self._lbl_sc_port = QLabel(self)
        self._lbl_sc_key = QLabel(self)
        sc_form.addRow(self._lbl_sc_host, self._sc_host)
        sc_form.addRow(self._lbl_sc_port, self._sc_port)
        sc_form.addRow(self._lbl_sc_key, self._sc_key)
        sc_box = QGroupBox(self)
        sc_box.setLayout(sc_form)

        # --- permissions section ---
        self._perm_default = QComboBox(self)
        self._perm_default.addItems(PERMISSION_LEVELS)
        self._perm_tools = {}
        perm_form = QFormLayout()
        self._lbl_perm_default = QLabel(self)
        perm_form.addRow(self._lbl_perm_default, self._perm_default)
        for tool in KNOWN_TOOLS:
            combo = QComboBox(self)
            combo.addItems(PERMISSION_LEVELS)
            self._perm_tools[tool] = combo
            lbl = QLabel(tool, self)
            perm_form.addRow(lbl, combo)
        perm_box = QGroupBox(self)
        perm_box.setLayout(perm_form)

        # --- avatar section ---
        self._avatar = QComboBox(self)
        self._pack_path = QLineEdit(self)
        self._pack_name = QLineEdit(self)
        self._pack_pick = QPushButton(self)
        self._pack_build = QPushButton(self)
        self._pack_delete = QPushButton(self)
        avatar_form = QFormLayout()
        self._lbl_avatar = QLabel(self)
        self._lbl_pack_photo = QLabel(self)
        self._lbl_pack_name = QLabel(self)
        avatar_form.addRow(self._lbl_avatar, self._avatar)
        avatar_form.addRow(self._lbl_pack_photo, self._pack_path)
        avatar_form.addRow(self._lbl_pack_name, self._pack_name)
        avatar_form.addRow("", self._pack_pick)
        avatar_form.addRow("", self._pack_build)
        avatar_form.addRow("", self._pack_delete)
        avatar_box = QGroupBox(self)
        avatar_box.setLayout(avatar_form)

        self._status = QLabel("", self)
        self._status.setObjectName("muted")
        self._save_btn = QPushButton(self)
        self._save_btn.clicked.connect(self.save)
        self._close_btn = QPushButton(self)
        self._close_btn.clicked.connect(self.close)
        buttons = QHBoxLayout()
        buttons.addWidget(self._save_btn)
        buttons.addWidget(self._close_btn)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        self._tabs = QTabWidget(self)
        general_box.setFlat(True)
        provider_box.setFlat(True)
        sc_box.setFlat(True)
        perm_box.setFlat(True)
        avatar_box.setFlat(True)
        for box in (general_box, provider_box, sc_box, perm_box, avatar_box):
            box.setTitle("")
        self._tabs.addTab(general_box, i18n.t("settings.section_general"))
        self._tabs.addTab(provider_box, i18n.t("settings.section_provider"))
        self._tabs.addTab(sc_box, i18n.t("settings.section_screen"))
        self._tabs.addTab(perm_box, i18n.t("settings.section_permissions"))
        self._tabs.addTab(avatar_box, i18n.t("settings.section_avatar"))
        layout.addWidget(self._tabs)
        layout.addWidget(self._status)
        layout.addLayout(buttons)

        self._pack_pick.clicked.connect(self._pick_photo)
        self._pack_build.clicked.connect(self._build_pack)
        self._pack_delete.clicked.connect(self._delete_pack)
        self._pack_build.setEnabled(False)
        self._pack_path.textChanged.connect(self._update_build_enabled)
        self._pack_name.textChanged.connect(self._update_build_enabled)

        language_bridge.changed.connect(self._on_language_changed)

        self.load()
        self.retranslate()

    def _on_language_changed(self, lang: str) -> None:
        self.retranslate()
        self.language_changed.emit(lang)

    def retranslate(self) -> None:
        t = i18n.t
        self.setWindowTitle(t("settings.title"))
        self._save_btn.setText(t("settings.save"))
        self._close_btn.setText(t("settings.close"))
        self._pack_pick.setText(t("settings.pack_pick"))
        self._pack_build.setText(t("settings.pack_build"))
        self._pack_delete.setText(t("settings.pack_delete"))
        self._pack_name.setPlaceholderText(t("settings.pack_name"))
        self._lbl_lang.setText(t("settings.lang"))
        self._lbl_theme.setText(t("settings.theme"))
        self._lbl_mode.setText(t("settings.mode"))
        self._lbl_persona.setText(t("settings.persona"))
        self._persona.setPlaceholderText(t("settings.persona_hint"))
        self._lbl_provider_type.setText(t("settings.provider_type"))
        self._lbl_provider_url.setText(t("settings.provider_url"))
        self._lbl_provider_model.setText(t("settings.provider_model"))
        self._btn_refresh_models.setText(t("settings.refresh_models"))
        self._lbl_provider_key.setText(t("settings.provider_key"))
        self._lbl_sc_host.setText(t("settings.sc_host"))
        self._lbl_sc_port.setText(t("settings.sc_port"))
        self._lbl_sc_key.setText(t("settings.sc_key"))
        self._lbl_perm_default.setText(t("settings.perm_default"))
        self._lbl_avatar.setText(t("settings.section_avatar"))
        self._lbl_pack_photo.setText(t("settings.pack_pick"))
        self._lbl_pack_name.setText(t("settings.pack_name"))
        self._lang.setItemText(0, t("settings.lang_tr"))
        self._lang.setItemText(1, t("settings.lang_en"))
        self._theme.setItemText(0, t("settings.theme_dark"))
        self._theme.setItemText(1, t("settings.theme_light"))
        self._mode.setItemText(0, "GUI")
        self._mode.setItemText(1, t("mode.avatar"))
        self._tabs.setTabText(0, t("settings.section_general"))
        self._tabs.setTabText(1, t("settings.section_provider"))
        self._tabs.setTabText(2, t("settings.section_screen"))
        self._tabs.setTabText(3, t("settings.section_permissions"))
        self._tabs.setTabText(4, t("settings.section_avatar"))

    def _on_provider_type_changed(self) -> None:
        # Secret key name follows the provider; then refetch the catalog.
        key_name = PROVIDER_KEY_SECRETS.get(self._provider_type.currentText(), "api_key")
        secrets = self._read(self._secrets_path)
        self._provider_key.setText(str(secrets.get(key_name, "")))
        self._fetch_models()

    def _fetch_models(self) -> None:
        """Fill the model dropdown from the provider catalog (background)."""
        ptype = self._provider_type.currentText()
        key_name = PROVIDER_KEY_SECRETS.get(ptype, "api_key")
        secrets = self._read(self._secrets_path)
        key_value = self._provider_key.text().strip()
        if key_value:
            secrets[key_name] = key_value
        settings = self._read(self._settings_path)
        settings["provider"] = {
            "type": ptype,
            "url": self._provider_url.text().strip(),
            "model": self._provider_model.currentText().strip(),
        }
        self._btn_refresh_models.setEnabled(False)
        self._model_worker = _ModelListWorker(settings, secrets)
        self._model_worker.signals.finished.connect(self._on_models_loaded)
        self._model_worker.signals.failed.connect(self._on_models_failed)
        self._model_worker.start()

    def _on_models_loaded(self, models: list) -> None:
        self._btn_refresh_models.setEnabled(True)
        current = self._provider_model.currentText().strip()
        self._provider_model.clear()
        self._provider_model.addItems(models)
        if current:
            # Keep whatever the user had (typed or selected) as the value.
            self._provider_model.setCurrentText(current)

    def _on_models_failed(self) -> None:
        self._btn_refresh_models.setEnabled(True)

    def load(self) -> None:
        settings = self._read(self._settings_path)
        secrets = self._read(self._secrets_path)
        prefs = load_prefs(self._ui_json)
        self._lang.setCurrentIndex(0 if prefs.lang == "tr" else 1)
        self._theme.setCurrentIndex(list(THEMES).index(prefs.theme))
        self._mode.setCurrentIndex(0 if (prefs.mode or "gui") == "gui" else 1)
        provider = settings.get("provider") or {}
        ptype_saved = provider.get("type", "ollama")
        if ptype_saved == "openai_compat":  # legacy value, pre-rename
            ptype_saved = "openai_compatible"
        self._provider_type.blockSignals(True)
        idx = self._provider_type.findText(ptype_saved)
        self._provider_type.setCurrentIndex(max(0, idx))
        self._provider_type.blockSignals(False)
        self._provider_url.setText(provider.get("url", ""))
        self._provider_model.setCurrentText(provider.get("model", ""))
        key_name = PROVIDER_KEY_SECRETS.get(self._provider_type.currentText(), "api_key")
        self._provider_key.setText(str(secrets.get(key_name, "")))
        if secrets.get(key_name):
            self._fetch_models()
        sc = settings.get("screen_control") or {}
        self._sc_host.setText(sc.get("host", "127.0.0.1"))
        self._sc_port.setValue(int(sc.get("port", 8745)))
        self._sc_key.setText(secrets.get("screen_control_api_key", ""))
        perms = settings.get("permissions") or {}
        idx = self._perm_default.findText(perms.get("*", "ask"))
        self._perm_default.setCurrentIndex(max(0, idx))
        for tool, combo in self._perm_tools.items():
            idx = combo.findText(perms.get(tool, "ask"))
            combo.setCurrentIndex(max(0, idx))
        self._avatar.clear()
        self._avatar.addItems(self._list_avatars())
        idx = self._avatar.findText(settings.get("avatar", "base"))
        if idx >= 0:
            self._avatar.setCurrentIndex(idx)
        self._persona.setPlainText(str((settings.get("agent") or {}).get("persona", "")))
        self._status.setText("")

    def save(self) -> None:
        settings = self._read(self._settings_path)
        secrets = self._read(self._secrets_path)
        # Never overwrite an unreadable secrets file with an empty dict (would wipe keys).
        if self._secrets_path.exists():
            try:
                json.loads(self._secrets_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._status.setText(i18n.t("settings.pack_bad_image"))
                return
        ptype = self._provider_type.currentText()
        provider = {"type": ptype, "model": self._provider_model.currentText().strip()}
        url = self._provider_url.text().strip()
        if url:
            provider["url"] = url
        settings["provider"] = provider
        sc = settings.get("screen_control") or {"enabled": True}
        sc["host"] = self._sc_host.text().strip() or "127.0.0.1"
        sc["port"] = int(self._sc_port.value())
        settings["screen_control"] = sc
        per_tool = {tool: combo.currentText() for tool, combo in self._perm_tools.items()}
        settings["permissions"] = merge_permissions(
            settings.get("permissions") or {},
            self._perm_default.currentText(),
            per_tool,
        )
        settings["avatar"] = self._avatar.currentText() or "base"
        agent = settings.get("agent") or {}
        agent["persona"] = self._persona.toPlainText().strip()
        settings["agent"] = agent
        key_name = PROVIDER_KEY_SECRETS.get(ptype, "api_key")
        key_value = self._provider_key.text().strip()
        if key_value:
            secrets[key_name] = key_value
        secrets["screen_control_api_key"] = self._sc_key.text().strip()
        self._write(self._settings_path, settings)
        self._write(self._secrets_path, secrets, mode=0o600)
        lang = "tr" if self._lang.currentIndex() == 0 else "en"
        theme = self._theme.currentText()
        mode = "gui" if self._mode.currentIndex() == 0 else "avatar"
        old = load_prefs(self._ui_json)
        save_prefs(self._ui_json, UiPrefs(mode=mode, theme=theme, lang=lang))
        if lang != i18n.current:
            i18n.set_language(lang)
            self.language_changed.emit(lang)
            self.retranslate()
        if theme != old.theme:
            self.theme_changed.emit(theme)
        self._status.setText(i18n.t("settings.save_restart_note"))
        self.saved.emit()

    def show_provider_tab(self) -> None:
        """Load, raise the window, and jump to the provider tab (first-run setup)."""
        self.load()
        self._tabs.setCurrentIndex(1)
        self.show()
        self.raise_()

    def _update_build_enabled(self, *_a) -> None:
        ok = bool(self._pack_path.text().strip()) and bool(self._pack_name.text().strip())
        self._pack_build.setEnabled(ok)

    def _pick_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, i18n.t("settings.pack_pick"), str(Path.home()), "Images (*.png *.jpg *.jpeg)"
        )
        if path:
            self._pack_path.setText(path)
            if not self._pack_name.text().strip():
                self._pack_name.setText(Path(path).stem)

    def _build_pack(self) -> None:
        src = self._pack_path.text().strip()
        if not src:
            self._status.setText(i18n.t("settings.pack_bad_image"))
            return
        try:
            name = sanitize_pack_name(self._pack_name.text() or Path(src).stem)
        except PackError:
            self._status.setText(i18n.t("settings.pack_bad_image"))
            return
        from core.paths import user_avatars_dir

        avatars_root = user_avatars_dir()
        out = avatars_root / name
        # Build on a background thread so the UI stays responsive.
        self._pack_build.setEnabled(False)
        self.setCursor(Qt.CursorShape.WaitCursor)
        worker = _PackBuildWorker(Path(src), out, name, parent=self)
        self._pack_worker = worker
        worker.signals.succeeded.connect(self._on_pack_built)
        worker.signals.failed.connect(self._on_pack_failed)
        worker.start()

    def _on_pack_built(self, name: str) -> None:
        self.unsetCursor()
        self._pack_build.setEnabled(True)
        self._status.setText(i18n.t("settings.pack_success", name=name))
        self._avatar.clear()
        self._avatar.addItems(self._list_avatars())
        idx = self._avatar.findText(name)
        if idx >= 0:
            self._avatar.setCurrentIndex(idx)

    def _on_pack_failed(self, name: str, kind: str) -> None:
        self.unsetCursor()
        self._pack_build.setEnabled(True)
        if kind == "exists":
            self._status.setText(i18n.t("settings.pack_exists", name=name))
        else:
            self._status.setText(i18n.t("settings.pack_bad_image"))

    def _delete_pack(self) -> None:
        name = self._avatar.currentText().strip()
        if not name:
            return
        if name == "base":
            self._status.setText(i18n.t("settings.pack_delete_builtin"))
            return
        answer = QMessageBox.question(
            self,
            i18n.t("settings.pack_delete"),
            i18n.t("settings.pack_delete_confirm", name=name),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        from core.paths import user_avatars_dir

        try:
            delete_pack(user_avatars_dir(), name)
        except PackError as exc:
            msg = (
                i18n.t("settings.pack_delete_builtin")
                if "built-in" in str(exc)
                else i18n.t("settings.pack_delete_failed", name=name)
            )
            self._status.setText(msg)
            return
        self._status.setText(i18n.t("settings.pack_deleted", name=name))
        current = self._avatar.currentText()
        self._avatar.clear()
        self._avatar.addItems(self._list_avatars())
        if current == name:
            idx = self._avatar.findText("base")
            if idx >= 0:
                self._avatar.setCurrentIndex(idx)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.hide()
        event.ignore()

    def _list_avatars(self) -> list:
        from core.paths import assets_dir, user_avatars_dir

        names: set[str] = set()
        for root in (assets_dir() / "avatars", user_avatars_dir()):
            if root.is_dir():
                names.update(p.name for p in root.iterdir() if p.is_dir())
        names.add("base")  # built-in always present
        return sorted(names)

    @staticmethod
    def _read(path: Path) -> dict:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _write(path: Path, data: dict, mode=None) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(payload)
            os.replace(tmp, path)
            if mode is not None:
                os.chmod(path, mode)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
