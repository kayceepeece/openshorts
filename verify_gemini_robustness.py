"""Verify the Gemini selection robustness work (report item 7, track D).

Two failure modes are covered, both of which used to cost whole jobs:

1. A policy block on ONE window used to take every other window with it. These
   tests block one window in a fake Gemini and assert the pass still returns
   clips from the windows around it (the detail prompt) and still scores the
   rest (the scoring prompt).
2. Footage with too little speech to clip by transcript used to return no
   clips at all. These tests hand the stage a sparse transcript and assert the
   Gemini-vision path is taken instead — once against a fake client (no
   network) and once against the real API when a key and a source video are
   available.

Run:  python verify_gemini_robustness.py [--live]
"""

import os
import re
import sys

import main

HERE = os.path.dirname(os.path.abspath(__file__))
# Window lines look like "window_003 [120.0-210.0] (score 9/12): text" in both
# the scoring and the detail prompt, so a fake can read back exactly which
# windows it was given and which of them it was asked to block.
WINDOW_RE = re.compile(r"(window_\d{3})\s*\[([\d.]+)-([\d.]+)\]")


# --- Fakes ------------------------------------------------------------------

class _Named:
    def __init__(self, name):
        self.name = name


class _FakeCandidate:
    def __init__(self, finish="STOP"):
        self.finish_reason = _Named(finish)


class _FakeUsage:
    prompt_token_count = 4000
    candidates_token_count = 500
    thoughts_token_count = 0


class _FakeResponse:
    def __init__(self, text="", finish="STOP", block_reason=None):
        self.text = text
        self.usage_metadata = _FakeUsage()
        self.prompt_feedback = type("_PF", (), {"block_reason": _Named(block_reason) if block_reason else None})()
        self.candidates = [_FakeCandidate(finish)]


class _FakeFile:
    name = "files/fake-video"


class _FakeFiles:
    def __init__(self, log):
        self.log = log

    def upload(self, file=None, config=None):
        self.log.append(("upload", (config or {}).get("display_name")))
        return _FakeFile()

    def get(self, name=None):
        return type("_Info", (), {"state": _Named("ACTIVE")})()

    def delete(self, name=None):
        self.log.append(("delete", name))
        return None


class FakeGemini:
    """Stand-in for genai.Client that blocks on chosen window ids.

    block_on: dict of prompt-kind -> window id to refuse. A prompt is refused
    only when it carries that id AND more than one window, which is the real
    failure shape: the filter rejects some COMBINATIONS of windows that are
    fine on their own.
    """

    def __init__(self, block_on=None, refuse_lone_window=True, visual_clips=4):
        self.block_on = block_on or {}
        self.refuse_lone_window = refuse_lone_window
        self.visual_clips = visual_clips
        self.calls = []          # (kind, [window ids in that prompt])
        self.served = []         # (kind, ids) for the calls that got through
        self.uploads = []

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def _prompt_text(contents):
        if isinstance(contents, str):
            return contents
        return "".join(str(part) for part in contents if isinstance(part, str))

    def _windows_in(self, prompt):
        return [(m.group(1), float(m.group(2)), float(m.group(3)))
                for m in WINDOW_RE.finditer(prompt)]

    def _blocked(self, kind, windows):
        target = self.block_on.get(kind)
        if not target or not windows:
            return False
        ids = [w[0] for w in windows]
        if target not in ids:
            return False
        return self.refuse_lone_window or len(ids) > 1

    # -- the client surface the stage uses ---------------------------------
    def __call__(self, api_key=None, **kwargs):
        return self

    @property
    def files(self):
        return _FakeFiles(self.uploads)

    @property
    def models(self):
        return self

    def generate_content(self, model=None, contents=None, config=None):
        prompt = self._prompt_text(contents)
        windows = self._windows_in(prompt)

        if "CANDIDATE WINDOWS (pre-scored" in prompt:
            kind = "detail"
        elif "Score EACH window" in prompt:
            kind = "score"
        elif "purely by what you SEE" in prompt:
            kind = "visual"
        else:
            kind = "other"

        self.calls.append((kind, [w[0] for w in windows]))

        if kind == "visual":
            shorts = [{"start": 5.0 + 20 * i, "end": 30.0 + 20 * i,
                       "predicted_score": 10 - i,
                       "video_description_for_tiktok": f"clip {i} #shorts",
                       "video_description_for_instagram": f"clip {i} #reels",
                       "video_title_for_youtube_short": f"Visual moment {i}",
                       "viral_hook_text": f"watch this {i}"}
                      for i in range(self.visual_clips)]
            return _FakeResponse(text='{"shorts": %s}' % _json(shorts))

        if self._blocked(kind, windows):
            return _FakeResponse(text="", finish="SAFETY")

        self.served.append((kind, [w[0] for w in windows]))

        if kind == "detail":
            shorts = [{"start": start + 1.0, "end": start + 31.0,
                       "predicted_score": 9,
                       "video_description_for_tiktok": "tt",
                       "video_description_for_instagram": "ig",
                       "video_title_for_youtube_short": "title",
                       "viral_hook_text": "hook"}
                      for _id, start, _end in windows]
            return _FakeResponse(text='{"shorts": %s}' % _json(shorts))

        scores = [{"id": wid, "score": 9, "why": "solid moment"} for wid, _s, _e in windows]
        return _FakeResponse(text='{"scores": %s}' % _json(scores))


