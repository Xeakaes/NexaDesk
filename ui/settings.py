"""Settings window v2: general (lang/theme/mode), provider, screen, perms, packs."""

from __future__ import annotations

import json
import os
import queue
import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
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

from ui.avatar.ai_pack import AiPackCancelled, build_ai_pack
from ui.avatar.pack import PackError, build_pack, delete_pack, sanitize_pack_name
from core.auth.github_device import poll_for_token, request_device_code
from core.providers.image_gen import ImageGenClient
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
    """Shared signal carrier for pack builds; created parented on the UI thread."""

    succeeded = Signal(str)  # pack name
    failed = Signal(str, str, str)  # name, kind, detail (B41)


class _PackBuildWorker:
    """Runs build_pack on a plain thread and reports via Qt signals.

    A plain ``threading.Thread`` (not ``QThread``) is used deliberately: the
    PySide6 ``QThread`` teardown + queued-signal delivery race segfaults on
    some CI runners. The signals live on a separate ``QObject`` whose thread
    affinity is the UI thread, so emitting from the worker thread is queued
    safely and no Qt object is destroyed mid-delivery.
    """

    def __init__(
        self, src: Path, out: Path, name: str, signals: _PackSignals
    ) -> None:
        # B61: the signal carrier is created on the UI thread, parented to
        # the window, and shared by all jobs — a per-job unparented carrier
        # destroyed on the worker thread while its queued MetaCall event was
        # still in flight segfaults (measured 6/6; shared+parented is 0/6).
        self.signals = signals
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
            # B41: keep the real reason — "exists" vs everything else, with
            # the PackError text as detail for the status line.
            kind = "exists" if "exists" in str(exc) else "bad_image"
            self.signals.failed.emit(self._name, kind, str(exc))
        except Exception as exc:  # noqa: BLE001 — surface any failure detail
            self.signals.failed.emit(self._name, "error", str(exc))
        else:
            self.signals.succeeded.emit(self._name)


class _ModelListWorker:
    """Fetches the provider's model catalog on a plain background thread.

    B61: results are handed back through a SimpleQueue + Event — no QObject,
    no signal. A per-job signal carrier destroyed on the worker thread while
    its queued MetaCall event was still in flight segfaulted the Settings
    window (use-after-free on the Python subclass wrapper). Plain attribute
    handoff is also unsafe on free-threaded builds, hence the queue.
    """

    def __init__(self, settings: dict, secrets: dict) -> None:
        self.gen = 0
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._done = threading.Event()
        self._settings = settings
        self._secrets = secrets
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def take(self) -> tuple[bool, list | None]:
        """Pop the (error, result) pair once the worker is done."""
        return self._queue.get_nowait()

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
            self._queue.put((True, None))
        else:
            self._queue.put((False, list(models)))
        finally:
            self._done.set()


class _GithubDeviceWorker:
    """Runs the GitHub OAuth device flow off the UI thread (B61-safe).

    Intermediate ``user_code`` (for the status line) rides a second queue so
    the UI can show it while the poll is still waiting for the browser.
    """

    def __init__(self) -> None:
        self.gen = 0
        self._queue: queue.SimpleQueue = queue.SimpleQueue()
        self._done = threading.Event()
        self.code_queue: queue.SimpleQueue = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, daemon=True)

    @property
    def done(self) -> bool:
        return self._done.is_set()

    def take(self) -> tuple[str | None, str | None]:
        """Pop the (error, token) pair once the worker is done."""
        return self._queue.get_nowait()

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        try:
            code = request_device_code()
            self.code_queue.put((code.user_code, code.verification_uri))
            token = poll_for_token(code)
            self._queue.put((None, token))
        except Exception as exc:  # noqa: BLE001 — surface the message in the status line
            self._queue.put((str(exc), None))
        finally:
            self._done.set()


class _AiPackSignals(QObject):
    """Shared signal carrier for AI pack builds; parented on the UI thread."""

    progress = Signal(str, int, int)  # state, index, total
    succeeded = Signal(str)  # pack name
    failed = Signal(str)  # error text
    cancelled = Signal()


