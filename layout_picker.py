"""Ask Gemini which layout a video needs, once per video.

Ported from upstream herdr-clipping (item 5). Adaptations for OpenShorts:
- The only Gemini model used is gemini-3.8-flash.
- gemini_worker helpers (prompt/schema/blocked-check) are inlined so this
  module has no dependency on upstream-internal files.
- apply() switches on the local layout modules (split/panel/screencast);
  there is no active_speaker module in this repo.

Off by default (``AUTO_LAYOUT=1``). A caller that already switched layouts on
by hand wins: this only ever ADDS, so an explicit choice is never overridden.
"""
import json
import os

# AUTO_LAYOUT=1 decides and applies. AUTO_LAYOUT=shadow decides, logs, and
# applies NOTHING: the render is byte-for-byte what it would have been.
#
# Shadow exists because everything measured about this picker was measured on 48
# YouTube clips chosen by hand, and the material users actually upload is a
# different distribution nobody has looked at. A week of shadow answers "what
# does it say about OUR videos" for 0.002 USD and ~2s per video, with no way to
# damage a clip somebody paid for.
_MODE = os.environ.get("AUTO_LAYOUT", "0").strip().lower()
SHADOW = _MODE == "shadow"
ENABLED = _MODE == "1" or SHADOW

# The only Gemini model this repo may call.
GEMINI_MODEL_NAME = "gemini-3.8-flash"

# 12 frames at 1024px wide. Both numbers are measured, not guessed: see above.
SAMPLE_FRAMES = int(os.environ.get("LAYOUT_SAMPLE_FRAMES", "12"))
SAMPLE_WIDTH = int(os.environ.get("LAYOUT_SAMPLE_WIDTH", "1024"))

# What each decision turns on. Keys match the layout names in the prompt.
DECISION_FLAGS = {
    "none": [],
    "screencast": ["screencast_layout"],
    "split": ["split_layout", "panel_layout"],
}

VALID = set(DECISION_FLAGS)

LAYOUT_CHOICE_PROMPT = """
These frames are sampled at regular intervals from a single landscape video.
You are choosing how to re-frame that video into a vertical 9:16 clip.

Pick ONE layout:

- "none": crop to the speaker and fill the frame. This is the RIGHT answer for
  ordinary talking heads, interviews shot in close-up, b-roll, sport, action,
  music, and any footage whose meaning survives a centre crop. Corner logos,
  score bugs, subscriber counters, lower-thirds and burned-in subtitles do NOT
  change this: they are decoration, and losing them costs nothing.
- "screencast": keep the screen. ONLY when the video is built around a screen
  recording, slides, a spreadsheet, a chart or a map that the viewer must read
  to follow it. If you cannot read words or numbers off the screen that matter
  to the point being made, it is not this.
- "split": stack two people. ONLY when two people are visible IN THE SAME SHOT
  at the same time in most frames, talking to each other. Frames that alternate
  between one-person close-ups are NOT this, however many people appear.

"none" is by far the most common correct answer. Choose anything else only if
you would defend it to an editor. If you are unsure, answer "none".

confidence is 0..1. why is at most 12 words.
"""