def _json(obj):
    import json
    return json.dumps(obj)


# --- Fixtures ---------------------------------------------------------------

def make_transcript(duration=900.0, dense=True):
    """A transcript shaped like a real one: 10s segments, word-level times."""
    import random
    rnd = random.Random(7)
    words_per_segment = 24 if dense else 3
    segments = []
    t = 0.0
    vocab = ("we shipped the feature overnight and the numbers were wild "
             "seven times better than the old pipeline honestly ask me how").split()
    while t < duration - 10.0:
        text = " ".join(rnd.choice(vocab) for _ in range(words_per_segment))
        segment_words = []
        wt = t
        for i, w in enumerate(text.split()):
            segment_words.append({"word": " " + w, "start": round(wt, 2),
                                  "end": round(wt + 0.4, 2), "probability": 0.9})
            wt += 0.4
        segments.append({"text": text, "start": round(t, 2),
                         "end": round(t + 9.5, 2), "words": segment_words})
        t += 10.0
    return {"text": " ".join(s["text"] for s in segments),
            "segments": segments, "language": "en",
            "duration_seconds": duration}


def make_sparse_transcript(duration=300.0):
    """Music over ambience: audio exists, words do not."""
    return {"text": "uh uh", "language": "en", "duration_seconds": duration,
            "segments": [{"text": "uh uh", "start": 1.0, "end": 2.5, "words": [
                {"word": " uh", "start": 1.0, "end": 1.4, "probability": 0.3},
                {"word": " uh", "start": 1.5, "end": 1.9, "probability": 0.3}]}]}


def run_stage(transcripts, videos=None, block_on=None, **kwargs):
    """Run detect_clips_windowed against a fake Gemini. Returns (result, fake)."""
    fake = FakeGemini(block_on=block_on)
    real_client = main.genai.Client
    main.genai.Client = fake
    try:
        result = main.detect_clips_windowed(
            transcripts, [""] * len(transcripts), "", "fake-key",
            videos=videos, **kwargs)
    finally:
        main.genai.Client = real_client
    return result, fake


def clip_windows(clips):
    """Start timestamp of every clip the stage handed back."""
    return [clip["start"] for clip in clips]


# --- Tests ------------------------------------------------------------------

def test_raise_if_blocked():
    """A blocked response must be recognised, and a normal one must not be."""
    blocked = _FakeResponse(text="", finish="SAFETY")
    ok = _FakeResponse(text='{"scores": []}')
    try:
        main.raise_if_blocked(ok)
    except main.GeminiBlockedError:
        print("   ❌ a normal response was read as a block")
        return False
    for name, response in (("SAFETY", blocked),
                          ("PROHIBITED_CONTENT", _FakeResponse(finish="PROHIBITED_CONTENT")),
                          ("prompt_feedback", _FakeResponse(block_reason="BLOCKLIST"))):
        try:
            main.raise_if_blocked(response)
        except main.GeminiBlockedError:
            continue
        print(f"   ❌ {name} was not recognised as a block")
        return False
    print("   ✅ blocks detected (finish_reason + prompt_feedback), clean response untouched")
    return True


def test_detail_bisection():
    """ACCEPTANCE: a block on one window still yields clips from the others."""
    transcript = make_transcript()
    blocked = "window_003"
    result, fake = run_stage([transcript], block_on={"detail": blocked})

    if not result or not result.get("shorts"):
        print("   ❌ the pass returned no clips at all after a block")
        return False

    detail_calls = [c for c in fake.calls if c[0] == "detail"]
    served = [ids for kind, ids in fake.served if kind == "detail"]
    if len(detail_calls) < 3:
        print(f"   ❌ the blocked shortlist was not bisected ({len(detail_calls)} detail call(s))")
        return False
    if detail_calls[0][1] == detail_calls[-1][1]:
        print("   ❌ every detail call carried the same windows — no retry happened")
        return False
    if any(blocked in ids for ids in served):
        print(f"   ❌ {blocked} was still detailed after being blocked")
        return False

    shorts = result["shorts"]
    kept = [wid for ids in served for wid in ids]
    if len(shorts) < 3:
        print(f"   ❌ only {len(shorts)} clip(s) survived; the other windows were lost")
        return False
    # One clip per window that got through, so the clip count is the window count.
    if len(shorts) != len(kept):
        print(f"   ❌ {len(kept)} windows were detailed but {len(shorts)} clips came back")
        return False

    print(f"   ✅ 1 blocked window ({blocked}) cost the job nothing: "
          f"{len(shorts)} clips from {len(kept)} windows, "
          f"{len(detail_calls)} bisected detail calls, {blocked} dropped")
    print("      clip spans: " + ", ".join(f"{c['start']:.1f}-{c['end']:.1f}" for c in shorts))
    return True


