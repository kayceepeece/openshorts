"""Reframe engine v2: analyze in Python, render natively in ffmpeg.

Ported from upstream herdr-clipping (reframe_v2.py) — the render-path swap
for process_video_to_vertical. v1 decodes every frame at full resolution in
OpenCV, crops/resizes in numpy and pipes raw frames back into ffmpeg. v2
splits that into:

  1. ANALYSIS — one ffmpeg-decoded pass at <=640px feeding the same
     detectors and the same SmoothedCameraman/SpeakerTracker state machines
     as v1, so the resulting camera trajectory (crop x per frame) is
     equivalent.
  2. RENDER — one ffmpeg process per scene doing decode -> dynamic crop
     (sendcmd) -> scale -> encode natively (TRACK scenes), or the
     blurred-backdrop / layout filtergraphs (GENERAL, SPLIT, PANEL,
     SCREENCAST, WIDE, INSET); segments are then concatenated with stream
     copy and the audio mapped straight from the source clip.

No raw-frame piping, no second full-res decode, one less intermediate encode.
Callers must treat any exception as "fall back to the v1 loop".

Pure helpers (sendcmd/concat generation, scene slicing) have no heavy
imports so they stay unit-testable in CI.

Local adaptations (vs upstream):
- Output size keeps the v1 rule (source height x 9/16 width, e.g. 608x1080
  for a 1080p source) instead of upstream's delivery_size upscale to
  1080-wide: the side-by-side acceptance is 608x1080 and every downstream
  consumer (captions, preview) was built against v1 dims.
- Layout routing reuses main.analyze_scenes_layout (SPLIT + active-speaker
  gate, PANEL, SCREENCAST/WIDE/INSET, layout_picker) so old and new engines
  make identical layout decisions; upstream's render() inlines its own
  subset (no PANEL, no layout_picker). PANEL renders through
  panel_layout.panel_filtergraph.
- INSET renders the real picture-in-picture (camera_inset.inset_filtergraph
  with the video-global box); v1 fell back to the blurred bed when no
  per-scene centre survived, which is kept as the failure fallback.
- Manual overrides accept upstream's number and {top, bottom} SPLIT forms
  plus this repo's {"x": f, "y": f} editor form (x is the locked TRACK
  centre, same as the v1 manual_centres path).
- Punch-in is always on (no PUNCH_IN env gate), matching the v1 loop: audio
  analysis failure degrades to no punches, never a failed render.
- No force_strategy / watermark / content_ranges parameters: nothing in
  this repo passes them (recut passes crop_overrides only; ranges are
  detected internally). The v1 loop had no watermark step either.
"""
import os
import subprocess
import tempfile

import camera_inset
import punch_in
import screencast_layout
import layout_ranges
import split_layout
import panel_layout
from ffmpeg_utils import (video_encode_args, blurred_backdrop, escape_filter_value,
                          QUALITY_FAST, METADATA_SCRUB)

ANALYSIS_MAX_WIDTH = 640

# Detection cadence of the analysis pass, mirroring upstream main's tunables
# (this repo's v1 loop hardcodes every-2nd-frame instead). The camera is a
# smoothed follower so the stride only moves when the target updates, not
# where it settles; stride 4 quarters the MediaPipe/YOLO calls of the pass.
DETECT_STRIDE = max(int(os.environ.get("DETECT_STRIDE", "4")), 1)
YOLO_FALLBACK_STRIDE = DETECT_STRIDE * 2
SCENE_CUT_RESET = os.environ.get("SCENE_CUT_RESET", "1") != "0"


# Short-form platforms (TikTok / Reels / Shorts) expect a 1080-wide vertical
# upload; anything smaller is treated as low quality and re-encoded from the
# already-soft source. The crop region is whatever the source height allows, so
# a 720p input yields a 406x720 crop — we scale that up to the delivery floor
# rather than shipping sub-HD. Sources that already exceed it are left alone
# (never downscale quality the user supplied).
DELIVERY_MIN_WIDTH = 1080


