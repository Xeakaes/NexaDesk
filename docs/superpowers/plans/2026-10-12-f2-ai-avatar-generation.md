# F2 AI Avatar Generation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Settings → Avatar gains "generate with AI": the configured provider's image model produces one identity-preserving emotion still per pack state, and the existing transform pipeline turns those into a fully animated 5-state pack; providers without image models keep the AI-less builder.

**Architecture:** A Qt-free image-generation client (`core/providers/image_gen.py`) speaks the OpenAI-compatible `images/edits` (photo reference) endpoint with a `images/generations` text-only fallback. A Qt-free orchestrator (`ui/avatar/ai_pack.py`) owns the fixed prompt dictionary and sequences the five generations. A small refactor of `ui/avatar/pack.py` lets the pack builder accept per-state base images. The Settings avatar tab wires it through a plain-thread worker (existing `_PackBuildWorker` pattern).

**Tech Stack:** Python 3.12, PySide6 (signals only), requests, Pillow; tests via pytest with `QT_QPA_PLATFORM=offscreen`.

**Spec:** `docs/superpowers/specs/2026-10-12-f2-ai-avatar-generation-design.md`

## Global Constraints

- All code, comments, tests, commits in English; chat with the user in Turkish.
- TDD Iron Law: every behavior gets a failing test first (RED → GREEN).
- Never `git add -A`; stage explicit paths only. Never commit `config/settings.json`, `config/logs/`, `assets/avatars/{max_verstopen,osaka,teto,teto_ekmek}`.
- Test command: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q` (currently 448 green; suite must stay green).
- Fixed prompts — exact strings from the spec; no user-editable prompt text anywhere.
- Emotion set = exactly the five REQUIRED_STATES: idle, thinking, working, speaking, error.
- New settings key: `settings["avatar_ai"] = {"model": "<str>"}`; default absent = empty model.
- Model dropdown filter: `IMAGE_MODEL_MARKERS = ("gpt-image", "dall-e", "dall_e", "flux", "imagen", "seedream", "stable-diffusion", "sd3", "image")`; field always editable (free entry).
- Timeout per generation call: 120 s. Calls strictly sequential.

## Review Focus

- Provider without an images endpoint: both `edits` and `generations` fail → `ImageGenError` surfaces the HTTP status; no pack directory left behind.
- Mid-set failure (e.g., rate limit on call 3 of 5): `build_ai_pack` deletes the partial `out_dir` before re-raising.
- Cancel between calls: `AiPackCancelled` raised, partial output removed, UI returns to idle state quietly.
- Response variance: `data[0].b64_json` (bytes) and `data[0].url` (download) both accepted; anything else → `ImageGenError`.
- Stale catalog after provider switch: the AI model dropdown uses its own fetch-generation counter (B23 pattern) so a slow old fetch cannot refill it.

---

### Task 1: Image-generation client

**Files:**
- Create: `core/providers/image_gen.py`
- Test: `tests/providers/test_image_gen.py`

**Interfaces:**
- Produces:
  - `IMAGE_MODEL_MARKERS: tuple[str, ...]`
  - `is_image_model(model_id: str) -> bool`
  - `class ImageGenError(Exception)` with attribute `status_code: int | None`
  - `class ImageGenClient.__init__(self, base_url: str, api_key: str, timeout_s: float = 120.0)`
  - `ImageGenClient.generate(self, model: str, prompt: str, photo: Path | None = None) -> bytes`
  - `decode_image_response(payload: dict) -> bytes` (module-level, used by tests and `generate`)
- Consumes: `requests`, `log_event` from `core.agent.telemetry` (signature `log_event(event: str, **fields)` — field name is `event`).

- [ ] **Step 1: Write failing tests** (`tests/providers/test_image_gen.py`)

```python
def test_is_image_model_markers():
    from core.providers.image_gen import is_image_model
    assert is_image_model("gpt-image-1")
    assert is_image_model("black-forest-labs/flux-1-dev")
    assert not is_image_model("llama-3.3-70b-versatile")

