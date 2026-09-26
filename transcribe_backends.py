"""Transcription backends: NVIDIA Parakeet (onnx-asr) with faster-whisper fallback.

Ported from upstream mutonby/openshorts, adapted for this repo:
  - local whisper config preserved exactly (base/int8/CPU, VAD, greedy decode)
  - merge_continuation_words implemented here (local subtitles.py lacks it)
  - Parakeet providers are CPU-first (this host is CPU-only); set
    TRANSCRIBE_GPU=1 to restore the upstream CUDA-first provider list.

Every caller goes through transcribe_media(), which returns the transcript
contract the whole pipeline depends on:

    {
      "text": str,          # full punctuated transcript
      "language": str,      # whisper-style short code ("es", "en", ...)
      "segments": [
        {"start": float, "end": float, "text": str,
         "words": [{"word": str, "start": float, "end": float}, ...]},
      ],
    }

Invariants the consumers rely on (clip cutting, karaoke subtitles):
  - word["word"] carries a LEADING SPACE on true word starts; continuation
    fragments are merged into their base word (merge_continuation_words).
  - all numerics are native Python floats (json.dump of the transcript).
  - words sorted by start, segments chronological, absolute file timestamps.

TRANSCRIBE_BACKEND env: "whisper" (default) | "parakeet".
The parakeet path falls back to whisper automatically when the model errors,
produces no usable words, or the detected language is outside its 25
supported European languages (e.g. Japanese/Chinese/Arabic uploads).
"""
import os
import subprocess
import sys
import tempfile
import threading
import time

PARAKEET_MODEL_ID = "nemo-parakeet-tdt-0.6b-v3"

# The 25 European languages parakeet-tdt-0.6b-v3 supports (ISO 639-1).
PARAKEET_LANGS = {
    "bg", "hr", "cs", "da", "nl", "en", "et", "fi", "fr", "de", "el", "hu",
    "it", "lv", "lt", "mt", "pl", "pt", "ro", "sk", "sl", "es", "sv", "ru",
    "uk",
}

# --- local whisper config (matches main.py's previous inline settings) --------

WHISPER_MODEL_SIZE = os.environ.get("WHISPER_MODEL_SIZE", "base")
WHISPER_DEVICE = os.environ.get("WHISPER_DEVICE", "cpu")
WHISPER_COMPUTE_TYPE = os.environ.get("WHISPER_COMPUTE_TYPE", "int8")
WHISPER_CPU_THREADS = int(os.environ.get("WHISPER_CPU_THREADS", "2"))

WHISPER_TRANSCRIBE_PARAMS = {
    "word_timestamps": True,
    "vad_filter": True,
    "beam_size": 1,  # greedy: keeps the decoder's working set minimal
    "condition_on_previous_text": True,
    "vad_parameters": {"min_silence_duration_ms": 500},
}


def merge_continuation_words(words):
    """Merge subword fragments (no leading space) into their base word.

    faster-whisper with word_timestamps=True sometimes emits a word as a base
    fragment plus continuations ("un" + "believable"). Downstream (clip
    cutting, karaoke captions) expects one entry per spoken word with a
    leading space on true word starts. Returns a new list.
    """
    merged = []
    for w in words or []:
        text = w.get("word", "")
        if not text:
            continue
        if text.startswith(" ") or not merged:
            entry = dict(w)
            if not entry["word"].startswith(" "):
                entry["word"] = " " + entry["word"]
            merged.append(entry)
        else:
            merged[-1]["word"] += text
            if "end" in w:
                merged[-1]["end"] = w["end"]
    return merged


# Serializes GPU transcription across concurrent jobs so N jobs can't stack
# N model contexts / decode batches in VRAM. CPU whisper stays ungated
# (CTranslate2 models are thread-safe and that matches the old behavior).
_ASR_SLOTS = int(os.environ.get("ASR_GPU_CONCURRENCY", "1"))
_ASR_GATE = threading.Semaphore(_ASR_SLOTS)


class host_asr_slot:
    """``with host_asr_slot():`` holds one of ASR_HOST_SLOTS flock slots.

    Blocks (polling once a second) until a slot is free. A crashed holder
    releases its lock with its file descriptor, so a slot can never leak.
    Degrades to a no-op where flock or the directory is unavailable.
    """

    def __init__(self, slots=None, lock_dir=None, poll=1.0):
        self.slots = int(os.environ.get("ASR_HOST_SLOTS", "2")) if slots is None else slots
        self.lock_dir = lock_dir or os.environ.get("ASR_LOCK_DIR", "output")
        self.poll = poll
        self._fh = None

    def __enter__(self):
        if self.slots <= 0:
            return self
        try:
            import fcntl
            os.makedirs(self.lock_dir, exist_ok=True)
        except Exception:
            return self
        announced = False
        while True:
            for i in range(self.slots):
                path = os.path.join(self.lock_dir, f".asr-gpu-{i}.lock")
                try:
                    fh = open(path, "a+")
                except OSError:
                    return self
                try:
                    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self._fh = fh
                    return self
                except OSError:
                    fh.close()
            if not announced:
                print("🎙️ Waiting for a free transcription slot…", flush=True)
                announced = True
            time.sleep(self.poll)

    def __exit__(self, *exc):
        if self._fh is not None:
            try:
                import fcntl
                fcntl.flock(self._fh, fcntl.LOCK_UN)
            except Exception:
                pass
            self._fh.close()
            self._fh = None
        return False


