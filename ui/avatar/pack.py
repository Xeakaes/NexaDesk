"""Avatar asset-pack builder: photo → 5-state frames + manifest (spec §8)."""

from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path

from PIL import Image

TOLERANCE = 48
PAD = 8
TARGET_H = 192

STATE_TRANSFORMS: dict[str, dict] = {
    "idle": {"dy": [0, -2, 0, 2], "fps": 6, "loop": True},
    "thinking": {"dx": [0, 3, 0, -3], "fps": 4, "loop": True},
    "working": {"dy": [0, -3, -5, -3, 0, 3], "fps": 10, "loop": True},
    "speaking": {"dy": [0, -4, 0, -2], "fps": 8, "loop": True},
    "error": {"dy": [0, 0, 0], "tint": [True, False, True], "fps": 5, "loop": False},
}


class PackError(ValueError):
    pass


BUILTIN_PACK = "base"


def sanitize_pack_name(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    cleaned = re.sub(r"_+", "_", cleaned)
    if not cleaned:
        raise PackError("empty pack name")
    return cleaned


def _near(c1, c2, tol: int) -> bool:
    return all(abs(a - b) <= tol for a, b in zip(c1[:3], c2[:3]))


def strip_background(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    seeds = []
    for x in range(w):
        seeds.append((x, 0))
        seeds.append((x, h - 1))
    for y in range(h):
        seeds.append((0, y))
        seeds.append((w - 1, y))
    bg = px[0, 0]
    seen = set()
    q = deque(seeds)
    while q:
        x, y = q.popleft()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h):
            continue
        seen.add((x, y))
        if _near(px[x, y], bg, TOLERANCE):
            px[x, y] = (0, 0, 0, 0)
            q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return img


def keep_largest_component(img: Image.Image) -> Image.Image:
    img = img.convert("RGBA")
    px = img.load()
    w, h = img.size
    visited = set()
    best: list[tuple[int, int]] = []
    for sy in range(h):
        for sx in range(w):
            if (sx, sy) in visited or px[sx, sy][3] == 0:
                continue
            comp: list[tuple[int, int]] = []
            q = deque([(sx, sy)])
            while q:
                x, y = q.popleft()
                if (x, y) in visited or not (0 <= x < w and 0 <= y < h):
                    continue
                visited.add((x, y))
                if px[x, y][3] == 0:
                    continue
                comp.append((x, y))
                q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
            if len(comp) > len(best):
                best = comp
    keep = set(best)
    for y in range(h):
        for x in range(w):
            if px[x, y][3] > 0 and (x, y) not in keep:
                px[x, y] = (0, 0, 0, 0)
    return img


def crop_pad_resize(img: Image.Image, target_h: int = TARGET_H) -> Image.Image:
    bbox = img.getbbox()
    if bbox is None:
        raise PackError("empty after background removal")
    img = img.crop(bbox)
    w, h = img.size
    canvas = Image.new("RGBA", (w + 2 * PAD, h + 2 * PAD), (0, 0, 0, 0))
    canvas.paste(img, (PAD, PAD))
    scale = target_h / canvas.height
    new_w = max(1, round(canvas.width * scale))
    return canvas.resize((new_w, target_h), Image.NEAREST)


def transform(base: Image.Image, dx: int = 0, dy: int = 0, tint: bool = False) -> Image.Image:
    out = Image.new("RGBA", base.size, (0, 0, 0, 0))
    out.paste(base, (dx, dy), base)
    if tint:
        px = out.load()
        for y in range(out.height):
            for x in range(out.width):
                r, g, b, a = px[x, y]
                if a > 0:
                    px[x, y] = (min(255, r + 102), int(g * 0.6), int(b * 0.6), a)
    return out


def build_pack_from_state_images(
    state_images: dict[str, Image.Image],
    out_dir: Path,
    name: str,
    *,
    preprocess: bool = True,
) -> Path:
    """Build a pack from one base image per REQUIRED_STATES entry.

    With ``preprocess=True`` each image runs the background-strip → largest
    component → crop/pad/resize pipeline first; ``False`` expects images that
    are already normalized (preprocessed once upstream, e.g. by build_pack).
    """
    from ui.avatar.manifest import REQUIRED_STATES

    name = sanitize_pack_name(name)
    missing = [s for s in REQUIRED_STATES if s not in state_images]
    if missing:
        raise PackError(f"missing states: {', '.join(missing)}")
    if out_dir.exists():
        raise PackError(f"exists: {out_dir}")
    # Build into a temp sibling, rename on success — no partial pack left on failure.
    import shutil
    import uuid

    tmp_dir = out_dir.parent / f".{out_dir.name}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        frames_dir = tmp_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        bases: dict[str, Image.Image] = {}
        for state in REQUIRED_STATES:
            img = state_images[state]
            if preprocess:
                try:
                    img = keep_largest_component(strip_background(img))
                    img = crop_pad_resize(img)
                except PackError:
                    raise
                except Exception as exc:
                    raise PackError(f"pipeline failed: {exc}") from exc
            bases[state] = img

        manifest: dict = {"name": name, "states": {}}
        for state, cfg in STATE_TRANSFORMS.items():
            n = max(
                len(cfg.get("dx") or [0]),
                len(cfg.get("dy") or [0]),
                len(cfg.get("tint") or [False]),
            )
            rels = []
            for i in range(n):
                dx = (cfg.get("dx") or [0] * n)[i]
                dy = (cfg.get("dy") or [0] * n)[i]
                tint = (cfg.get("tint") or [False] * n)[i]
                frame = transform(bases[state], dx=dx, dy=dy, tint=tint)
                rel = f"frames/{state}_{i:02d}.png"
                frame.save(tmp_dir / rel)
                rels.append(rel)
            manifest["states"][state] = {
                "frames": rels,
                "fps": cfg["fps"],
                "loop": cfg["loop"],
            }
        (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        tmp_dir.rename(out_dir)
        return out_dir
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def build_pack_from_emotion_images(
    emotion_images: dict[str, Image.Image],
    out_dir: Path,
    name: str,
    *,
    preprocess: bool = True,
) -> Path:
    """Build a v2 pack from one base image per REQUIRED_EMOTIONS entry.

    Each emotion still runs the background-strip → largest component →
    crop/pad/resize pipeline (when ``preprocess=True``) once, then the
    STATE_TRANSFORMS loop writes ``frames/<emotion>/<state>_XX.png`` and a
    v2 manifest with the full emotion × state grid.
    """
    from ui.avatar.manifest import REQUIRED_EMOTIONS

    name = sanitize_pack_name(name)
    missing = [e for e in REQUIRED_EMOTIONS if e not in emotion_images]
    if missing:
        raise PackError(f"missing emotions: {', '.join(missing)}")
    if out_dir.exists():
        raise PackError(f"exists: {out_dir}")
    import shutil
    import uuid

    tmp_dir = out_dir.parent / f".{out_dir.name}.tmp-{uuid.uuid4().hex[:8]}"
    try:
        bases: dict[str, Image.Image] = {}
        for emotion in REQUIRED_EMOTIONS:
            img = emotion_images[emotion]
            if preprocess:
                try:
                    img = keep_largest_component(strip_background(img))
                    img = crop_pad_resize(img)
                except PackError:
                    raise
                except Exception as exc:
                    raise PackError(f"pipeline failed: {exc}") from exc
            bases[emotion] = img

        manifest: dict = {"name": name, "format": 2, "emotions": {}}
        for emotion in REQUIRED_EMOTIONS:
            frames_dir = tmp_dir / "frames" / emotion
            frames_dir.mkdir(parents=True, exist_ok=True)
            manifest["emotions"][emotion] = {}
            for state, cfg in STATE_TRANSFORMS.items():
                n = max(
                    len(cfg.get("dx") or [0]),
                    len(cfg.get("dy") or [0]),
                    len(cfg.get("tint") or [False]),
                )
                rels = []
                for i in range(n):
                    dx = (cfg.get("dx") or [0] * n)[i]
                    dy = (cfg.get("dy") or [0] * n)[i]
                    tint = (cfg.get("tint") or [False] * n)[i]
                    frame = transform(bases[emotion], dx=dx, dy=dy, tint=tint)
                    rel = f"frames/{emotion}/{state}_{i:02d}.png"
                    frame.save(tmp_dir / rel)
                    rels.append(rel)
                manifest["emotions"][emotion][state] = {
                    "frames": rels,
                    "fps": cfg["fps"],
                    "loop": cfg["loop"],
                }
        (tmp_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        tmp_dir.rename(out_dir)
        return out_dir
    except BaseException:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def build_pack(source_image: Path, out_dir: Path, name: str) -> Path:
    name = sanitize_pack_name(name)
    if out_dir.exists():
        raise PackError(f"exists: {out_dir}")
    try:
        img = Image.open(source_image)
        img.load()
    except Exception as exc:
        raise PackError(f"bad image: {exc}") from exc
    # Pre-downscale huge sources so the flood-fill background removal stays fast.
    img.thumbnail((512, 512))
    try:
        base = keep_largest_component(strip_background(img))
        base = crop_pad_resize(base)
    except PackError:
        raise
    except Exception as exc:
        raise PackError(f"pipeline failed: {exc}") from exc
    return build_pack_from_state_images(
        {state: base for state in STATE_TRANSFORMS}, out_dir, name, preprocess=False
    )


def delete_pack(avatars_root: Path, name: str) -> None:
    """Delete an avatar pack directory under avatars_root.

    Safety rails: never deletes the built-in 'base' pack, rejects path
    traversal, and only removes directories that look like real packs
    (contain manifest.json).
    """
    import shutil

    if name == BUILTIN_PACK:
        raise PackError("built-in pack cannot be deleted")
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        raise PackError(f"invalid pack name: {name!r}")
    root = avatars_root.resolve()
    target = (avatars_root / name).resolve()
    if root not in target.parents:
        raise PackError(f"invalid pack name: {name!r}")
    if not target.is_dir():
        raise PackError(f"not found: {name}")
    if not (target / "manifest.json").is_file():
        raise PackError(f"not a pack: {name}")
    shutil.rmtree(target)
