# Track E — Reframe v2 native-ffmpeg render engine

## What changed
Ported upstream's native-ffmpeg 9:16 render engine (report item 1):
- `ffmpeg_utils.py` (new, 373 lines) — verbatim port of upstream.
- `reframe_v2.py` (new, 625 lines) — ported engine with local adaptations:
  - v1 output dims (608x1080) kept instead of upstream's 1080-wide upscale.
  - Layout routing reuses `main.analyze_scenes_layout` (SPLIT + active-speaker
    gate, PANEL, SCREENCAST/WIDE/INSET, layout_picker) — identical layout
    decisions to v1; PANEL via `panel_layout.panel_filtergraph`.
  - INSET renders true picture-in-picture via `camera_inset.inset_filtergraph`;
    v1's blurred-bed fallback kept as failure fallback.
  - Manual overrides accept upstream's number + {top,bottom} SPLIT forms plus
    this repo's {"x": f, "y": f} editor form.
  - Punch-in always on (no env gate), matching v1; audio failure -> no punches.
- `punch_in.py` — added `crop_boxes` + `sendcmd_lines` (verbatim upstream math).
- `main.py` — `SmoothedCameraman.begin_scene()` + `SpeakerTracker.reset()`
  (v2-only helpers, v1 untouched); `process_video_to_vertical` now tries v2
  and falls back to `_process_video_to_vertical_v1` (old loop preserved
  verbatim, clearly marked). No runtime feature flags.
- `camera_inset.py` — docstring updated (ffmpeg_utils.py now exists).

## Side-by-side verification (demo-openshorts.mp4, 41s)
- V1: 148.8s | V2: 97.8s (34% faster on CPU).
- Both: valid 608x1080 h264 + aac mp4, ~41.7s.
- Layout sidecars byte-identical (same layout decisions).
- TRACK scene framing visually identical (checked frames at 25s).
- INSET scenes: v2 renders true PiP; v1 fell back to blurred bed (intended
  improvement, not a regression).
- Fallback path (forced v2 failure -> v1 render) works; recut end-to-end OK.

## Status
Verified and ready to merge. The only open note: worker exited before writing
this file; verification completed by reviewer.
