"""SCREENCAST layout: full-width content on top, the speaker underneath.

Ported from upstream herdr-clipping (item 5). Adaptations for OpenShorts:
- Heuristic detectors ON by default (SCREENCAST_LAYOUT=1 unless set to 0).
- All Gemini calls use model gemini-3.8-flash.
- gemini_worker helpers (prompt/schema/upload/blocked-check) are inlined so
  this module has no dependency on upstream-internal files.
- Face detection goes through main.get_face_detection()/main.DETECT_LOCK.
- detect_content_ranges falls back to a local pixel heuristic when no
  GEMINI_API_KEY is set (static + detailed + faceless stretches).

The fourth layout. It targets the failure this repo has now attacked three
times: a screen recording that happens to contain a face gets classified TRACK,
the 9:16 crop keeps a centre strip, and the chart or headline the shot is
actually about comes out sliced mid-word.
"""
import json
import mimetypes
import os
import time

import numpy as np

ENABLED = os.environ.get("SCREENCAST_LAYOUT", "1") == "1"

# The only Gemini model this repo may call.
GEMINI_MODEL_NAME = "gemini-3.8-flash"

# Fraction of the frame width the content must span. A corner ticker, logo or
# channel bug sits far below this; a screen recording, slide or spreadsheet sits
# near 1.0. This is the axis the previous attempt did not ask about.
MIN_WIDTH_FRACTION = 0.5

# Above this the content fills the frame, so any presenter is composited ON TOP
# of it rather than sitting beside it. Stacking then shows the same content
# twice: measured on an Excel walkthrough where the speaker is keyed into the
# corner, the bottom band came out as a zoomed crop of the same spreadsheet.
# Those scenes get the full-width GENERAL layout instead, which is the fix they
# actually needed — the default GENERAL ratio crops ~24% off the sides, and on a
# spreadsheet the discarded columns are the point.
STACK_MAX_WIDTH_FRACTION = 0.85

# Seconds of overlap before a scene counts as showing the content.
MIN_OVERLAP_SECONDS = 0.25

# The speaker crop below the content needs a face of at least this width
# (fraction of frame width). Smaller than this and the bottom half is mostly
# desktop with a stamp-sized webcam in it, which is worse than GENERAL.
MIN_FACE_WIDTH = 0.05

WIDE_CONTENT_PROMPT_TEMPLATE = """
You are preparing a landscape video to be re-framed to a vertical 9:16 crop.
The crop keeps a tall centre strip and THROWS AWAY the left and right sides.

List every time range where on-screen content would be cut by that, and for each
one report HOW MUCH OF THE FRAME WIDTH the content spans.

width_fraction is the single most important field. Measure the content's own
horizontal extent, from its left edge to its right edge, as a fraction of the
full frame width:
- a spreadsheet, slide, screen recording or map filling the picture: 0.9 - 1.0
- a chart or diagram beside a speaker: 0.4 - 0.7
- a lower-third or headline strip across the bottom: 0.6 - 0.9
- a logo, channel bug, score counter or subscriber count in a corner: 0.1 - 0.2
- subtitles centred at the bottom: 0.3 - 0.5

Report what you actually see. Do NOT inflate the number to make a range seem
worth reporting, and do NOT leave out corner graphics — report them with their
true small width_fraction. A range reported honestly at 0.15 is useful; the same
range reported at 0.9 makes the video worse.

COUNT a range when the frame shows:
- a screen recording, slide, spreadsheet, chart, graph or map
- headlines, labels, statistics or comparison tables burned into the picture
- a side-by-side or split-screen layout
- any diagram or product shot where the edges carry the meaning

DO NOT count an ordinary talking head, even against a busy background, and do
not count b-roll, landscapes, crowds or action footage with no graphics.

TIME CONTRACT — STRICT:
- ABSOLUTE SECONDS from the start, numbers only, up to 3 decimals.
- 0 <= start < end <= {video_duration}.
- Merge ranges that are less than 1 second apart.
- Return an EMPTY list if the video never shows such content. An empty list is
  the correct, expected answer for most talking-head and b-roll videos — do not
  invent ranges to seem useful.

For "what", name the content in three words or fewer (e.g. "stock chart",
"spreadsheet", "corner ticker").
"""

