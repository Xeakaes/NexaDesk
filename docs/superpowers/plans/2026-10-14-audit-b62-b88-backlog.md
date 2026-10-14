# NexaDesk Audit Fixes (B62–B88) + Handoff Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix every verified finding of the two audit reports (B62–B88) and then complete the standing §2.2 handoff backlog, keeping the 561-test suite green after every commit.

**Architecture:** Pure TDD against the existing suites. No new modules: fixes land in the files the audits pinpoint (`ui/settings.py`, `ui/app.py`, `ui/gui/main_window.py`, `ui/avatar_app.py`, `vendor/sc_server/sdk.py`, etc.). Each finding becomes one task with its own failing test first, then the minimal fix, then a commit. Six phases ordered by priority exactly as the user approved: P0/P1 → error visibility → P2 → P3 → cross-check findings → backlog.

**Tech Stack:** Python 3.12, PySide6 (offscreen), pytest, ruff. No new dependencies.

**Spec:** `/home/xeakaes/İndirilenler/NexaDesk-Denetim-Raporu.md` (primary, findings B62–B88 with file:line and repro) + `/home/xeakaes/İndirilenler/NexaDesk-ikinci-rapor-capraz-kontrol.md` (§4 false positives must NOT be "fixed") + `/home/xeakaes/Masaüstü/handoff.md` (§2.2 backlog, hard rules).

## Global Constraints