def test_generate_with_photo_uses_edits_multipart(monkeypatch):
    # capture requests.post call; assert url endswith /images/edits,
    # data has model/prompt/size/n=1, files has image=(photo bytes),
    # Authorization: Bearer k; return {"data": [{"b64_json": b64 of PNG}]}
    # -> returns raw PNG bytes

def test_generate_falls_back_to_generations_text_only(monkeypatch):
    # edits raises HTTPError 404 -> POST /images/generations JSON body,
    # no files; response data[0].url -> downloader returns bytes

def test_generate_both_endpoints_fail_raises(monkeypatch):
    # both raise -> ImageGenError with status_code from the generations attempt

def test_decode_image_response_rejects_unknown_shape():
    # {} or {"data": []} -> ImageGenError
```

- [ ] **Step 2: Run tests, confirm FAIL**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/providers/test_image_gen.py -q` — FAIL (module missing).

- [ ] **Step 3: Implement `core/providers/image_gen.py`**

`generate`: if `photo` is not None try `POST f"{base_url}/images/edits"` as multipart (`model`, `prompt`, `size="1024x1024"`, `n="1"`, `image` file tuple); on any requests exception or non-2xx fall through to `POST f"{base_url}/images/generations"` JSON `{"model", "prompt", "size", "n": 1}`; both use `Authorization: Bearer {api_key}`; decode via `decode_image_response` (`b64_json` → `base64.b64decode`, else `url` → `requests.get(url, timeout=timeout_s).content`); `log_event("image_gen", model=..., endpoint=..., ok=...)` per attempt; raise `ImageGenError` carrying `status_code` when both fail.

- [ ] **Step 4: Run tests, confirm PASS**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/providers/test_image_gen.py -q` — PASS.

- [ ] **Step 5: Commit**

```bash
git add core/providers/image_gen.py tests/providers/test_image_gen.py
git commit -m "feat: OpenAI-compatible image-generation client (F2)"
```

---

### Task 2: Pack builder accepts per-state base images

**Files:**
- Modify: `ui/avatar/pack.py` (`build_pack` + new sibling)
- Test: `tests/ui/test_pack_states.py` (new)

**Interfaces:**
- Produces:
  - `build_pack_from_state_images(state_images: dict[str, Image.Image], out_dir: Path, name: str, *, preprocess: bool = True) -> Path`
    - raises `PackError` if any `REQUIRED_STATES` key is missing from `state_images`
    - with `preprocess=True` runs `strip_background` → `keep_largest_component` → `crop_pad_resize` on each image before transforms
  - `build_pack(source_image: Path, out_dir: Path, name: str) -> Path` — unchanged signature; now normalizes once, then delegates with the same image for every state (`preprocess=False`).
- Consumes: existing `strip_background`, `keep_largest_component`, `crop_pad_resize`, `transform`, `STATE_TRANSFORMS`, `REQUIRED_STATES`, `PackError`.

- [ ] **Step 1: Write failing test**

```python
def test_build_pack_from_state_images_requires_all_states(tmp_path):
    # missing "error" -> PackError

def test_build_pack_from_state_images_writes_distinct_states(tmp_path):
    # idle image red 64x64, thinking image blue 64x64, others green
    # -> manifest has 5 states; frames/ files exist; the first frame of
    # idle is predominantly red, thinking predominantly blue (pixel sample)
```

- [ ] **Step 2: Run, confirm FAIL** — `PackError has no attribute / function not defined`.

- [ ] **Step 3: Implement in `ui/avatar/pack.py`**

Extract the body of `build_pack` after image load into `build_pack_from_state_images`; the per-state loop source image is `state_images[state]` (preprocessed when `preprocess=True`); manifest writing identical to today. `build_pack` becomes: load PIL image, single preprocess, delegate.

- [ ] **Step 4: Run new + existing pack/avatar tests**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_pack_states.py tests/ui/test_pack.py -q` — PASS (existing `test_pack.py` skips remain skips).

- [ ] **Step 5: Commit**

```bash
git add ui/avatar/pack.py tests/ui/test_pack_states.py
git commit -m "refactor: pack builder accepts per-state base images (F2)"
```

---

### Task 3: Emotion prompts + AI pack orchestration