# JSON schema for the wide-content answer (dict form so no pydantic needed).
WIDE_CONTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "ranges": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "number"},
                    "end": {"type": "number"},
                    "what": {"type": "string"},
                    "width_fraction": {"type": "number"},
                },
                "required": ["start", "end"],
            },
        }
    },
    "required": ["ranges"],
}


class GeminiBlockedError(ValueError):
    """The API refused the request for content-policy reasons (deterministic)."""


_BLOCKED_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST",
                           "SPII", "IMAGE_SAFETY", "RECITATION"}


def raise_if_blocked(response):
    """Raise GeminiBlockedError when the API refused to answer on policy grounds."""
    pf = getattr(response, "prompt_feedback", None)
    reason = getattr(pf, "block_reason", None)
    if reason:
        name = getattr(reason, "name", None) or str(reason)
        raise GeminiBlockedError(
            f"Gemini blocked this video's content ({name}). The AI provider's "
            "usage policies reject this material, so it can't be analyzed.")
    for c in (getattr(response, "candidates", None) or []):
        fr = getattr(c, "finish_reason", None)
        name = (getattr(fr, "name", None) or str(fr or "")).upper()
        if name in _BLOCKED_FINISH_REASONS:
            raise GeminiBlockedError(
                f"Gemini blocked its answer for this video ({name}). The AI "
                "provider's usage policies reject this material, so it can't be analyzed.")


def upload_media(client, path, mime_type=None):
    """Upload a local file to the Gemini Files API, by handle and never by path.

    Handed a path, the SDK copies ``os.path.basename(path)`` verbatim into the
    ``X-Goog-Upload-File-Name`` header, and httpx encodes header values as
    ASCII — so non-ASCII titles died before a byte left the container. Passing
    an open handle skips that header entirely; the readable name still travels
    as ``display_name``, which goes in the JSON body and is UTF-8 all the way.
    """
    guessed = mime_type or mimetypes.guess_type(path)[0] or ""
    if not guessed.startswith(("video/", "audio/", "image/")):
        guessed = "video/mp4"
    with open(path, "rb") as fh:
        return client.files.upload(
            file=fh,
            config={"mime_type": guessed,
                    "display_name": os.path.basename(path)},
        )


def content_bands(orig_w, orig_h, out_w, out_h):
    """(content_height, speaker_height) for the stacked screencast frame.

    The content keeps its full width, which is the entire point of this layout,
    so its height follows from the source aspect: a 16:9 source gives 608px of a
    1920px frame. The speaker takes the rest.
    """
    content_h = int(round(out_w * orig_h / float(orig_w)))
    content_h -= content_h % 2
    content_h = max(2, min(content_h, out_h - 2))
    speaker_h = out_h - content_h
    return content_h, speaker_h


def speaker_crop(orig_w, orig_h, out_w, speaker_h, face_centre):
    """Crop box (w, h, x, y) for the speaker band, framed on the face."""
    aspect = out_w / float(speaker_h)

    crop_h = orig_h
    crop_w = int(round(crop_h * aspect))
    if crop_w > orig_w:
        crop_w = orig_w
        crop_h = int(round(crop_w / aspect))

    crop_w -= crop_w % 2
    crop_h -= crop_h % 2

    cx, cy = face_centre
    x = int(round(cx - crop_w / 2.0))
    x = max(0, min(x, orig_w - crop_w))
    y = int(round(cy - crop_h * 0.42))
    y = max(0, min(y, orig_h - crop_h))

    return crop_w, crop_h, x - (x % 2), y - (y % 2)