def test_score_bisection():
    """A blocked scoring batch must not write off every window in it."""
    transcript = make_transcript()
    blocked = "window_002"
    result, fake = run_stage([transcript], block_on={"score": blocked})
    if not result or not result.get("shorts"):
        print("   ❌ the pass returned no clips after a blocked scoring batch")
        return False

    windows = main.build_transcript_windows(transcript, 900.0)
    all_ids = [w["id"] for w in windows]
    score_calls = [c for c in fake.calls if c[0] == "score"]
    scored = [wid for kind, ids in fake.served if kind == "score" for wid in ids]
    unscored = [wid for wid in all_ids if wid not in scored]
    if unscored != [blocked]:
        print(f"   ❌ expected only {blocked} to go unscored, got {unscored}")
        return False
    if len(score_calls) < 3:
        print(f"   ❌ the blocked scoring batch was not bisected ({len(score_calls)} call(s))")
        return False
    # The dropped window must fall out of the shortlist on its own merit, and
    # the rest must still be ranked by their real scores.
    detail_served = [ids for kind, ids in fake.served if kind == "detail"]
    shortlisted = {wid for ids in detail_served for wid in ids}
    if blocked in shortlisted:
        print(f"   ❌ {blocked} scored 0 and still reached the detail pass")
        return False
    print(f"   ✅ {len(scored)} of {len(all_ids)} windows still scored over "
          f"{len(score_calls)} bisected calls; only {blocked} was dropped "
          f"(shortlist kept {len(shortlisted)} of the rest)")
    return True


def test_sparse_speech_visual_path():
    """ACCEPTANCE: a sparse-speech input takes the Gemini-vision path."""
    transcript = make_sparse_transcript()
    video = os.path.join(HERE, "demo-openshorts.mp4")
    if not os.path.exists(video):
        print("   ⚠️ no source video to watch — skipped")
        return True

    result, fake = run_stage([transcript], videos=[video])
    kinds = [c[0] for c in fake.calls]
    if not result or not result.get("shorts"):
        print("   ❌ a sparse transcript produced no clips at all")
        return False
    if "visual" not in kinds:
        print(f"   ❌ the vision path was never taken (calls: {kinds})")
        return False
    if "score" in kinds or "detail" in kinds:
        print(f"   ❌ the transcript path was used anyway (calls: {kinds})")
        return False
    if not fake.uploads or fake.uploads[0][0] != "upload":
        print("   ❌ the footage was never uploaded to the Files API")
        return False
    if ("delete", _FakeFile.name) not in fake.uploads:
        print("   ❌ the uploaded file was never deleted")
        return False
    shorts = result["shorts"]
    if any(c.get("video_index") != 0 for c in shorts):
        print("   ❌ vision clips are not attributed to their video")
        return False
    if not result.get("cost_analysis", {}).get("input_tokens"):
        print("   ❌ the vision call's tokens never reached the cost report")
        return False
    print(f"   ✅ sparse transcript -> vision: {len(shorts)} clip(s), "
          f"{fake.uploads[0][1]} uploaded then deleted, cost tracked")
    return True


def test_visual_path_degrades():
    """A vision failure must cost the job nothing — and must not re-upload."""
    transcript = make_sparse_transcript()
    video = os.path.join(HERE, "demo-openshorts.mp4")
    if not os.path.exists(video):
        print("   ⚠️ no source video to watch — skipped")
        return True

    class _BrokenVision(FakeGemini):
        def generate_content(self, model=None, contents=None, config=None):
            prompt = self._prompt_text(contents)
            if "purely by what you SEE" in prompt:
                self.calls.append(("visual", []))
                return _FakeResponse(text="", finish="SAFETY")
            return super().generate_content(model=model, contents=contents, config=config)

    fake = _BrokenVision()
    real_client = main.genai.Client
    main.genai.Client = fake
    try:
        result = main.detect_clips_windowed(
            [transcript], [""], "", "fake-key", videos=[video])
    finally:
        main.genai.Client = real_client

    if result is not None:
        print("   ❌ a blocked video was reported as clips")
        return False
    if len([c for c in fake.calls if c[0] == "visual"]) != 1:
        print(f"   ❌ the vision pass was retried after a block: "
              f"{[c[0] for c in fake.calls]}")
        return False
    print("   ✅ a blocked video is reported as no clips, once, with no job failure")
    return True


