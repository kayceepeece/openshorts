"""Rewrite a clip's hook and title from what is actually on its screen.

Ported from upstream herdr-clipping (``hook_grounding.py``). Adaptations for
OpenShorts:
- Always on: no feature flag, no env gating. No screen content (or any
  failure) keeps the transcript hook silently.
- The only Gemini model this repo may call is gemini-3.8-flash.
- gemini_worker helpers (prompt/schema/blocked-check) are inlined so this
  module has no dependency on upstream-internal files (same pattern as
  layout_picker.py).
- Frame extraction reuses frame_sampler.read_at instead of a seek per sample.

The moment picker chooses clips and writes their hook from the transcript
alone; it never sees a frame. On a talking head that is fine. On a clip the
reframe rendered as SCREENCAST / WIDE / INSET the meaning is on the screen
(a settings dialog, a spreadsheet, a terminal) and the hook comes out as a
summary of the video's topic while the viewer is watching something specific.

So, for those clips only, once the render has said which stretches live on
the screen (the ``<clip>.layout.json`` sidecar, copied into
``clip['layout_ranges']``), three frames from those stretches at 1024px plus
the clip's own transcript go to Gemini and the hook and title are rewritten
to name what is shown. About 3k tokens per clip.

Frames need a model that can see, so this is Gemini-only: without a
GEMINI_API_KEY the function returns None and the transcript-based hook
stands. Never raises: a hook problem must never cost the clip.
"""
from __future__ import annotations

import json
import os
from typing import Optional

SCREEN_LAYOUTS = {"screencast", "wide", "inset"}
FRAMES = 3
WIDTH = 1024
# Ignore a blip: the screen stretches must cover this share of the clip.
MIN_SHARE = 0.25

# The only Gemini model this repo may call.
GEMINI_MODEL_NAME = "gemini-3.8-flash"

GROUNDED_HOOK_PROMPT = """
These frames come from ONE short clip (the whole clip, in order) and the
transcript below is exactly what is said during it. Most of this clip's
meaning is on the screen, not in the face.

1. `on_screen`: one line naming what is shown — the app, window, product,
   document, code, chart or on-screen text — as specifically as the frames
   allow (read visible titles and labels).
2. `viral_hook_text`: max 10 words, in TRANSCRIPT_LANGUAGE. It MUST mention
   the thing you named in `on_screen` (or the action being done to it: set
   up, connect, compare, fix, type) AND keep the strongest concrete fact of
   the clip: a number, a multiplier, a price, a name ("7x faster", "$136 a
   month", "3,400 stars") from the transcript or the current hook. Never a
   summary of the video's general topic, never a slogan that would fit any
   clip of this video, never drop a figure for a vaguer phrase.
3. `video_title_for_youtube_short`: max 100 chars, same rule, in
   TRANSCRIPT_LANGUAGE, no fake claims.

The current hook and title below were written WITHOUT seeing the frames and
are the kind of topic summary you must replace. Do not reuse their wording.

TRANSCRIPT_LANGUAGE: {language}
CURRENT_HOOK (to replace): {current_hook}
CURRENT_TITLE (to replace): {current_title}
TRANSCRIPT:
{transcript}

Return only:
{{"on_screen": "<one line>", "viral_hook_text": "<max 10 words>", "video_title_for_youtube_short": "<max 100 chars>"}}
"""

# JSON schema for the grounded-hook answer (dict form so no pydantic needed).
GROUNDED_HOOK_SCHEMA = {
    "type": "object",
    "properties": {
        "on_screen": {"type": "string"},
        "viral_hook_text": {"type": "string"},
        "video_title_for_youtube_short": {"type": "string"},
    },
    "required": ["viral_hook_text"],
}

_BLOCKED_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST",
                           "SPII", "IMAGE_SAFETY", "RECITATION"}


def raise_if_blocked(response):
    """Raise ValueError when the API refused to answer on policy grounds."""
    pf = getattr(response, "prompt_feedback", None)
    reason = getattr(pf, "block_reason", None)
    if reason:
        name = getattr(reason, "name", None) or str(reason)
        raise ValueError(f"Gemini blocked this video's content ({name}).")
    for c in (getattr(response, "candidates", None) or []):
        fr = getattr(c, "finish_reason", None)
        name = (getattr(fr, "name", None) or str(fr or "")).upper()
        if name in _BLOCKED_FINISH_REASONS:
            raise ValueError(f"Gemini blocked its answer ({name}).")


def screen_video() -> bool:
    """True when the layout picker (or the user) called this source a
    screencast. On such a video a GENERAL stretch, which the scene classifier
    emits for "no face in frame", is a full-screen slide, dialog or terminal,
    even when the width gate did not upgrade it to SCREENCAST."""
    try:
        import screencast_layout
        return bool(getattr(screencast_layout, "ENABLED", False))
    except Exception:
        return False


def screen_ranges(ranges, on_screen_video=None):
    """(start, end) pairs, clip seconds, of the stretches rendered on-screen."""
    import layout_ranges
    layouts = set(SCREEN_LAYOUTS)
    if screen_video() if on_screen_video is None else on_screen_video:
        layouts.add("general")
    return [(r["start"], r["end"]) for r in layout_ranges.normalise(ranges)
            if r["layout"] in layouts]