def screencast_filtergraph(orig_w, orig_h, out_w, out_h, face_centre):
    """Full-width content above, face-framed speaker below."""
    content_h, speaker_h = content_bands(orig_w, orig_h, out_w, out_h)
    cw, ch, cx, cy = speaker_crop(orig_w, orig_h, out_w, speaker_h, face_centre)

    return (
        f"[0:v]split=2[ca][sa];"
        # The content band is the WHOLE frame scaled down. Nothing is cropped
        # off the sides, which is the one thing this layout exists to guarantee.
        f"[ca]scale={out_w}:{content_h}[content];"
        f"[sa]crop=w={cw}:h={ch}:x={cx}:y={cy},scale={out_w}:{speaker_h}[speaker];"
        f"[content][speaker]vstack=inputs=2,"
        f"pad={out_w}:{out_h}:0:0,setsar=1[v]"
    )


def detect_faces_full_res(frame):
    """Face boxes from the UNSCALED frame, in original coordinates.

    main.detect_face_candidates() runs detection on a 640px copy, which is the
    right trade for a talking head whose face spans a third of the frame. A
    presenter inset into a screen recording does not survive it: measured on a
    1920x1080 Excel walkthrough, the presenter's ~110px face becomes ~37px at
    640 and BlazeFace returned zero detections on every sample. At full width
    the same frames detect fine. Six samples per scene, so the cost is paid on
    screencast candidates only.
    """
    import cv2
    import main as m

    h, w, _ = frame.shape
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    with m.DETECT_LOCK:
        results = m.get_face_detection().process(rgb)
    if not results.detections:
        return []

    out = []
    for detection in results.detections:
        b = detection.location_data.relative_bounding_box
        box = [int(b.xmin * w), int(b.ymin * h),
               int(b.width * w), int(b.height * h)]
        out.append({'box': box, 'score': box[2] * box[3]})
    return out


def _face_centre(candidates, frame_w):
    """Centre of the biggest usable face in a frame, or None."""
    big = [c for c in candidates if c['box'][2] >= MIN_FACE_WIDTH * frame_w]
    if not big:
        return None
    box = max(big, key=lambda c: c['score'])['box']
    return box[0] + box[2] / 2.0, box[1] + box[3] / 2.0


def overlapping_width(scene_start, scene_end, ranges):
    """Widest content the scene overlaps, as a fraction of frame width.

    0.0 when the scene overlaps nothing, which leaves its routing untouched.
    """
    widest = 0.0
    for r in ranges:
        start, end = r[0], r[1]
        width = r[3] if len(r) > 3 else 1.0
        if min(scene_end, end) - max(scene_start, start) > MIN_OVERLAP_SECONDS:
            widest = max(widest, width)
    return widest


# --- heuristic content detection (no Gemini key needed) ----------------------

# A screen/slide stays pixel-identical between samples a second apart (only
# compression noise moves), while a speaker never does. Mean abs diff of two
# 320px-wide gray samples under this is "static".
HEUR_STATIC_DIFF = 6.0
# Laplacian variance of a 320px gray sample. Talking heads and b-roll sit well
# under this; slides/spreadsheets/IDE windows sit well above it.
HEUR_DETAIL_VAR = 250.0
# Faces wider than this mean the shot is about the person, not a screen.
HEUR_MAX_FACE_WIDTH = 0.10
# A content stretch must hold this long before it reroutes a scene.
HEUR_MIN_RANGE_SECONDS = 2.0


