# GitHub Copilot Device-Flow OAuth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Offer "Sign in with GitHub" in Settings via the official OAuth device grant; store the `gho_` token in `secrets.github_api_key` so the existing Copilot chat provider works without a manually created PAT.

**Architecture:** A pure-requests auth module (`core/auth/github_device.py`) owns the device flow; the Settings window drives it on a B61-safe background worker (SimpleQueue + Event) and writes the token through the existing `_write(..., mode=0o600)` secrets helper. `core/providers/github.py` is untouched.

**Tech Stack:** Python 3.11+, `requests`, PySide6 (UI only), pytest with offscreen Qt.

**Spec:** `docs/superpowers/specs/2026-10-13-github-device-oauth-design.md`

## Global Constraints

- Chat replies in Turkish; all code, comments, commits, tests in English.
- Never `git add -A`; stage explicit paths only.
- Tests: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q` must stay green (baseline 552).
- OAuth client id `Iv1.b507a08c78f299fb` (public GitHub CLI app id — not a secret).
- Scopes string: `repo read:org gist workflow` (space-separated for the API).
- Secrets key name stays `github_api_key`; write with `mode=0o600`.
- B61 rule: no per-job unparented QObjects; worker results via `queue.SimpleQueue` + `threading.Event`; UI updates on the UI thread only.

## Review Focus

- **User denies or never completes authorization** — poll must surface `access_denied`/timeout as a readable status message, not hang; test: poll raises on `access_denied` and on deadline.
- **Expired device code** (GitHub's ~15 min window) — same path as denial; test: poll raises on `expired_token`.
- **Button visible for non-github providers** — leaks an unusable flow; test: button hidden when provider type ≠ github.
- **Token overwrite of an existing PAT** — re-login replaces `github_api_key` only after a successful poll; test: failed poll leaves secrets unchanged.
- **Worker/QObject safety on frozen builds** — device worker must reuse the SimpleQueue pattern; code review check (existing invariant tests must stay green).

---

### Task 1: Device-flow auth module

**Files:**
- Create: `core/auth/__init__.py` (empty)
- Create: `core/auth/github_device.py`
- Test: `tests/core/test_github_device.py`

**Interfaces:**
- Consumes: `requests` only.
- Produces (relied on by Task 2):
  - `class GitHubDeviceError(Exception)` — human-readable message.
  - `@dataclass DeviceCode`: `device_code: str`, `user_code: str`, `verification_uri: str`, `interval: float`, `expires_in: float`.
  - `def request_device_code(session: requests.Session | None = None) -> DeviceCode`
  - `def poll_for_token(device_code: DeviceCode, *, session: requests.Session | None = None, sleep=time.sleep, deadline_s: float | None = None) -> str` — returns the `gho_` access token; raises `GitHubDeviceError` on `expired_token`, `access_denied`, network failure, or deadline. Default deadline = `expires_in`.

- [ ] **Step 1: Write the failing unit tests**

In `tests/core/test_github_device.py` (reuse the FakeSession/FakeResponse style from `tests/providers/test_image_gen.py`):

```python
def test_request_device_code_posts_client_and_scopes(): ...
    # asserts POST to https://github.com/login/device/code with
    # client_id == "Iv1.b507a08c78f299fb" and scope == "repo read:org gist workflow"
    # parses device_code/user_code/verification_uri/interval/expires_in

def test_poll_returns_token_after_pending(): ...
    # script: {"error": "authorization_pending"} then {"access_token": "gho_abc"}
    # sleep spy records the interval

