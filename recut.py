"""
Recut engine: re-render any finished clip from a segment list without
re-running the whole clip job.

Two paths, chosen automatically:

- FAST: every requested segment falls inside content the current canonical
  clip file already holds -> cut straight out of that file. Seconds, no AI,
  no source video needed.
- SOURCE: a segment reaches outside what the canonical file holds -> cut
  from the retained source video and re-run the vertical reframe.

The pure helpers here are importable without the heavy stack; the reframe
and caption steps are imported lazily only on the paths that need them.

Segment lists are always expressed in SOURCE-ABSOLUTE seconds (the same
clock the clip metadata's start/end use). The clip's recipe remembers the
clip's current cut plus the source range the immutable canonical file was
originally cut from, so the fast path can always be checked and rebased.
"""

import os
import subprocess
import time
import uuid

# EDL limits. Generous on purpose — this is for a human fixing cuts,
# not for stitching feature films.
MAX_SEGMENTS = 12
MIN_SEGMENT_SECONDS = 0.5
MAX_TOTAL_SECONDS = 180.0

# Segments may start/end a hair outside the canonical range through float
# round-tripping; treat them as inside.
RANGE_TOLERANCE = 0.05

# Same ceiling as other ffmpeg work: a hung ffmpeg must not pin the
# executor thread forever.
FFMPEG_TIMEOUT_SECONDS = 1800


class RecutError(ValueError):
    """Invalid segment list — safe to surface verbatim as a 400 detail."""


def normalize_segments(segments, source_duration=None):
    """Validate and clamp a segment list. Returns [{'start', 'end'}, ...].

    Order is preserved — the segment order IS the clip order, and reusing
    a source range twice is legal (an echo/replay is a real editing move).
    """
    if not isinstance(segments, (list, tuple)) or not segments:
        raise RecutError("segments must be a non-empty list")
    if len(segments) > MAX_SEGMENTS:
        raise RecutError(f"too many segments (max {MAX_SEGMENTS})")

    normalized = []
    for i, seg in enumerate(segments):
        try:
            start = float(seg["start"])
            end = float(seg["end"])
        except (KeyError, TypeError, ValueError):
            raise RecutError(f"segment {i + 1}: start/end must be numbers")
        if start != start or end != end:  # NaN guard
            raise RecutError(f"segment {i + 1}: start/end must be numbers")
        start = max(0.0, start)
        if source_duration is not None:
            end = min(float(source_duration), end)
            start = min(start, float(source_duration))
        if end - start < MIN_SEGMENT_SECONDS:
            raise RecutError(
                f"segment {i + 1} is shorter than {MIN_SEGMENT_SECONDS}s")
        normalized.append({"start": round(start, 3), "end": round(end, 3)})

    if total_duration(normalized) > MAX_TOTAL_SECONDS:
        raise RecutError(f"clip would exceed {MAX_TOTAL_SECONDS:.0f}s")
    return normalized


def total_duration(segments):
    return round(sum(s["end"] - s["start"] for s in segments), 3)


def within_range(segments, range_start, range_end, tolerance=RANGE_TOLERANCE):
    """True when every segment fits inside [range_start, range_end]."""
    return all(
        s["start"] >= float(range_start) - tolerance
        and s["end"] <= float(range_end) + tolerance
        for s in segments
    )


def rebase_segments(segments, range_start, range_end=None):
    """Map source-absolute segments onto a file cut at ``range_start``.

    The canonical clip's t=0 is the source's ``range_start``. Clamps to the
    file bounds so tolerance-admitted segments never produce negative seeks.
    """
    rebased = []
    for seg in segments:
        start = max(0.0, seg["start"] - float(range_start))
        end = seg["end"] - float(range_start)
        if range_end is not None:
            end = min(end, float(range_end) - float(range_start))
        rebased.append({"start": round(start, 3), "end": round(end, 3)})
    return rebased


