# F1 Avatar Emotion Spectrum — Design Spec

**Date:** 2026-10-13
**Status:** approved-for-implementation by user directive (2026-10-13: "devam et, durmana gerek yok, sormana gerek yok" — approval gates waived; F1 questions settled in-chat: LLM classification, 5 AI generations + transform states)

## Goal

Add a second axis — **emotion** — to avatar packs: 5 emotions (neutral, happy, sad, angry, surprised) × the existing 5 states (idle, thinking, working, speaking, error) = 25 animation variants per pack. The agent classifies each final reply into one emotion via a small LLM call; the avatar renders `state × emotion`. Old packs (v1 manifests, no emotion axis) keep working as neutral-only. F1 and F2 share one pack-format change and one generation pipeline.

## User decisions (2026-10-13)

1. **Emotion selection = LLM classification.** After each final assistant reply, one small provider call classifies the text into `neutral | happy | sad | angry | surprised`. Cost/latency accepted; failure falls back to `neutral`, never blocks or fails the task.
2. **Generation = 5 AI calls, not 25.** AI generates one still per **emotion** (identity-preserving, fixed prompts); the existing deterministic transform pipeline (`dx/dy/tint` per state) produces each emotion's 5 state animations → 25 variants at F2's cost. Per-state expressions ("working = focused") are intentionally given up; states keep motion/tint only. Runtime never feeds images back to the model — frame selection is by `(emotion, state)` codename lookup.

## Pack format v2

```json
{
  "name": "ai_hero",
  "format": 2,
  "emotions": {
    "neutral": {
      "idle":    {"frames": ["frames/neutral/idle_00.png", "..."], "fps": 6, "loop": true},
      "thinking": {...}, "working": {...}, "speaking": {...}, "error": {...}
    },
    "happy": {...}, "sad": {...}, "angry": {...}, "surprised": {...}
  }
}
```

- Frame paths live under `frames/<emotion>/<state>_XX.png`.
- **v1 compatibility:** a manifest with top-level `"states"` and no `"emotions"` loads as `{"neutral": <states>}`. Any pack the loader accepts renders identically to today when emotion is neutral.
- `REQUIRED_EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised")` — same completeness rule as states: all five required in v2 manifests; emotion keys outside the set are rejected.
- Classic AI-less `build_pack` keeps emitting **v1** (single base image → neutral-only). Only the AI path emits v2.

## Components

### 1. Loader — `ui/avatar/manifest.py`

- `load_manifest(path) -> Manifest` where `Manifest` is a frozen dataclass with `emotions: dict[str, dict[str, StateAnim]]` and a `states` property returning `emotions["neutral"]` (back-compat for v1 semantics).
- Validation: v2 requires every `REQUIRED_EMOTIONS` entry, each with every `REQUIRED_STATES` entry; unknown emotion keys → `ManifestError`. v1 path unchanged except it wraps into the emotion structure.
- Frame file existence is **not** validated here (tracked separately as B46; out of F1 scope).

### 2. Emotion classifier — `core/agent/emotion.py` (Qt-free)

```python
EMOTIONS = ("neutral", "happy", "sad", "angry", "surprised")

def classify_emotion(provider, text: str, cancel: CancellationToken) -> str: ...
```