# --- pure helpers (CI-testable) --------------------------------------------

def delivery_size(orig_w, orig_h, aspect_ratio):
    """Output (width, height) for a reframe of this source.

    Picks the largest crop the source allows, then upscales to
    ``DELIVERY_MIN_WIDTH`` if that crop is narrower. Both dimensions come back
    even (x264/NVENC reject odd ones).

    NOTE: kept for parity with upstream (pure, unit-testable). The render
    below ships v1 dims via _output_size instead — see module docstring.
    """
    out_h = orig_h
    out_w = int(out_h * aspect_ratio)
    if out_w > orig_w:
        out_w = orig_w
        out_h = int(out_w / aspect_ratio)

    if out_w < DELIVERY_MIN_WIDTH:
        out_w = DELIVERY_MIN_WIDTH
        out_h = int(round(out_w / aspect_ratio))

    return out_w + (out_w % 2), out_h + (out_h % 2)


def _output_size(orig_w, orig_h, aspect_ratio):
    """v1-compatible output dims: source height x aspect width (even)."""
    out_h = orig_h
    out_w = int(out_h * aspect_ratio)
    if out_w > orig_w:
        out_w = orig_w
        out_h = int(out_w / aspect_ratio)
    if out_w % 2:
        out_w += 1
    if out_h % 2:
        out_h += 1
    return out_w, out_h


def source_already_fits(orig_w, orig_h, aspect_ratio, tol=0.01):
    """True when the source is already at (or past) the target aspect.

    Such a source has no width to throw away, so every layout that rearranges
    the frame is a downgrade: GENERAL puts it in a blurred bed, SPLIT stacks
    two crops of an already-narrow frame, SCREENCAST/INSET carve panels out of
    it. TRACK is the only one that leaves it alone — its crop is the whole
    frame — so a vertical upload should pass straight through.
    """
    return orig_w / float(orig_h) <= aspect_ratio * (1 + tol)


def dedupe_sendcmd_lines(xs, fps, target="crop@c"):
    """sendcmd lines setting crop x per frame, deduped to change-points.

    Timestamps are relative to the segment (the render seeks per scene).
    """
    lines = []
    prev = None
    for i, x in enumerate(xs):
        if x != prev:
            lines.append(f"{i / fps:.4f} {target} x {x};")
            prev = x
    return lines


def scene_frame_ranges(scene_boundaries, strategies, total_frames):
    """Clamp scene (start, end) frame ranges to the decoded frame count,
    dropping empty ranges. Each range keeps its strategy so later indices
    can't misalign when a range is dropped."""
    ranges = []
    for i, (start_f, end_f) in enumerate(scene_boundaries):
        strategy = strategies[i] if i < len(strategies) else 'TRACK'
        start_f = max(0, min(start_f, total_frames))
        end_f = max(start_f, min(end_f, total_frames))
        if end_f > start_f:
            ranges.append((start_f, end_f, strategy))
    return ranges


def concat_list_content(segment_paths):
    # Single quotes per concat-demuxer spec; our paths are tempfile-generated
    # (no quotes in them).
    return "".join(f"file '{p}'\n" for p in segment_paths)


# How much of the frame height the real content should fill in GENERAL layout.
#
# Fitting a 16:9 source to the full output width leaves it 608px tall in a
# 1920px frame — the content is 32% of the screen and 68% is blurred filler.
# That reads as a thumbnail floating in soup, and it is what a GENERAL scene
# looked like in real delivered clips (audited 26-jul-2026).
#
# Scaling the content up and letting the sides overflow trades width for
# presence, and the trade has to stay conservative: GENERAL is chosen for group
# shots and landscapes, exactly the material where cropping the sides cuts
# someone out of frame. At 0.42 a 16:9 source keeps ~76% of its width while
# going from 32% to 42% of the frame height. 0.55 was tried and rejected — it
# reaches 55% height but throws away 42% of the width.
#
# GENERAL_CONTENT_HEIGHT_RATIO=0.32 restores the old full-width behaviour.
GENERAL_CONTENT_HEIGHT_RATIO = float(
    os.environ.get("GENERAL_CONTENT_HEIGHT_RATIO", "0.42"))


