"""Punch-in: a short push toward the subject on the beats that carry the clip.

Ported from upstream herdr-clipping (punch_in.py + reframe_v2.py usage).
Adaptations for OpenShorts:

- Enabled by default: no PUNCH_IN env gate, no feature flag. If audio
  analysis fails for any reason, emphasis_times returns [] (graceful
  no-op) and the render is unchanged — it never crashes the render.
- No ffmpeg sendcmd: the local render path (main.process_video_to_vertical)
  crops numpy frames per frame, so callers compute a per-frame zoom array
  with zoom_curve() and scale the SmoothFollower crop box with zoom_box()
  before cropping.
- Audio envelope is computed locally with ffmpeg (mono 8kHz RMS per window),
  same normalisation as upstream's active_speaker.audio_envelope, which this
  repo does not ship. numpy-only, no new dependencies.
- Applied to the single-speaker TRACK/GENERAL path only. Multi-region
  layouts (SPLIT, SCREENCAST, PANEL, WIDE) compose a grid out of static
  boxes — zooming the composed frame makes no sense, so those paths skip it.

The push is deliberately small (MAX_ZOOM 1.12: visible as intent, short of
cutting into a head framed by the TRACK crop). The curve is asymmetric on
purpose: fast in, hold, slow out — how a human operator does it.

MAX_ZOOM and MIN_GAP_SECONDS were swept over a 20-clip corpus upstream
(18.0/0.60 picked for the tightest spread, worst case 3.0/min) — keep them.
"""
import subprocess

import numpy as np

# Peak zoom. 1.12 crops ~11% off each dimension at full push.
MAX_ZOOM = 1.12

# Envelope, in seconds: snap in, sit there, drift out.
RISE_SECONDS = 0.25
HOLD_SECONDS = 1.30
FALL_SECONDS = 0.55

# Never punch twice inside this window. Two pushes in quick succession read
# as a glitch, and the second one lands before the first has released.
MIN_GAP_SECONDS = 18.0

# Audio-envelope resolution used to find beats.
BEAT_WINDOW = 0.2

# A beat must exceed the clip's median loudness by this much of the gap to
# its peak. Low values punch on every syllable; this keeps real emphasis.
BEAT_PROMINENCE = 0.60


def _ease(t):
    """Smoothstep on [0, 1]. Linear ramps look mechanical at this duration."""
    t = min(max(t, 0.0), 1.0)
    return t * t * (3.0 - 2.0 * t)


def zoom_curve(n_frames, fps, emphasis_times, max_zoom=None,
               start_offset=0.0):
    """Per-frame zoom factor (1.0 = untouched) for one scene.

    ``emphasis_times`` are absolute seconds; ``start_offset`` is where this
    scene begins, so callers can pass clip-level beats unchanged.
    """
    max_zoom = MAX_ZOOM if max_zoom is None else max_zoom
    zooms = [1.0] * max(0, n_frames)
    if not zooms or max_zoom <= 1.0:
        return zooms

    fps = float(fps) or 30.0
    span = RISE_SECONDS + HOLD_SECONDS + FALL_SECONDS
    for t in emphasis_times:
        local = t - start_offset
        if local <= -span or local >= n_frames / fps:
            continue
        for f in range(max(0, int(local * fps)),
                       min(n_frames, int((local + span) * fps) + 1)):
            dt = f / fps - local
            if dt < 0:
                continue
            if dt < RISE_SECONDS:
                amount = _ease(dt / RISE_SECONDS)
            elif dt < RISE_SECONDS + HOLD_SECONDS:
                amount = 1.0
            elif dt < span:
                amount = 1.0 - _ease(
                    (dt - RISE_SECONDS - HOLD_SECONDS) / FALL_SECONDS)
            else:
                continue
            # Overlapping pushes take the strongest rather than compounding.
            zooms[f] = max(zooms[f], 1.0 + (max_zoom - 1.0) * amount)
    return zooms


def zoom_box(x1, y1, x2, y2, zoom, orig_w, orig_h):
    """Scale a crop box about its own centre by ``zoom`` (>= 1.0 zooms in).

    Keeping the centre fixed is what makes this a push rather than a pan:
    the subject stays put and the frame closes in around them. The box is
    clamped inside the source frame; zoom <= 1.0 returns the box unchanged.
    """
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    if zoom is None or zoom <= 1.0:
        return x1, y1, x2, y2
    cx = (x1 + x2) / 2.0
    cy = (y1 + y2) / 2.0
    w = max(2, (x2 - x1) / float(zoom))
    h = max(2, (y2 - y1) / float(zoom))
    nx1 = int(round(cx - w / 2.0))
    ny1 = int(round(cy - h / 2.0))
    nx2 = int(round(nx1 + w))
    ny2 = int(round(ny1 + h))
    # Clamp inside the source frame, preserving size where possible.
    if nx1 < 0:
        nx2 -= nx1
        nx1 = 0
    if ny1 < 0:
        ny2 -= ny1
        ny1 = 0
    if nx2 > orig_w:
        nx1 -= nx2 - orig_w
        nx2 = orig_w
    if ny2 > orig_h:
        ny1 -= ny2 - orig_h
        ny2 = orig_h
    nx1 = max(0, nx1)
    ny1 = max(0, ny1)
    if nx2 <= nx1 or ny2 <= ny1:
        return x1, y1, x2, y2
    return nx1, ny1, nx2, ny2


def _audio_envelope(video_path, duration, window=BEAT_WINDOW):
    """Per-window RMS of the clip's audio, normalised to its own peak.

    Local equivalent of upstream active_speaker.audio_envelope (not shipped
    in this repo). Returns [] when the source has no/decodable audio.
    """
    try:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-t", f"{max(0.0, duration):.4f}",
             "-i", video_path,
             "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=300).stdout
    except (subprocess.SubprocessError, OSError):
        return []
    if not raw:
        return []
    try:
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    except (ValueError, TypeError):
        return []
    per_window = max(1, int(8000 * window))
    n = len(samples) // per_window
    if n < 1:
        return []
    windows = samples[:n * per_window].reshape(n, per_window)
    rms = np.sqrt(np.mean(windows ** 2, axis=1))
    peak = rms.max()
    return (rms / peak).tolist() if peak > 0 else [0.0] * n


def emphasis_times(video_path, duration, window=BEAT_WINDOW,
                   min_gap=MIN_GAP_SECONDS, prominence=BEAT_PROMINENCE):
    """Seconds where the audio leaps above its own baseline.

    A stand-in for the hook words until the transcript is wired through.
    Returns [] for silent or unreadable audio (or any failure), which
    simply means no punches — never raises.
    """
    try:
        envelope = _audio_envelope(video_path, duration, window)
        if not envelope:
            return []

        values = np.asarray(envelope, dtype=float)
        baseline = float(np.median(values))
        peak = float(values.max())
        if peak - baseline <= 1e-6:
            return []

        threshold = baseline + (peak - baseline) * prominence
        times = []
        last = -1e9
        for i, v in enumerate(values):
            t = i * window
            if v >= threshold and t - last >= min_gap:
                times.append(round(t, 3))
                last = t
        return times
    except Exception:
        return []