def wanted(ranges, clip_duration) -> bool:
    """True when enough of the clip lives on the screen to reground the hook.

    Never raises: bad input just means the transcript hook stands.
    """
    try:
        if not clip_duration or float(clip_duration) <= 0:
            return False
        covered = sum(e - s for s, e in screen_ranges(ranges))
        return covered / float(clip_duration) >= MIN_SHARE
    except Exception:
        return False


def clip_words(transcript, start, end) -> str:
    """What is said between ``start`` and ``end`` (source seconds)."""
    try:
        if not isinstance(transcript, dict):
            return ""
        out = []
        for seg in (transcript.get("segments", []) or []):
            if not isinstance(seg, dict):
                continue
            words = seg.get("words") or []
            if words:
                out.extend(w.get("word", "") for w in words
                           if isinstance(w, dict)
                           and w.get("end", 0) > start and w.get("start", 0) < end)
            elif seg.get("end", 0) > start and seg.get("start", 0) < end:
                out.append(seg.get("text", ""))
        return " ".join(t.strip() for t in out if t and t.strip())
    except Exception:
        return ""


def sample_times(ranges, clip_duration, n=None):
    """``n`` timestamps spread over the on-screen stretches (whole clip if
    the sidecar has none), never on the very first frame of a stretch, where
    a cut is still settling."""
    n = n or FRAMES
    try:
        duration = float(clip_duration)
    except (TypeError, ValueError):
        duration = 0.0
    if duration <= 0:
        return []
    try:
        spans = screen_ranges(ranges) or [(0.0, duration)]
    except Exception:
        spans = [(0.0, duration)]
    total = sum(e - s for s, e in spans) or duration
    times = []
    for i in range(n):
        target = total * (i + 0.5) / n
        for s, e in spans:
            if target <= e - s:
                times.append(s + target)
                break
            target -= e - s
    return times


def frames_at(video_path, times, width=None):
    """JPEG bytes of the frame at each timestamp, at ``width`` px wide.

    Reads through frame_sampler.read_at (one forward pass, no seek per
    sample). Raises on failure — callers inside reground() catch it; the
    module boundary itself (wanted/reground) never raises.
    """
    import cv2

    import frame_sampler

    width = width or WIDTH
    out = []
    cap = cv2.VideoCapture(video_path)
    try:
        if not cap.isOpened():
            return []
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        indices = sorted(int(float(t) * fps) for t in times or [])
        for frame in frame_sampler.read_at(cap, indices):
            if frame is None:
                continue
            h, w = frame.shape[:2]
            scaled = cv2.resize(frame, (width, max(2, int(h * width / w))),
                                interpolation=cv2.INTER_AREA)
            ok, buf = cv2.imencode(".jpg", scaled, [cv2.IMWRITE_JPEG_QUALITY, 80])
            if ok:
                out.append(buf.tobytes())
    finally:
        cap.release()
    return out


def _ask_gemini(frames, prompt, api_key):
    """One vision call; returns the parsed dict. Split out so tests can stub it."""
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)
    parts = [genai_types.Part.from_bytes(data=b, mime_type="image/jpeg") for b in frames]
    response = client.models.generate_content(
        model=GEMINI_MODEL_NAME,
        contents=parts + [prompt],
        config=genai_types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=GROUNDED_HOOK_SCHEMA,
        ))
    raise_if_blocked(response)
    return json.loads(response.text) or {}


def reground(clip_path, clip, transcript, start, end) -> Optional[dict]:
    """Rewrite ``clip['viral_hook_text']`` / ``video_title_for_youtube_short``
    in place from the clip's frames. Returns what changed (also stored under
    ``clip['hook_grounding']``), or None when skipped or failed.

    Never raises: any failure keeps the transcript hook and returns None, so
    a hook problem can never cost the clip.
    """
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        if not isinstance(clip, dict):
            return None
        try:
            duration = float(end) - float(start)
        except (TypeError, ValueError):
            return None
        times = sample_times(clip.get("layout_ranges"), duration)
        if not times:
            return None
        frames = frames_at(clip_path, times)
        if not frames:
            return None
        language = str((transcript if isinstance(transcript, dict) else {}).get("language")
                       or "unknown")
        prompt = GROUNDED_HOOK_PROMPT.format(
            language=language,
            current_hook=clip.get("viral_hook_text") or "",
            current_title=clip.get("video_title_for_youtube_short") or "",
            transcript=clip_words(transcript, start, end)[:4000] or "(no speech)")
        answer = _ask_gemini(frames, prompt, api_key)
        if not isinstance(answer, dict):
            return None
        hook = str(answer.get("viral_hook_text") or "").strip()
        title = str(answer.get("video_title_for_youtube_short") or "").strip()
        if not hook:
            return None
        before = {"viral_hook_text": clip.get("viral_hook_text"),
                  "video_title_for_youtube_short": clip.get("video_title_for_youtube_short")}
        clip["viral_hook_text"] = hook
        if title:
            clip["video_title_for_youtube_short"] = title[:100]
        clip["hook_grounding"] = {
            "on_screen": str(answer.get("on_screen") or "")[:200],
            "viral_hook_text": hook,
            "video_title_for_youtube_short": clip.get("video_title_for_youtube_short"),
            "before": before,
            "frames": len(frames),
        }
        print(f"   🪝 Hook regrounded on screen ({clip['hook_grounding']['on_screen'][:60]}): {hook}")
        return clip["hook_grounding"]
    except Exception as e:
        print(f"   ⚠️ Hook grounding failed ({type(e).__name__}: {e}) — keeping the transcript hook.")
        return None