def full_width_content_height(orig_w, orig_h, out_w):
    """Height the source fills when its FULL width is kept (even)."""
    fg_h = int(round(out_w * orig_h / float(orig_w)))
    return fg_h + (fg_h % 2)


def general_filtergraph(out_w, out_h, content_h=None, orig_w=None, orig_h=None):
    """Blurred-background 'general shot' layout: bg fills the frame (centre-
    cropped, blurred), fg is scaled to a readable share of the height and
    centred, overflowing the sides rather than floating small in the middle.

    ``content_h`` overrides the height ratio. Passing the full-width height
    turns the side-cropping off entirely, which is what a scene full of charts
    or spreadsheets needs: the default 0.42 ratio buys presence by throwing away
    ~24% of the width, and on that material the discarded columns are the point.

    ``orig_w``/``orig_h`` floor the foreground at the height where the source
    fills the output width. The 0.42 ratio buys presence on a LANDSCAPE source
    by overflowing the sides; on a portrait one the same number is a shrink —
    an already-9:16 upload came back as a 453px sliver floating over a blurred
    copy of itself. Filling the width is the floor, never the target.
    """
    fg_h = content_h if content_h else int(out_h * GENERAL_CONTENT_HEIGHT_RATIO)
    if orig_w and orig_h:
        fg_h = max(fg_h, full_width_content_height(orig_w, orig_h, out_w))
    fg_h += fg_h % 2
    return (
        f"[0:v]split=2[bga][fga];"
        f"[bga]{blurred_backdrop(out_w, out_h, 12)}[bg];"
        # Scale by HEIGHT, then trim any overflow to the output width. crop
        # centres by default, and min() makes it a no-op when the scaled source
        # is already narrower than the frame (portrait/square sources).
        f"[fga]scale=-2:{fg_h},crop=w=min(iw\\,{out_w}):h=ih[fg];"
        f"[bg][fg]overlay=x=(W-w)/2:y=(H-h)/2,setsar=1[v]"
    )


# --- analysis ---------------------------------------------------------------