class _NullGate:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_NULL_GATE = _NullGate()


class _TranscribeProgress:
    """Emits '🎙️ Transcribing… NN% (Xs)' lines at 25% steps."""

    def __init__(self, total_seconds):
        self.total = max(float(total_seconds or 0), 0.0)
        self.started = time.time()
        self.next_pct = 25

    def update(self, position_seconds):
        if self.total <= 0:
            return
        pct = min(int(position_seconds / self.total * 100), 100)
        while pct >= self.next_pct and self.next_pct <= 100:
            elapsed = int(time.time() - self.started)
            print(f"🎙️ Transcribing… {self.next_pct}% ({elapsed}s)", flush=True)
            self.next_pct += 25


def _emit_progress(end_seconds, duration):
    """Machine-readable progress marker consumed by the API status poller."""
    if duration and duration > 0:
        pct = min(100, int((end_seconds / duration) * 100))
        print(f"PROGRESS:{pct}", flush=True)


# --- whisper singleton --------------------------------------------------------

_whisper_model = None
_whisper_key = None
_whisper_lock = threading.Lock()
# Set after a CUDA failure so later transcriptions go straight to CPU.
_whisper_force_cpu = False


def _get_whisper_model():
    """Process-wide WhisperModel singleton, rebuilt if the env config changes."""
    global _whisper_model, _whisper_key
    size, device, compute = WHISPER_MODEL_SIZE, WHISPER_DEVICE, WHISPER_COMPUTE_TYPE
    if _whisper_force_cpu:
        device, compute = "cpu", "int8"
    key = (size, device, compute)
    with _whisper_lock:
        if _whisper_model is None or _whisper_key != key:
            from faster_whisper import WhisperModel
            _whisper_model = WhisperModel(
                key[0], device=key[1], compute_type=key[2],
                cpu_threads=WHISPER_CPU_THREADS)
            _whisper_key = key
    return _whisper_model, device


def _whisper_device():
    return "cpu" if _whisper_force_cpu else WHISPER_DEVICE


def _run_whisper_once(media_path, duration=None, **params):
    gate = _ASR_GATE if _whisper_device() != "cpu" else _NULL_GATE
    with gate:
        model, _device = _get_whisper_model()
        segments, info = model.transcribe(media_path, **params)
        progress = _TranscribeProgress(getattr(info, "duration", 0) or duration)
        materialized = []
        for segment in segments:
            materialized.append(segment)
            progress.update(segment.end)
            _emit_progress(segment.end, duration)
            print(f"   [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
        # VAD trims trailing silence, so the last segment can end short of the
        # media duration — force the 100% line.
        progress.update(progress.total)
        if duration and duration > 0:
            print("PROGRESS:100", flush=True)
        return materialized, info


def run_whisper_transcription(media_path, duration=None, **params):
    """Transcribe and FULLY materialize the segments inside the GPU gate.

    faster-whisper returns a lazy generator — decoding happens while
    iterating, so the gate must wrap list(segments), not just transcribe().
    Returns (segments_list, info).

    A CUDA failure retries once on CPU and pins CPU for the rest of the
    process instead of dying when VRAM runs out.
    """
    global _whisper_model, _whisper_force_cpu
    try:
        return _run_whisper_once(media_path, duration=duration, **params)
    except RuntimeError as e:
        if _whisper_force_cpu or "cuda" not in str(e).lower():
            raise
        print(f"⚠️ [ASR] whisper GPU failed ({e}) — retrying on CPU", flush=True)
        _whisper_force_cpu = True
        with _whisper_lock:
            _whisper_model = None
        return _run_whisper_once(media_path, duration=duration, **params)


def _transcribe_with_whisper(media_path, duration=None):
    segments, info = run_whisper_transcription(
        media_path, duration=duration, **WHISPER_TRANSCRIBE_PARAMS)

    out_segments = []
    text_parts = []
    for segment in segments:
        words = [
            {"word": w.word, "start": float(w.start), "end": float(w.end),
             "probability": float(w.probability)}
            for w in (segment.words or [])
        ]
        out_segments.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": segment.text,
            "words": merge_continuation_words(words),
        })
        text_parts.append(segment.text.strip())

    print(f"   Detected language '{info.language}' "
          f"with probability {info.language_probability:.2f}")

    return {
        "text": " ".join(part for part in text_parts if part),
        "language": info.language,
        "segments": out_segments,
    }