def test_live_visual_path(live):
    """End-to-end against the real API: sparse speech -> real clips."""
    if not live:
        print("   ⏭️  skipped (pass --live to run it)")
        return True
    if not os.environ.get("GEMINI_API_KEY"):
        print("   ⏭️  skipped (no GEMINI_API_KEY)")
        return True
    video = os.path.join(HERE, "demo-openshorts.mp4")
    if not os.path.exists(video):
        print("   ⏭️  skipped (no source video)")
        return True

    transcript = make_sparse_transcript()
    result = main.detect_clips_windowed(
        [transcript], [""], "", os.environ["GEMINI_API_KEY"], videos=[video])
    if not result or not result.get("shorts"):
        print("   ❌ the live vision path returned no clips")
        return False
    shorts = result["shorts"]
    duration = 900.0
    bad = [c for c in shorts
           if not (0 <= c["start"] < c["end"] <= duration)]
    if bad:
        print(f"   ❌ {len(bad)} clip(s) outside [0, {duration}]")
        return False
    cost = result.get("cost_analysis", {})
    print(f"   ✅ live {main.CLIP_SELECTION_MODEL} vision pass: {len(shorts)} clips, "
          f"${cost.get('total_cost', 0):.6f}")
    for clip in shorts[:5]:
        print(f"      {clip['start']:8.2f}-{clip['end']:8.2f}  "
              f"{clip.get('viral_hook_text', '')[:40]!r}")
    return True


def test_live_transcript_path(live):
    """End-to-end against the real API: dense speech still clips by transcript.

    The regression guard for this change: the normal two-pass path must behave
    exactly as before (score windows, detail the shortlist, snap, dedupe).
    """
    if not live:
        print("   ⏭️  skipped (pass --live to run it)")
        return True
    if not os.environ.get("GEMINI_API_KEY"):
        print("   ⏭️  skipped (no GEMINI_API_KEY)")
        return True

    transcript = make_transcript(duration=300.0, dense=True)
    words = sum(len(s["text"].split()) for s in transcript["segments"])
    if main.speech_is_sparse(transcript, 300.0):
        print(f"   ❌ the fixture is not dense enough ({words} words) to test the transcript path")
        return False

    result = main.detect_clips_windowed(
        [transcript], [""], "", os.environ["GEMINI_API_KEY"])
    if not result or not result.get("shorts"):
        print("   ❌ the ordinary transcript path returned no clips")
        return False
    shorts = result["shorts"]
    if any(c.get("video_index") != 0 for c in shorts):
        print("   ❌ clips are not attributed to their video")
        return False
    if any(not (0 <= c["start"] < c["end"] <= 300.0) for c in shorts):
        print("   ❌ a clip falls outside the video")
        return False
    if not any(c.get("viral_hook_text") for c in shorts):
        print("   ❌ the copy fields are missing")
        return False
    cost = result.get("cost_analysis", {})
    print(f"   ✅ live {main.CLIP_SELECTION_MODEL} two-pass path: "
          f"{len(shorts)} clips from {words} words, "
          f"${cost.get('total_cost', 0):.6f}, no vision upload")
    for clip in shorts[:3]:
        print(f"      {clip['start']:7.2f}-{clip['end']:7.2f} "
              f"score {clip.get('predicted_score')}  {clip.get('viral_hook_text', '')[:40]!r}")
    return True


TESTS = [
    ("policy-block detection", test_raise_if_blocked),
    ("detail-pass split-bisection", test_detail_bisection),
    ("scoring-pass split-bisection", test_score_bisection),
    ("sparse speech -> visual path", test_sparse_speech_visual_path),
    ("visual path degrades gracefully", test_visual_path_degrades),
    ("live Gemini vision path", test_live_visual_path),
    ("live Gemini transcript path", test_live_transcript_path),
]

_LIVE = {test_live_visual_path, test_live_transcript_path}


def main_():
    live = "--live" in sys.argv
    print("🧪 Verifying Gemini selection robustness (bisection + visual fallback)\n")
    failures = []
    for name, test in TESTS:
        print(f"▶ {name}")
        try:
            ok = test(live) if test in _LIVE else test()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"   ❌ raised {type(e).__name__}: {e}")
            ok = False
        if not ok:
            failures.append(name)
        print()
    if failures:
        print(f"❌ {len(failures)} check(s) failed: {', '.join(failures)}")
        return 1
    print("✨ Verification successful — all checks passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main_())