def apply_crop_overrides(xs, strategies, scene_boundaries, overrides,
                         crop_w, orig_w, orig_h=None, splits=None):
    """Frame the scenes the user positioned by hand.

    ``overrides`` maps a scene index to one of:

      * a number — the crop CENTRE as a fraction of the source width, giving a
        single locked 9:16 window for that scene (the v1 manual_centres form);
      * ``{"x": f, "y": f}`` — this repo's editor form; ``x`` is the locked
        centre exactly like the bare number (the crop is full-height, so ``y``
        carries no geometry);
      * ``{"top": v, "bottom": v}`` — two centres, stacking those two regions
        one above the other (the SPLIT layout). Each half is either a bare
        fraction (horizontal only) or ``{"x": f, "y": f}``; SPLIT crops are
        SHORTER than the source, so they carry a vertical centre too.

    Fractions travel instead of pixels because the editor knows where it
    dropped the rectangle, not the source's dimensions, and the same number
    survives a source re-encode at another resolution.

    A hand-framed scene overrides its automatic verdict outright: the single
    form forces TRACK so a scene the detector had sent to GENERAL (blurred
    background) comes back to a vertical crop, and the split form writes
    straight into ``splits``, so the user can stack a scene the detector never
    proposed — no dependency on SPLIT_LAYOUT being switched on.

    Runs after every automatic pass, so a manual choice always wins. Unknown
    scene indices and malformed values are skipped rather than rejected: a
    stale editor tab must not fail the render.
    """
    max_x = max(0, orig_w - crop_w)

    def to_x(fraction):
        return max(0, min(int(round(float(fraction) * orig_w - crop_w / 2)), max_x))

    for raw_idx, value in (overrides or {}).items():
        try:
            idx = int(raw_idx)
        except (TypeError, ValueError):
            continue
        if not 0 <= idx < len(scene_boundaries):
            continue
        start_f, end_f = scene_boundaries[idx]
        end_f = min(end_f, len(xs))
        if end_f <= start_f:
            continue

        if isinstance(value, dict) and 'top' in value and 'bottom' in value:
            # Split: the halves are centres in SOURCE PIXELS, which is what
            # split_filtergraph expects — unlike the single-crop path, there is
            # no crop window to offset by.
            # split_geometry reads centre[0]/centre[1]: each half is a POINT,
            # not a horizontal position, because its crop is shorter than the
            # source and has to be placed vertically as well.
            def point(half):
                if isinstance(half, dict):
                    fx, fy = float(half['x']), float(half.get('y', 0.5))
                else:
                    fx, fy = float(half), 0.5
                return (fx * orig_w, fy * orig_h)

            try:
                centres = (point(value['top']), point(value['bottom']))
            except (KeyError, TypeError, ValueError):
                continue
            if splits is None or not orig_h:
                continue
            splits[start_f] = centres
            strategies[idx] = 'SPLIT'
            continue

        try:
            if isinstance(value, dict):
                value = value.get('x', 0.5)
            x = to_x(value)
        except (TypeError, ValueError):
            continue
        xs[start_f:end_f] = [x] * (end_f - start_f)
        strategies[idx] = 'TRACK'
        # A scene taken over by a single locked crop must not also carry a
        # stale split recipe from the detector.
        if splits is not None:
            splits.pop(start_f, None)

    return xs, strategies