**Files:**
- Create: `ui/avatar/ai_pack.py`
- Test: `tests/ui/test_ai_pack.py`

**Interfaces:**
- Produces:
  - `IDENTITY_BLOCK: str` (exact spec copy)
  - `EMOTION_PROMPTS: dict[str, str]` — keys exactly `idle, thinking, working, speaking, error` (exact spec clauses)
  - `emotion_prompt(state: str) -> str` → `f"{IDENTITY_BLOCK}\n\n{EMOTION_PROMPTS[state]}"`; `KeyError` for unknown state
  - `class AiPackCancelled(Exception)`
  - `build_ai_pack(photo: Path, out_dir: Path, name: str, generate, *, progress=None, cancelled=None) -> Path`
    - `generate(state: str, prompt: str) -> bytes` ( injected; returns encoded image bytes)
    - `progress(state: str, index: int, total: int) -> None` called before each generation (1-based index)
    - `cancelled() -> bool` polled before each generation; truthy → raise `AiPackCancelled` after removing `out_dir`
    - decodes bytes via `PIL.Image.open(BytesIO(...))`, collects per-state images, delegates to `build_pack_from_state_images`
    - any other exception → remove `out_dir` if created, re-raise
- Consumes: `build_pack_from_state_images` (Task 2), `ui.avatar.pack.sanitize_pack_name` for nothing (name arrives sanitized by caller).

- [ ] **Step 1: Write failing tests** (`tests/ui/test_ai_pack.py`)

```python
def test_prompt_contract():
    # EMOTION_PROMPTS keys == REQUIRED_STATES set; every value non-empty;
    # emotion_prompt("idle") starts with IDENTITY_BLOCK

def test_build_ai_pack_generates_five_and_builds(tmp_path):
    # fake generate returns tiny PNG bytes; progress records
    # [("idle",1,5), ..., ("error",5,5)]; result dir has manifest.json

def test_build_ai_pack_cleans_up_on_cancel(tmp_path):
    # cancelled() True after 2 calls -> AiPackCancelled; out_dir gone

def test_build_ai_pack_cleans_up_on_generator_failure(tmp_path):
    # generate raises RuntimeError on call 3 -> propagates; out_dir gone
```

- [ ] **Step 2: Run, confirm FAIL**

- [ ] **Step 3: Implement `ui/avatar/ai_pack.py`**

Exact strings: `IDENTITY_BLOCK` and the five clauses verbatim from the spec table. `build_ai_pack` loop over `tuple(EMOTION_PROMPTS)` in order idle→thinking→working→speaking→error.

- [ ] **Step 4: Run tests, confirm PASS**

- [ ] **Step 5: Commit**

```bash
git add ui/avatar/ai_pack.py tests/ui/test_ai_pack.py
git commit -m "feat: AI emotion-set pack orchestration with fixed prompts (F2)"
```

---

### Task 4: Settings persistence + AI model dropdown

**Files:**
- Modify: `ui/settings.py` (avatar section widgets, `save`, `load`, new fetch worker hookup)
- Modify: `ui/i18n.py` (keys in Step 1)
- Test: `tests/ui/test_settings.py`

**Interfaces:**
- Produces (UI attributes later tasks reuse):
  - `self._ai_model: QComboBox` (editable)
  - `self._ai_generate: QPushButton`, `self._ai_cancel: QPushButton` (cancel hidden until running)
  - `SettingsWindow._fetch_ai_models(self) -> None`, `_on_ai_models_loaded(self, models: list, gen: int | None = None)`
- Consumes: `is_image_model` (Task 1), `create_provider`, `_ModelListWorker`, `PROVIDER_KEY_SECRETS`, B23 generation-guard idiom (own counter `_ai_fetch_gen`).

- [ ] **Step 1: Write failing tests + i18n keys**

Tests in `tests/ui/test_settings.py`:

```python
def test_avatar_ai_model_round_trip(tmp_path):
    # set _ai_model to "gpt-image-1", save(), reload() -> value kept;
    # saved JSON has settings["avatar_ai"]["model"] == "gpt-image-1"

def test_ai_model_dropdown_filters_to_image_models(tmp_path, monkeypatch):
    # stub create_provider list_models -> ["gpt-image-1", "llama-3.3-70b"]
    # _on_ai_models_loaded([...]) leaves only image models in the combo

def test_ai_model_fetch_generation_guard(tmp_path, monkeypatch):
    # start fetch #1 (github), then fetch #2 (groq); emit from worker #1
    # -> combo unchanged; emit from worker #2 -> applied (B23 pattern)
```

i18n keys (tr + en): `settings.ai_model`, `settings.ai_generate`, `settings.ai_cancel`, `settings.ai_privacy`, `settings.ai_progress`, `settings.ai_success`, `settings.ai_failed`, `settings.ai_fallback`.

- [ ] **Step 2: Run, confirm FAIL**

- [ ] **Step 3: Implement**

Avatar form rows for `_ai_model` / `_ai_generate` / `_ai_cancel` / privacy hint label; `_update_build_enabled` also gates `_ai_generate` on non-empty model text; `save()` writes `settings["avatar_ai"] = {"model": ...}`; `load()` reads it; `_fetch_ai_models` called on provider-type change next to `_fetch_models` and after load when a key exists.

- [ ] **Step 4: Run tests, confirm PASS** (settings + i18n suites)

- [ ] **Step 5: Commit**

```bash
git add ui/settings.py ui/i18n.py tests/ui/test_settings.py
git commit -m "feat: settings avatar_ai model persistence and filtered dropdown (F2)"
```

---

### Task 5: Generate flow wiring (worker, progress, cancel, success)

**Files:**
- Modify: `ui/settings.py` (`_AiPackWorker`, `_start_ai_pack`, `_on_ai_*` slots)
- Test: `tests/ui/test_settings.py` (and full suite at the end)

**Interfaces:**
- Produces:
  - `class _AiPackWorker(src: Path, out: Path, name: str, model: str, client: ImageGenClient)` with `_AiPackSignals`: `progress = Signal(str, int, int)`, `succeeded = Signal(str)`, `failed = Signal(str)`, `cancelled = Signal()`; `start()`, `wait(ms=5000)`, `cancel()` (sets a `threading.Event`)
  - `SettingsWindow._start_ai_pack(self) -> None` — resolves photo from `_pack_path`, name via `sanitize_pack_name` (fallback photo stem), `out = user_avatars_dir() / name`, builds `ImageGenClient` from current provider form values (`base_url` field text or `preset_url` via lazy `core.providers` import; key from `PROVIDER_KEY_SECRETS` + secrets file), starts worker
- Consumes: `build_ai_pack` (Task 3), `_on_pack_built` / `_on_pack_failed` (existing success/failure slots reuse), `ImageGenClient` (Task 1).

- [ ] **Step 1: Write failing tests**

```python
def test_ai_generate_success_reuses_pack_built_slot(tmp_path, monkeypatch):
    # monkeypatch settings.build_ai_pack to touch out_dir/manifest and call
    # progress; fake client; start worker; wait; assert succeeded path:
    # _avatar combo contains the new pack name and status shows ai_success

def test_ai_generate_cancel_removes_partial_and_reenables(tmp_path, monkeypatch):
    # build_ai_pack blocked on an Event; cancel(); worker emits cancelled;
    # out_dir absent; _ai_generate enabled again

def test_ai_generate_failure_shows_status(tmp_path, monkeypatch):
    # build_ai_pack raises ImageGenError("429") -> status contains ai_failed
```

- [ ] **Step 2: Run, confirm FAIL**

- [ ] **Step 3: Implement worker + slots**

Worker mirrors `_PackBuildWorker` (plain thread + QObject signal carrier). `build_ai_pack` call signature from Task 3; client injected. On `succeeded` call `self._on_pack_built(name)`. On `cancelled` restore UI quietly (no error box). On `failed` set `_status` via `settings.ai_failed` with the error text.

- [ ] **Step 4: Run targeted + full suite**

Run: `QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests/ui/test_settings.py -q` then full `tests -q` — all PASS.

- [ ] **Step 5: Commit**

```bash
git add ui/settings.py tests/ui/test_settings.py
git commit -m "feat: settings AI avatar generation flow (F2)"
```