# --- parakeet -----------------------------------------------------------------

_parakeet_model = None
_parakeet_lock = threading.Lock()

# How many VAD segments (up to 20 s each) the encoder takes per batch.
PARAKEET_VAD_BATCH = int(os.environ.get("PARAKEET_VAD_BATCH", "4"))


def parakeet_providers():
    """onnxruntime providers for Parakeet.

    CPU-first: this host is CPU-only. Set TRANSCRIBE_GPU=1 to restore the
    upstream CUDA-first list (with its tuned arena/cuDNN options) on a GPU box.
    """
    if os.environ.get("TRANSCRIBE_GPU", "0") == "1":
        cuda_opts = {
            "arena_extend_strategy": "kSameAsRequested",
            "cudnn_conv_use_max_workspace": "0",
            "cudnn_conv_algo_search": "HEURISTIC",
        }
        return [("CUDAExecutionProvider", cuda_opts), "CPUExecutionProvider"]
    return ["CPUExecutionProvider"]


def parakeet_session_options():
    """onnxruntime SessionOptions: pool threads sleep, never spin."""
    import onnxruntime as rt
    opts = rt.SessionOptions()
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return opts


def vad_load_kwargs():
    """Silero VAD on the CPU, one sleeping thread."""
    import onnxruntime as rt
    opts = rt.SessionOptions()
    opts.intra_op_num_threads = 1
    opts.inter_op_num_threads = 1
    opts.add_session_config_entry("session.intra_op.allow_spinning", "0")
    opts.add_session_config_entry("session.inter_op.allow_spinning", "0")
    return {"sess_options": opts, "providers": ["CPUExecutionProvider"]}


def _get_parakeet_model():
    global _parakeet_model
    with _parakeet_lock:
        if _parakeet_model is None:
            import onnx_asr
            model = onnx_asr.load_model(PARAKEET_MODEL_ID,
                                        providers=parakeet_providers(),
                                        sess_options=parakeet_session_options())
            vad = onnx_asr.load_vad("silero", **vad_load_kwargs())
            _parakeet_model = model.with_vad(
                vad, batch_size=PARAKEET_VAD_BATCH).with_timestamps()
    return _parakeet_model


def release_models():
    """Drop the resident ASR models and hand their memory back."""
    global _whisper_model, _whisper_key, _parakeet_model
    for _ in range(_ASR_SLOTS):
        _ASR_GATE.acquire()
    try:
        with _whisper_lock:
            whisper, _whisper_model, _whisper_key = _whisper_model, None, None
        with _parakeet_lock:
            parakeet, _parakeet_model = _parakeet_model, None
    finally:
        for _ in range(_ASR_SLOTS):
            _ASR_GATE.release()
    if whisper is not None:
        try:
            whisper.model.unload_model()
        except Exception as e:
            print(f"⚠️ [ASR] whisper unload failed ({type(e).__name__}: {e})")
    del whisper, parakeet
    tn2 = sys.modules.get("scene_detection")
    if tn2 is not None:
        try:
            tn2._tn2_model = None
        except Exception:
            pass
    import gc
    gc.collect()
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    if "onnxruntime" in sys.modules or "faster_whisper" in sys.modules:
        print("🧹 [ASR] resident models released")


def _extract_wav(media_path):
    """Parakeet wants 16kHz mono PCM wav; ffmpeg-extract to a temp file."""
    fd, wav_path = tempfile.mkstemp(suffix=".wav", prefix="asr_")
    os.close(fd)
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error", "-i", media_path,
        "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav_path,
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.PIPE, timeout=1800)
    return wav_path


def _words_from_tokens(tokens, timestamps, seg_start, seg_end):
    """Group parakeet BPE tokens into words with absolute timestamps.

    Tokens already carry the leading-space word-start convention (" T",
    "odo", " el", ...); timestamps are token START times in seconds relative
    to the VAD segment. A token without a leading space (subword
    continuations, punctuation like ",") belongs to the previous word — the
    same semantics merge_continuation_words expects. Word end is inferred:
    next word's start, capped near the word's last token so a long inter-word
    silence doesn't stretch the highlight.
    """
    words = []
    last_token_ts = []
    for token, ts in zip(tokens, timestamps):
        if not token:
            continue
        abs_ts = float(ts) + seg_start
        if token.startswith(" ") or not words:
            words.append({
                "word": token if token.startswith(" ") else " " + token,
                "start": abs_ts,
            })
            last_token_ts.append(abs_ts)
        else:
            words[-1]["word"] += token
            last_token_ts[-1] = abs_ts

    for i, word in enumerate(words):
        next_start = words[i + 1]["start"] if i + 1 < len(words) else seg_end
        cap = last_token_ts[i] + 0.6
        word["end"] = float(max(word["start"] + 0.05, min(next_start, cap)))

    return words