def test_poll_raises_on_access_denied(): ...
def test_poll_raises_on_expired_token(): ...
def test_poll_raises_on_deadline(): ...
    # deadline_s smaller than interval → raises without looping forever
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/core/test_github_device.py -v`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement `core/auth/github_device.py`**

Constants `CLIENT_ID = "Iv1.b507a08c78f299fb"`, `SCOPES = "repo read:org gist workflow"`,
`_DEVICE_CODE_URL = "https://github.com/login/device/code"`,
`_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"`.
`request_device_code` posts form data; response may be form-encoded or JSON — accept both (`Content-Type` check: parse with `requests`' `parse_qs` when needed).
`poll_for_token` loops: POST `grant_type=urn:ietf:params:oauth:grant-type:device_code` + `client_id` + `device_code`; on `access_token` return it; on `authorization_pending`/`slow_down` sleep `interval` (bump +5s on `slow_down`); on anything else raise `GitHubDeviceError(f"...")`. Enforce `deadline_s` (default `expires_in`) before each request.

- [ ] **Step 4: Run tests to verify they pass**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/core/test_github_device.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add core/auth/__init__.py core/auth/github_device.py tests/core/test_github_device.py
git commit -m "feat(auth): GitHub OAuth device-flow client (official gh CLI app)"
```

### Task 2: Settings "Sign in with GitHub" flow

**Files:**
- Modify: `ui/settings.py` (provider form construction ~line 300-320, `_provider_type` change handler / retranslate block ~495, new worker class near `_ModelListWorker` ~129)
- Modify: `ui/i18n.py` (new keys next to `settings.ai_url`)
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Consumes: `core.auth.github_device.request_device_code`, `poll_for_token`, `GitHubDeviceError`, `DeviceCode` (Task 1).
- Produces: Settings behavior only — `github_login` button attribute `self._github_login`; secrets file gains/updates `github_api_key` with the `gho_` token.

i18n keys (exact copy):

```python
"settings.github_login": {"tr": "GitHub ile giriş yap", "en": "Sign in with GitHub"},
"settings.github_device_code": {
    "tr": "Tarayıcıda açılan sayfaya kodu girin: {code}",
    "en": "Enter this code in the browser: {code}",
},
"settings.github_signed_in": {"tr": "Giriş başarılı", "en": "Signed in"},
"settings.github_sign_in_failed": {"tr": "Giriş başarısız: {error}", "en": "Sign-in failed: {error}"},
```

- [ ] **Step 1: Write the failing UI tests**

```python
def test_github_login_button_only_for_github_provider(tmp_path):
    # load(); switch _provider_type to "github" → _github_login visible
    # switch to "groq" → hidden

def test_github_device_flow_success_writes_secret(tmp_path, monkeypatch):
    # monkeypatch ui.settings.request_device_code → DeviceCode(fake...)
    # monkeypatch ui.settings.poll_for_token → "gho_testtoken"
    # click _github_login (or call the start method), drive the worker to
    # completion, then assert secrets file github_api_key == "gho_testtoken"
    # and _provider_key text is non-empty (masked field)

def test_github_device_flow_failure_leaves_secret_untouched(tmp_path, monkeypatch):
    # monkeypatch poll_for_token to raise GitHubDeviceError("access denied")
    # after worker completes: secrets file unchanged, status label shows
    # settings.github_sign_in_failed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_settings.py -k github -v`
Expected: FAIL — `_github_login` missing.

- [ ] **Step 3: Implement the worker (`_GithubDeviceWorker`)**

Same B61 shape as `_ModelListWorker`: plain class, `threading.Thread`, `queue.SimpleQueue`, `threading.Event`, `done` property, `take() -> tuple[bool, str | None]` returning `(error_message, token)`. Thread body: `request_device_code()` then `poll_for_token(code)`; catch `GitHubDeviceError`/`requests.RequestException` into the error slot. Store the `verification_uri` on the worker as a plain attribute so the UI thread can open the browser (set before `start()` by the caller from `request_device_code`? No — request runs on the worker; instead expose a second queue for the code: simplest is a `code_queue: queue.SimpleQueue` the worker puts `(user_code, verification_uri)` into immediately after `request_device_code`, drained by the UI poll).

- [ ] **Step 4: Implement the UI wiring**

- `__init__`: create `self._github_login = QPushButton(self)`, add to the provider form under the key row; connect `clicked → self._start_github_login`.
- `self._github_device_worker` / `self._github_device_gen` attributes (gen guard: a second click supersedes the first).
- `_start_github_login`: start worker; drain `code_queue` on next poll-timer tick → `QDesktopServices.openUrl(QUrl(verification_uri))` once + status `t("settings.github_device_code").format(code=user_code)`.
- Poll worker completion on the existing `_poll_timer` (extend `_poll_workers`): on success `_write(self._secrets_path, {**secrets, "github_api_key": token}, mode=0o600)`, set `_provider_key` text to the token, status `github_signed_in`; on error status `github_sign_in_failed.format(error=...)`.
- Provider-type change handler: `_github_login.setVisible(ptype == "github")` (mirror the B18 reset).
- retranslate: button text + all new keys.

- [ ] **Step 5: Run the tests and the full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_settings.py -k github -v && QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q`
Expected: all green, full suite ≥ 555 passed.

- [ ] **Step 6: Commit**

```bash
git add ui/settings.py ui/i18n.py tests/ui/test_settings.py
git commit -m "feat(settings): Sign in with GitHub via official OAuth device flow"
```

### Task 3: Verification and ship prep

**Files:** none new; run existing checks.

- [ ] **Step 1: Full suite + quick frozen sanity**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q`
Expected: green.

- [ ] **Step 2: Commit anything outstanding; report to the partner**

Do not tag a release without asking (release policy: the partner decides when to rebuild assets).