- Baseline: **561 passed** (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q`). Every task's gate: suite still green, no test count regressions (new tests add to the count).
- Chat language Turkish; **all code, comments, commits, docs English**. Never write Turkish in files/commits.
- **Never commit:** `assets/avatars/{max_verstopen,osaka,teto,teto_ekmek}`, `config/settings.json`, `config/logs/`, `config/update_check.json`. Never `git add -A` / `git add .` — explicit paths only.
- No tagging, building or releasing during Phases 1–6. The tag move (Task 32) runs only after the user confirms.
- The 9 false positives from cross-check §4 (stdout guard, server cleanup, DPI awareness, version resolver, SQLite claim, paths facade, mode-switch handoff, live theme, thumbnail claim) are **out of scope** — touching them would break working code.
- Findings marked "optional" (handoff §2.2 item 4) are last; skip them if the user says so mid-run.

## Review Focus

Failure modes the audit spec implies but a careless fix could still ship:

1. **Theme round-trip:** saving "light" then re-reading `ui.json` must yield `load_prefs().theme == "light"` — a fix that only writes the token but lets `retranslate()` regress would reintroduce B62. Pinned in Task 1.
2. **Provider-switch race:** resetting the model on type change must not let a superseded `_on_models_loaded` refill the box (B23 gen guard must still hold). Pinned in Task 3.
3. **Permission semantics end-to-end:** the merged dict must drive `PermissionPolicy.check()` (not just look right in the file) — a unit-only merge test would pass while the app still allows. Pinned in Task 4.
4. **Unreadable settings vs unreadable secrets:** B66's guard must block the save without breaking the window open (load path) — a guard that throws in `__init__` reproduces the original crash. Pinned in Task 5.
5. **Frozen GUI error path:** B67's dialog must appear when `build_runtime` raises a non-key `ProviderError` — QMessageBox must be asserted without blocking (offscreen `exec` + direct button click). Pinned in Task 6.

---

## Phase 1 — Settings save contract (P0: B62–B66)

### Task 1: B62 — save the theme token, not the localized label

**Files:**
- Modify: `ui/settings.py:922` (inside `save()`)
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Produces: `SettingsWindow.save()` writes `theme ∈ {"dark","light"}` to `ui.json`; `theme_changed` signal carries the token.

- [ ] **Step 1: Write the failing test**

```python
def test_save_writes_theme_token_not_label(qt_settings_window):
    w = qt_settings_window          # fixture: real SettingsWindow on temp paths
    w._theme.setCurrentIndex(1)     # light; combo text is localized ("Açık")
    w.save()
    from ui.prefs import load_prefs
    assert load_prefs(w._ui_json).theme == "light"
    raw = json.loads(w._ui_json.read_text(encoding="utf-8"))
    assert raw["theme"] == "light"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_settings.py::test_save_writes_theme_token_not_label -v`
Expected: FAIL — `theme == "dark"` (label "Açık" rejected by `load_prefs`)

- [ ] **Step 3: Implement** in `ui/settings.py:922`

```python
theme = list(THEMES)[self._theme.currentIndex()]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_settings.py::test_save_writes_theme_token_not_label -v` → PASS

- [ ] **Step 5: Full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q` → 562 passed (561 + this test)

- [ ] **Step 6: Commit**

```bash
git add ui/settings.py tests/ui/test_settings.py
git commit -m "fix(settings): save theme token instead of localized label (B62)"
```

### Task 2: B63 — never persist an empty model; fetch the Ollama catalog

**Files:**
- Modify: `ui/settings.py:879` (`save()`), `ui/settings.py:835` (`load()` fetch gate)
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Produces: `settings["provider"]` omits the `model` key when the combo is empty; `load()` calls `_fetch_models()` when the provider type supports `list_models` even without a secrets key.

- [ ] **Step 1: Write the failing tests**

```python
def test_save_omits_empty_provider_model(qt_settings_window):
    w = qt_settings_window
    w._provider_type.setCurrentText("ollama")
    w._provider_model.setCurrentText("")
    w.save()
    provider = json.loads(w._settings_path.read_text(encoding="utf-8"))["provider"]
    assert "model" not in provider
    from core.providers import create_provider
    p = create_provider(json.loads(w._settings_path.read_text()), {}, None)
    assert p.model == "llama3.2"   # provider default survives

def test_load_fetches_models_for_keyless_provider(qt_settings_window, monkeypatch):
    w = qt_settings_window
    w._provider_type.setCurrentText("ollama")
    calls = []
    monkeypatch.setattr(w, "_fetch_models", lambda: calls.append(1))
    monkeypatch.setattr(w, "_fetch_ai_models", lambda: None)
    w.load()   # no secrets key for ollama
    assert calls, "catalog fetch must run for a keyless local provider"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_settings.py -k "empty_provider_model or keyless" -v`
Expected: FAIL — `provider["model"] == ""`; fetch not called

- [ ] **Step 3: Implement**

In `save()` (`ui/settings.py:878-879`):

```python
ptype = self._provider_type.currentText()
model = self._provider_model.currentText().strip()
provider = {"type": ptype}
if model:
    provider["model"] = model
```

In `load()` (`ui/settings.py:835`): replace the secrets-only gate with a type-aware one:

```python
if ptype_saved == "ollama" or secrets.get(key_name):
    self._fetch_models()
    self._fetch_ai_models()
```

- [ ] **Step 4: Run tests to verify they pass** → PASS

- [ ] **Step 5: Full suite** → 564 passed

- [ ] **Step 6: Commit**

```bash
git add ui/settings.py tests/ui/test_settings.py
git commit -m "fix(settings): omit empty provider model and fetch keyless catalogs (B63)"
```

### Task 3: B64 — reset the model when the provider type changes

**Files:**
- Modify: `ui/settings.py:569-583` (`_on_provider_type_changed`)
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Consumes: `_fetch_models()` gen guard (B23) unchanged.
- Produces: after a type change, `_provider_model` holds no stale text.

- [ ] **Step 1: Write the failing test**

```python
def test_provider_type_change_clears_stale_model(qt_settings_window):
    w = qt_settings_window
    w._provider_type.setCurrentText("ollama")
    w._provider_model.setCurrentText("llama3.2")
    w._provider_type.setCurrentText("groq")   # switch type
    assert w._provider_model.currentText().strip() == ""
```

- [ ] **Step 2: Run test to verify it fails** → FAIL (still "llama3.2")

- [ ] **Step 3: Implement** — in `_on_provider_type_changed`, next to the B18 URL reset:

```python
# B64: the previous provider's model id must not survive a type change.
self._provider_model.clear()
```

Keep `self._fetch_models()` after it; `_on_models_loaded` refills from the new catalog and the `current == ""` branch already skips the re-apply.

- [ ] **Step 4: Run test → PASS** · **Step 5: full suite → 565 passed**

- [ ] **Step 6: Commit**

```bash
git add ui/settings.py tests/ui/test_settings.py
git commit -m "fix(settings): clear model combo on provider type change (B64)"
```

### Task 4: B65 — persist only permission entries that differ from the default

**Files:**
- Modify: `ui/settings.py:891-896` (the `merge_permissions` call in `save()`)
- Test: `tests/ui/test_settings_merge.py`

**Interfaces:**
- Consumes: `merge_permissions(existing, default, per_tool)` (unchanged signature), `PermissionPolicy.check()`.

- [ ] **Step 1: Write the failing test**

```python
def test_deny_default_applies_to_known_tools_end_to_end(qt_settings_window):
    w = qt_settings_window
    w._perm_default.setCurrentText("deny")
    for combo in w._perm_tools.values():
        combo.setCurrentText("deny")
    w.save()
    settings = json.loads(w._settings_path.read_text(encoding="utf-8"))
    from core.tools.registry import PermissionPolicy, PermissionLevel
    policy = PermissionPolicy(settings["permissions"])
    assert policy.check("screenshot") is PermissionLevel.DENY
    # per-tool rows equal to the default must not be materialized
    assert "screenshot" not in settings["permissions"]
```

- [ ] **Step 2: Run test to verify it fails** → FAIL (`check("screenshot") == ASK`)

- [ ] **Step 3: Implement** in `save()`:

```python
default_level = self._perm_default.currentText()
per_tool = {t: c.currentText() for t, c in self._perm_tools.items()}
settings["permissions"] = merge_permissions(
    settings.get("permissions") or {},
    default_level,
    {t: v for t, v in per_tool.items() if v != default_level},
)
```

- [ ] **Step 4: Run test → PASS**; also run `tests/ui/test_settings_merge.py` (unknown-tool preservation must stay green)

- [ ] **Step 5: Full suite → 566 passed**

- [ ] **Step 6: Commit**

```bash
git add ui/settings.py tests/ui/test_settings_merge.py
git commit -m "fix(settings): persist only non-default permission rows (B65)"
```

### Task 5: B66 — survive an unreadable/corrupt settings file without silent data loss

**Files:**
- Modify: `ui/settings.py:1074-1081` (`_read`), `ui/settings.py:868-877` (`save()` guard), `ui/settings.py:815` (`load()`)
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Produces: `SettingsWindow._read(path) -> tuple[dict, str | None]` — `(data, error)`; `error` non-None means the file exists but could not be parsed/read. All internal callers updated. `save()` refuses to write when either file has an error; `load()` still populates the form and reports the error in the status line.

- [ ] **Step 1: Write the failing tests**

```python
def test_save_blocked_when_settings_json_corrupt(qt_settings_window, tmp_path):
    w = qt_settings_window
    w._settings_path.write_text("{not json", encoding="utf-8")
    before = w._settings_path.read_text(encoding="utf-8")
    w.save()
    assert w._settings_path.read_text(encoding="utf-8") == before  # not clobbered
    assert w._status.text()                  # user is told

def test_open_settings_survives_unreadable_file(qt_settings_window):
    w = qt_settings_window
    w._settings_path.mkdir()                # a directory: read raises OSError
    sw = SettingsWindow(w._settings_path, w._secrets_path, w._ui_json)  # must not raise
    assert sw._status.text()
```

- [ ] **Step 2: Run tests to verify they fail** → FAIL (`IsADirectoryError` escapes; file clobbered)

- [ ] **Step 3: Implement**

`_read` becomes error-reporting (keeps OSError and JSONDecodeError separate):

```python
@staticmethod
def _read(path: Path) -> tuple[dict, str | None]:
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
```

Every call site becomes `data, err = self._read(path)`. In `load()`: keep the first error in `self._status`. In `save()`: replace the current secrets-only guard with — if `settings_err or secrets_err` → set status (reuse an existing generic error i18n key or add `settings.read_error` in `ui/i18n.py` tr+en) and `return` before any write. Drop the now-redundant inline `json.loads` secrets guard.

- [ ] **Step 4: Run tests → PASS**

- [ ] **Step 5: Full suite** (all `_read` call sites compile) → 568 passed

- [ ] **Step 6: Commit**

```bash
git add ui/settings.py ui/i18n.py tests/ui/test_settings.py
git commit -m "fix(settings): report read errors and never overwrite unreadable config (B66)"
```

### Task 6: B67 — show a dialog for provider errors that are not a missing key

**Files:**
- Modify: `ui/app.py:62-84` (`_build_runtime_or_none`)
- Test: `tests/ui/test_setup_flow.py`

**Interfaces:**
- Consumes: `show_config_error(exc)`, `is_missing_key_error(exc)`.

- [ ] **Step 1: Write the failing test**

```python
def test_unknown_provider_type_shows_dialog_not_silent_exit(monkeypatch):
    import core.bootstrap as bootstrap
    from core.providers.base import ProviderError
    def boom(*a, **k):
        raise ProviderError("unknown provider type: bogus", error_code="unknown_provider")
    monkeypatch.setattr(bootstrap, "build_runtime", boom)
    import ui.app as ui_app
    monkeypatch.setattr(ui_app, "show_config_error", lambda exc: setattr(boom, "shown", exc))
    assert ui_app._build_runtime_or_none() is None
    assert getattr(boom, "shown", None) is not None
```

- [ ] **Step 2: Run → FAIL** (`ProviderError` propagates out of `_build_runtime_or_none`)

- [ ] **Step 3: Implement** — widen the outer handler in `_build_runtime_or_none`:

```python
except ConfigError as exc:
    show_config_error(exc); return None
except ProviderError as exc:      # B67: any other provider failure (bad type,
    show_config_error(exc)        # broken URL) must not kill the GUI silently
    return None
```

(`show_config_error` already formats `exc`; no i18n change needed.)

- [ ] **Step 4: Run → PASS** · **Step 5: full suite → 569 passed**

- [ ] **Step 6: Commit**

```bash
git add ui/app.py tests/ui/test_setup_flow.py
git commit -m "fix(app): show a dialog for non-key provider errors in GUI mode (B67)"
```

---

## Phase 2 — Error visibility (P1: B68–B69)

### Task 7: B68 — surface the tool error reason in the transcript

**Files:**
- Modify: `ui/gui/main_window.py:661-668` (`tool_finished` branch), `ui/avatar_app.py:292-299`
- Test: `tests/ui/test_chat.py`

**Interfaces:**
- Consumes: runtime payload `{"tool_name","ok","summary","error_code"}` (`core/agent/runtime.py:506,528`).
- Produces: on failure the line reads `screenshot bitti (Hata): <summary>` truncated to ~120 chars, full text as tooltip.

- [ ] **Step 1: Write the failing test**

```python
def test_tool_failure_shows_summary(chat_window):
    # feed a tool_finished event with ok=False and a reason
    ev = FakeEvent("tool_finished", session_id=chat_window._session_id,
                   payload={"tool_name": "screenshot", "ok": False,
                            "summary": "server_unreachable: no reply on 8745",
                            "error_code": "server_unreachable"})
    chat_window._on_event(ev)
    text = chat_window._messages[-1]["text"]
    assert "server_unreachable" in text
```

- [ ] **Step 2: Run → FAIL** (line is only `… (Hata)`)

- [ ] **Step 3: Implement** in both handlers:

```python
line = i18n.t(key, name=name)
if not ok:
    summary = str(payload.get("summary") or "")
    if summary and summary != "ok":
        line = f"{line}: {summary[:120]}"
```

- [ ] **Step 4: Run → PASS** · **Step 5: full suite → 570 passed**

- [ ] **Step 6: Commit**

```bash
git add ui/gui/main_window.py ui/avatar_app.py tests/ui/test_chat.py
git commit -m "feat(chat): show the tool error reason in the transcript (B68)"
```

### Task 8: B69 — resolve the screen-control token from the data dir

**Files:**
- Modify: `vendor/sc_server/sdk.py:85-90`
- Modify: `tests/test_vendor.py::test_sdk_local_token_fallback_reads_sc_server_dir`

**Interfaces:**
- Produces: `ScreenControlClient._load_local_token()` reads `$SCREEN_CONTROL_DATA_DIR/.token`, then `config_dir()/.token` (same order as `server.py:205-206` + `entry.py`), never `vendor/sc_server/.token`.

- [ ] **Step 1: Fix the test to the real contract** (it currently pins the wrong path):

```python
def test_sdk_local_token_fallback_reads_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SCREEN_CONTROL_DATA_DIR", str(tmp_path))
    (tmp_path / ".token").write_text("tok-123", encoding="utf-8")
    assert _client_without_key()._load_local_token() == "tok-123"
```

- [ ] **Step 2: Run → FAIL** (still resolves `Path(__file__).parent / ".token"`)

- [ ] **Step 3: Implement**

```python
def _load_local_token(self) -> str:
    data_dir = os.environ.get("SCREEN_CONTROL_DATA_DIR")
    candidates = []
    if data_dir:
        candidates.append(Path(data_dir) / ".token")
    from core.paths import config_dir
    candidates.append(config_dir() / ".token")
    for token_file in candidates:
        if token_file.exists():
            return token_file.read_text().strip()
    raise ScreenControlError("No API key provided and no local .token file found")
```

(`import os` at module top if missing.)

- [ ] **Step 4: Run `tests/test_vendor.py -q` → PASS** · **Step 5: full suite → 571 passed**

- [ ] **Step 6: Commit**

```bash
git add vendor/sc_server/sdk.py tests/test_vendor.py
git commit -m "fix(screen-control): read the fallback token from the data dir (B69)"
```

---

## Phase 3 — P2 findings (B70–B76)

### Task 9: B70 — apply screen-control host/port live and expose `enabled`

**Files:**
- Modify: `ui/settings.py` (screen tab: add an `enabled` checkbox bound to `screen_control.enabled`, default True; save it)
- Modify: `ui/gui/main_window.py:419` (`_on_settings_saved`), `ui/avatar_app.py:139` — after `apply_screen_control`, call `maybe_spawn_server(load_settings(...))` (already imported in both files) so a port change respawns/verifies the server.
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Produces: `settings["screen_control"]["enabled"]: bool`; save path triggers `app_entry.entry.maybe_spawn_server`.

- [ ] **Step 1: Failing test:** saving with `enabled=False` writes the key; saving with a new port leaves `maybe_spawn_server` called (monkeypatch it, assert call).
- [ ] **Step 2: FAIL** · **Step 3: Implement** per Files.
- [ ] **Step 4: PASS** · **Step 5: full suite → 572 passed**
- [ ] **Step 6: Commit:** `fix(settings): apply screen-control changes live and add enabled toggle (B70)`

### Task 10: B71 — hide the sidebar header and use an icon for collapse/expand

**Files:**
- Modify: `ui/gui/main_window.py:365-389` (`_toggle_sidebar`), `retranslate()`
- Test: `tests/ui/test_chat.py`

**Interfaces:**
- Produces: collapsed state → `_sessions_header` hidden, `_collapse_btn` text `"☰"` (expand) / `"»"` (collapse), button fixed 48px-friendly.

- [ ] **Step 1: Failing test:** collapse → `not w._sessions_header.isVisible()` and `w._collapse_btn.text() == "☰"` and `w._collapse_btn.width() <= 48`.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (add header + button to the hide/show tuple; set the icon glyph instead of the long label; keep `retranslate` from overwriting the glyph — guard with `self._sidebar_expanded`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 573 passed**
- [ ] **Step 6: Commit:** `fix(gui): compact sidebar collapse control (B71)`

### Task 11: B72 — write avatar-mode events to the owning session

**Files:**
- Modify: `ui/avatar_app.py` (`_on_event`: use `event.session_id` for every `_history.append`, add `_active_task_session` set on `_on_send` and cleared on terminal events — mirror `main_window`'s B9 pattern)
- Test: `tests/ui/test_avatar_app.py`

**Interfaces:**
- Produces: `App._active_task_session: str | None`; late events route to it, not `self._sid`.

- [ ] **Step 1: Failing test:** start a task on session A, switch `app._sid` to session B, deliver `assistant_message` for A → history of A gains the message, B unchanged.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (copy `_is_active_task_session` semantics from `ui/gui/main_window.py:595-604`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 574 passed**
- [ ] **Step 6: Commit:** `fix(avatar): persist events to the running task's session (B72)`

### Task 12: B73 — store error/cancel lines under a non-assistant role

**Files:**
- Modify: `ui/gui/main_window.py:741,763` (`_on_error`, `_on_cancelled` persist with role `"error"`), `ui/gui/main_window.py:529` (seed filter stays `("user","assistant")`), `_append` name map gains `"error"` → objectName `msg_error`, avatar_app parity.
- Modify: `ui/theme.py` (add `QFrame#msg_error` styled like `msg_tool` with a danger tint)
- Test: `tests/ui/test_chat.py`, `tests/ui/test_history.py`

**Interfaces:**
- Produces: history rows with `role="error"`; `HistoryStore` needs no schema change (role is TEXT).

- [ ] **Step 1: Failing test:** `_on_error` persists `role == "error"`; `_load_session` re-render does NOT seed it into `runtime.seed_session` pairs.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (also apply the report's notification fix: `_on_error` skips `_maybe_notify` when `self.isActiveWindow()` — parity with `_on_finished`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 575 passed**
- [ ] **Step 6: Commit:** `fix(gui): keep error/cancel lines out of model context (B73)`

### Task 13: B74 — report rejected attachments instead of silently skipping

**Files:**
- Modify: `ui/gui/main_window.py:_pick_attachments`, `ui/bubble.py:_pick_attachments`
- Test: `tests/ui/test_file_attach.py`

**Interfaces:**
- Produces: rejected count shown via `self._activity.setText(...)` (GUI) / `set_tool_activity(...)` (bubble) with i18n key `chat.attach_rejected` (tr+en, added to `ui/i18n.py`).

- [ ] **Step 1: Failing test:** monkeypatch `load_attachment` to raise for one path → status/activity line contains the rejected count, no exception.
- [ ] **Step 2: FAIL** · **Step 3: Implement** + add i18n keys both languages.
- [ ] **Step 4: PASS** · **Step 5: full suite → 576 passed**
- [ ] **Step 6: Commit:** `feat(chat): report rejected attachments (B74)`

### Task 14: B75 — i18n for the avatar boot error; drop the hard-coded font

**Files:**
- Modify: `ui/avatar_app.py:426` (message box → i18n keys `avatar.boot_failed` tr+en), `ui/bubble.py:49-50` (remove the `QFont("Sans Serif", 10)` override — app font already applies)
- Modify: `ui/i18n.py`
- Test: `tests/ui/test_i18n.py`, `tests/ui/test_fonts.py`

- [ ] **Step 1: Failing test:** set language `en`, assert `i18n.t("avatar.boot_failed")` is English and contains no Turkish characters; assert no `QFont` assignment remains in `BubbleWindow.__init__` (source check).
- [ ] **Step 2: FAIL** · **Step 3: Implement** + tr/en entries.
- [ ] **Step 4: PASS** · **Step 5: full suite → 577 passed**
- [ ] **Step 6: Commit:** `fix(i18n): localize avatar boot failure; use app font in bubble (B75)`

### Task 15: B76 — tidy the dependency manifests

**Files:**
- Modify: `requirements.txt`, `requirements-packaging.txt`
- Note (user, 2026-10-14): this also bloats the release bundle — pytest sits in the runtime list, flask is duplicated across both files, pyautogui installs unconditionally on Linux though only the Windows backend uses it. Fix is release-blocking.

- [ ] **Step 1: Failing check** — add `tests/test_requirements.py`:

```python
def test_pyautogui_is_windows_only():
    req = Path("requirements.txt").read_text()
    assert 'pyautogui>=0.9.54; sys_platform == "win32"' in req or \
           "pyautogui" not in req

def test_no_duplicate_and_no_test_deps_in_runtime():
    req = Path("requirements.txt").read_text().splitlines()
    assert len(req) == len(set(req))
    assert not any(l.startswith("pytest") for l in req)
```

- [ ] **Step 2: FAIL** · **Step 3: Implement:** `pyautogui` → platform-markered; move `pytest` to `requirements-packaging.txt` (CI installs both — verify `.github/workflows/*` reference both files before moving); dedupe `flask`/`Pillow`/`requests`.
- [ ] **Step 4: PASS** · **Step 5: full suite + `pip install -r requirements.txt -r requirements-packaging.txt` dry-check → green**
- [ ] **Step 6: Commit:** `chore(deps): platform-marker pyautogui, dedupe manifests (B76)`

---

## Phase 4 — P3 findings (B77–B81)

### Task 16: B77 + B78 + B80 — docs and dead-key cleanup

**Files:**
- Modify: `README.md` (TR sentence: "port 8745 **boşta değilse**" → "port 8745 **boşsa**")
- Modify: `docs/index.html` (Security card: "denied by default" → "ask by default")
- Modify: `config_template/settings.json` (drop `language`, `theme`), `ui/i18n.py` (drop the 5 unused keys), `core/tools/screen_control.py:176` (use `timeout_s` or drop the parameter — drop it and update its 2 callers/tests)
- Note (user, 2026-10-14): these two doc lines become publicly wrong information at release — fix is in scope and required before the tag.

- [ ] **Step 1: Failing tests** — `tests/test_docs_copy.py` already exists; add: README TR must not contain "boşta değilse"; a grep test that `config_template/settings.json` has no `language`/`theme` keys; `tests/test_qt_free_core.py`-style source check for `del timeout_s`.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (before deleting i18n keys, grep them: `chat.tool_activity`, `chat.tool_prefix`, `settings.ai_fallback`, `settings.lang_restart_note`, `settings.pack_title`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 578 passed** (count may shift with key deletions; never below baseline)
- [ ] **Step 6: Commit:** `docs+chore: fix README TR wording, landing claim, drop dead keys (B77,B78,B80)`

### Task 16b: source-run version banner fix (`core.__version__`)

**Files:**
- Modify: `core/__init__.py` (`__version__ = "0.0.0"` → the release version, `"0.2.4"`)
- Test: `tests/core/test_paths.py` (or `tests/test_update_check.py`)

**Why (user note, 2026-10-14):** `_version.txt` is gitignored, so a source checkout has no baked version; `bundled_version()` falls back to `core.__version__` = `"0.0.0"`, `is_newer(latest, "0.0.0")` is always True → the "new version available" banner shows on every launch for source users. Frozen builds are unaffected (APP_VERSION / _version.txt win).

- [ ] **Step 1: Failing test:** `parse_version`/`is_newer` sanity + `bundled_version()` fallback must not be `"0.0.0"`: assert `tuple(int(p) for p in core.__version__.split(".")) > (0, 0, 0)` and `not is_newer("v0.2.4", core.__version__)`.
- [ ] **Step 2: FAIL** (version is "0.0.0")
- [ ] **Step 3: Implement:** set `__version__ = "0.2.4"` — must be bumped in the same commit that moves the release tag from now on (ledger this as a release-step reminder).
- [ ] **Step 4: PASS** · **Step 5: full suite → green**
- [ ] **Step 6: Commit:** `fix(version): set source-run __version__ to the release version`

### Task 16c: postinstall icon-cache refresh

**Files:**
- Modify: `packaging/postinstall.sh`

- [ ] **Step 1: Failing test** (in `tests/test_packaging_manifest.py`, which already guards packaging files): assert the postinstall script runs `gtk-update-icon-cache` (guarded by `command -v`, best-effort like the desktop-database line).
- [ ] **Step 2: FAIL** · **Step 3: Implement:**

```sh
command -v gtk-update-icon-cache >/dev/null 2>&1 && gtk-update-icon-cache -q -f /usr/share/icons/hicolor || true
```

- [ ] **Step 4: PASS** · **Step 5: full suite → green**
- [ ] **Step 6: Commit:** `packaging: refresh gtk icon cache on install`

### Task 17: B79 — CI: scope the retry, add lint, refresh the checklist

**Files:**
- Modify: `.github/workflows/ci.yml`

- [ ] **Step 1:** Replace the blanket `pytest || pytest` retry with a targeted one: run the suite once; on exit 139 only (segfault), rerun once and mark the job "flake-retried"; any other exit code fails immediately. Add a `lint` step: `pip install ruff && ruff check --select F,E9 --exclude vendor .` (baseline: the single unused import in app code — fix it in this task if it fails).
- [ ] **Step 2:** Update `checklists/full-gui-desktop-manual.md` "122+" → "561+" **and fix its stale commands** (user note: it still references `config/ui.json` and `.venv/bin/python -m ui.app` — point them at `ui/paths.py`'s real ui.json location and the current entrypoint `ui/app.py`).
- [ ] **Step 3: Local verification:** `ruff check --select F,E9 --exclude vendor .` passes on the repo now.
- [ ] **Step 4: Full suite → green** · **Step 5: Commit:** `ci: scope segfault retry to exit 139, add lint step (B79)`

### Task 18: B81 — pin the Settings `save()` contract (regression net)

**Files:**
- Test: `tests/ui/test_settings.py`

- [ ] **Step 1:** Collect the contract into one named test module section `# B81: save() contract` asserting: theme token round-trip, model omission, permission-diff-only rows, corrupt-file guard, `avatar_ai` preserved, `persona` round-trip, screen-control loopback clamp. (Most assertions already exist from Tasks 1–5; this task adds the missing ones: `avatar_ai`, persona, loopback clamp.)
- [ ] **Step 2: FAIL (new assertions)** · **Step 3: Implement missing fixes if any assertion reveals a real bug (report first).**
- [ ] **Step 4: PASS** · **Step 5: full suite → 580 passed**
- [ ] **Step 6: Commit:** `test(settings): pin the save() contract (B81)`

---

## Phase 5 — Cross-check findings (B82–B88)

### Task 19: B82 — avatar state debounce + frame cache

**Files:**
- Modify: `ui/avatar/window.py:218-231` (`set_state`: min-dwell timer per state, default 200 ms; `_render_frame`: `QPixmap` cache dict keyed by path, invalidated only on pack switch)
- Test: `tests/ui/test_state_machine.py` + new `tests/ui/test_avatar_window.py`

- [ ] **Step 1: Failing test:** `set_state("thinking"); set_state("working")` immediately → `current_state()` still `"thinking"` until 200 ms elapses (use `QTest.qWait` or a fake clock); frame cache: two `set_state` calls to the same state do not re-read the file (monkeypatch `QPixmap` counter).
- [ ] **Step 2: FAIL** · **Step 3: Implement** (timer parented to the window; timer fire applies the pending state; cache cleared in `_load_pack`/`__init__`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 582 passed**
- [ ] **Step 6: Commit:** `fix(avatar): debounce state changes and cache frames (B82)`

### Task 20: B83 — re-place the bubble when it resizes

**Files:**
- Modify: `ui/bubble.py` (add `resized` callback or `resizeEvent` hook), `ui/avatar_app.py:193-205` (clamp both axes to screen geometry, use availableGeometry)
- Test: `tests/ui/test_avatar_drag.py`

- [ ] **Step 1: Failing test:** force `bubble.resize(...)` taller → `_place_bubble` runs and `bubble.y() >= screen.top()`; bottom overflow clamped.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (BubbleWindow gets `on_geometry_change: Callable | None = None`, invoked from `resizeEvent`; App wires it to `_place_bubble` with full-screen clamping: `y = min(max(y, avail.top()), avail.bottom() - h)`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 583 passed**
- [ ] **Step 6: Commit:** `fix(avatar): keep the bubble inside the screen on resize (B83)`

### Task 21: B84 — explain INPUT_BLOCKED / Wayland limits

**Files:**
- Modify: `ui/gui/main_window.py` + `ui/avatar_app.py` tool_finished failure branch: when `error_code`-in-summary matches `INPUT_BLOCKED`/`403`, append i18n `chat.error_input_blocked` ("uinput izni gerekli — Linux'ta /dev/uinput erişimi verin ya da X11'e geçin" / EN equivalent)
- Modify: `ui/i18n.py`
- Modify: `README.md` install note (one line under Linux prerequisites)

- [ ] **Step 1: Failing test** in `tests/ui/test_chat.py`: failure payload with `error_code="INPUT_BLOCKED"` → transcript line contains the i18n hint.
- [ ] **Step 2: FAIL** · **Step 3: Implement** + tr/en keys.
- [ ] **Step 4: PASS** · **Step 5: full suite → 584 passed**
- [ ] **Step 6: Commit:** `feat(chat): explain blocked input (uinput/Wayland) on failure (B84)`

### Task 22: B85 — target xdotool at the focused window; restore focus after confirm

**Files:**
- Modify: `vendor/sc_server/sc_backends/linux.py` (`key_press`, `key_down`, `key_up`, `key_hotkey`, `type_text`): capture `xdotool getactivewindow` once per operation (module-level helper `_active_window_id()`) and pass `--window <id>` to every `xdotool` call when non-empty.
- Modify: `ui/confirmation.py` — after the dialog closes, `parent.activateWindow()` (and `raise_()`).

- [ ] **Step 1: Failing test** (in `tests/tools/` or `tests/test_vendor.py`): monkeypatch `run_x11` to record argv; `type_text("hi")` → every recorded `xdotool type/key` argv contains `--window`.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (cache the window id for the duration of one `type_text`/`key_hotkey` call; if `getactivewindow` fails, fall back to the current behavior with no `--window`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 585 passed**
- [ ] **Step 6: Commit:** `fix(screen-control): direct xdotool at the target window (B85)`

### Task 23: B86 — provider connection test + dirty indicator

**Files:**
- Modify: `ui/settings.py` (provider tab: "Test connection" button → runs a `_ModelListWorker`-style one-shot `list_models()` and reports ok/fail in the status line; `self._dirty` flag set by any `textChanged`/`currentIndexChanged` in `__init__`, cleared in `save()`/`load()`; `closeEvent` shows a yes/no prompt when dirty)
- Modify: `ui/i18n.py` (tr+en: `settings.test_connection`, `settings.test_ok`, `settings.test_fail`, `settings.unsaved_changes`)
- Test: `tests/ui/test_settings.py`

- [ ] **Step 1: Failing tests:** (a) editing the key sets `w._dirty`; `save()` clears it; `closeEvent` with dirty → prompt shown (monkeypatch QMessageBox); (b) test-connection with a monkeypatched failing provider → status shows the failure.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (reuse `_ModelListWorker` + `_poll_workers` drain — add the worker attr to the poll list).
- [ ] **Step 4: PASS** · **Step 5: full suite → 587 passed**
- [ ] **Step 6: Commit:** `feat(settings): connection test and unsaved-changes guard (B86)`

### Task 24: B87 — i18n for device-flow errors + a copy button for the code

**Files:**
- Modify: `ui/settings.py:684-708` (`_drain_github_login`): status line shows the user code in a selectable form — replace the QLabel status for this case with the code appended to a `QLineEdit(read-only)` row, or simpler: add a "Copy" button (`QGuiApplication.clipboard().setText(user_code)`) next to the status text while the code is shown.
- Modify: `ui/i18n.py`: map known `GitHubDeviceError` kinds to tr/en (`github_err_expired`, `github_err_denied`, `github_err_network`) — key the mapping off a new `code` attribute on `GitHubDeviceError` (add `code: str` to `core/auth/github_device.py` exceptions: `expired_token`, `access_denied`, `network`, else `github_err_generic`).
- Test: `tests/ui/test_settings.py`, `tests/core/test_github_device.py` (path per repo layout — grep for existing device tests)

- [ ] **Step 1: Failing tests:** error message for `expired_token` renders Turkish when lang=tr; clipboard receives the user code on button click.
- [ ] **Step 2: FAIL** · **Step 3: Implement**.
- [ ] **Step 4: PASS** · **Step 5: full suite → 589 passed**
- [ ] **Step 6: Commit:** `feat(settings): localize device-flow errors and add code copy (B87)`

### Task 25: B88 — reflect agent state in the tray icon

**Files:**
- Modify: `ui/tray.py` (`TrayController.set_agent_state(state: str)` — greyscale the icon pixmap for `busy`, red-dot overlay for `error`, normal otherwise; store the base `QPixmap`)
- Modify: `ui/gui/main_window.py` (`_set_busy`, `_on_error`) and `ui/avatar_app.py` (busy/error events) call `set_agent_state`
- Test: `tests/ui/test_tray.py`

- [ ] **Step 1: Failing test:** `controller.set_agent_state("busy")` → pixmap differs from the base (cacheKey changes); menu text unchanged.
- [ ] **Step 2: FAIL** · **Step 3: Implement** (guard: tray may be unavailable; icon may be null → no-op).
- [ ] **Step 4: PASS** · **Step 5: full suite → 590 passed**
- [ ] **Step 6: Commit:** `feat(tray): show agent state in the tray icon (B88)`

---

## Phase 6 — Handoff §2.2 backlog (runs on the user's "yap" — already given)

### Task 25b: B-ek — deduplicate the base avatar frames

**Files:**
- Modify: `assets/avatars/base/frames/` (9 exact-duplicate PNGs: keep the first of each md5 group, e.g. `error_02`, `idle_03`, `working_05`)
- Test: `tests/ui/test_pack_states.py` (assert no two frame files share an md5; count/manifest expectations updated if any test pins filenames)

- [ ] **Step 1: Failing test:** walk `assets/avatars/base/frames/`, group by md5 → assert no duplicates.
- [ ] **Step 2: FAIL** (9 duplicates found) · **Step 3: Verify `load_manifest`/`AvatarWindow` reference the *kept* names (grep each deleted name first — if a name is referenced in code, delete its twin instead); remove the duplicates.
- [ ] **Step 4: PASS** · **Step 5: full suite → green** · **Step 6: Commit:** `chore(assets): drop duplicate base avatar frames (B-ek)`

### Task 26: Backlog 1 — inline `+` attach in avatar mode

**Files:**
- Modify: `ui/bubble.py` (replace the text attach button with the chat's `attach_plus` 28×28 `+` button + chip bar, ported from `ui/gui/main_window.py:176-199`)
- Test: `tests/ui/test_file_attach.py`

- [ ] **Step 1: Failing test:** bubble has an `attach_plus` button with tooltip `chat.attach`; clicking it opens no dialog headlessly but the pending-chip API works (`_pending_attachments` + chip refresh).
- [ ] **Step 2: FAIL** · **Step 3: Implement** (copy chip-bar code; keep `_attach_btn` removal consistent with `retranslate`).
- [ ] **Step 4: PASS** · **Step 5: full suite → 591 passed**
- [ ] **Step 6: Commit:** `feat(avatar): inline + attach with chips (backlog 1)`

### Task 27: Backlog 2 — pack/AiPack workers → UI-thread polling (B61 parity)

**Files:**
- Modify: `ui/settings.py` (`_PackBuildWorker`, `_AiPackWorker`): drop the cross-thread `_PackSignals`/`_AiPackSignals` emits; carry results on `queue.SimpleQueue` + `threading.Event` like `_ModelListWorker`; drain in `_poll_workers`.
- Test: `tests/ui/test_settings_fetch_race.py` (extend), `tests/ui/test_ai_pack.py`

- [ ] **Step 1: Failing test:** stress test — start N pack builds while closing the window; no signal emitted from a worker thread (assert via a counter on the queue drain, mirroring `test_settings_fetch_race`).
- [ ] **Step 2: FAIL** · **Step 3: Implement** (keep progress reporting on the queue too: a `progress` queue drained each tick).
- [ ] **Step 4: PASS** · **Step 5: full suite → 593 passed**
- [ ] **Step 6: Commit:** `fix(settings): drain pack workers on the UI thread (B61 parity, backlog 2)`

### Task 28: Backlog 3 — shutdown hardening for bridge/avatar_app

**Files:**
- Modify: `ui/avatar_app.py` (`quit()`/`close()`: stop any `QTimer`s, close the settings window, join in-flight workers like `SettingsWindow.closeEvent` does), `ui/bridge.py` (drop signal connections on close)

- [ ] **Step 1: Failing test:** `App.quit()` with an active pack worker → worker joined within 5 s (reuse `wait()`); bridge `sig` disconnected (no delivery after close).
- [ ] **Step 2: FAIL** · **Step 3: Implement.**
- [ ] **Step 4: PASS** · **Step 5: full suite → 594 passed**
- [ ] **Step 6: Commit:** `fix(avatar): harden shutdown paths (backlog 3)`

### Task 29 (optional): Backlog 4 — avatar pack gallery + chat history search

- [ ] Only if the user confirms mid-run. Gallery: thumbnail grid in the avatar picker; search: filter field above `_sessions` list (`HistoryStore.list_sessions` already returns titles; client-side filter).
- [ ] Tests + suite green + commit.

### Task 30: Final verification

- [ ] `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q` → all green, count ≥ 594
- [ ] `ruff check --select F,E9 --exclude vendor .` → clean
- [ ] `git status` → only intended files; no forbidden paths staged
- [ ] Report the final test count and changed-file list to the user.

### Task 31: Release (STOP — ask the user first)

- [ ] **Ask the user** whether to force-move tag `v0.2.4` to the new HEAD (`git tag -f v0.2.4 HEAD && git push -f origin v0.2.4`) so CI rebuilds the 3 assets. **Do not run this without explicit confirmation.**

---

## Post-run notes (not part of the plan)

- The reports' §7 UX wishlist (Markdown rendering, retry/copy actions, session reorder, window geometry memory, monospace font) is deliberately excluded — it is product work, not audit fixes; propose it separately if the user wants.
- Cross-check §4 false positives must never be "fixed" (see Global Constraints).