def _transcribe_with_parakeet(media_path, duration=None):
    wav_path = _extract_wav(media_path)
    try:
        # 16kHz mono s16le wav -> 32000 bytes per second of audio.
        try:
            duration = os.path.getsize(wav_path) / 32000.0
        except OSError:
            duration = 0.0
        with _ASR_GATE:
            model = _get_parakeet_model()  # inside the gate: see release_models
            progress = _TranscribeProgress(duration)
            results = []
            for seg in model.recognize(wav_path):
                results.append(seg)
                progress.update(float(seg.end))
                _emit_progress(float(seg.end), duration)
                print(f"   [{float(seg.start):.2f}s -> {float(seg.end):.2f}s] {seg.text}")
            progress.update(progress.total)
            if duration and duration > 0:
                print("PROGRESS:100", flush=True)
    finally:
        try:
            os.remove(wav_path)
        except OSError:
            pass

    out_segments = []
    text_parts = []
    for seg in results:
        seg_start = float(seg.start)
        seg_end = float(seg.end)
        seg_text = str(seg.text or "").strip()
        if not seg_text:
            continue
        out_segments.append({
            "start": seg_start,
            "end": seg_end,
            "text": seg_text,
            "words": _words_from_tokens(
                list(seg.tokens or []), list(seg.timestamps or []),
                seg_start, seg_end,
            ),
        })
        text_parts.append(seg_text)

    text = " ".join(text_parts)
    return {
        "text": text,
        "language": _detect_language(text),
        "segments": out_segments,
    }


def _detect_language(text):
    """Parakeet doesn't report a language; classify the transcribed text.

    py3langid is pure-Python and returns ISO 639-1 codes compatible with the
    whisper codes the pipeline expects.
    """
    sample = (text or "").strip()
    if len(sample) < 20:
        return "en"
    try:
        import py3langid
        lang, _score = py3langid.classify(sample[:4000])
        return lang
    except Exception:
        return "en"


def _parakeet_fallback_reason(transcript, duration_hint=None):
    """Return why the parakeet result is untrustworthy, or None if it's fine."""
    segments = transcript.get("segments") or []
    total_words = sum(len(s.get("words") or []) for s in segments)
    if total_words == 0:
        return "no words recognized"
    language = transcript.get("language")
    if language not in PARAKEET_LANGS:
        return f"language '{language}' outside parakeet's supported set"
    duration = duration_hint or (segments[-1]["end"] if segments else 0)
    # Real speech averages >100 wpm; under ~12 wpm on a long video means the
    # audio was mostly not recognized (e.g. unsupported language or music).
    if duration > 60 and total_words < duration * 0.2:
        return f"only {total_words} words in {duration:.0f}s of audio"
    return None


# --- public entry point -------------------------------------------------------

class NoAudioError(Exception):
    """The media has no audio track — nothing to transcribe."""


def _has_audio_stream(media_path) -> bool:
    """True if the file has at least one audio stream (ffprobe)."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=index", "-of", "csv=p=0", media_path],
            capture_output=True, text=True, timeout=60,
        )
        return bool(out.stdout.strip())
    except Exception:
        return True  # probe failed — don't block, let the backend try


def transcribe_media(media_path, duration=None):
    """Transcribe with the configured backend, falling back to whisper.

    duration (seconds) enables the PROGRESS:{pct} markers the API status
    poller consumes.
    """
    # Silent videos have no audio stream; every ASR backend then crashes deep
    # inside libav with an opaque error. Detect it up front and fail with a
    # clear, actionable reason instead.
    if not _has_audio_stream(media_path):
        raise NoAudioError(
            "This video has no audio track. OpenShorts finds viral moments from "
            "speech, so it needs a video with audio.")

    backend = os.environ.get("TRANSCRIBE_BACKEND", "whisper").strip().lower()

    if backend == "parakeet":
        try:
            transcript = _transcribe_with_parakeet(media_path, duration=duration)
            reason = _parakeet_fallback_reason(transcript)
            if reason is None:
                print(f"🎙️ [ASR] parakeet ok: lang={transcript['language']} "
                      f"segments={len(transcript['segments'])}")
                return transcript
            print(f"⚠️ [ASR] parakeet result rejected ({reason}) — "
                  f"falling back to whisper")
        except Exception as e:
            print(f"⚠️ [ASR] parakeet failed ({type(e).__name__}: {e}) — "
                  f"falling back to whisper")

    return _transcribe_with_whisper(media_path, duration=duration)