def detect_content_ranges_heuristic(video_path, video_duration):
    """Pixel-heuristic content ranges: static + detailed + (faceless or tiny
    faces). Conservative on purpose: a wrong WIDE merely letterboxes a shot,
    but it still must not fire on ordinary talking heads. Returns
    (start, end, what, width_fraction) tuples like the Gemini path."""
    import cv2
    import main as m

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return []
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
        if total <= 0 or video_duration <= 0:
            return []
        step = max(1, int(round(fps)))  # ~1 sample per second
        idxs = list(range(0, total, step))[:120]
        prev_small = None
        flags = []
        for f_idx in idxs:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                flags.append(None)
                prev_small = None
                continue
            small = cv2.resize(frame, (320, max(2, int(320 * frame.shape[0] / frame.shape[1]))),
                               interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            detail = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            if prev_small is not None and prev_small.shape == gray.shape:
                static = float(np.mean(cv2.absdiff(gray, prev_small))) < HEUR_STATIC_DIFF
            else:
                static = False
            prev_small = gray
            if not static or detail < HEUR_DETAIL_VAR:
                flags.append(False)
                continue
            faces = m.detect_face_candidates(frame)
            fw = frame.shape[1]
            big = [c for c in faces if c['box'][2] >= HEUR_MAX_FACE_WIDTH * fw]
            if big:
                flags.append(False)
                continue
            tiny = bool(faces)
            flags.append('presenter' if tiny else 'screen')
        ranges = []
        run_start = None
        run_kind = None
        for k, (f_idx, flag) in enumerate(zip(idxs, flags)):
            t = f_idx / fps
            if flag:
                if run_start is None:
                    run_start, run_kind = t, flag
                elif flag != run_kind:
                    run_kind = 'screen' if 'screen' in (run_kind, flag) else flag
            else:
                if run_start is not None and t - run_start >= HEUR_MIN_RANGE_SECONDS:
                    width = 0.7 if run_kind == 'presenter' else 0.95
                    what = 'screen+face' if run_kind == 'presenter' else 'screen content'
                    ranges.append((run_start, t, what, width))
                run_start, run_kind = None, None
        if run_start is not None:
            t = min(float(video_duration), idxs[-1] / fps + 1.0)
            if t - run_start >= HEUR_MIN_RANGE_SECONDS:
                width = 0.7 if run_kind == 'presenter' else 0.95
                what = 'screen+face' if run_kind == 'presenter' else 'screen content'
                ranges.append((run_start, t, what, width))
        return ranges
    finally:
        cap.release()


def detect_content_ranges(video_path, video_duration):
    """Time ranges where on-screen content spans most of the frame width.

    Returns (start, end, what, width_fraction) tuples, or [] on any failure:
    a missing answer must degrade to today's routing rather than break the job.
    Uses Gemini when GEMINI_API_KEY is set, otherwise the local pixel heuristic.
    """
    if not ENABLED:
        return []
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return detect_content_ranges_heuristic(video_path, video_duration)

    from google import genai
    from google.genai import types as genai_types

    print("🔎 Checking for full-width on-screen content…")
    # This is the ONE stage that sends the whole video file to Google rather
    # than a handful of frames, so it is also the one that leaves a copy of a
    # user's source on someone else's servers. The Files API keeps an upload for
    # 48 h unless it is deleted; the finally block below deletes it as soon as
    # the answer is back, which is what makes "we do not leave your video with
    # the model provider" a true sentence in the privacy policy.
    client = None
    file_upload = None
    try:
        client = genai.Client(api_key=api_key)
        file_upload = upload_media(client, video_path)
        deadline = time.time() + 180
        while True:
            info = client.files.get(name=file_upload.name)
            state = str(getattr(getattr(info, "state", info), "name", "")).upper()
            if state == "ACTIVE":
                break
            if state == "FAILED" or time.time() > deadline:
                print("   ⚠️ Upload not usable — keeping face-only routing.")
                return []
            time.sleep(2)

        response = client.models.generate_content(
            model=GEMINI_MODEL_NAME,
            contents=[file_upload,
                      WIDE_CONTENT_PROMPT_TEMPLATE.format(
                          video_duration=video_duration)],
            config=genai_types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=WIDE_CONTENT_SCHEMA,
            ))
        raise_if_blocked(response)
        raw = (json.loads(response.text) or {}).get("ranges") or []
    except Exception as e:
        print(f"   ⚠️ On-screen check failed ({e}) — trying the local heuristic.")
        try:
            return detect_content_ranges_heuristic(video_path, video_duration)
        except Exception as e2:
            print(f"   ⚠️ Heuristic also failed ({e2}) — keeping face-only routing.")
            return []
    finally:
        # Every exit path, including the two early returns above and the failure
        # branch: a video left behind because the call raised is exactly the
        # copy nobody would ever notice.
        if client is not None and file_upload is not None:
            try:
                client.files.delete(name=file_upload.name)
            except Exception as e:
                print(f"   ⚠️ Could not delete the uploaded source from Gemini "
                      f"Files ({e}) — it expires there in 48 h.")

    ranges = []
    for r in raw:
        try:
            s = max(0.0, float(r.get("start", 0)))
            e = min(float(video_duration), float(r.get("end", 0)))
            width = float(r.get("width_fraction", 0))
        except (TypeError, ValueError):
            continue
        # The width gate is the whole point: everything narrower survives a 9:16
        # crop and must not move a single scene.
        if e - s >= 0.5 and width >= MIN_WIDTH_FRACTION:
            ranges.append((s, e, str(r.get("what", ""))[:40], width))
    ranges.sort()

    if ranges:
        print("   📊 " + ", ".join(
            f"{w}@{s:.0f}-{e:.0f}s ({frac:.0%} wide)"
            for s, e, w, frac in ranges[:5]))
    else:
        print("   ✅ No full-width content — routing unchanged.")
    return ranges