- One `provider.complete()` call, **no tool schemas** (empty list), system prompt: classify the user-visible reply into exactly one of the five words; answer with that single word.
- Parse: strip, lowercase, first token; if it is in `EMOTIONS` return it, else `neutral`. Never raises: provider errors, empty text, cancellation → `neutral` (cancellation checked first so a cancelled task doesn't fire a network call).
- Bounded: the provider's own HTTP timeout applies; no retry.

### 3. Runtime integration — `core/agent/runtime.py` + `core/events.py`

- New event `assistant_emotion` added to `EVENT_NAMES`, payload `{"emotion": "<one of EMOTIONS>"}`.
- In the final-response path (where `assistant_message` + `agent_finished` are published), after `assistant_message` and before `agent_finished`: run `classify_emotion` (guarded by try/except → neutral) and publish `assistant_emotion`. Runs on the agent worker thread; adds one sequential LLM call per completed task.
- Cancelled/error tasks publish no emotion event.

### 4. Avatar window — `ui/avatar/window.py`

- Holds `self._emotion: str = "neutral"` and the `Manifest`.
- `set_emotion(emotion: str) -> None`: unknown emotion → treat as `neutral`; if changed, reset frame index, re-render, keep current **state** and timer.
- Frame lookup: `self._manifest.emotions.get(self._emotion, neutral)[self._state]`.
- `current_emotion()` accessor for tests.

### 5. UI wiring — `ui/avatar_app.py`

- In `_on_event`, handle `assistant_emotion`: `self.avatar.set_emotion(event.payload.get("emotion", "neutral"))`. GUI mode ignores the event (no avatar).
- `agent_cancelled` / `agent_error` reset emotion to `neutral` via `set_emotion` (state machine already moves to error/idle).

### 6. Generation — `ui/avatar/ai_pack.py` + `ui/avatar/pack.py` (F2 rework)

- `EMOTION_PROMPTS` becomes **emotion-keyed**:

  | emotion | clause (appended after `IDENTITY_BLOCK`) |
  |---|---|
  | neutral | `Calm and neutral, relaxed expression.` |
  | happy | `Happy and cheerful, smiling expression.` |
  | sad | `Sad and downcast, melancholic expression.` |
  | angry | `Angry and annoyed, frowning expression.` |
  | surprised | `Surprised and wide-eyed, startled expression.` |

- `build_ai_pack(photo, out_dir, name, generate, *, progress, cancelled)`: generates one still per `REQUIRED_EMOTIONS` (5 calls, same progress/cancel/cleanup semantics as today), then delegates to a new builder:
- `build_pack_from_emotion_images(emotion_images: dict[str, Image.Image], out_dir, name, *, preprocess=True) -> Path` in `pack.py`: per emotion, run strip→largest→crop/resize once, then the existing `STATE_TRANSFORMS` loop writes `frames/<emotion>/<state>_XX.png`; emits the v2 manifest. Temp-dir + rename atomicity unchanged; missing emotion or state → `PackError`.
- `build_pack` (classic) and `build_pack_from_state_images` keep emitting v1 manifests untouched.

### 7. Settings

- No new settings keys. The existing `avatar_ai.model` (or provider default) is the classifier model as well. No toggle (user accepted the classification cost).

## Error handling

- Classifier never raises; worst case every reply is `neutral`.
- Emotion events with garbage payloads render `neutral`.
- v1 packs + emotion events → window looks up `emotions["neutral"]`; identical visuals to today.
- AI generation failure/cancel: identical cleanup semantics as F2 (no partial dir; pre-existing dir untouched — the review fix stays).

## Testing (TDD list)

1. `core/agent/emotion.py`: parse happy-path / extra text / garbage / empty / provider error / cancellation → correct emotion or neutral; never raises.
2. Manifest: v2 loads 5×5; v1 wraps as neutral-only; missing emotion and unknown emotion key → `ManifestError`; `states` property == neutral.
3. `build_pack_from_emotion_images`: writes 25 variants under `frames/<emotion>/`; v2 manifest shape; preprocess on/off; missing keys → `PackError`; existing dir untouched.
4. `build_ai_pack` rework: fake generator → 5 calls (emotion-keyed prompts), v2 output; cancel mid-set → cleanup.
5. Window: `set_emotion` switches frame set, keeps state, unknown → neutral; v1 pack renders under any emotion.
6. Runtime: stub provider whose text reply classifies as "happy" → `assistant_emotion` event with `happy`; classifier raising → `neutral`; cancelled task → no event.
7. `avatar_app._on_event("assistant_emotion")` calls `set_emotion` (existing offscreen pattern).
8. Classic `build_pack` still emits v1 (regression pin).

## Non-goals

- Per-state expressions in AI packs (explicitly traded away).
- Emotion toggle in Settings; per-tool/per-event emotion rules; GUI-mode emotion display.
- B46 frame-existence validation; gallery UI for generated packs (0.2.3+).