def snap_segments(segments, transcript, source_duration):
    """Snap each segment's bounds onto word boundaries (ground truth beats
    millisecond arithmetic — same rationale as the pipeline's snapping)."""
    from clip_selection import snap_clip_to_words

    words = transcript_words(transcript)
    if not words:
        return segments
    snapped = []
    for seg in segments:
        start, end = snap_clip_to_words(
            seg["start"], seg["end"], words, source_duration,
            min_duration=MIN_SEGMENT_SECONDS, max_duration=MAX_TOTAL_SECONDS)
        snapped.append({"start": start, "end": end})
    return snapped


def transcript_words(transcript):
    """Flatten a transcript to [{'w','s','e'}, ...] sorted by start."""
    words = []
    for segment in (transcript or {}).get("segments", []):
        for w in segment.get("words", []) or []:
            try:
                words.append({
                    "w": str(w.get("word", "")).strip(),
                    "s": float(w["start"]),
                    "e": float(w["end"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
    words.sort(key=lambda w: w["s"])
    return words


def virtual_transcript(transcript, segments):
    """Remap a source-absolute transcript onto the concatenated clip timeline.

    Each segment becomes one synthetic transcript segment whose words are
    shifted so t=0 is the start of the recut clip. This is what lets the
    caption step keep working on multi-segment recuts: it keeps slicing
    "words between clip_start and clip_end" exactly as before, against
    this transcript with clip_start=0.
    """
    out_segments = []
    offset = 0.0
    for seg in segments:
        seg_start, seg_end = float(seg["start"]), float(seg["end"])
        seg_duration = seg_end - seg_start
        words = []
        for w in transcript_words(transcript):
            if w["e"] <= seg_start or w["s"] >= seg_end:
                continue
            words.append({
                # Leading space = the word-boundary convention the caption
                # block collector expects; without it a line's words glue
                # together.
                "word": " " + w["w"],
                "start": round(max(0.0, w["s"] - seg_start) + offset, 3),
                "end": round(min(seg_duration, w["e"] - seg_start) + offset, 3),
            })
        out_segments.append({
            "start": round(offset, 3),
            "end": round(offset + seg_duration, 3),
            "text": "".join(w["word"] for w in words).strip(),
            "words": words,
        })
        offset += seg_duration
    return {
        "language": (transcript or {}).get("language", "en"),
        "segments": out_segments,
    }


def _encode_args():
    # Same encode as the pipeline's clip cut in main.py, plus +faststart so
    # the browser preview doesn't hang on the delivered file.
    return ["-c:v", "libx264", "-crf", "18", "-preset", "fast",
            "-pix_fmt", "yuv420p", "-c:a", "aac",
            "-movflags", "+faststart"]


def cut_commands(input_path, segments, part_paths):
    """ffmpeg argv for each segment cut. Re-encodes for frame-accurate cuts
    with uniform parameters so the parts concat cleanly."""
    commands = []
    for seg, part in zip(segments, part_paths):
        commands.append([
            "ffmpeg", "-y",
            "-ss", str(seg["start"]),
            "-to", str(seg["end"]),
            "-i", input_path,
            *_encode_args(),
            part,
        ])
    return commands


def concat_command(list_path, out_path):
    """Concat demuxer over identically-encoded parts — stream copy, no
    generation loss on the join."""
    return [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", list_path, "-c", "copy",
        "-movflags", "+faststart", out_path,
    ]


def run_cut_concat(input_path, segments, out_path, workdir, runner=None):
    """Cut every segment from ``input_path`` and join them into ``out_path``."""
    run = runner or _run_ffmpeg
    if len(segments) == 1:
        run(cut_commands(input_path, segments, [out_path])[0])
        return out_path

    # Unique per invocation: two concurrent recuts in the same job dir must
    # not overwrite each other's parts (or delete them via the finally below).
    token = uuid.uuid4().hex[:8]
    part_paths = [
        os.path.join(workdir, f"temp_recut_part_{token}_{i}.mp4")
        for i in range(len(segments))
    ]
    list_path = os.path.join(workdir, f"temp_recut_concat_{token}.txt")
    try:
        for command in cut_commands(input_path, segments, part_paths):
            run(command)
        with open(list_path, "w") as f:
            for part in part_paths:
                # Absolute paths: the concat demuxer resolves relative entries
                # against the LIST FILE's directory, not the process cwd.
                f.write(f"file '{os.path.abspath(part)}'\n")
        run(concat_command(list_path, out_path))
    finally:
        for path in part_paths + [list_path]:
            if os.path.exists(path):
                os.remove(path)
    return out_path


def _run_ffmpeg(command):
    try:
        result = subprocess.run(
            command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=FFMPEG_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        raise RuntimeError(
            f"ffmpeg timed out after {FFMPEG_TIMEOUT_SECONDS}s ({command[1:6]}...)")
    if result.returncode != 0:
        tail = (result.stderr or b"").decode("utf-8", "replace")[-400:]
        raise RuntimeError(f"ffmpeg failed ({command[1:6]}...): {tail}")


def perform_recut(*, input_path, segments, output_dir, clean_name,
                  reframe=False, output_format="mp4", captions_transcript=None,
                  burn_captions=True, runner=None, crop_overrides=None):
    """Render a recut clip. Returns (served_filename, clean_filename).

    - ``input_path``/``segments``: the file to cut from and the times ON THAT
      FILE (the caller rebases for the fast path).
    - ``reframe``: run the vertical reframe on the joined cut (source path
      only — the canonical file is already framed).
    - ``captions_transcript``: a clip-relative transcript (see
      ``virtual_transcript``); when given and non-empty, captions are burned
      onto a ``subtitled_<ts>_`` derivative, preserving the invariant that
      the clean file stays clean for later re-styling.
    - ``crop_overrides``: scene index -> crop centre (fraction of source
      width, or {"x": f, "y": f}) for scenes the user framed by hand.
      Source path only; the canonical file is already cropped so its
      framing can no longer be changed. The CUT is never touched.
    """
    # The uuid token keeps two same-second saves of one clip from writing (and
    # then serving) the same filename; the timestamp keeps "newest derived
    # file" resolution working in _canonical_clip_file.
    out_name = f"recut_{int(time.time())}_{uuid.uuid4().hex[:6]}_{clean_name}"
    out_path = os.path.join(output_dir, out_name)
    work_name = f"temp_{out_name}"
    work_path = os.path.join(output_dir, work_name)

    try:
        run_cut_concat(input_path, segments, work_path, output_dir,
                       runner=runner)

        if reframe:
            from main import process_video_to_vertical  # heavy — lazy
            if not process_video_to_vertical(work_path, out_path, crop_overrides=crop_overrides):
                raise RuntimeError("reframe failed on the recut clip")
            # process_video_to_vertical writes a fresh layout sidecar itself.
        else:
            os.rename(work_path, out_path)
            # Fast path never reframes, so carry the canonical clip's layout
            # ranges across the new cut (see layout_ranges.remap).
            try:
                import layout_ranges  # lazy — tiny module
                remapped = layout_ranges.remap(
                    layout_ranges.read(input_path), segments)
                if remapped:
                    layout_ranges.write(
                        out_path,
                        [(r["start"], r["end"], r["layout"]) for r in remapped])
            except Exception:
                pass

        served_name = out_name
        if burn_captions and captions_transcript \
                and captions_transcript.get("segments"):
            from subtitles import generate_srt, burn_subtitles  # lazy
            srt_path = os.path.join(
                output_dir, f"recut_{int(time.time())}_captions.srt")
            ok = generate_srt(captions_transcript, 0.0,
                              total_duration(segments), srt_path)
            if ok:
                captioned_name = f"subtitled_{int(time.time())}_{out_name}"
                captioned_path = os.path.join(output_dir, captioned_name)
                try:
                    # Captions sit on the seam between stacked speakers on
                    # SPLIT stretches (see layout_ranges.split_ranges).
                    split_ranges = None
                    try:
                        import layout_ranges  # lazy — tiny module
                        split_ranges = layout_ranges.split_ranges(
                            layout_ranges.read(out_path)) or None
                    except Exception:
                        pass
                    burn_subtitles(out_path, srt_path, captioned_path,
                                   split_ranges=split_ranges)
                    served_name = captioned_name
                finally:
                    if os.path.exists(srt_path):
                        os.remove(srt_path)
        return served_name, out_name
    finally:
        if os.path.exists(work_path):
            os.remove(work_path)