def detect_screencast_scenes(video_path, scenes, strategies, ranges, samples=6):
    """Route scenes that show wide on-screen content.

    Returns ``{scene_index: ('SCREENCAST', centre) | ('WIDE', None)}``:

      - SCREENCAST stacks the content over the presenter, for content that
        leaves room beside itself (width below STACK_MAX_WIDTH_FRACTION) and
        where a presenter is actually found.
      - WIDE is the blurred layout with side-cropping disabled, for content that
        fills the frame, or that has no presenter to stack.
    """
    if not ENABLED or not ranges:
        return {}
    # Below the gate on purpose: main pulls torch/mediapipe, and the disabled
    # path (the default, and what CI exercises) must not pay that import.
    import cv2
    import main as m

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return {}

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    found = {}

    try:
        for i, (start, end) in enumerate(scenes):
            s_f, e_f = start.get_frames(), end.get_frames()
            width = overlapping_width(s_f / fps, e_f / fps, ranges)
            if not width:
                continue

            # Content that fills the frame has the presenter on top of it, so
            # there is nothing to stack — just stop cropping the sides.
            if width > STACK_MAX_WIDTH_FRACTION:
                found[i] = ('WIDE', None)
                continue

            last_f = e_f - 1
            if total_frames:
                last_f = min(last_f, total_frames - 1)
            if last_f < s_f:
                continue

            centres = []
            for f_idx in np.linspace(s_f, last_f, samples):
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(f_idx)))
                ok, frame = cap.read()
                if not ok:
                    continue
                centre = _face_centre(detect_faces_full_res(frame), frame_w)
                if centre is None:
                    # A presenter keyed into the corner of a screen recording is
                    # often too small for BlazeFace even at full resolution
                    # (measured: zero detections across an Excel walkthrough
                    # where the person is plainly visible). YOLO finds the body
                    # in the same frames, and a body centre frames the speaker
                    # just as well for this layout.
                    person = m.detect_person_yolo(frame)
                    if person:
                        centre = (person[0] + person[2] / 2.0,
                                  person[1] + person[3] / 2.0)
                if centre:
                    centres.append(centre)

            # Half the samples: a webcam inset is static and easy to find, so a
            # weaker signal than this means there is no presenter to stack, and
            # the content still deserves its full width.
            if len(centres) < samples / 2.0:
                found[i] = ('WIDE', None)
                continue

            found[i] = ('SCREENCAST',
                        (float(np.median([c[0] for c in centres])),
                         float(np.median([c[1] for c in centres]))))
    finally:
        cap.release()

    return found