def _analyze_trajectory(input_video, scenes_boundaries, scene_strategies,
                        fps, orig_w, orig_h, cameraman, tracker):
    """Replays v1's per-frame decision loop on a downscaled ffmpeg-decoded
    stream. Returns xs: crop x per frame (None on non-TRACK frames)."""
    import numpy as np
    import main as m

    small_w = min(ANALYSIS_MAX_WIDTH, orig_w)
    if small_w % 2:
        small_w -= 1
    small_h = max(int(orig_h * small_w / orig_w), 2)
    if small_h % 2:
        small_h += 1
    scale = orig_w / small_w
    frame_bytes = small_w * small_h * 3

    proc = subprocess.Popen(
        ["ffmpeg", "-loglevel", "error", "-i", input_video,
         "-vf", f"scale={small_w}:{small_h}",
         "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=frame_bytes * 4)

    xs = []
    frame_number = 0
    current_scene_index = 0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            frame = np.frombuffer(buf, dtype=np.uint8).reshape((small_h, small_w, 3))

            if current_scene_index < len(scenes_boundaries):
                start_f, end_f = scenes_boundaries[current_scene_index]
                if frame_number >= end_f and current_scene_index < len(scenes_boundaries) - 1:
                    current_scene_index += 1

            strategy = (scene_strategies[current_scene_index]
                        if current_scene_index < len(scene_strategies) else 'TRACK')

            # SPLIT, PANEL, SCREENCAST, INSET and WIDE crops are static (fixed
            # boxes for the whole scene), so like GENERAL they need no camera
            # trajectory.
            if strategy in ('GENERAL', 'SPLIT', 'PANEL', 'SCREENCAST', 'WIDE',
                            'INSET'):
                cameraman.current_center_x = orig_w / 2
                cameraman.target_center_x = orig_w / 2
                xs.append(None)
            else:
                is_scene_start = (
                    current_scene_index < len(scenes_boundaries)
                    and frame_number == scenes_boundaries[current_scene_index][0])
                cut = is_scene_start and SCENE_CUT_RESET
                if cut:
                    # New shot: forget the old subject and cut to the new one
                    # (see SmoothedCameraman.begin_scene).
                    tracker.reset()
                    cameraman.begin_scene()

                if frame_number % DETECT_STRIDE == 0 or cut:
                    candidates = m.detect_face_candidates(frame)
                    for cand in candidates:
                        cand['box'] = [int(v * scale) for v in cand['box']]
                        cand['score'] = cand['box'][2] * cand['box'][3]
                    target_box = tracker.get_target(candidates, frame_number, orig_w)
                    if target_box:
                        cameraman.update_target(target_box)
                    elif frame_number % YOLO_FALLBACK_STRIDE == 0 or cut:
                        person_box = m.detect_person_yolo(frame)
                        if person_box:
                            cameraman.update_target([int(v * scale) for v in person_box])

                x1, _y1, _x2, _y2 = cameraman.get_crop_box(force_snap=is_scene_start)
                xs.append(x1)

            frame_number += 1
    finally:
        proc.stdout.close()
        proc.wait()

    return xs


# --- render -----------------------------------------------------------------

def _run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=1800)


def render(input_video, final_output_video, aspect_ratio, crop_overrides=None):
    """Full v2 reframe of one clip. Raises on failure (caller falls back).

    ``crop_overrides`` maps scene index -> crop centre as a fraction of the
    source width (or the {"x","y"} / {"top","bottom"} dict forms — see
    apply_crop_overrides), for scenes the user framed by hand in the editor.
    Scenes not listed keep the automatic camera, so correcting one bad shot
    never disturbs the ones the tracker got right.

    Layout routing (TRACK/GENERAL upgrades to SPLIT/PANEL/SCREENCAST/WIDE/
    INSET, active-speaker gate, layout_picker) comes from
    main.analyze_scenes_layout, the same call the v1 loop makes, so both
    engines frame from identical decisions.
    """
    import main as m

    print("   🚀 Reframe engine v2 (ffmpeg-native render)")
    scenes, fps = m.detect_scenes(input_video)
    fps = float(fps) or 30.0  # PySceneDetect can hand back a Fraction
    orig_w, orig_h = m.get_video_resolution(input_video)

    # v1 dims (see module docstring): upstream's delivery_size upscale is
    # deliberately not applied.
    out_w, out_h = _output_size(orig_w, orig_h, aspect_ratio)

    if not scenes:
        import cv2
        cap = cv2.VideoCapture(input_video)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        from scenedetect import FrameTimecode
        scenes = [(FrameTimecode(0, fps), FrameTimecode(total, fps))]

    scene_boundaries = [(s.get_frames(), e.get_frames()) for s, e in scenes]
    # A source shot vertical is already the output: nothing to reframe. The
    # scene classifier still sends its face-less shots (a slide, a chart, a
    # screen recording) to GENERAL, and GENERAL on such a source shrank the
    # whole frame into the middle of a blurred copy of itself. Skip the
    # classifier and every layout upgrade instead of trying to survive them.
    passthrough = source_already_fits(orig_w, orig_h, aspect_ratio)
    if passthrough:
        strategies = ['TRACK'] * len(scenes)
        split_scenes, panel_scenes, screencast_scenes = {}, {}, {}
        print(f"   ↕️  Source is already {orig_w}x{orig_h} vertical — "
              f"passing it through, no reframe")
    else:
        strategies = m.analyze_scenes_strategy(input_video, scenes)
        strategies, split_scenes, panel_scenes, screencast_scenes = \
            m.analyze_scenes_layout(input_video, scenes, strategies)

    # The layout dicts are keyed by scene INDEX; the render seeks per scene,
    # so re-key by START FRAME (scene_frame_ranges() drops empty ranges, so
    # indices there don't line up with `scenes` — start_f always survives).
    splits = {}
    for scene_idx, centres in (split_scenes or {}).items():
        if 0 <= scene_idx < len(scene_boundaries):
            splits[scene_boundaries[scene_idx][0]] = centres
    panels = {}
    for scene_idx, centres in (panel_scenes or {}).items():
        if 0 <= scene_idx < len(scene_boundaries):
            panels[scene_boundaries[scene_idx][0]] = centres
    screencasts = {}
    for scene_idx, plan_centre in (screencast_scenes or {}).items():
        if 0 <= scene_idx < len(scene_boundaries):
            screencasts[scene_boundaries[scene_idx][0]] = plan_centre
    if splits:
        print(f"   🪞 SPLIT layout on {len(splits)} scene(s) [v2]")
    if panels:
        print(f"   🧩 PANEL layout on {len(panels)} scene(s) [v2]")

    n_inset = sum(1 for p, _c in screencasts.values() if p == 'INSET')
    # The webcam box is fixed for the whole video, so it is found once. v1
    # never had a per-scene centre for INSET (it rendered those scenes on the
    # blurred bed); the box here is what promotes them to picture-in-picture.
    inset_box = None
    if n_inset:
        try:
            inset_box = camera_inset.detect(input_video)
        except Exception as e:
            print(f"   ⚠️ Inset check failed ({e}) — using the general bed.")
        if inset_box:
            print(f"   📹 Webcam inset at {inset_box}")
        else:
            print("   ⚠️ No inset box found — INSET scenes use the general bed.")

    # The crop geometry comes from the SOURCE dims only — SmoothedCameraman
    # derives crop_width/crop_height from video_width/video_height and never
    # reads the output pair.
    cameraman = m.SmoothedCameraman(out_w, out_h, orig_w, orig_h)
    tracker = m.SpeakerTracker(cooldown_frames=30)

    xs = _analyze_trajectory(input_video, scene_boundaries, strategies, fps,
                             orig_w, orig_h, cameraman, tracker)
    if not xs:
        raise RuntimeError("analysis produced no frames")

    # Beats are found once per clip; each scene takes the ones inside it. Any
    # audio failure degrades to no punches — it never fails the render.
    beats = []
    try:
        beats = punch_in.emphasis_times(input_video, len(xs) / fps)
    except Exception as e:
        print(f"   ⚠️ Punch-in disabled ({e})")
        beats = []
    if beats:
        print(f"   🔍 Punch-in on {len(beats)} beat(s)")

    crop_w, crop_h = cameraman.crop_width, cameraman.crop_height

    # Last word on the trajectory: a scene the user framed by hand beats every
    # automatic verdict above.
    if crop_overrides:
        xs, strategies = apply_crop_overrides(
            xs, strategies, scene_boundaries, crop_overrides, crop_w,
            orig_w, orig_h=orig_h, splits=splits)
        print(f"   ✋ Manual framing on {len(crop_overrides)} scene(s)")

    ranges = scene_frame_ranges(scene_boundaries, strategies, len(xs))
    if not ranges:
        raise RuntimeError("no usable scene ranges")

    general_bed = general_filtergraph(out_w, out_h,
                                      orig_w=orig_w, orig_h=orig_h)

    workdir = tempfile.mkdtemp(prefix="reframe_v2_")
    segments = []
    try:
        for idx, (start_f, end_f, strategy) in enumerate(ranges):
            seg_path = os.path.join(workdir, f"seg_{idx:03d}.mp4")
            ss = start_f / fps
            dur = (end_f - start_f) / fps

            try:
                if strategy == 'INSET':
                    if inset_box is None:
                        raise ValueError("no inset box — general bed fallback")
                    graph = camera_inset.inset_filtergraph(
                        orig_w, orig_h, out_w, out_h, inset_box)
                elif strategy == 'SCREENCAST':
                    _plan, centre = screencasts.get(start_f, ('SCREENCAST', None))
                    if centre is None:
                        raise ValueError("screencast scene lost its centre")
                    graph = screencast_layout.screencast_filtergraph(
                        orig_w, orig_h, out_w, out_h, centre)
                elif strategy == 'WIDE':
                    graph = general_filtergraph(
                        out_w, out_h,
                        full_width_content_height(orig_w, orig_h, out_w))
                elif strategy == 'SPLIT':
                    left, right = splits[start_f]
                    graph = split_layout.split_filtergraph(
                        orig_w, orig_h, out_w, out_h, left, right)
                elif strategy == 'PANEL':
                    graph = panel_layout.panel_filtergraph(
                        orig_w, orig_h, out_w, out_h, panels[start_f])
                elif strategy == 'GENERAL':
                    graph = general_bed
                else:
                    seg_xs = [x if x is not None else 0 for x in xs[start_f:end_f]]
                    cmd_path = os.path.join(workdir, f"cmd_{idx:03d}.txt")
                    if beats:
                        zooms = punch_in.zoom_curve(len(seg_xs), fps, beats,
                                                    start_offset=ss)
                        boxes = punch_in.crop_boxes(seg_xs, zooms, crop_w, crop_h,
                                                    orig_w, orig_h)
                        lines = punch_in.sendcmd_lines(boxes, fps)
                        first = boxes[0]
                        init = f"w={first[0]}:h={first[1]}:x={first[2]}:y={first[3]}"
                    else:
                        lines = dedupe_sendcmd_lines(seg_xs, fps)
                        # sendcmd only ever moves x, so y is whatever it starts as.
                        # crop_h equals the source height on any landscape input,
                        # making this 0; it only bites on a source TALLER than the
                        # target, where y=0 threw away the bottom of the frame
                        # instead of trimming both ends.
                        crop_y = max(0, (orig_h - crop_h) // 2)
                        init = f"w={crop_w}:h={crop_h}:x={seg_xs[0]}:y={crop_y}"
                    with open(cmd_path, "w") as f:
                        f.write("\n".join(lines) + "\n")
                    graph = (
                        f"[0:v]sendcmd=f='{escape_filter_value(cmd_path)}',"
                        f"crop@c={init},"
                        f"scale={out_w}:{out_h},setsar=1[v]"
                    )
            except Exception as e:
                # One scene's recipe must never kill the clip: the blurred bed
                # keeps every pixel, just less artfully framed.
                print(f"   ⚠️ Scene {idx} ({strategy}) graph failed ({e}) — "
                      f"using the general bed")
                graph = general_bed

            _run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-ss", f"{ss:.4f}", "-t", f"{dur:.4f}",
                "-i", input_video,
                "-filter_complex", graph, "-map", "[v]",
                *video_encode_args(QUALITY_FAST), "-an", seg_path,
            ])
            segments.append(seg_path)

        list_path = os.path.join(workdir, "concat.txt")
        with open(list_path, "w") as f:
            f.write(concat_list_content(segments))

        # Concat video segments (stream copy) + audio straight from the clip.
        _run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", list_path,
            "-i", input_video,
            "-map", "0:v:0", "-map", "1:a:0?",
            "-c:v", "copy", "-c:a", "copy", *METADATA_SCRUB,
            # +faststart moves the moov atom to the front so the browser <video>
            # can start playing before the whole file downloads. Without it the
            # in-app preview spins forever (download still works) — the moov
            # lands at the end of a plain concat.
            "-movflags", "+faststart",
            final_output_video,
        ])
    finally:
        import shutil
        shutil.rmtree(workdir, ignore_errors=True)

    # Tell the caption pass which stretches are stacked (see layout_ranges).
    layout_ranges.write(final_output_video,
                        [(s / fps, e / fps, strategy) for s, e, strategy in ranges])
    print(f"   ✅ Clip saved to {final_output_video}")
    return True
