# GitHub Copilot Device-Flow OAuth — Design

Date: 2026-10-13
Status: approved (design); spec review pending

## Problem

The GitHub Copilot chat provider (`core/providers/github.py`) requires a
manually created Personal Access Token. Users regularly fail to obtain one
("API key alamıyoruz"), while GitHub's own Copilot CLI authenticates with an
OAuth device flow that needs no PAT. NexaDesk should offer the same flow.

## Goal

Sign in with GitHub from Settings using the official OAuth device
authorization grant; store the resulting `gho_` token in
`secrets.github_api_key` so the existing Copilot token exchange works
unchanged. PAT users keep working.

## Non-goals

- No refresh-token handling in v1 (tokens are long-lived; re-login from
  Settings when expired).
- No changes to `core/providers/github.py` auth logic.
- No web-OAuth image providers (ChatGPT/Gemini/Copilot) — separate future
  work, experimental, requires an explicit "unofficial method" notice.

## Design

### 1. Auth module — `core/auth/github_device.py` (new package `core/auth/`)

- Official GitHub CLI OAuth app client id: `Iv1.b507a08c78f299fb`
  (public identifier used by `gh`; not a secret).
- Scopes: `repo,read:org,gist,workflow` (gh CLI standard set).
- `request_device_code(session) -> DeviceCode`
  `POST https://github.com/login/device/code`
  JSON body `client_id`, `scope` (space-joined); expects `device_code`,
  `user_code`, `verification_uri`, `interval`, `expires_in`.
- `poll_for_token(device_code, session, *, deadline_s) -> str`
  `POST https://github.com/login/oauth/access_token`
  with `grant_type=urn:ietf:params:oauth:grant-type:device_code`.
  Poll every `interval` seconds until `access_token` appears, the
  authorization is `expired`/`denied`, or `deadline_s` elapses.
  Raises `GitHubDeviceError` with a human-readable message on failure.
- Pure `requests` (no Qt); unit-testable with a fake session.
- Device-flow polling runs on a worker thread (same pattern as existing
  settings workers); UI is updated via the B61-safe poll/queue model or a
  window-parented signal carrier, never an unparented per-job QObject.

### 2. Settings UI

- When provider type is `github`, the key line-edit is replaced (or
  supplemented) by a **"Sign in with GitHub"** button (`github_login`).
- Click flow:
  1. Start device-flow worker (non-blocking).
  2. Open `verification_uri` in the system browser.
  3. Show the `user_code` in the settings status line
     (`settings.github_device_code`: "Open the browser and enter code {code}").
  4. Worker polls; on success write the token to
     `secrets.github_api_key`, refresh the key field (masked), status
     "Signed in".
  5. On denial/expiry: status message; button re-enabled.
- Button hidden for every non-github provider type (B18-style reset stays).

### 3. Compatibility

- `secrets.github_api_key` now holds either a PAT (`ghp_`/`github_pat_`)
  or a device-flow OAuth token (`gho_`); `core/providers/github.py` sends
  it as a Bearer token to `copilot_internal/v2/token` either way — no
  provider code change.
- Users who already saved a PAT see no difference until they choose to
  re-login.

### 4. Error handling

- Network failure during code request: `GitHubDeviceError` → status line.
- `expired_token` / `access_denied` from the poll endpoint: status line.
- Timeout (default 15 min, GitHub's device-code lifetime): status line.
- Token exchange in `github.py` keeps its existing error path for tokens
  without Copilot access (e.g., account without subscription).

### 5. Testing

- `tests/core/test_github_device.py`:
  - `request_device_code` posts correct payload and parses response.
  - poll returns token after pending polls (fake clock/interval).
  - poll raises on `expired_token` and `access_denied`.
  - poll raises on deadline.
- `tests/ui/test_settings.py`:
  - `github_login` button visible only for provider type `github`.
  - device-flow success writes `secrets.github_api_key` and updates the
    key field (worker simulated).
- Existing github provider tests unchanged and green.

## Open questions

None — approved as designed.