# JSON schema for the layout answer (dict form so no pydantic needed).
LAYOUT_CHOICE_SCHEMA = {
    "type": "object",
    "properties": {
        "layout": {"type": "string"},
        "confidence": {"type": "number"},
        "why": {"type": "string"},
    },
    "required": ["layout"],
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


def _module_flags(decision):
    """Modules to enable for a decision, ignoring anything unrecognised."""
    return DECISION_FLAGS.get(str(decision or "none").strip().lower(), [])


def apply(decision):
    """Switch on the modules a decision needs. Returns the modules touched.

    Deliberately additive: an operator who set SPLIT_LAYOUT=1 for a job wants
    stacking regardless of what the model thinks, and a model that says "none"
    must not quietly undo that.
    """
    import panel_layout
    import screencast_layout
    import split_layout

    modules = {"split_layout": split_layout,
               "screencast_layout": screencast_layout,
               "panel_layout": panel_layout}

    touched = []
    for name in _module_flags(decision):
        module = modules.get(name)
        if module is not None and not getattr(module, "ENABLED", False):
            module.ENABLED = True
            touched.append(name)
    return touched


def _encode_frame(frame, width):
    import cv2

    h, w = frame.shape[:2]
    scaled = cv2.resize(frame, (width, max(2, int(h * width / w))),
                        interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", scaled, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return buf.tobytes() if ok else None


def _ffmpeg_frames(video_path, n):
    """The same evenly spread frames, decoded by the ffmpeg CLI.

    OpenCV's bundled FFmpeg has no software AV1 decoder, so on the AV1 sources
    YouTube often serves every read failed ("Failed to get pixel format") and
    the picker fell back to the default layout for the whole video (prod,
    25-sep-2026). The system ffmpeg decodes AV1 with libdav1d.
    """
    import subprocess

    import cv2
    import numpy as np

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", video_path],
            capture_output=True, text=True, timeout=60)
        duration = float(probe.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return []
    frames = []
    for i in range(n):
        try:
            r = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{i * duration / n:.3f}",
                 "-i", video_path, "-frames:v", "1", "-c:v", "png",
                 "-f", "image2pipe", "-"],
                capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            continue
        frame = cv2.imdecode(np.frombuffer(r.stdout, np.uint8), cv2.IMREAD_COLOR)
        if frame is not None:
            frames.append(frame)
    return frames


def sample_frames(video_path, n=None, width=None):
    """JPEG bytes for ``n`` frames spread evenly across the video."""
    import cv2

    n = n or SAMPLE_FRAMES
    width = width or SAMPLE_WIDTH
    cap = cv2.VideoCapture(video_path)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    out = []
    try:
        if total > 0:
            for i in range(n):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(i * total / n))
                ok, frame = cap.read()
                if not ok:
                    continue
                jpg = _encode_frame(frame, width)
                if jpg:
                    out.append(jpg)
    finally:
        cap.release()
    if not out and os.path.exists(video_path):
        out = [j for j in (_encode_frame(f, width) for f in _ffmpeg_frames(video_path, n)) if j]
    return out


def pick(video_path, video_duration):
    """The layout Gemini picks for this video, or "none" on any failure.

    Never raises: a missing answer has to degrade to today's routing rather
    than break the job.
    """
    if not ENABLED:
        return "none"
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return "none"

    print("🎛️  Choosing a layout for this video…")
    try:
        # Inside the try on purpose: the contract above is that this never
        # raises, and an unimportable SDK is just one more reason to fall back.
        from google import genai
        from google.genai import types as genai_types

        frames = sample_frames(video_path)
        if not frames:
            print("   ⚠️ No readable frames — keeping the default layout.")
            return "none"

        client = genai.Client(api_key=api_key)
        parts = [genai_types.Part.from_bytes(data=b, mime_type="image/jpeg")
                 for b in frames]
        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=parts + [LAYOUT_CHOICE_PROMPT],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=LAYOUT_CHOICE_SCHEMA,
            ))
        raise_if_blocked(response)
        answer = json.loads(response.text) or {}
    except Exception as e:
        print(f"   ⚠️ Layout choice failed ({e}) — keeping the default layout.")
        return "none"

    decision = str(answer.get("layout", "none")).strip().lower()
    if decision not in VALID:
        print(f"   ⚠️ Unknown layout '{decision}' — keeping the default layout.")
        return "none"

    why = str(answer.get("why", ""))[:80]
    confidence = answer.get("confidence")
    print(f"   🎬 Layout: {decision} (confianza {confidence}) — {why}")
    return decision


def pick_and_apply(video_path, video_duration):
    """Decide, switch on (unless shadowing), report what changed."""
    decision = pick(video_path, video_duration)

    if SHADOW:
        # One greppable line per job. Deliberately not routed through the
        # analytics module: that one is opt-in and host-scoped, and a shadow
        # run has to work on any deployment, including self-hosted.
        would = _module_flags(decision)
        print(f"[layout-shadow] decision={decision} "
              f"would_enable={','.join(would) if would else 'none'} "
              f"duration={video_duration:.0f}s")
        return decision

    touched = apply(decision)
    if touched:
        print(f"   ✅ Enabled: {', '.join(touched)}")
    return decision
