# F2 — AI Avatar Generation (Design)

Date: 2026-10-12
Status: approved (conversational design, 2026-10-12)
Backlog ref: `nexadesk-0.2.2-plan.md` F2

## Goal

Let a user turn a single base photo into a fully animated 5-state avatar pack
using their already-configured model provider, with the AI output kept
faithful to the original character. When the configured provider offers no
image-generation model, the existing AI-less pack builder runs unchanged.

## Non-goals

- No free-text user prompt — all prompts are fixed, app-owned strings.
- No multi-photo references, no style picker, no editing of existing packs.
- No per-state custom user instructions.
- No new provider types; image generation rides the existing provider config.

## User flow (Settings → Avatar)

1. User picks a source photo (file dialog) and an image model.
2. User presses **Generate**. A background worker:
   - generates one image per pack state (5 sequential calls),
   - normalizes each image through the existing pack pipeline
     (`strip_background` → `keep_largest_component` → `crop_pad_resize`),
   - derives animation frames per state via the existing transforms,
   - writes the pack (images + `manifest.json`) under `user_avatars_dir()`,
   - selects the new pack as the current avatar.
3. Progress ("Generating state 3/5: working…") is shown; **Cancel** aborts
   between calls and removes any partial output.

A short hint states that the photo is sent to the configured provider
(same privacy wording family as the docs B16 rewrite).

## Emotion-set generation contract

Fixed prompt dictionary (English, lives in code):

- Common identity block (prepended to every prompt):

  > Recreate this exact character from the photo — same face, hair, colors,
  > outfit, and art style. Do not redesign, do not add or remove elements.
  > Neutral flat background. Character centered, full upper body visible.

- Per-state clause (`EMOTION_PROMPTS`, exactly these five keys):

  | state | clause |
  |---|---|
  | idle | `Calm and neutral, relaxed expression.` |
  | thinking | `Pensive, looking slightly upward as if thinking.` |
  | working | `Focused and busy, determined expression.` |
  | speaking | `Cheerful and talkative, mid-conversation expression.` |
  | error | `Surprised or alarmed, wide-eyed reaction.` |

The source photo is attached as the reference input (see client section).
Each call produces one still; animation is entirely our transform pipeline.

## Image-generation client

- Two OpenAI-compatible endpoints, tried in order per call:
  1. `POST {base_url}/images/edits` (multipart: `model`, `prompt`, `image`
     = the source photo, `size=1024x1024`, `n=1`) — the photo acts as the
     identity reference (gpt-image-1 style).
  2. On any rejection (model or endpoint does not support edits),
     fall back once to `POST {base_url}/images/generations` (JSON:
     `{"model", "prompt", "size": "1024x1024", "n": 1}`) with the identity
     block alone (text-only).
- `base_url` comes from the current provider config (including the
  `preset_url` fallbacks from B18); the key from the matching
  `PROVIDER_KEY_SECRETS` entry.
- Response handling for both endpoints: accept `data[0].b64_json` or
  `data[0].url` (download).
- Both attempts are logged via the existing telemetry `log_event`.
- Sequential calls, 120 s timeout each, no parallelism (rate-limit friendly).
- Lives in `core/providers/image_gen.py` (pure `requests`, no Qt).

## Model selection and persistence

- Settings key: `settings["avatar_ai"] = {"model": "<model id>"}`.
- The model dropdown is populated from `create_provider().list_models()`
  filtered by `IMAGE_MODEL_MARKERS` (`gpt-image`, `dall-e`, `dall_e`,
  `flux`, `imagen`, `seedream`, `stable-diffusion`, `sd3`, `image`), plus
  the field stays editable for free entry.
- Changing the provider refreshes the dropdown (same worker pattern as the
  chat model list, respecting the B23 generation guard).

## Fallback (no image-generation model)

If the provider has no key configured, `list_models` fails, the model field
is empty, or every catalog model misses the markers **and** the user left
the field empty, the UI disables Generate and links to the existing
AI-less pack builder. Direct API: `build_pack(photo, out, name)` unchanged.

## Naming and switching

- Pack name: `sanitize_pack_name(photo stem)`; on collision append `-2`,
  `-3`, ….
- After a successful build the pack is written into the user avatars dir
  and selected as the current avatar (settings `avatar` key updated, avatar
  app/ChatWindow pick it up through the existing settings-save path).

## Error handling and cancellation

- Any failed generation aborts the whole operation: no manifest is written,
  already-written temp images are deleted, the UI shows the provider's error
  message (rate limit / auth mapped like B17 where applicable).
- Cancel between calls: same cleanup, quiet exit.
- The worker never touches the live runtime; it only writes files and emits
  UI-thread signals (existing `_PackBuildWorker` pattern).

## Testing (TDD)

1. Prompt contract: exactly five states, shared identity block, no
   user-editable text paths.
2. Client: request shape for edits (multipart) and generations (JSON),
   b64 and url response handling, edits→generations fallback, error
   propagation (fake session).
3. Flow: fake client → five emotion images → pack on disk with valid
   manifest, all five states present, frames exist.
4. Fallback: no markers and empty model → Generate disabled / AI-less path
   invoked.
5. Cancellation and mid-run failure: no partial pack left behind.
6. Settings: `avatar_ai.model` round-trip; dropdown refresh respects the
   fetch generation guard.

## Decisions log

- 2026-10-12: provider-based selection; image-output models (not vision
  input models) with free entry; hide/disable when none available.
- 2026-10-12: prompts are app-fixed; user supplies only the photo.
- 2026-10-12: AI generates the emotion set (one still per state); our
  transform pipeline completes the animated work set.
- 2026-10-12: entry point Settings → Avatar; AI-less builder remains the
  fallback path.
