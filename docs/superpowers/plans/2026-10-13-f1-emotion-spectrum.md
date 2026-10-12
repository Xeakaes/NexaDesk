# F1 Emotion Spectrum Implementation Plan

> **For agentic workers:** Execute inline with superpowers:executing-plans + superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 5 emotions × 5 states per pack; LLM classifies each final reply; avatar renders state×emotion; v1 packs stay neutral-only.

**Spec:** `docs/superpowers/specs/2026-10-13-f1-emotion-spectrum-design.md` (binding authority; user waived review gates — proceed without pausing).

## Global Constraints

- English artifacts, Turkish chat; TDD RED→GREEN; explicit-path commits; suite stays green (`QT_QPA_PLATFORM=offscreen .venv/bin/pytest tests -q`, currently 471).
- Never commit `config/settings.json`, `config/logs/`, `assets/avatars/{max_verstopen,osaka,teto,teto_ekmek}`.
- Classifier never raises; fallback `neutral`. Classic `build_pack` keeps emitting v1 manifests.

## Review Focus

- v1 pack + `assistant_emotion(happy)` → renders identical frames to neutral (no KeyError).
- Classifier cancellation: cancelled task must not fire a provider call.
- `build_pack_from_emotion_images` atomicity: failure leaves no dir; pre-existing dir untouched (F2 review fix preserved).
- `set_emotion` during `error` state: error tint frames must come from the new emotion, timer restarts correctly.
- Runtime: emotion published before `agent_finished` (UI applies it while still speaking).

---

### Task 1: Emotion classifier (Qt-free)

**Files:** Create `core/agent/emotion.py`, `tests/core/test_emotion.py`

**Interfaces:**
- Produces: `EMOTIONS: tuple[str, ...]` (neutral, happy, sad, angry, surprised); `classify_emotion(provider, text: str, cancel) -> str`
- Consumes: `provider.complete(messages, [], cancel)` (empty schemas), `ChatMessage` from `core.providers.base`, `CancellationToken`.

- [ ] Step 1: failing tests — happy-path single word; "Sure! Here you go: happy" → happy; garbage → neutral; empty text → neutral (no provider call); provider raises → neutral; cancelled token → neutral and no provider call.
- [ ] Step 2: confirm FAIL (import error).
- [ ] Step 3: implement — system prompt "Classify the assistant reply into exactly one word: neutral, happy, sad, angry, or surprised. Answer with that single word only."; user message = reply text; parse first token lowercased.
- [ ] Step 4: PASS. Commit `feat: LLM emotion classifier for avatar replies (F1)`.

### Task 2: Manifest v2 loader

**Files:** Modify `ui/avatar/manifest.py`; extend `tests/ui/test_manifest.py`

**Interfaces:**
- Produces: `REQUIRED_EMOTIONS`; frozen dataclass `Manifest(emotions: dict[str, dict[str, StateAnim]])` with `.states` property → `emotions["neutral"]`; `load_manifest` returns `Manifest`.
- Consumes: existing `StateAnim`, `ManifestError`.

- [ ] Step 1: failing tests — v2 full pack loads; v1 wraps as `{"neutral": ...}` and `.states` equals old return; missing emotion → ManifestError; unknown emotion key → ManifestError; v2 missing state inside an emotion → ManifestError.
- [ ] Step 2: confirm FAIL.
- [ ] Step 3: implement; keep v1 frame-path resolution identical.
- [ ] Step 4: PASS (manifest + avatar window existing tests may need `load_manifest(...).states` adjustments — update call sites in `window.py` in this task if compile breaks, or land window changes with Task 4; prefer minimal: `window.py` reads `.states` now).
- [ ] Commit `feat: manifest v2 emotion axis with v1 compatibility (F1)`.

### Task 3: Pack builder — per-emotion images → v2 pack

**Files:** Modify `ui/avatar/pack.py`; Create `tests/ui/test_pack_emotions.py`

**Interfaces:**
- Produces: `build_pack_from_emotion_images(emotion_images: dict[str, Image.Image], out_dir: Path, name: str, *, preprocess: bool = True) -> Path`
- Consumes: `strip_background`, `keep_largest_component`, `crop_pad_resize`, `transform`, `STATE_TRANSFORMS`, `REQUIRED_EMOTIONS` (manifest.py), `PackError`.

- [ ] Step 1: failing tests — missing emotion → PackError; existing out_dir untouched (marker survives); 25 frames under `frames/<emotion>/`; v2 manifest shape; preprocess=False keeps pixel colors.
- [ ] Step 2: confirm FAIL.
- [ ] Step 3: implement (temp-dir + rename, same atomicity pattern).
- [ ] Step 4: PASS + full `tests/ui/test_pack*.py` green. Commit `feat: pack builder emits v2 emotion packs (F1)`.

### Task 4: AI generation rework (emotion-keyed) + window emotion rendering

**Files:** Modify `ui/avatar/ai_pack.py`, `ui/avatar/window.py`; extend `tests/ui/test_ai_pack.py`, Create `tests/ui/test_avatar_emotion.py`

**Interfaces:**
- `ai_pack.EMOTION_PROMPTS` re-keyed to REQUIRED_EMOTIONS (exact clauses from spec); `emotion_prompt(emotion)`; `build_ai_pack` generates per-emotion stills then calls `build_pack_from_emotion_images`.
- `window.set_emotion(emotion)`, `window.current_emotion()`; lookup `emotions.get(emotion, neutral)[state]`; unknown → neutral; state preserved.

- [ ] Step 1: failing tests — prompt contract keys == REQUIRED_EMOTIONS; build_ai_pack fake generator → 5 emotion-keyed calls, v2 manifest, cancel/failure cleanup (existing tests updated for new key set); window set_emotion switches frames + keeps state; unknown emotion → neutral; v1 pack + set_emotion("happy") renders neutral frames (no crash).
- [ ] Step 2: confirm FAIL.
- [ ] Step 3: implement both.
- [ ] Step 4: PASS. Commit `feat: AI emotion-still generation and emotion-aware avatar window (F1)`.

### Task 5: Runtime event + avatar_app wiring

**Files:** Modify `core/events.py`, `core/agent/runtime.py`, `ui/avatar_app.py`; extend `tests/core/test_runtime*.py` (existing runtime tests), `tests/ui/test_avatar_app.py`

**Interfaces:**
- `EVENT_NAMES` += `"assistant_emotion"`; runtime publishes it after `assistant_message`, before `agent_finished`; classifier failures → neutral; cancelled tasks → no event.
- `avatar_app._on_event`: `assistant_emotion` → `avatar.set_emotion(...)`; `agent_cancelled`/`agent_error` → `set_emotion("neutral")`.

- [ ] Step 1: failing tests — stub provider reply "I'm so glad!" with stub classifier path (monkeypatch classify to deterministic or use real classifier with stub provider returning "happy") → event published with happy; classifier raising → neutral; cancelled → no event; avatar_app offscreen: emotion event reaches set_emotion (spy).
- [ ] Step 2: confirm FAIL.
- [ ] Step 3: implement.
- [ ] Step 4: PASS; full suite green. Commit `feat: assistant_emotion event and avatar wiring (F1)`.

## Self-review note
- Task 2 touches `window.py` minimally (`.states`); Task 4 does the emotion logic — split keeps each commit compiling.
- Classic v1 emission pinned by existing `test_build_pack_produces_five_states` + a new assertion in Task 3 that `build_pack` manifest has no `"emotions"` key.