class _AiPackWorker:
    """Runs build_ai_pack on a plain thread (same pattern as _PackBuildWorker)."""

    def __init__(
        self,
        src: Path,
        out: Path,
        name: str,
        model: str,
        client,
        signals: _AiPackSignals,
    ) -> None:
        # B61: shared UI-thread parented carrier (see _PackBuildWorker).
        self.signals = signals
        self._src = src
        self._out = out
        self._name = name
        self._model = model
        self._client = client
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def wait(self, ms: int = 5000) -> bool:
        self._thread.join(timeout=ms / 1000.0)
        return not self._thread.is_alive()

    def is_alive(self) -> bool:
        return self._thread.is_alive()

    def cancel(self) -> None:
        self._cancel.set()

    def _run(self) -> None:
        def generate(state: str, prompt: str) -> bytes:
            return self._client.generate(self._model, prompt, photo=self._src)

        try:
            build_ai_pack(
                self._src,
                self._out,
                self._name,
                generate,
                progress=self.signals.progress.emit,
                cancelled=self._cancel.is_set,
            )
        except AiPackCancelled:
            self.signals.cancelled.emit()
        except Exception as exc:  # noqa: BLE001 — surfaced via the failed slot
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(self._name)


def merge_permissions(existing: dict, default: str, per_tool: dict) -> dict:
    merged = dict(existing)
    merged["*"] = default
    for tool, level in per_tool.items():
        if level == default:
            # B65: a row equal to the default is not written; check() falls
            # through to "*" so the default actually takes effect.
            merged.pop(tool, None)
        else:
            merged[tool] = level
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
        self._update_check_cb = QCheckBox(self)
        general_form.addRow("", self._update_check_cb)
        self._notify_cb = QCheckBox(self)
        general_form.addRow("", self._notify_cb)
        self._close_to_tray_cb = QCheckBox(self)
        general_form.addRow("", self._close_to_tray_cb)
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
        self._provider_warning = QLabel(self)
        self._provider_warning.setWordWrap(True)
        self._provider_warning.setVisible(False)
        provider_form.addRow("", self._provider_warning)
        # Shown only for provider type "github": one-click Copilot sign-in
        # via the official OAuth device flow (gh CLI app, no PAT paste).
        self._github_login = QPushButton(self)
        self._github_login.setVisible(False)
        provider_form.addRow("", self._github_login)
        provider_form.addRow(self._lbl_provider_url, self._provider_url)
        provider_form.addRow(self._lbl_provider_model, model_row)
        provider_form.addRow(self._lbl_provider_key, self._provider_key)
        provider_box = QGroupBox(self)
        provider_box.setLayout(provider_form)
        self._model_worker: _ModelListWorker | None = None
        self._model_fetch_gen = 0  # B23: latest catalog fetch wins
        self._ai_model_worker: _ModelListWorker | None = None
        self._btn_refresh_models.clicked.connect(self._fetch_models)
        self._provider_type.currentTextChanged.connect(self._on_provider_type_changed)
        self._github_device_worker: _GithubDeviceWorker | None = None
        self._github_device_gen = 0  # B23 parity: latest sign-in wins
        self._github_browser_gen = 0  # open the browser once per sign-in
        self._github_login.clicked.connect(self._start_github_login)

        # --- screen control section ---
        self._sc_host = QLineEdit(self)
        self._sc_port = QSpinBox(self)
        self._sc_port.setRange(1, 65535)
        self._sc_key = QLineEdit(self)
        self._sc_key.setEchoMode(QLineEdit.EchoMode.Password)
        # B70: screen_control.enabled existed in the schema but the GUI had
        # no switch for it — a server could not be turned off from Settings.
        self._sc_enabled = QCheckBox(self)
        sc_form = QFormLayout()
        self._lbl_sc_host = QLabel(self)
        self._lbl_sc_port = QLabel(self)
        self._lbl_sc_key = QLabel(self)
        self._lbl_sc_enabled = QLabel(self)
        sc_form.addRow(self._lbl_sc_enabled, self._sc_enabled)
        sc_form.addRow(self._lbl_sc_host, self._sc_host)
        sc_form.addRow(self._lbl_sc_port, self._sc_port)
        sc_form.addRow(self._lbl_sc_key, self._sc_key)
        sc_box = QGroupBox(self)
        sc_box.setLayout(sc_form)

        # --- permissions section ---
        self._perm_default = QComboBox(self)
        self._perm_default.addItems(PERMISSION_LEVELS)
        self._perm_default_prev = self._perm_default.currentText()
        self._perm_default.currentTextChanged.connect(self._on_perm_default_changed)
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
        self._ai_model = QComboBox(self)
        self._ai_model.setEditable(True)
        self._ai_url = QLineEdit(self)
        self._lbl_ai_url = QLabel(self)
        self._ai_generate = QPushButton(self)
        self._ai_cancel = QPushButton(self)
        self._ai_cancel.hide()
        self._ai_privacy = QLabel(self)
        self._ai_privacy.setObjectName("muted")
        avatar_form = QFormLayout()
        self._lbl_avatar = QLabel(self)
        self._lbl_pack_photo = QLabel(self)
        self._lbl_pack_name = QLabel(self)
        self._lbl_ai_model = QLabel(self)
        avatar_form.addRow(self._lbl_avatar, self._avatar)
        avatar_form.addRow(self._lbl_pack_photo, self._pack_path)
        avatar_form.addRow(self._lbl_pack_name, self._pack_name)
        avatar_form.addRow("", self._pack_pick)
        avatar_form.addRow("", self._pack_build)
        avatar_form.addRow("", self._pack_delete)
        avatar_form.addRow(self._lbl_ai_model, self._ai_model)
        avatar_form.addRow(self._lbl_ai_url, self._ai_url)
        avatar_form.addRow("", self._ai_generate)
        avatar_form.addRow("", self._ai_cancel)
        avatar_form.addRow("", self._ai_privacy)
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
        self._ai_generate.setEnabled(False)
        self._ai_model.editTextChanged.connect(self._update_build_enabled)
        self._ai_generate.clicked.connect(self._start_ai_pack)
        self._ai_cancel.clicked.connect(self._cancel_ai_pack)
        self._ai_fetch_gen = 0  # F2: latest AI catalog fetch wins

        language_bridge.changed.connect(self._on_language_changed)

        # B61: model-fetch results are drained on the UI thread — a worker
        # thread's cross-thread signal emit segfaults frozen builds.
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._poll_workers)
        self._poll_timer.start()

        # B61: one shared, window-parented carrier per pack worker family —
        # created and connected on the UI thread, never destroyed mid-emit.
        self._pack_signals = _PackSignals(self)
        self._pack_signals.succeeded.connect(self._on_pack_built)
        self._pack_signals.failed.connect(self._on_pack_failed)
        self._ai_pack_signals = _AiPackSignals(self)
        self._ai_pack_signals.progress.connect(self._on_ai_progress)
        self._ai_pack_signals.succeeded.connect(self._on_ai_succeeded)
        self._ai_pack_signals.failed.connect(self._on_ai_failed)
        self._ai_pack_signals.cancelled.connect(self._on_ai_cancelled)

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
        self._update_check_cb.setText(t("settings.update_check"))
        self._notify_cb.setText(t("settings.notify"))
        self._close_to_tray_cb.setText(t("settings.close_to_tray"))
        self._lbl_provider_type.setText(t("settings.provider_type"))
        self._provider_warning.setText(t("settings.github_unofficial"))
        self._lbl_provider_url.setText(t("settings.provider_url"))
        self._lbl_provider_model.setText(t("settings.provider_model"))
        self._btn_refresh_models.setText(t("settings.refresh_models"))
        self._lbl_provider_key.setText(t("settings.provider_key"))
        self._github_login.setText(t("settings.github_login"))
        self._lbl_sc_host.setText(t("settings.sc_host"))
        self._lbl_sc_port.setText(t("settings.sc_port"))
        self._lbl_sc_key.setText(t("settings.sc_key"))
        self._lbl_sc_enabled.setText(t("settings.sc_enabled"))
        self._lbl_perm_default.setText(t("settings.perm_default"))
        self._lbl_avatar.setText(t("settings.section_avatar"))
        self._lbl_pack_photo.setText(t("settings.pack_pick"))
        self._lbl_pack_name.setText(t("settings.pack_name"))
        self._lbl_ai_model.setText(t("settings.ai_model"))
        self._lbl_ai_url.setText(t("settings.ai_url"))
        self._ai_url.setPlaceholderText(t("settings.ai_url_placeholder"))
        self._ai_generate.setText(t("settings.ai_generate"))
        self._ai_cancel.setText(t("settings.ai_cancel"))
        self._ai_privacy.setText(t("settings.ai_privacy"))
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
        ptype = self._provider_type.currentText()
        key_name = PROVIDER_KEY_SECRETS.get(ptype, "api_key")
        secrets = self._read(self._secrets_path)
        self._provider_key.setText(str(secrets.get(key_name, "")))
        # B18: a custom URL from the previous provider must not survive a
        # type change — saving would send the new provider's key to that host.
        from core.providers import preset_url

        self._provider_url.setText(preset_url(ptype))
        # B64: same reasoning for the model — keeping "llama3.2" after a
        # switch to groq sends a request the new catalog never knew.
        # _on_models_loaded refills from the new catalog (empty current
        # text means nothing to re-apply). Qt quirk: clear() leaves the
        # line-edit text behind when the box has no items yet, so reset
        # the editor explicitly.
        self._provider_model.clear()
        self._provider_model.setEditText("")
        self._provider_warning.setVisible(ptype == "github")
        self._github_login.setVisible(ptype == "github")
        self._fetch_models()
        self._fetch_ai_models()

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
        self._model_fetch_gen += 1
        self._model_worker.gen = self._model_fetch_gen
        self._model_worker.start()
        self._poll_timer.start()

    def _on_models_loaded(self, models: list, gen: int | None = None) -> None:
        if gen is not None and gen != self._model_fetch_gen:
            # B23: a superseded fetch (previous provider type) must not
            # overwrite the dropdown the user is looking at now.
            return
        self._btn_refresh_models.setEnabled(True)
        current = self._provider_model.currentText().strip()
        self._provider_model.clear()
        self._provider_model.addItems(models)
        if current:
            # Keep whatever the user had (typed or selected) as the value.
            self._provider_model.setCurrentText(current)

    def _on_models_failed(self, gen: int | None = None) -> None:
        if gen is not None and gen != self._model_fetch_gen:
            return
        self._btn_refresh_models.setEnabled(True)

    def _fetch_ai_models(self) -> None:
        """Fill the AI image-model dropdown from the provider catalog (F2)."""
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
        self._ai_model_worker = _ModelListWorker(settings, secrets)
        self._ai_fetch_gen += 1
        self._ai_model_worker.gen = self._ai_fetch_gen
        self._ai_model_worker.start()
        self._poll_timer.start()

    def _on_ai_models_loaded(self, models: list, gen: int | None = None) -> None:
        if gen is not None and gen != self._ai_fetch_gen:
            # A superseded fetch must not overwrite the AI dropdown (B23 idiom).
            return
        from core.providers.image_gen import is_image_model

        image_models = [m for m in models if is_image_model(m)]
        current = self._ai_model.currentText().strip()
        self._ai_model.clear()
        self._ai_model.addItems(image_models)
        if current:
            self._ai_model.setCurrentText(current)

    def _on_ai_models_failed(self, gen: int | None = None) -> None:
        if gen is not None and gen != self._ai_fetch_gen:
            return

    def _poll_workers(self) -> None:
        """Drain finished model-fetch workers on the UI thread (B61)."""
        self._drain_worker(
            "_model_worker", "_model_fetch_gen",
            self._on_models_loaded, self._on_models_failed,
        )
        self._drain_worker(
            "_ai_model_worker", "_ai_fetch_gen",
            self._on_ai_models_loaded, self._on_ai_models_failed,
        )
        self._drain_github_login()
        if (
            self._model_worker is None
            and self._ai_model_worker is None
            and self._github_device_worker is None
        ):
            self._poll_timer.stop()

    def _drain_github_login(self) -> None:
        """Surface the user_code immediately; apply the token when ready."""
        worker = self._github_device_worker
        if worker is None:
            return
        while not worker.code_queue.empty():
            user_code, uri = worker.code_queue.get_nowait()
            if worker.gen == self._github_device_gen:
                self._status.setText(
                    f"{i18n.t('settings.github_device_code')} {user_code}  ({uri})"
                )
                if self._github_browser_gen != worker.gen:
                    self._github_browser_gen = worker.gen
                    QDesktopServices.openUrl(QUrl(uri))
        if not worker.done:
            return
        error, token = worker.take()  # always pop, even for superseded jobs
        self._github_device_worker = None
        if worker.gen != self._github_device_gen:
            return  # superseded sign-in: drop the stale result (B23)
        self._github_login.setEnabled(True)
        if error:
            self._status.setText(f"{i18n.t('settings.github_sign_in_failed')}: {error}")
            return
        secrets = self._read(self._secrets_path)
        secrets["github_api_key"] = token
        self._write(self._secrets_path, secrets, mode=0o600)
        self._provider_key.setText(token)
        self._status.setText(i18n.t("settings.github_signed_in"))

    def _start_github_login(self) -> None:
        """Kick off the GitHub OAuth device flow (background, B61-safe)."""
        if self._github_device_worker is not None:
            return  # one sign-in at a time; the old worker is already running
        self._github_device_gen += 1
        worker = _GithubDeviceWorker()
        worker.gen = self._github_device_gen
        self._github_device_worker = worker
        self._github_login.setEnabled(False)
        self._status.setText(i18n.t("settings.github_device_code"))
        worker.start()
        self._poll_timer.start()

    def _drain_worker(self, worker_attr: str, gen_attr: str, on_ok, on_fail) -> None:
        worker = getattr(self, worker_attr, None)
        if worker is None or not worker.done:
            return
        error, result = worker.take()  # always pop, even for superseded jobs
        setattr(self, worker_attr, None)
        gen = getattr(self, gen_attr)
        if worker.gen != gen:
            return  # superseded fetch (B23): drop the stale result
        if error:
            on_fail(gen)
        else:
            on_ok(result or [], gen)

    def _ai_client(self) -> ImageGenClient:
        """Build an ImageGenClient from the current provider form values."""
        from core.providers import preset_url

        ptype = self._provider_type.currentText()
        base_url = (
            self._ai_url.text().strip()
            or self._provider_url.text().strip()
            or preset_url(ptype)
        )
        key_name = PROVIDER_KEY_SECRETS.get(ptype, "api_key")
        key_value = self._provider_key.text().strip()
        if not key_value:
            key_value = str(self._read(self._secrets_path).get(key_name, ""))
        return ImageGenClient(base_url, key_value)

    def _start_ai_pack(self) -> None:
        src = self._pack_path.text().strip()
        if not src:
            self._status.setText(i18n.t("settings.pack_bad_image"))
            return
        try:
            name = sanitize_pack_name(self._pack_name.text() or Path(src).stem)
        except PackError:
            self._status.setText(i18n.t("settings.pack_bad_image"))
            return
        model = self._ai_model.currentText().strip()
        if not model:
            return
        from core.paths import user_avatars_dir

        out = user_avatars_dir() / name
        if out.exists():
            # Never burn five generations only to collide — and never let
            # cleanup touch an existing user pack (review Critical #1).
            self._status.setText(i18n.t("settings.pack_exists", name=name))
            return
        self._ai_generate.setEnabled(False)
        self._ai_cancel.show()
        self.setCursor(Qt.CursorShape.WaitCursor)
        worker = _AiPackWorker(
            Path(src), out, name, model, self._ai_client(),
            signals=self._ai_pack_signals,
        )
        self._ai_worker = worker
        worker.start()

    def _cancel_ai_pack(self) -> None:
        worker = getattr(self, "_ai_worker", None)
        if worker is not None:
            worker.cancel()

    def _on_ai_progress(self, state: str, index: int, total: int) -> None:
        self._status.setText(
            i18n.t("settings.ai_progress", i=index, total=total, name=state)
        )

    def _on_ai_succeeded(self, name: str) -> None:
        self.unsetCursor()
        self._ai_cancel.hide()
        self._ai_worker = None  # terminal: release the control lock
        self._update_build_enabled()
        self._on_pack_built(name)
        self._status.setText(i18n.t("settings.ai_success", name=name))

    def _on_ai_failed(self, error: str) -> None:
        self.unsetCursor()
        self._ai_cancel.hide()
        self._ai_worker = None
        self._update_build_enabled()
        self._status.setText(i18n.t("settings.ai_failed", error=error))

    def _on_ai_cancelled(self) -> None:
        self.unsetCursor()
        self._ai_cancel.hide()
        self._ai_worker = None
        self._update_build_enabled()
        self._status.setText("")

    def _on_perm_default_changed(self, text: str) -> None:
        # B65: rows that still equal the OLD default follow the new default;
        # rows the user explicitly set (different value) are left alone.
        old = self._perm_default_prev
        self._perm_default_prev = text
        if text == old:
            return
        for combo in self._perm_tools.values():
            if combo.currentText() == old:
                combo.setCurrentText(text)

    def load(self) -> None:
        settings, settings_err = self._read_report(self._settings_path)
        secrets, secrets_err = self._read_report(self._secrets_path)
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
        self._github_login.setVisible(self._provider_type.currentText() == "github")
        self._provider_url.setText(provider.get("url", ""))
        self._provider_model.setCurrentText(provider.get("model", ""))
        key_name = PROVIDER_KEY_SECRETS.get(self._provider_type.currentText(), "api_key")
        self._provider_key.setText(str(secrets.get(key_name, "")))
        # B63: local Ollama needs no key — gate the catalog fetch on the
        # provider, not on a secrets entry that will never exist for it.
        if ptype_saved == "ollama" or secrets.get(key_name):
            self._fetch_models()
            self._fetch_ai_models()
        ai = settings.get("avatar_ai") or {}
        self._ai_url.setText(str(ai.get("url") or ""))
        self._ai_model.setCurrentText(str(ai.get("model", "")))
        sc = settings.get("screen_control") or {}
        self._sc_enabled.setChecked(bool(sc.get("enabled", True)))
        self._sc_host.setText(sc.get("host", "127.0.0.1"))
        self._sc_port.setValue(int(sc.get("port", 8745)))
        self._sc_key.setText(secrets.get("screen_control_api_key", ""))
        perms = settings.get("permissions") or {}
        idx = self._perm_default.findText(perms.get("*", "ask"))
        # B65: loading the default cascades into rows that equal it — that
        # is fine here (rows are about to be set explicitly), but block the
        # signal so the cascade can't fight the per-tool load below.
        self._perm_default.blockSignals(True)
        self._perm_default.setCurrentIndex(max(0, idx))
        self._perm_default.blockSignals(False)
        self._perm_default_prev = self._perm_default.currentText()
        default_level = self._perm_default_prev
        for tool, combo in self._perm_tools.items():
            # B65: an unset tool row shows the DEFAULT level (falls through
            # to "*" in check()), not a hardcoded "ask".
            idx = combo.findText(perms.get(tool, default_level))
            combo.setCurrentIndex(max(0, idx))
        self._avatar.clear()
        self._avatar.addItems(self._list_avatars())
        idx = self._avatar.findText(settings.get("avatar", "base"))
        if idx >= 0:
            self._avatar.setCurrentIndex(idx)
        self._persona.setPlainText(str((settings.get("agent") or {}).get("persona", "")))
        self._update_check_cb.setChecked(
            bool((settings.get("updates") or {}).get("check_enabled", True))
        )
        self._notify_cb.setChecked(
            bool((settings.get("notifications") or {}).get("enabled", True))
        )
        self._close_to_tray_cb.setChecked(
            bool((settings.get("tray") or {}).get("close_to_tray", True))
        )
        # B66: form is populated with defaults, but the user must know the
        # file on disk could not be read (and save() will refuse to touch it).
        read_err = settings_err or secrets_err
        self._status.setText(
            i18n.t("settings.read_error", detail=read_err) if read_err else ""
        )

    def save(self) -> None:
        settings, settings_err = self._read_report(self._settings_path)
        secrets, secrets_err = self._read_report(self._secrets_path)
        # B66: never overwrite an unreadable file with an empty dict — that
        # is silent, total data loss for the user's remaining config.
        read_err = settings_err or secrets_err
        if read_err:
            self._status.setText(i18n.t("settings.read_error", detail=read_err))
            return
        ptype = self._provider_type.currentText()
        # B63: never persist an empty model — "" would shadow the provider
        # default inside create_provider (key-absent is the only case the
        # default applies), so the key is omitted instead.
        provider = {"type": ptype}
        model = self._provider_model.currentText().strip()
        if model:
            provider["model"] = model
        url = self._provider_url.text().strip()
        if url:
            provider["url"] = url
        settings["provider"] = provider
        sc = settings.get("screen_control") or {"enabled": True}
        host = self._sc_host.text().strip() or "127.0.0.1"
        if host not in ("127.0.0.1", "localhost"):
            host = "127.0.0.1"  # docs promise loopback-only; clamp, never expose to LAN
        sc["enabled"] = self._sc_enabled.isChecked()  # B70
        sc["host"] = host
        sc["port"] = int(self._sc_port.value())
        settings["screen_control"] = sc
        per_tool = {tool: combo.currentText() for tool, combo in self._perm_tools.items()}
        settings["permissions"] = merge_permissions(
            settings.get("permissions") or {},
            self._perm_default.currentText(),
            per_tool,
        )
        settings["avatar"] = self._avatar.currentText() or "base"
        settings["avatar_ai"] = {
            "model": self._ai_model.currentText().strip(),
            "url": self._ai_url.text().strip(),
        }
        agent = settings.get("agent") or {}
        agent["persona"] = self._persona.toPlainText().strip()
        settings["agent"] = agent
        updates = settings.get("updates") or {}
        updates["check_enabled"] = self._update_check_cb.isChecked()
        settings["updates"] = updates
        notifications = settings.get("notifications") or {}
        notifications["enabled"] = self._notify_cb.isChecked()
        settings["notifications"] = notifications
        tray = settings.get("tray") or {}
        tray["close_to_tray"] = self._close_to_tray_cb.isChecked()
        settings["tray"] = tray
        key_name = PROVIDER_KEY_SECRETS.get(ptype, "api_key")
        key_value = self._provider_key.text().strip()
        if key_value:
            secrets[key_name] = key_value
        secrets["screen_control_api_key"] = self._sc_key.text().strip()
        self._write(self._settings_path, settings)
        self._write(self._secrets_path, secrets, mode=0o600)
        lang = "tr" if self._lang.currentIndex() == 0 else "en"
        # B62: retranslate() localizes the combo labels, so the visible text
        # is "Açık"/"Karanlık" — save the stable token, not the label.
        theme = list(THEMES)[self._theme.currentIndex()]
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
        has_photo = bool(self._pack_path.text().strip()) and bool(self._pack_name.text().strip())
        ai_running = getattr(self, "_ai_worker", None) is not None and self._ai_worker.is_alive()
        # B40: a classic pack build in flight must also lock the button —
        # textChanged used to re-enable it mid-build.
        pack_running = (
            getattr(self, "_pack_worker", None) is not None
            and self._pack_worker.is_alive()
        )
        self._pack_build.setEnabled(has_photo and not ai_running and not pack_running)
        if ai_running:
            # A generation run owns the AI controls; never allow a second worker.
            self._ai_generate.setEnabled(False)
            return
        has_ai = bool(self._pack_path.text().strip()) and bool(
            self._ai_model.currentText().strip()
        )
        self._ai_generate.setEnabled(has_ai)

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
        worker = _PackBuildWorker(Path(src), out, name, signals=self._pack_signals)
        self._pack_worker = worker
        worker.start()

    def _on_pack_built(self, name: str) -> None:
        self.unsetCursor()
        self._pack_worker = None  # terminal: release the build lock (B40)
        self._pack_build.setEnabled(True)
        self._status.setText(i18n.t("settings.pack_success", name=name))
        self._avatar.clear()
        self._avatar.addItems(self._list_avatars())
        idx = self._avatar.findText(name)
        if idx >= 0:
            self._avatar.setCurrentIndex(idx)

    def _on_pack_failed(self, name: str, kind: str, detail: str = "") -> None:
        self.unsetCursor()
        self._pack_worker = None  # terminal: release the build lock (B40)
        self._pack_build.setEnabled(True)
        if kind == "exists":
            self._status.setText(i18n.t("settings.pack_exists", name=name))
        elif kind == "error" and detail:
            # B41: surface the real reason instead of a generic message.
            self._status.setText(detail)
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
        # B61: stop the poll timer, drop worker refs, and join in-flight
        # fetch threads — exiting while a daemon worker is inside OpenSSL
        # (urllib TLS) races libcrypto's atexit cleanup and segfaults.
        self._poll_timer.stop()
        for attr in ("_model_worker", "_ai_model_worker"):
            worker = getattr(self, attr, None)
            if worker is not None:
                worker.wait(500)
                setattr(self, attr, None)
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
    def _read_report(path: Path) -> tuple[dict, str | None]:
        # B66: distinguish "missing" (fine, start empty) from "unreadable"
        # (must never be overwritten with defaults — that is silent data loss).
        if not path.exists():
            return {}, None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}, f"{path.name}: invalid JSON"
        except OSError as exc:
            return {}, f"{path.name}: {exc}"
        if not isinstance(data, dict):
            return {}, f"{path.name}: expected an object"
        return data, None

    @staticmethod
    def _read(path: Path) -> dict:
        # Tolerant read for call sites that only need best-effort values
        # (provider catalogs, avatar packs); load()/save() use _read_report.
        return SettingsWindow._read_report(path)[0]

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
