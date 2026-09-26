import time
import threading
import cv2
import subprocess
import argparse
import re
import sys
import os
import numpy as np
from tqdm import tqdm
# import whisper (replaced by faster_whisper inside function)
from google import genai
from dotenv import load_dotenv
import json

# Per-scene layout system (item 5): SPLIT/SCREENCAST/INSET/WIDE/PANEL.
import layout_picker
import layout_ranges
import split_layout
import screencast_layout
import panel_layout

# Punch-in emphasis zooms (item 6): audio-envelope push-ins on the TRACK path.
import punch_in

# Hook grounding (item 7): rewrite hook/title from on-screen frames for
# screen-content clips. Never raises; a hook failure keeps the transcript hook.
import hook_grounding

# Windowed clip-selection helpers (ported from upstream): word-snapping,
# scoring windows, overlap dedupe, score-based trimming. Stdlib-only.
from clip_selection import (
    build_transcript_windows, score_batches, shortlist_target,
    clip_count_targets, trim_to_best, dedupe_overlapping,
    snap_clip_to_words, compact_words, clip_duration_bounds,
)

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='google.protobuf')

# Load environment variables
load_dotenv()

# --- Constants ---
ASPECT_RATIO = 9 / 16

# Load helper to build clipping prompt dynamically based on content type
def get_clipping_prompt(input_data_section, user_detection_prompt="", content_type='general', clip_count=None, min_duration=15.0, max_duration=60.0):
    # Sanity-clamp duration bounds: bad input degrades instead of breaking the job
    try:
        min_duration = float(min_duration)
    except (TypeError, ValueError):
        min_duration = 15.0
    try:
        max_duration = float(max_duration)
    except (TypeError, ValueError):
        max_duration = 60.0
    min_duration = min(max(min_duration, 5.0), 175.0)
    max_duration = min(max(max_duration, 10.0), 180.0)
    if max_duration < min_duration + 5.0:
        max_duration = min(180.0, min_duration + 5.0)

    # Load universal rules
    general_rules = ""
    try:
        general_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", "clips_general.txt")
        if os.path.exists(general_path):
            with open(general_path, "r", encoding="utf-8") as f:
                general_rules = f.read().strip()
    except Exception as e:
        print(f"⚠️ Failed to load universal clipping rules: {e}")

    # Load domain-specific rules
    domain_rules = ""
    if content_type and content_type != 'general':
        try:
            domain_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", f"clips_{content_type}.txt")
            if os.path.exists(domain_path):
                with open(domain_path, "r", encoding="utf-8") as f:
                    domain_rules = f.read().strip()
                print(f"✅ Loaded domain clipping rules ({content_type}): {domain_path}")
        except Exception as e:
            print(f"⚠️ Failed to load domain clipping rules for {content_type}: {e}")

    # Explicit directive to reference the dossier if one is present:
    dossier_directive = ""
    if "VISUAL DOSSIER:" in input_data_section:
        dossier_directive = """
⚠️ DOSSIER REFERENCE REQUIREMENT:
A forensic visual dossier is provided in the input data. It contains a ranked list of "Best Clips" or key plays/moments.
You MUST:
1. Cross-reference the transcript with the dossier's identified highlights.
2. Prioritize selecting/refining clips matching the dossier's key events and best clips, unless the transcript reveals a much stronger verbal moment that has no visual component.
3. Ensure the start and end times you output align accurately with the events described in the dossier.
"""

    if clip_count and int(clip_count) > 0:
        target_clause = f"choose EXACTLY {int(clip_count)} of the MOST VIRAL moments (or up to {int(clip_count)} if the video duration is short)"
    else:
        target_clause = "choose the 3–15 MOST VIRAL moments"

    min_d = float(min_duration) if min_duration is not None else 15.0
    max_d = float(max_duration) if max_duration is not None else 60.0

    if abs(min_d - max_d) < 0.1:
        duration_clause = f"Each clip MUST be as close as possible to EXACTLY {min_d:.0f} seconds long (between {max(5.0, min_d - 2.0):.1f} and {max_d + 2.0:.1f} seconds)."
    else:
        duration_clause = f"Each clip MUST be between {min_d:.1f} and {max_d:.1f} seconds long (inclusive)."

    prompt = f"""You are a senior short-form video editor. Read the ENTIRE transcript and visual dossier for the input video(s) to {target_clause} for TikTok/IG Reels/YouTube Shorts. {duration_clause}

⚠️ FFMPEG TIME CONTRACT — STRICT REQUIREMENTS:
- Return timestamps in ABSOLUTE SECONDS from the start of the video (usable in: ffmpeg -ss <start> -to <end> -i <input> ...).
- Only NUMBERS with decimal point, up to 3 decimals (examples: 0, 1.250, 17.350).
- Ensure 0 ≤ start < end ≤ VIDEO_DURATION_SECONDS.
- {duration_clause}
- Prefer starting 0.2–0.4 s BEFORE the hook and ending 0.2–0.4 s AFTER the payoff.
- Use silence moments for natural cuts; never cut in the middle of a word or phrase.
- STRICTLY FORBIDDEN to use time formats other than absolute seconds.

{general_rules}

{domain_rules}

{dossier_directive}

{input_data_section}

{user_detection_prompt}

STRICT EXCLUSIONS:
- No generic intros/outros or purely sponsorship segments unless they contain the hook.
- No clips < {min_d:.1f} s or > {max_d:.1f} s.

OUTPUT — RETURN ONLY VALID JSON (no markdown, no comments). Order clips by predicted performance (best to worst) and include "predicted_score" (0-12, your TOTAL SCORE) on each clip. Write descriptions that are natural to the content type and optimised for each platform:
{{
  "shorts": [
    {{
      "video_index": <0-based index of the video this clip is from, e.g., 0 if only one video is provided>,
      "start": <number in seconds, e.g., 12.340>,
      "end": <number in seconds, e.g., 37.900>,
      "predicted_score": <your TOTAL SCORE for this clip, 0-12>,
      "video_description_for_tiktok": "<description for TikTok oriented to get views>",
      "video_description_for_instagram": "<description for Instagram oriented to get views>",
      "video_title_for_youtube_short": "<title for YouTube Short oriented to get views 100 chars max>",
      "viral_hook_text": "<SHORT punchy text overlay (max 10 words). MUST BE IN THE SAME LANGUAGE AS THE VIDEO TRANSCRIPT. Examples: 'POV: You realized...', 'Did you know?', 'Stop doing this!'>"
    }}
  ]
}}
"""
    return prompt

OVERLAP_TOLERANCE_SECONDS = 1.0  # allow up to 1s of overlap with previous clips

def overlaps_used(start, end, used_ranges, tolerance=OVERLAP_TOLERANCE_SECONDS):
    """Return True if [start,end] overlaps any used range by more than `tolerance` seconds."""
    for (u_start, u_end) in used_ranges:
        overlap = min(end, u_end) - max(start, u_start)
        if overlap > tolerance:
            return True
    return False

def trim_to_used(start, end, used_ranges, tolerance=OVERLAP_TOLERANCE_SECONDS):
    """Trim a clip that overlaps a used range back to the boundary.
    Keeps the non-overlapping head/tail where possible; returns None if the
    clip is fully inside a used range or can't keep the 15s minimum."""
    for (u_start, u_end) in used_ranges:
        overlap = min(end, u_end) - max(start, u_start)
        if overlap <= tolerance:
            continue
        extends_left  = start < u_start   # non-overlapping head before the used range
        extends_right = end > u_end       # non-overlapping tail after the used range
        if extends_left and extends_right:
            # Spans the whole used range: keep the larger non-overlapping side
            left_len  = u_start - start
            right_len = end - u_end
            if left_len >= right_len:
                new_start, new_end = start, u_start
            else:
                new_start, new_end = u_end, end
        elif extends_left:
            # Starts before the used range and ends inside it: keep the head
            new_start, new_end = start, u_start
        elif extends_right:
            # Ends after the used range and starts inside it: keep the tail
            new_start, new_end = u_end, end
        else:
            # Fully inside the used range: nothing to salvage
            return None
        if new_end - new_start >= 15.0:  # keep 15s minimum (matching prompt contract)
            return (new_start, new_end)
        return None
    return (start, end)

def build_used_moments_block(video_index, used_moments):
    """Build a prompt exclusion block for a specific video, if any ranges exist."""
    ranges = [u for u in used_moments if u.get("video_index") == video_index]
    if not ranges:
        return ""
    fmt = ", ".join(f"[{r['start']:.1f}-{r['end']:.1f}]" for r in sorted(ranges, key=lambda r: r['start']))
    return f"""⚠️ ALREADY-CLIPPED MOMENTS EXCLUSION:
The following time ranges for this video were ALREADY clipped in previous jobs: {fmt}
You MUST select DIFFERENT moments. STRICTLY avoid these ranges — do not overlap them by more than 1 second.
These are hard constraints; do not pick moments inside or spanning these ranges.
"""

# YOLO model is lazily loaded on first use to keep transcription-only jobs
# from pulling in torch/ultralytics (large memory cost on small VPS boxes).
YOLO_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt")
_yolo_model = None

# Serializes MediaPipe inference: the detector object is not thread-safe, and
# the screencast layout's full-resolution pass shares it with the frame loop.
DETECT_LOCK = threading.Lock()

def get_yolo_model():
    """Load (and cache) the YOLO model on first call."""
    global _yolo_model
    if _yolo_model is None:
        from ultralytics import YOLO
        _yolo_model = YOLO(YOLO_MODEL_PATH)
    return _yolo_model

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed (lazily imported too)
_face_detection = None

def get_face_detection():
    """Load (and cache) MediaPipe FaceDetection on first call."""
    global _face_detection
    if _face_detection is None:
        import mediapipe as mp
        mp_face_detection = mp.solutions.face_detection
        _face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)
    return _face_detection

class SmoothedCameraman:
    """
    Handles smooth camera movement.
    Simplified Logic: "Heavy Tripod"
    Only moves if the subject leaves the center safe zone.
    Moves slowly and linearly.
    """
    def __init__(self, output_width, output_height, video_width, video_height):
        self.output_width = output_width
        self.output_height = output_height
        self.video_width = video_width
        self.video_height = video_height
        
        # Initial State
        self.current_center_x = video_width / 2
        self.target_center_x = video_width / 2
        
        # Calculate crop dimensions once
        self.crop_height = video_height
        self.crop_width = int(self.crop_height * ASPECT_RATIO)
        if self.crop_width > video_width:
             self.crop_width = video_width
             self.crop_height = int(self.crop_width / ASPECT_RATIO)
             
        # Safe Zone: 20% of the video width
        # As long as the target is within this zone relative to current center, DO NOT MOVE.
        self.safe_zone_radius = self.crop_width * 0.25

    def update_target(self, face_box):
        """
        Updates the target center based on detected face/person.
        """
        if face_box:
            x, y, w, h = face_box
            self.target_center_x = x + w / 2
    
    def get_crop_box(self, force_snap=False):
        """
        Returns the (x1, y1, x2, y2) for the current frame.
        """
        if force_snap:
            self.current_center_x = self.target_center_x
        else:
            diff = self.target_center_x - self.current_center_x
            
            # SIMPLIFIED LOGIC:
            # 1. Is the target outside the safe zone?
            if abs(diff) > self.safe_zone_radius:
                # 2. If yes, move towards it slowly (Linear Speed)
                # Determine direction
                direction = 1 if diff > 0 else -1
                
                # Speed: 2 pixels per frame (Slow pan)
                # If the distance is HUGE (scene change or fast movement), speed up slightly
                if abs(diff) > self.crop_width * 0.5:
                    speed = 15.0 # Fast re-frame
                else:
                    speed = 3.0  # Slow, steady pan
                
                self.current_center_x += direction * speed
                
                # Check if we overshot (prevent oscillation)
                new_diff = self.target_center_x - self.current_center_x
                if (direction == 1 and new_diff < 0) or (direction == -1 and new_diff > 0):
                    self.current_center_x = self.target_center_x
            
            # If inside safe zone, DO NOTHING (Stationary Camera)
                
        # Clamp center
        half_crop = self.crop_width / 2
        
        if self.current_center_x - half_crop < 0:
            self.current_center_x = half_crop
        if self.current_center_x + half_crop > self.video_width:
            self.current_center_x = self.video_width - half_crop
            
        x1 = int(self.current_center_x - half_crop)
        x2 = int(self.current_center_x + half_crop)
        
        x1 = max(0, x1)
        x2 = min(self.video_width, x2)
        
        y1 = 0
        y2 = self.video_height
        
        return x1, y1, x2, y2

class SpeakerTracker:
    """
    Tracks speakers over time to prevent rapid switching and handle temporary obstructions.
    """
    def __init__(self, stabilization_frames=15, cooldown_frames=30):
        self.active_speaker_id = None
        self.speaker_scores = {}  # {id: score}
        self.last_seen = {}       # {id: frame_number}
        self.locked_counter = 0   # How long we've been locked on current speaker
        
        # Hyperparameters
        self.stabilization_threshold = stabilization_frames # Frames needed to confirm a new speaker
        self.switch_cooldown = cooldown_frames              # Minimum frames before switching again
        self.last_switch_frame = -1000
        
        # ID tracking
        self.next_id = 0
        self.known_faces = [] # [{'id': 0, 'center': x, 'last_frame': 123}]

    def get_target(self, face_candidates, frame_number, width):
        """
        Decides which face to focus on.
        face_candidates: list of {'box': [x,y,w,h], 'score': float}
        """
        current_candidates = []
        
        # 1. Match faces to known IDs (simple distance tracking)
        for face in face_candidates:
            x, y, w, h = face['box']
            center_x = x + w / 2
            
            best_match_id = -1
            min_dist = width * 0.15 # Reduced matching radius to avoid jumping in groups
            
            # Try to match with known faces seen recently
            for kf in self.known_faces:
                if frame_number - kf['last_frame'] > 30: # Forgot faces older than 1s (was 2s)
                    continue
                    
                dist = abs(center_x - kf['center'])
                if dist < min_dist:
                    min_dist = dist
                    best_match_id = kf['id']
            
            # If no match, assign new ID
            if best_match_id == -1:
                best_match_id = self.next_id
                self.next_id += 1
            
            # Update known face
            self.known_faces = [kf for kf in self.known_faces if kf['id'] != best_match_id]
            self.known_faces.append({'id': best_match_id, 'center': center_x, 'last_frame': frame_number})
            
            current_candidates.append({
                'id': best_match_id,
                'box': face['box'],
                'score': face['score']
            })

        # 2. Update Scores with decay
        for pid in list(self.speaker_scores.keys()):
             self.speaker_scores[pid] *= 0.85 # Faster decay (was 0.9)
             if self.speaker_scores[pid] < 0.1:
                 del self.speaker_scores[pid]

        # Add new scores
        for cand in current_candidates:
            pid = cand['id']
            # Score is purely based on size (proximity) now that we don't have mouth
            raw_score = cand['score'] / (width * width * 0.05)
            self.speaker_scores[pid] = self.speaker_scores.get(pid, 0) + raw_score

        # 3. Determine Best Speaker
        if not current_candidates:
            # If no one found, maintain last active speaker if cooldown allows
            # to avoid black screen or jump to 0,0
            return None 
            
        best_candidate = None
        max_score = -1
        
        for cand in current_candidates:
            pid = cand['id']
            total_score = self.speaker_scores.get(pid, 0)
            
            # Hysteresis: HUGE Bonus for current active speaker
            if pid == self.active_speaker_id:
                total_score *= 3.0 # Sticky factor
                
            if total_score > max_score:
                max_score = total_score
                best_candidate = cand

        # 4. Decide Switch
        if best_candidate:
            target_id = best_candidate['id']
            
            if target_id == self.active_speaker_id:
                self.locked_counter += 1
                return best_candidate['box']
            
            # New person
            if frame_number - self.last_switch_frame < self.switch_cooldown:
                old_cand = next((c for c in current_candidates if c['id'] == self.active_speaker_id), None)
                if old_cand:
                    return old_cand['box']
            
            self.active_speaker_id = target_id
            self.last_switch_frame = frame_number
            self.locked_counter = 0
            return best_candidate['box']
            
        return None

def detect_face_candidates(frame):
    """
    Returns list of all detected faces using lightweight FaceDetection.
    """
    height, width, _ = frame.shape
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    with DETECT_LOCK:
        results = get_face_detection().process(rgb_frame)
    
    candidates = []
    
    if not results.detections:
        return []
        
    for detection in results.detections:
        bboxC = detection.location_data.relative_bounding_box
        x = int(bboxC.xmin * width)
        y = int(bboxC.ymin * height)
        w = int(bboxC.width * width)
        h = int(bboxC.height * height)
        
        candidates.append({
            'box': [x, y, w, h],
            'score': w * h # Area as score
        })
            
    return candidates

def detect_person_yolo(frame):
    """
    Fallback: Detect largest person using YOLO when face detection fails.
    Returns [x, y, w, h] of the person's 'upper body' approximation.
    """
    # Use the lazily-loaded YOLO model (avoids torch/ultralytics import for transcribe-only runs)
    results = get_yolo_model()(frame, verbose=False, classes=[0]) # class 0 is person
    
    if not results:
        return None
        
    best_box = None
    max_area = 0
    
    for result in results:
        boxes = result.boxes
        for box in boxes:
            x1, y1, x2, y2 = [int(i) for i in box.xyxy[0]]
            w = x2 - x1
            h = y2 - y1
            area = w * h
            
            if area > max_area:
                max_area = area
                # Focus on the top 40% of the person (head/chest) for framing
                # This approximates where the face is if we can't detect it directly
                face_h = int(h * 0.4)
                best_box = [x1, y1, w, face_h]
                
    return best_box

def create_general_frame(frame, output_width, output_height):
    """
    Creates a 'General Shot' frame: 
    - Background: Blurred zoom of original
    - Foreground: Original video scaled to fit width, centered vertically.
    """
    orig_h, orig_w = frame.shape[:2]
    
    # 1. Background (Fill Height)
    # Crop center to aspect ratio
    bg_scale = output_height / orig_h
    bg_w = int(orig_w * bg_scale)
    bg_resized = cv2.resize(frame, (bg_w, output_height))
    
    # Crop center of background
    start_x = (bg_w - output_width) // 2
    if start_x < 0: start_x = 0
    background = bg_resized[:, start_x:start_x+output_width]
    if background.shape[1] != output_width:
        background = cv2.resize(background, (output_width, output_height))
        
    # Blur background
    background = cv2.GaussianBlur(background, (51, 51), 0)
    
    # 2. Foreground (Fit Width)
    scale = output_width / orig_w
    fg_h = int(orig_h * scale)
    foreground = cv2.resize(frame, (output_width, fg_h))
    
    # 3. Overlay
    y_offset = (output_height - fg_h) // 2
    
    # Clone background to avoid modifying it
    final_frame = background.copy()
    final_frame[y_offset:y_offset+fg_h, :] = foreground
    
    return final_frame

def analyze_scenes_strategy(video_path, scenes):
    """
    Analyzes each scene to determine if it should be TRACK (Single person) or GENERAL (Group/Wide).
    Returns list of strategies corresponding to scenes.
    """
    cap = cv2.VideoCapture(video_path)
    strategies = []
    
    if not cap.isOpened():
        return ['TRACK'] * len(scenes)
        
    for start, end in tqdm(scenes, desc="   Analyzing Scenes"):
        # Sample 3 frames (start, middle, end)
        frames_to_check = [
            start.get_frames() + 5,
            int((start.get_frames() + end.get_frames()) / 2),
            end.get_frames() - 5
        ]
        
        face_counts = []
        for f_idx in frames_to_check:
            cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
            ret, frame = cap.read()
            if not ret: continue
            
            # Detect faces
            candidates = detect_face_candidates(frame)
            face_counts.append(len(candidates))
            
        # Decision Logic
        if not face_counts:
            avg_faces = 0
        else:
            avg_faces = sum(face_counts) / len(face_counts)
            
        # Strategy:
        # 0 faces -> GENERAL (Landscape/B-roll)
        # 1 face -> TRACK
        # > 1.2 faces -> GENERAL (Group)
        
        if avg_faces > 1.2 or avg_faces < 0.5:
            strategies.append('GENERAL')
        else:
            strategies.append('TRACK')
            
    cap.release()
    return strategies

def analyze_scenes_layout(video_path, scenes, strategies):
    """Upgrade per-scene TRACK/GENERAL verdicts to richer layouts.

    Runs after analyze_scenes_strategy and only ever upgrades GENERAL scenes
    (plus letting SCREENCAST win over SPLIT where both qualify):

      - SPLIT: two coexisting speakers stacked one above the other — kept
        only when active_speaker (mouth-motion + audio energy) says both
        actually take turns; otherwise the scene stays GENERAL.
      - PANEL: 3-4 coexisting people tiled into a 2x2 grid.
      - SCREENCAST: full-width content stacked over the presenter.
      - WIDE: full-width content with no presenter (blurred bed, no side crop).
      - INSET: a screen recording with a corner webcam (camera_inset): the
        screen keeps its full width and the person stays readable. The
        renderer handles the label (presenter-over-content stack, or the
        full-width bed when no presenter centre survived).

    Heuristic detectors run by default (their modules gate on SPLIT_LAYOUT /
    PANEL_LAYOUT / SCREENCAST_LAYOUT, all default-on). The Gemini
    layout_picker only adds modules when AUTO_LAYOUT=1 (or logs in shadow
    mode) and never overrides an explicit choice.

    Returns (strategies, splits, panels, screencasts) where splits maps scene
    index -> (left_centre, right_centre), panels maps scene index -> [centres],
    and screencasts maps scene index -> ('SCREENCAST'|'WIDE'|'INSET', centre).
    """
    strategies = list(strategies)
    splits = {}
    panels = {}
    screencasts = {}

    try:
        duration = get_video_duration(video_path)
    except Exception:
        duration = 0.0
    try:
        layout_picker.pick_and_apply(video_path, duration or 0.0)
    except Exception as e:
        print(f"   ⚠️ Layout picker failed ({e}) — keeping heuristic routing.")

    try:
        for scene_idx, centres in split_layout.detect_split_scenes(
                video_path, scenes, strategies).items():
            if scene_idx < len(strategies) and strategies[scene_idx] == 'GENERAL':
                strategies[scene_idx] = 'SPLIT'
                splits[scene_idx] = centres
        if splits:
            print(f"   🪞 SPLIT layout on {len(splits)} scene(s)")
    except Exception as e:
        print(f"   ⚠️ Split detection failed ({e}) — keeping base strategies.")

    # Active-speaker gate (active_speaker): geometry alone stacks scenes where
    # one person sits silent for the whole scene. Only keep SPLIT when
    # mouth-motion + audio energy says both actually take turns. Undecided
    # (no attributed windows) or any failure keeps SPLIT — a new signal must
    # never crash a clip job or cost a good stack.
    try:
        import active_speaker
        if splits:
            import cv2 as _cv2spk
            _spk_cap = _cv2spk.VideoCapture(video_path)
            _spk_fps = _spk_cap.get(_cv2spk.CAP_PROP_FPS) or 30.0
            _spk_cap.release()
            for scene_idx in list(splits):
                try:
                    s_f = scenes[scene_idx][0].get_frames()
                    e_f = scenes[scene_idx][1].get_frames()
                    verdicts = active_speaker.verdicts_for_scene(
                        video_path, s_f, e_f, _spk_fps, splits[scene_idx])
                    if not active_speaker.has_evidence(verdicts):
                        continue  # no evidence — keep SPLIT
                    if not active_speaker.is_conversation(verdicts):
                        a, b = active_speaker.shares(verdicts)
                        print(f"   🔇 Scene {scene_idx}: one speaker holds the "
                              f"floor ({max(a, b):.0%}) — not stacking")
                        splits.pop(scene_idx, None)
                        if scene_idx < len(strategies):
                            strategies[scene_idx] = 'GENERAL'
                except Exception as e:
                    print(f"   ⚠️ Speaker gate skipped for scene {scene_idx} "
                          f"({e}) — keeping SPLIT.")
    except Exception as e:
        print(f"   ⚠️ Speaker gate failed ({e}) — keeping base strategies.")

    try:
        for scene_idx, centres in panel_layout.detect_panel_scenes(
                video_path, scenes, strategies).items():
            if scene_idx < len(strategies) and strategies[scene_idx] == 'GENERAL':
                strategies[scene_idx] = 'PANEL'
                panels[scene_idx] = centres
        if panels:
            print(f"   🧩 PANEL layout on {len(panels)} scene(s)")
    except Exception as e:
        print(f"   ⚠️ Panel detection failed ({e}) — keeping base strategies.")

    # SCREENCAST wins over SPLIT on the rare scene that qualifies for both:
    # two faces beside a chart still means the chart is what the shot is about.
    try:
        content_ranges = screencast_layout.detect_content_ranges(
            video_path, duration or 0.0)
    except Exception as e:
        print(f"   ⚠️ Content-range detection failed ({e}) — no screen layouts.")
        content_ranges = []
    if content_ranges:
        try:
            # Webcam-inset check (camera_inset): a screen recording with a
            # corner camera gets INSET so the screen keeps its full width and
            # the person stays readable. Settled geometrically (anchored
            # corner + person detection + stability gate), not by Gemini, and
            # detected once per video. Any failure keeps the SCREENCAST/WIDE
            # routing below — never a crash.
            try:
                import camera_inset
                inset = camera_inset.detect(video_path)
            except Exception as e:
                print(f"   ⚠️ Inset check failed ({e}) — using the screen layouts.")
                inset = None
            if inset:
                print(f"   📹 Webcam inset at {inset}")
            for scene_idx, (plan, centre) in screencast_layout.detect_screencast_scenes(
                    video_path, scenes, strategies, content_ranges).items():
                if scene_idx >= len(strategies):
                    continue
                # An inset beats both screen plans: it is the only routing
                # that can show the screen whole AND the person at a readable
                # size. The per-scene centre is dropped (upstream does the
                # same): the box is video-global, and the renderer falls back
                # to the full-width bed for INSET without a centre.
                if inset:
                    plan, centre = 'INSET', None
                strategies[scene_idx] = plan
                splits.pop(scene_idx, None)
                panels.pop(scene_idx, None)
                if plan in ('SCREENCAST', 'INSET'):
                    screencasts[scene_idx] = (plan, centre)
            n_screen = sum(1 for p, _ in screencasts.values() if p == 'SCREENCAST')
            n_inset = sum(1 for p, _ in screencasts.values() if p == 'INSET')
            n_wide = sum(1 for s in strategies if s == 'WIDE')
            if n_screen:
                print(f"   🖥️ SCREENCAST layout on {n_screen} scene(s)")
            if n_inset:
                print(f"   📹 Camera-inset layout on {n_inset} scene(s)")
            if n_wide:
                print(f"   📐 Full-width layout on {n_wide} scene(s)")
        except Exception as e:
            print(f"   ⚠️ Screencast routing failed ({e}) — keeping base strategies.")

    return strategies, splits, panels, screencasts

def _crop_resize(frame, box, out_w, out_h):
    """Crop ``box`` = (w, h, x, y) from frame and scale to (out_w, out_h)."""
    w, h, x, y = (int(v) for v in box[:4])
    fh, fw = frame.shape[:2]
    x = max(0, min(x, fw - 1))
    y = max(0, min(y, fh - 1))
    w = max(2, min(w, fw - x))
    h = max(2, min(h, fh - y))
    crop = frame[y:y + h, x:x + w]
    return cv2.resize(crop, (out_w, out_h), interpolation=cv2.INTER_AREA)

def _pad_to(frame, out_w, out_h):
    """Bottom/right black pad to (out_w, out_h), mirroring the filtergraphs."""
    h, w = frame.shape[:2]
    if h == out_h and w == out_w:
        return frame
    canvas = np.zeros((out_h, out_w, 3), dtype=frame.dtype)
    canvas[:min(h, out_h), :min(w, out_w)] = frame[:out_h, :out_w]
    return canvas

def render_split_frame(frame, left_centre, right_centre, out_w, out_h,
                       orig_w, orig_h):
    """NumPy equivalent of split_layout.split_filtergraph: two speaker crops
    stacked, left-hand speaker on top."""
    top_box = split_layout.split_geometry(orig_w, orig_h, out_w, out_h, left_centre)
    bot_box = split_layout.split_geometry(orig_w, orig_h, out_w, out_h, right_centre)
    half_h = top_box[4]
    top = _crop_resize(frame, top_box, out_w, half_h)
    bot = _crop_resize(frame, bot_box, out_w, half_h)
    return _pad_to(np.vstack([top, bot]), out_w, out_h)

def render_screencast_frame(frame, face_centre, out_w, out_h, orig_w, orig_h):
    """NumPy equivalent of screencast_layout.screencast_filtergraph:
    full-width content above, face-framed speaker below."""
    content_h, speaker_h = screencast_layout.content_bands(orig_w, orig_h, out_w, out_h)
    content = cv2.resize(frame, (out_w, content_h), interpolation=cv2.INTER_AREA)
    spk_box = screencast_layout.speaker_crop(orig_w, orig_h, out_w, speaker_h, face_centre)
    speaker = _crop_resize(frame, spk_box, out_w, speaker_h)
    return _pad_to(np.vstack([content, speaker]), out_w, out_h)

def render_panel_frame(frame, centres, out_w, out_h, orig_w, orig_h):
    """NumPy equivalent of panel_layout.panel_filtergraph: 3-4 people tiled
    into a 2x2 grid (a trio's fourth cell holds the letterboxed wide shot)."""
    cols, rows, tile_w, tile_h = panel_layout.tile_grid(len(centres), out_w, out_h)
    gaps = panel_layout.neighbour_gaps(centres)
    tiles = []
    for centre, gap in zip(centres, gaps):
        box = panel_layout.panel_geometry(orig_w, orig_h, tile_w, tile_h, centre,
                                           neighbour_gap=gap)
        tiles.append(_crop_resize(frame, box, tile_w, tile_h))
    if len(tiles) == 3:
        fh, fw = frame.shape[:2]
        wide_h = max(2, int(round(tile_w * fh / float(fw))) - (int(round(tile_w * fh / float(fw))) % 2))
        if wide_h > tile_h:
            wide_h = tile_h - (tile_h % 2)
        wide = cv2.resize(frame, (tile_w, wide_h), interpolation=cv2.INTER_AREA)
        cell = np.zeros((tile_h, tile_w, 3), dtype=frame.dtype)
        y0 = (tile_h - wide_h) // 2
        cell[y0:y0 + wide_h] = wide
        tiles.append(cell)
    top = np.hstack(tiles[0:2])
    bot = np.hstack(tiles[2:4])
    return _pad_to(np.vstack([top, bot]), out_w, out_h)

def render_inset_frame(frame, face_centre, out_w, out_h, orig_w, orig_h):
    """INSET fallback without the webcam-inset detector: a known presenter
    stacks over the full-width screen (like SCREENCAST), otherwise the
    content keeps its full width over a blurred bed (like WIDE)."""
    if face_centre is not None:
        return render_screencast_frame(frame, face_centre, out_w, out_h, orig_w, orig_h)
    return create_general_frame(frame, out_w, out_h)

def detect_scenes(video_path):
    """Detect scenes via the scene_detection module: TransNetV2 neural
    shot-boundary detector by default, with automatic fallback to the
    legacy PySceneDetect ContentDetector. SCENE_ENGINE=pyscenedetect
    forces the legacy engine."""
    from scene_detection import detect_scenes as _detect
    return _detect(video_path)

def get_video_resolution(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise IOError(f"Could not open video file {video_path}")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()
    return width, height


def sanitize_filename(filename):
    """Remove invalid characters from filename."""
    filename = re.sub(r'[<>:"/\\|?*#]', '', filename)
    filename = filename.replace(' ', '_')
    return filename[:100]


def download_youtube_video(url, output_dir="."):
    """
    Downloads a YouTube video using yt-dlp.
    Returns the path to the downloaded video and the video title.
    """
    import yt_dlp
    print(f"🔍 Debug: yt-dlp version: {yt_dlp.version.__version__}")
    print("📥 Downloading video from YouTube...")
    step_start_time = time.time()

    cookies_path = '/app/cookies.txt'
    cookies_env = os.environ.get("YOUTUBE_COOKIES")
    if cookies_env:
        print("🍪 Found YOUTUBE_COOKIES env var, creating cookies file inside container...")
        try:
            with open(cookies_path, 'w') as f:
                f.write(cookies_env)
            if os.path.exists(cookies_path):
                 print(f"   Debug: Cookies file created. Size: {os.path.getsize(cookies_path)} bytes")
                 with open(cookies_path, 'r') as f:
                     content = f.read(100)
                     print(f"   Debug: First 100 chars of cookie file: {content}")
        except Exception as e:
            print(f"⚠️ Failed to write cookies file: {e}")
            cookies_path = None
    else:
        cookies_path = None
        print("⚠️ YOUTUBE_COOKIES env var not found.")

    # Fall back to a bind-mounted cookies file when YOUTUBE_COOKIES is unset.
    if cookies_path is None and os.path.exists('/app/youtube_cookies.txt'):
        cookies_path = '/app/youtube_cookies.txt'
        print(f"🍪 Found cookies on disk at {cookies_path} (size: {os.path.getsize(cookies_path)} bytes)")

        # Parse Netscape cookie file and warn about upcoming expiry of auth cookies.
        try:
            latest_expiry = 0
            found_auth_cookie = False
            target_names = {'__Secure-1PSID', '__Secure-3PSID', 'SID', 'LOGIN_INFO'}
            with open('/app/youtube_cookies.txt', 'r') as cf:
                for raw_line in cf:
                    line = raw_line.strip()
                    if not line or line.startswith('#'):
                        continue
                    fields = line.split('\t')
                    if len(fields) < 5:
                        continue
                    name = fields[0]
                    if name not in target_names:
                        continue
                    try:
                        expiry = int(fields[4])
                    except (TypeError, ValueError):
                        continue
                    found_auth_cookie = True
                    if expiry > latest_expiry:
                        latest_expiry = expiry
            if found_auth_cookie and latest_expiry > 0:
                days_left = int((latest_expiry - time.time()) // 86400)
                if days_left < 0:
                    days_left = 0
                print(f"⚠️ YouTube cookies expire in {days_left} days")
        except Exception:
            # Malformed cookies file must never crash the download.
            pass

    # bgutil-ytdlp-pot-provider HTTP sidecar URL (defaults to docker-compose service name).
    bgutil_url = os.environ.get('BGUTIL_URL', 'http://bgutil:4416')
    print(f"🔧 PO Token provider: {bgutil_url}")

    # Common yt-dlp options to work around YouTube bot detection.
    # extractor_args tries multiple player clients in order; tv_embed / android
    # avoid the OAuth/PO-token checks that block server IPs.
    _COMMON_YDL_OPTS = {
        'quiet': False,
        'verbose': True,
        'no_warnings': False,
        'cookiefile': cookies_path if cookies_path else None,
        'socket_timeout': 30,
        'retries': 10,
        'fragment_retries': 10,
        'nocheckcertificate': True,
        'cachedir': False,
        'js_runtimes': ['node'],
        'remote_components': ['ejs:github'],
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'mweb', 'tv_simply', 'ios'],
                'player_skip': ['webpage', 'configs'],
            },
            'youtubepot-bgutilhttp': {
                'base_url': bgutil_url,
            },
        },
        'http_headers': {
            'User-Agent': (
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                'AppleWebKit/537.36 (KHTML, like Gecko) '
                'Chrome/120.0.0.0 Safari/537.36'
            ),
        },
    }

    with yt_dlp.YoutubeDL(_COMMON_YDL_OPTS) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            video_title = info.get('title', 'youtube_video')
            sanitized_title = sanitize_filename(video_title)
        except Exception as e:
            # Force print to stderr/stdout immediately so it's captured before crash
            import sys
            import traceback
            
            # Print minimal error first to ensure something gets out
            print("🚨 YOUTUBE DOWNLOAD ERROR 🚨", file=sys.stderr)
            
            error_msg = f"""
            
❌ ================================================================= ❌
❌ FATAL ERROR: YOUTUBE DOWNLOAD FAILED
❌ ================================================================= ❌
            
REASON: YouTube has blocked the download request (Error 429/Unavailable).
        This is likely a temporary IP ban on this server.

👇 SOLUTION FOR USER 👇
---------------------------------------------------------------------
1. Download the video manually to your computer.
2. Use the 'Upload Video' tab in this app to process it.
---------------------------------------------------------------------

Technical Details: {str(e)}
            """
            # Print to both streams to ensure capture
            print(error_msg, file=sys.stdout)
            print(error_msg, file=sys.stderr)
            
            # Force flush
            sys.stdout.flush()
            sys.stderr.flush()
            
            # Wait a split second to allow buffer to drain before raising
            time.sleep(0.5)
            
            raise e
    
    output_template = os.path.join(output_dir, f'{sanitized_title}.%(ext)s')
    expected_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
    if os.path.exists(expected_file):
        os.remove(expected_file)
        print(f"🗑️  Removed existing file to re-download with H.264 codec")
    
    ydl_opts = {
        **_COMMON_YDL_OPTS,
        'format': 'bestvideo[vcodec^=avc1][ext=mp4]+bestaudio[ext=m4a]/bestvideo[vcodec^=avc1]+bestaudio/best[ext=mp4]/best',
        'outtmpl': output_template,
        'merge_output_format': 'mp4',
        'overwrites': True,
    }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
    
    downloaded_file = os.path.join(output_dir, f'{sanitized_title}.mp4')
    
    if not os.path.exists(downloaded_file):
        for f in os.listdir(output_dir):
            if f.startswith(sanitized_title) and f.endswith('.mp4'):
                downloaded_file = os.path.join(output_dir, f)
                break
    
    step_end_time = time.time()
    print(f"✅ Video downloaded in {step_end_time - step_start_time:.2f}s: {downloaded_file}")
    
    return downloaded_file, sanitized_title

def process_video_to_vertical(input_video, final_output_video, crop_overrides=None):
    """
    Core logic to convert horizontal video to vertical using scene detection and Active Speaker Tracking (MediaPipe).
    ``crop_overrides`` maps scene index -> crop centre fraction (or {"x": f, "y": f})
    for scenes the user framed by hand. The CUT is never touched.
    """
    script_start_time = time.time()
    
    # Define temporary file paths based on the output name
    base_name = os.path.splitext(final_output_video)[0]
    temp_video_output = f"{base_name}_temp_video.mp4"
    temp_audio_output = f"{base_name}_temp_audio.aac"
    
    # Clean up previous temp files if they exist
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    if os.path.exists(final_output_video): os.remove(final_output_video)

    print(f"🎬 Processing clip: {input_video}")
    print("   Step 1: Detecting scenes...")
    scenes, fps = detect_scenes(input_video)
    
    if not scenes:
        print("   ❌ No scenes were detected. Using full video as one scene.")
        # If scene detection fails or finds nothing, treat whole video as one scene
        cap = cv2.VideoCapture(input_video)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        cap.release()
        from scenedetect import FrameTimecode
        scenes = [(FrameTimecode(0, fps), FrameTimecode(total_frames, fps))]

    print(f"   ✅ Found {len(scenes)} scenes.")

    print("\n   🧠 Step 2: Preparing Active Tracking...")
    original_width, original_height = get_video_resolution(input_video)
    
    OUTPUT_HEIGHT = original_height
    OUTPUT_WIDTH = int(OUTPUT_HEIGHT * ASPECT_RATIO)
    if OUTPUT_WIDTH % 2 != 0:
        OUTPUT_WIDTH += 1

    # Initialize Cameraman
    cameraman = SmoothedCameraman(OUTPUT_WIDTH, OUTPUT_HEIGHT, original_width, original_height)
    
    # --- New Strategy: Per-Scene Analysis ---
    print("\n   🤖 Step 3: Analyzing Scenes for Strategy (Single vs Group)...")
    scene_strategies = analyze_scenes_strategy(input_video, scenes)
    # scene_strategies is a list of 'TRACK' or 'General' corresponding to scenes

    print("\n   🎛️ Step 3b: Upgrading Scenes to Layouts (SPLIT/PANEL/SCREENCAST/WIDE)...")
    scene_strategies, split_scenes, panel_scenes, screencast_scenes = analyze_scenes_layout(
        input_video, scenes, scene_strategies)

    # Per-scene render plans: static crop boxes are precomputed once (they
    # depend only on the source geometry and the detected centres, not on the
    # frame content), so the frame loop just crops/resizes/stacks.
    scene_plans = []
    for i, strategy in enumerate(scene_strategies):
        plan = (strategy, None)
        try:
            if strategy == 'SPLIT' and i in split_scenes:
                left, right = split_scenes[i]
                top_box = split_layout.split_geometry(
                    original_width, original_height, OUTPUT_WIDTH, OUTPUT_HEIGHT, left)
                bot_box = split_layout.split_geometry(
                    original_width, original_height, OUTPUT_WIDTH, OUTPUT_HEIGHT, right)
                plan = ('SPLIT', (top_box, bot_box))
            elif strategy == 'PANEL' and i in panel_scenes:
                centres = panel_scenes[i]
                cols, rows, tile_w, tile_h = panel_layout.tile_grid(
                    len(centres), OUTPUT_WIDTH, OUTPUT_HEIGHT)
                gaps = panel_layout.neighbour_gaps(centres)
                boxes = [panel_layout.panel_geometry(
                    original_width, original_height, tile_w, tile_h, c,
                    neighbour_gap=g) for c, g in zip(centres, gaps)]
                plan = ('PANEL', (tile_w, tile_h, boxes))
            elif strategy in ('SCREENCAST', 'INSET') and i in screencast_scenes:
                _plan, centre = screencast_scenes[i]
                if centre is not None:
                    content_h, speaker_h = screencast_layout.content_bands(
                        original_width, original_height, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                    spk_box = screencast_layout.speaker_crop(
                        original_width, original_height, OUTPUT_WIDTH, speaker_h, centre)
                    plan = (strategy, (content_h, speaker_h, spk_box))
                else:
                    plan = (strategy, None)
        except Exception as e:
            print(f"   ⚠️ Layout plan failed for scene {i} ({e}) — using {strategy} cameraman path.")
        scene_plans.append(plan)
    
    print("\n   ✂️ Step 4: Processing video frames...")
    
    command = [
        'ffmpeg', '-y', '-f', 'rawvideo', '-vcodec', 'rawvideo',
        '-s', f'{OUTPUT_WIDTH}x{OUTPUT_HEIGHT}', '-pix_fmt', 'bgr24',
        '-r', str(fps), '-i', '-', '-c:v', 'libx264',
        '-pix_fmt', 'yuv420p', '-preset', 'fast', '-crf', '23', '-an', temp_video_output
    ]

    ffmpeg_process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

    cap = cv2.VideoCapture(input_video)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Punch-in zooms (TRACK path only): audio-envelope emphasis beats for
    # the whole clip, as a per-frame zoom array on the clip timeline
    # starting at 0. Multi-region layouts (SPLIT/PANEL/SCREENCAST/WIDE)
    # skip it in the frame loop below. Any failure degrades to no
    # punches — it never fails the render.
    try:
        _punch_fps = float(fps) or 30.0
        _clip_duration = total_frames / _punch_fps if _punch_fps > 0 else 0.0
        _punch_beats = punch_in.emphasis_times(input_video, _clip_duration)
        _punch_zooms = punch_in.zoom_curve(total_frames, _punch_fps,
                                            _punch_beats)
        if _punch_beats:
            print(f"   🔍 Punch-in on {len(_punch_beats)} beat(s)")
    except Exception as e:
        print(f"   ⚠️ Punch-in disabled ({e})")
        _punch_zooms = []

    frame_number = 0
    current_scene_index = 0
    
    # Pre-calculate scene boundaries
    scene_boundaries = []
    for s_start, s_end in scenes:
        scene_boundaries.append((s_start.get_frames(), s_end.get_frames()))

    # Manual crop overrides: scene index -> crop CENTRE as a fraction of the
    # source width, for scenes the user framed by hand. Parsed once here;
    # enforced per-frame in the loop below as a locked TRACK window (a manual
    # choice beats the automatic strategy, including GENERAL blur). Runs on
    # the source path (reframe) so the canonical file's framing can be
    # overridden per scene. Unknown indices and malformed values are skipped
    # silently — a stale editor tab must never fail the render.
    manual_centres = {}
    if crop_overrides:
        try:
            for raw_idx, value in crop_overrides.items():
                try:
                    idx = int(raw_idx)
                except (TypeError, ValueError):
                    continue
                if not (0 <= idx < len(scene_boundaries)):
                    continue
                try:
                    if isinstance(value, dict):
                        fraction = float(value.get("x", 0.5))
                    else:
                        fraction = float(value)
                except (TypeError, ValueError):
                    continue
                manual_centres[idx] = max(0.0, min(1.0, fraction))
        except Exception:
            pass
    if manual_centres:
        print(f"   ✋ Manual framing on {len(manual_centres)} scene(s)")

    # Global tracker for single-person shots
    speaker_tracker = SpeakerTracker(cooldown_frames=30)

    with tqdm(total=total_frames, desc="   Processing", file=sys.stdout) as pbar:
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret:
                break

            # Update Scene Index
            if current_scene_index < len(scene_boundaries):
                start_f, end_f = scene_boundaries[current_scene_index]
                if frame_number >= end_f and current_scene_index < len(scene_boundaries) - 1:
                    current_scene_index += 1
            
            # Determine Strategy for current frame based on scene
            current_strategy = scene_strategies[current_scene_index] if current_scene_index < len(scene_strategies) else 'TRACK'
            current_plan = scene_plans[current_scene_index] if current_scene_index < len(scene_plans) else ('TRACK', None)

            # Apply Strategy
            if current_scene_index in manual_centres:
                # Hand-framed scene: locked TRACK window at the override
                # centre, ignoring the face tracker and any multi-region
                # layout plan. Never raises: fall back to the automatic path.
                try:
                    frac = manual_centres[current_scene_index]
                    cw = cameraman.crop_width
                    if cw >= original_width:
                        x1, x2 = 0, original_width
                    else:
                        max_x = original_width - cw
                        xc = frac * original_width
                        xc = max(cw / 2, min(original_width - cw / 2, xc))
                        x1 = int(round(xc - cw / 2))
                        x1 = max(0, min(x1, max_x))
                        x2 = x1 + cw
                    cameraman.current_center_x = x1 + (x2 - x1) / 2
                    cameraman.target_center_x = cameraman.current_center_x
                    y1, y2 = 0, original_height
                    if _punch_zooms and frame_number < len(_punch_zooms):
                        x1, y1, x2, y2 = punch_in.zoom_box(
                            x1, y1, x2, y2, _punch_zooms[frame_number],
                            original_width, original_height)
                    if y2 > y1 and x2 > x1:
                        cropped = frame[y1:y2, x1:x2]
                        output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                    else:
                        output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                except Exception as e:
                    print(f"   ⚠️ Manual crop failed on scene {current_scene_index} ({e}) — using auto framing.")
                    manual_centres.pop(current_scene_index, None)
                    candidates = detect_face_candidates(frame)
                    target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                    if target_box:
                        cameraman.update_target(target_box)
                    x1, y1, x2, y2 = cameraman.get_crop_box(force_snap=False)
                    if y2 > y1 and x2 > x1:
                        cropped = frame[y1:y2, x1:x2]
                        output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                    else:
                        output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
            elif current_strategy == 'SPLIT' and current_plan[1] is not None:
                # Two speakers stacked one above the other (split filtergraph geometry)
                top_box, bot_box = current_plan[1]
                half_h = top_box[4]
                top = _crop_resize(frame, top_box, OUTPUT_WIDTH, half_h)
                bot = _crop_resize(frame, bot_box, OUTPUT_WIDTH, half_h)
                output_frame = _pad_to(np.vstack([top, bot]), OUTPUT_WIDTH, OUTPUT_HEIGHT)
                cameraman.current_center_x = original_width / 2
                cameraman.target_center_x = original_width / 2

            elif current_strategy == 'PANEL' and current_plan[1] is not None:
                # 3-4 people tiled into a 2x2 grid (panel filtergraph geometry)
                tile_w, tile_h, boxes = current_plan[1]
                tiles = [_crop_resize(frame, b, tile_w, tile_h) for b in boxes]
                if len(tiles) == 3:
                    fh, fw = frame.shape[:2]
                    wide_h = max(2, int(round(tile_w * fh / float(fw))))
                    wide_h -= wide_h % 2
                    if wide_h > tile_h:
                        wide_h = tile_h - (tile_h % 2)
                    wide = cv2.resize(frame, (tile_w, wide_h), interpolation=cv2.INTER_AREA)
                    cell = np.zeros((tile_h, tile_w, 3), dtype=frame.dtype)
                    y0 = (tile_h - wide_h) // 2
                    cell[y0:y0 + wide_h] = wide
                    tiles.append(cell)
                output_frame = _pad_to(np.vstack([np.hstack(tiles[0:2]),
                                                  np.hstack(tiles[2:4])]),
                                       OUTPUT_WIDTH, OUTPUT_HEIGHT)
                cameraman.current_center_x = original_width / 2
                cameraman.target_center_x = original_width / 2

            elif current_strategy in ('SCREENCAST', 'INSET') and current_plan[1] is not None:
                # Full-width content above, face-framed speaker below
                content_h, speaker_h, spk_box = current_plan[1]
                content = cv2.resize(frame, (OUTPUT_WIDTH, content_h),
                                     interpolation=cv2.INTER_AREA)
                speaker = _crop_resize(frame, spk_box, OUTPUT_WIDTH, speaker_h)
                output_frame = _pad_to(np.vstack([content, speaker]),
                                       OUTPUT_WIDTH, OUTPUT_HEIGHT)
                cameraman.current_center_x = original_width / 2
                cameraman.target_center_x = original_width / 2

            elif current_strategy in ('GENERAL', 'WIDE') or (
                    current_strategy in ('SCREENCAST', 'INSET') and current_plan[1] is None):
                # "Plano General" -> Blur Background + Fit Width.
                # WIDE is the same bed with side-cropping disabled, which is
                # exactly what create_general_frame does (fit full width).
                # SCREENCAST/INSET without a presenter centre fall back here too.
                output_frame = create_general_frame(frame, OUTPUT_WIDTH, OUTPUT_HEIGHT)
                
                # Reset cameraman/tracker so they don't drift while inactive
                cameraman.current_center_x = original_width / 2
                cameraman.target_center_x = original_width / 2
                
            else:
                # "Single Speaker" -> Track & Crop
                
                # Detect every 2nd frame for performance
                if frame_number % 2 == 0:
                    candidates = detect_face_candidates(frame)
                    target_box = speaker_tracker.get_target(candidates, frame_number, original_width)
                    if target_box:
                        cameraman.update_target(target_box)
                    else:
                        person_box = detect_person_yolo(frame)
                        if person_box:
                            cameraman.update_target(person_box)

                # Snap camera on scene change to avoid panning from previous scene position
                is_scene_start = (frame_number == scene_boundaries[current_scene_index][0])
                
                x1, y1, x2, y2 = cameraman.get_crop_box(force_snap=is_scene_start)

                # Punch-in: push toward the subject on emphasis beats by
                # scaling the tracked crop box about its centre. Other
                # layouts (SPLIT/PANEL/SCREENCAST/WIDE/GENERAL above) skip
                # this — zooming a composed grid makes no sense.
                if _punch_zooms and frame_number < len(_punch_zooms):
                    x1, y1, x2, y2 = punch_in.zoom_box(
                        x1, y1, x2, y2, _punch_zooms[frame_number],
                        original_width, original_height)

                # Crop
                if y2 > y1 and x2 > x1:
                    cropped = frame[y1:y2, x1:x2]
                    output_frame = cv2.resize(cropped, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
                else:
                    output_frame = cv2.resize(frame, (OUTPUT_WIDTH, OUTPUT_HEIGHT))

            ffmpeg_process.stdin.write(output_frame.tobytes())
            frame_number += 1
            pbar.update(1)
    
    ffmpeg_process.stdin.close()
    stderr_output = ffmpeg_process.stderr.read().decode()
    ffmpeg_process.wait()
    cap.release()

    if ffmpeg_process.returncode != 0:
        print("\n   ❌ FFmpeg frame processing failed.")
        print("   Stderr:", stderr_output)
        return False

    print("\n   🔊 Step 5: Extracting audio...")
    audio_extract_command = [
        'ffmpeg', '-y', '-i', input_video, '-vn', '-acodec', 'copy', temp_audio_output
    ]
    try:
        subprocess.run(audio_extract_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    except subprocess.CalledProcessError:
        print("\n   ❌ Audio extraction failed (maybe no audio?). Proceeding without audio.")
        pass

    print("\n   ✨ Step 6: Merging...")
    if os.path.exists(temp_audio_output):
        merge_command = [
            'ffmpeg', '-y', '-i', temp_video_output, '-i', temp_audio_output,
            '-c:v', 'copy', '-c:a', 'copy', final_output_video
        ]
    else:
         merge_command = [
            'ffmpeg', '-y', '-i', temp_video_output,
            '-c:v', 'copy', final_output_video
        ]
        
    try:
        subprocess.run(merge_command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        print(f"   ✅ Clip saved to {final_output_video}")
    except subprocess.CalledProcessError as e:
        print("\n   ❌ Final merge failed.")
        print("   Stderr:", e.stderr.decode())
        return False

    # Tell the caption pass which stretches use which layout (see
    # layout_ranges): times are in the CLIP's own timeline, which is also the
    # timeline captions are laid on.
    try:
        layout_fps = float(fps)
        layout_list = []
        for i, (s_f, e_f) in enumerate(scene_boundaries):
            s = max(0, s_f) / layout_fps
            e = min(e_f, frame_number) / layout_fps
            strategy = scene_strategies[i] if i < len(scene_strategies) else 'TRACK'
            if i in manual_centres:
                strategy = 'TRACK'  # hand-framed scenes render as locked TRACK
            if e > s:
                layout_list.append((s, e, strategy))
        layout_ranges.write(final_output_video, layout_list)
    except Exception as e:
        print(f"   ⚠️ Could not write layout sidecar ({e})")

    # Clean up temp files
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    
    return True

def transcribe_video(video_path, duration=None):
    """Transcribe via transcribe_backends (TRANSCRIBE_BACKEND=parakeet|whisper).

    Keeps this function's contract: {'text', 'segments', 'language'} plus the
    PROGRESS:{pct} markers the API status poller consumes. Backend selection
    and all fallback logic live in transcribe_backends.transcribe_media.
    """
    from transcribe_backends import transcribe_media
    backend = os.environ.get("TRANSCRIBE_BACKEND", "whisper").strip().lower()
    label = "Parakeet" if backend == "parakeet" else "Faster-Whisper (CPU Optimized)"
    print(f"🎙️  Transcribing video with {label}...")
    return transcribe_media(video_path, duration=duration)

def get_viral_clips(transcript_result, video_duration, content_type='general'):
    print("🤖  Analyzing with Gemini...")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in environment variables.")
        return None


    client = genai.Client(api_key=api_key)
    
    # We use gemini-3.8-flash (verified available via API 2026-09-26).
    model_name = 'gemini-3.8-flash'
    
    print(f"🤖  Initializing Gemini with model: {model_name}")

    # Extract words
    words = []
    for segment in transcript_result['segments']:
        for word in segment.get('words', []):
            words.append({
                'w': word['word'],
                's': word['start'],
                'e': word['end']
            })
    words = compact_words(words)  # round timestamps: full float precision wastes tokens

    input_data_section = f"VIDEO_DURATION_SECONDS: {video_duration}\n"
    input_data_section += f"TRANSCRIPT_TEXT:\n{json.dumps(transcript_result['text'])}\n"
    input_data_section += f"WORDS_JSON:\n{json.dumps(words)}\n"

    prompt = get_clipping_prompt(input_data_section, content_type=content_type)

    try:
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        # --- Cost Calculation ---
        try:
            usage = response.usage_metadata
            if usage:
                # Gemini 3.8 Flash Pricing (intro rate thru Dec 31 2026; doubles Jan 1 2027)
                # Input: $0.75 per 1M tokens
                # Output: $3.75 per 1M tokens
                
                input_price_per_million = 0.75
                output_price_per_million = 3.75
                
                prompt_tokens = usage.prompt_token_count
                output_tokens = usage.candidates_token_count
                
                input_cost = (prompt_tokens / 1_000_000) * input_price_per_million
                output_cost = (output_tokens / 1_000_000) * output_price_per_million
                total_cost = input_cost + output_cost
                
                cost_analysis = {
                    "input_tokens": prompt_tokens,
                    "output_tokens": output_tokens,
                    "input_cost": input_cost,
                    "output_cost": output_cost,
                    "total_cost": total_cost,
                    "model": model_name
                }

                print(f"💰 Token Usage ({model_name}):")
                print(f"   - Input Tokens: {prompt_tokens} (${input_cost:.6f})")
                print(f"   - Output Tokens: {output_tokens} (${output_cost:.6f})")
                print(f"   - Total Estimated Cost: ${total_cost:.6f}")
                
        except Exception as e:
            print(f"⚠️ Could not calculate cost: {e}")
            cost_analysis = None
        # ------------------------

        # Clean response if it contains markdown code blocks
        text = response.text
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        result_json = json.loads(text)
        # Snap clip boundaries onto word boundaries: cuts land in pauses, not mid-word
        lo, hi = clip_duration_bounds()
        for clip in result_json.get('shorts', []):
            s, e = snap_clip_to_words(clip.get('start', 0.0), clip.get('end', 0.0),
                                      words, video_duration,
                                      min_duration=lo, max_duration=hi)
            clip['start'], clip['end'] = s, e
        if cost_analysis:
            result_json['cost_analysis'] = cost_analysis
            
        return result_json
    except Exception as e:
        print(f"❌ Gemini Error: {e}")
        return None

def generate_dossier(video_path, api_key, content_type='general', custom_prompt=''):
    print("📤 Uploading video to Gemini File API...")
    client = genai.Client(api_key=api_key)
    file_upload = client.files.upload(file=video_path)
    print("⏳ Waiting for video processing by Gemini...")
    while True:
        file_info = client.files.get(name=file_upload.name)
        if file_info.state == "ACTIVE":
            print("✅ Video processed and ready.")
            break
        elif file_info.state == "FAILED":
            raise Exception("Video processing failed by Gemini.")
        time.sleep(2)
        
    try:
        prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts", f"dossier_{content_type}.txt")
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                structure_text = f.read().strip()
            print(f"✅ Loaded domain dossier rules ({content_type}): {prompt_path}")
        else:
            structure_text = """## Overview
## Timeline (with [MM:SS–MM:SS] format)
## Key Moments / Reveals
## Participants / People
## Quotes
## Best Clips (ranked)
## Ambiguities
## Editor Notes (hook, cold open, short-form potential)"""
    except Exception as e:
        print(f"⚠️ Failed to load dossier structure for {content_type}: {e}")
        structure_text = """## Overview
## Timeline (with [MM:SS–MM:SS] format)
## Key Moments / Reveals
## Participants / People
## Quotes
## Best Clips (ranked)
## Ambiguities
## Editor Notes (hook, cold open, short-form potential)"""

    user_instruction_section = ""
    if custom_prompt:
        user_instruction_section = f"""
ADDITIONAL USER INSTRUCTIONS — APPLY THESE TO THE DOSSIER:
{custom_prompt.strip()}

When these instructions conflict with the default structure above, prioritize the user instructions for relevance, but still follow the required output format.
"""

    prompt = f"""Analyze this video like a forensic content assistant.

Goal: Produce a complete Markdown dossier so another AI can generate 
clipping scripts without watching the source.

Output requirements:
- Be exhaustive, but concise
- Use timestamps for every meaningful event
- Identify all people visible or mentioned
- Separate confirmed identities from inferred identities
- Mark uncertainty explicitly
- Include any announcement, reveal, or key moment
- Include only facts supported by the video
- Do not hallucinate names, scores, or outcomes
{user_instruction_section}
Structure:
{structure_text}"""

    print("🤖 Generating forensic analysis dossier from Gemini...")
    try:
        response = client.models.generate_content(
            model='gemini-3.8-flash',
            contents=[file_upload, prompt]
        )
        dossier_text = response.text
        try:
            client.files.delete(name=file_upload.name)
            print("🗑️ Cleaned up file from Gemini File API.")
        except Exception as e:
            print(f"⚠️ Could not delete Gemini File API file: {e}")
        return dossier_text
    except Exception as e:
        print(f"❌ Error generating dossier: {e}")
        try:
            client.files.delete(name=file_upload.name)
        except Exception:
            pass
        raise e

def get_video_duration(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return 0.0
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps > 0 else 0.0
    cap.release()
    return duration

def detect_clips_stage2(transcripts, dossiers, custom_prompt, api_key, content_type='general', used_moments=None, clip_count=None, min_duration=15.0, max_duration=60.0):
    # PINNED FALLBACK — intentionally unreferenced. The windowed two-pass
    # detector (detect_clips_windowed) is the live clip path; this older
    # per-video detector is kept as a known-good rollback if the windowed
    # path ever misbehaves. Do not delete; do not call without a reason.
    """Process each video as its own isolated Gemini API call.

    Each video = one upload + one clip-detection call. Multi-video jobs
    accumulate results across calls rather than concatenating everything
    into one massive prompt. This prevents quality degradation on long/many
    videos and keeps token payloads bounded.
    """
    from itertools import zip_longest

    print(f"🤖 Analyzing with Gemini for Clip Detection ({len(transcripts)} video(s))...")
    client = genai.Client(api_key=api_key)
    model_name = 'gemini-3.8-flash'

    # Gemini 3.8 Flash pricing (intro rate thru Dec 31 2026; doubles Jan 1 2027)
    INPUT_PRICE_PER_MILLION  = 0.75
    OUTPUT_PRICE_PER_MILLION = 3.75

    # Token estimation constants
    TOKEN_ESTIMATE_DIVISOR = 4      # ~4 chars per token
    TOKEN_WARN_THRESHOLD   = 40_000  # ~1–1.5 hours of word-level transcript

    user_prompt_str = ""
    if custom_prompt:
        user_prompt_str = f"USER DETECTION PROMPT / INSTRUCTIONS:\n{custom_prompt}\n"

    all_shorts      = []
    total_cost_data = {
        "input_tokens":  0,
        "output_tokens": 0,
        "input_cost":    0.0,
        "output_cost":   0.0,
        "total_cost":    0.0,
        "model":         model_name,
        "video_count":   len(transcripts),
    }

    def _gemini_call(video_index, trans, doss, extra_exclusions=None):
        """One Gemini clip-detection call for a single video. Returns parsed shorts list."""
        # Build word list
        words = []
        for segment in trans.get('segments', []):
            for word in segment.get('words', []):
                words.append({'w': word['word'], 's': word['start'], 'e': word['end']})
        words = compact_words(words)  # round timestamps: full float precision wastes tokens
        duration = trans.get('duration_seconds', 0.0)

        input_data_section  = "=== VIDEO INDEX 0 ===\n"
        input_data_section += f"VIDEO_DURATION_SECONDS: {duration}\n"
        input_data_section += f"TRANSCRIPT_TEXT:\n{json.dumps(trans.get('text', ''))}\n"
        input_data_section += f"WORDS_JSON:\n{json.dumps(words)}\n"
        if doss:
            input_data_section += f"VISUAL DOSSIER:\n{doss}\n"
        # Add the exclusion block so Gemini avoids already-clipped moments
        excl_block = build_used_moments_block(video_index, used_moments)
        if excl_block:
            input_data_section += "\n" + excl_block
        # Repair pass: additionally exclude ranges that were just rejected
        if extra_exclusions:
            fmt = ", ".join(f"[{r[0]:.1f}-{r[1]:.1f}]" for r in sorted(extra_exclusions))
            input_data_section += f"\n⚠️ ADDITIONAL HARD EXCLUSIONS (rejected as duplicates): {fmt}\n"

        raw_payload = input_data_section + user_prompt_str
        estimated_tokens = len(raw_payload) // TOKEN_ESTIMATE_DIVISOR
        print(f"   📊 Estimated input tokens: ~{estimated_tokens:,}")
        if estimated_tokens > TOKEN_WARN_THRESHOLD:
            print(f"   ⚠️  Large payload detected ({estimated_tokens:,} tokens > {TOKEN_WARN_THRESHOLD:,} threshold).")

        prompt = get_clipping_prompt(input_data_section, user_detection_prompt=user_prompt_str, content_type=content_type, clip_count=clip_count, min_duration=min_duration, max_duration=max_duration)
        response = client.models.generate_content(model=model_name, contents=prompt)

        # Cost tracking
        try:
            usage = response.usage_metadata
            if usage:
                prompt_tokens = usage.prompt_token_count or 0
                output_tokens = usage.candidates_token_count or 0
                input_cost    = (prompt_tokens / 1_000_000) * INPUT_PRICE_PER_MILLION
                output_cost   = (output_tokens / 1_000_000) * OUTPUT_PRICE_PER_MILLION
                call_cost     = input_cost + output_cost
                print(f"   💰 Token usage: {prompt_tokens:,} in / {output_tokens:,} out → ${call_cost:.6f}")
                total_cost_data["input_tokens"]  += prompt_tokens
                total_cost_data["output_tokens"] += output_tokens
                total_cost_data["input_cost"]    += input_cost
                total_cost_data["output_cost"]   += output_cost
                total_cost_data["total_cost"]    += call_cost
        except Exception as cost_err:
            print(f"   ⚠️ Could not calculate cost for video {video_index}: {cost_err}")

        text = response.text
        if text.startswith("```json"):
            text = text[7:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        video_result = json.loads(text)
        shorts = video_result.get("shorts", [])
        for clip in shorts:
            clip["video_index"] = video_index
            # Snap boundaries onto word boundaries (cuts land in pauses, not mid-word)
            s, e = snap_clip_to_words(clip.get('start', 0.0), clip.get('end', 0.0),
                                      words, duration,
                                      min_duration=min_duration, max_duration=max_duration)
            clip['start'], clip['end'] = s, e
        return shorts

    for video_index, (trans, doss) in enumerate(zip_longest(transcripts, dossiers, fillvalue="")):
        if trans == "":
            # Dossiers list was longer — skip phantom entry
            continue

        print(f"\n📹 Processing video {video_index + 1}/{len(transcripts)}...")
        try:
            shorts = _gemini_call(video_index, trans, doss)
            all_shorts.extend(shorts)
            print(f"   ✅ Found {len(shorts)} clip(s) for video {video_index + 1}")
        except Exception as e:
            print(f"   ❌ Gemini error on video {video_index + 1}: {e}")
            # Continue processing remaining videos rather than aborting entire job
            continue

    if not all_shorts:
        print("❌ No clips detected across any videos.")
        return None

    # ── Overlap post-filter + auto-repair against previously-clipped moments ──
    rejected = []          # clips rejected for overlap (kept for user review)
    if used_moments:
        accepted = []          # clips kept (possibly trimmed to boundary)
        need_repair = {vi: [] for vi in range(len(transcripts))}

        for clip in all_shorts:
            vi = clip.get('video_index', 0)
            start = clip.get('start', 0.0)
            end = clip.get('end', 0.0)
            used_ranges = [u for u in used_moments if u.get("video_index") == vi]
            if not used_ranges:
                accepted.append(clip)
                continue
            ranges = [(u['start'], u['end']) for u in used_ranges]
            if overlaps_used(start, end, ranges):
                # Try to salvage a small overlap by trimming to the boundary
                trimmed = trim_to_used(start, end, ranges)
                if trimmed and trimmed != (start, end) and not overlaps_used(trimmed[0], trimmed[1], ranges):
                    clip['start'], clip['end'] = trimmed
                    accepted.append(clip)
                    print(f"   ✂️ Trimmed clip [{start:.1f}-{end:.1f}] → [{trimmed[0]:.1f}-{trimmed[1]:.1f}] to avoid overlap")
                else:
                    rejected.append(clip)
                    need_repair[vi].append((start, end))
                    print(f"   ⛔ Rejected clip [{start:.1f}-{end:.1f}] (overlaps previous moments) — will request a replacement")
            else:
                accepted.append(clip)

        # Auto-repair: request replacements for rejected clips, one repair call per video
        if rejected:
            print(f"\n🔧 Auto-repair: requesting {len(rejected)} replacement clip(s)...")
            for vi in sorted(need_repair):
                if not need_repair[vi]:
                    continue
                if vi >= len(transcripts):
                    continue
                try:
                    print(f"   Re-calling Gemini for video {vi + 1} to replace rejected ranges...")
                    replacements = _gemini_call(vi, transcripts[vi], dossiers[vi] if vi < len(dossiers) else "", extra_exclusions=need_repair[vi])
                    for clip in replacements:
                        s = clip.get('start', 0.0); e = clip.get('end', 0.0)
                        ranges = [(u['start'], u['end']) for u in used_moments if u.get("video_index") == vi]
                        if overlaps_used(s, e, ranges):
                            print(f"   ⛔ Replacement [{s:.1f}-{e:.1f}] also overlaps — discarding")
                            rejected.append(clip)
                        else:
                            accepted.append(clip)
                            print(f"   ✅ Replacement [{s:.1f}-{e:.1f}] accepted")
                except Exception as e:
                    print(f"   ❌ Auto-repair failed for video {vi + 1}: {e}")

        all_shorts = accepted

        if rejected:
            print(f"\n   ⚠️ {len(rejected)} clip(s) were rejected for overlapping previous clips. They are kept in 'rejected_clips' for your review.")

    # Print cumulative cost summary for multi-video jobs
    if len(transcripts) > 1:
        print(f"\n💰 Total cost across {len(transcripts)} videos:")
        print(f"   - Input tokens:  {total_cost_data['input_tokens']:,}  (${total_cost_data['input_cost']:.6f})")
        print(f"   - Output tokens: {total_cost_data['output_tokens']:,} (${total_cost_data['output_cost']:.6f})")
        print(f"   - Grand total:   ${total_cost_data['total_cost']:.6f}")

    return {
        "shorts":        all_shorts,
        "rejected_clips": rejected,
        "cost_analysis": total_cost_data,
    }


# ============================================================================
# Gemini selection robustness: policy-block bisection + sparse-speech fallback
# ----------------------------------------------------------------------------
# Two failure modes used to cost whole jobs in this stage. Neither is a flag:
# both are always on, both fail soft, and neither can raise out of the stage —
# losing a clip is recoverable, losing the job is not.
#
# 1. A POLICY BLOCK on one window cost every window around it. The detail pass
#    sent a video's whole shortlist in one prompt, so one blocked window took
#    the video with it and the job came back "no clips"; the scoring pass
#    scored a blocked batch as 0, which quietly dropped those windows from the
#    shortlist instead. A block is deterministic for a given prompt (verified
#    in prod: a stand-up video came back PROHIBITED_CONTENT in ~300ms on every
#    attempt, and BLOCK_NONE does not lift it), so re-sending the batch cannot
#    help — splitting it can. Google's filter also fires on COMBINATIONS of
#    windows that pass on their own, which is why _bisect_on_block halves the
#    batch instead of shrinking it: only the halves that still block recurse.
#
# 2. Footage with too little speech to clip by transcript (a nursery rhyme, a
#    dashcam drive, music over ambience, a wordless screencast) built one thin
#    scoring window, Gemini returned no clips from it, and the job died on "no
#    clips detected". The signal in that footage is visual, so the vision path
#    watches it and picks moments from the imagery.
# ============================================================================

# Every Gemini call in this stage goes through this one model. Its price is the
# intro rate (thru 31 Dec 2026, doubling 1 Jan 2027) and is kept beside the
# name so a future swap cannot leave the cost report quoting the wrong table.
CLIP_SELECTION_MODEL = 'gemini-3.8-flash'
CLIP_SELECTION_PRICE_PER_MILLION = (0.75, 3.75)   # (input, output)


class GeminiBlockedError(ValueError):
    """The API refused the request for content-policy reasons.

    Deterministic for a given prompt, so callers must split or drop the
    offending item — never retry it — and must never surface it as "the model
    found no good moments here", which is what an unexamined block looks like.
    """


_BLOCKED_FINISH_REASONS = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST",
                           "SPII", "IMAGE_SAFETY", "RECITATION"}


def raise_if_blocked(response):
    """Raise GeminiBlockedError when Gemini refused to answer on policy grounds.

    A block is not an error: the SDK returns HTTP 200 with no text and a
    finish reason, so every caller below used to read it as "nothing worth
    clipping here" and return an empty result. That is how one blocked window
    came to look like a whole video with no viral moments in it.
    """
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


def _bisect_on_block(items, run, label, merge=None, describe=None, empty=None):
    """Run ``run`` over ``items``; on a policy block, bisect and retry the halves.

    Splits in half rather than dropping one item, because the filter rejects
    some COMBINATIONS of windows that are fine on their own — bisecting is the
    only way to keep the innocent windows around an offending one. A single
    item that still blocks alone is dropped with a log line: one unusable
    window must never cost the job. ``merge`` joins the halves' results (list
    concatenation by default, dict update for the scoring pass). ``empty`` is
    what a dropped item contributes to the join — it must match ``merge``'s
    container type (a [] joined into the scoring pass's dicts crashes it).
    """
    if empty is None:
        empty = {} if merge is not None else []
    items = list(items or [])
    if not items:
        return empty
    try:
        return run(items)
    except GeminiBlockedError as e:
        if len(items) == 1:
            who = describe(items[0]) if describe else "this item"
            print(f"   🚫 {label}: Gemini blocked {who} on its own — dropping it ({e})")
            return empty
        mid = len(items) // 2
        print(f"   🚫 {label}: Gemini blocked a batch of {len(items)} — retrying as "
              f"{mid} + {len(items) - mid}")
        join = merge or (lambda a, b: list(a) + list(b))
        return join(_bisect_on_block(items[:mid], run, label, merge, describe, empty),
                    _bisect_on_block(items[mid:], run, label, merge, describe, empty))


def _clean_json_text(text):
    """Strip the markdown fences a model wraps its JSON answer in."""
    text = (text or "").strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


# --- Speech too sparse to clip by transcript -------------------------------
# Ordinary speech is 120-160 words/min, so anything under these floors has no
# words to be a signal. A nursery-rhyme video or a dashcam drive has an audio
# track, so it transcribes to one thin segment ("Uh uh"), builds one scoring
# window and returns no clips — quiet footage that competitors simply skip.
# These are constants, not env gates: a fallback that costs an upload when it
# guesses wrong is cheaper than the jobs it rescues.
MIN_SPEECH_WORDS = 8
MIN_SPEECH_WORDS_PER_MIN = 5.0


def speech_is_sparse(transcript, duration):
    """True when the transcript is too thin to drive clip selection."""
    words = sum(len((seg.get("text") or "").split())
                for seg in (transcript or {}).get("segments", []))
    minutes = max(float(duration or 0) / 60.0, 1e-6)
    return words < MIN_SPEECH_WORDS or words / minutes < MIN_SPEECH_WORDS_PER_MIN


VISUAL_CLIP_PROMPT = """
You are a senior short-form video editor. This {content_type} footage has almost no
usable speech, so judge it purely by what you SEE. Watch the whole thing and pick
the {min_clips}–{max_clips} MOST engaging visual moments for TikTok / Reels / Shorts:
action, reveals, transformations, striking or funny shots, satisfying payoffs,
dramatic movement, or a scene change worth cutting on. If the footage is a screen
recording, judge the on-screen demonstrations instead.

TIME CONTRACT — STRICT:
- Timestamps in ABSOLUTE SECONDS from the start (usable with ffmpeg -ss/-to).
- Only numbers with up to 3 decimals (examples: 0, 12.5, 47.250).
- 0 <= start < end <= {video_duration}.
- Each clip {min_secs:g} to {max_secs:g} seconds long. If the whole video is shorter
  than {min_secs:g}s, return one clip spanning the full video.
- Cut on visual scene changes, never mid-motion.

For each clip, write the copy in {language}: a scroll-stopping hook, a TikTok and
an Instagram description (1-2 punchy sentences plus 3-5 hashtags), a YouTube title
of at most 100 characters, and an honest 0-12 estimate of its viral potential.
Name the concrete thing that happens on screen — never a summary of the video's
general topic. Order clips best to worst by how likely they are to stop a viewer
scrolling.

Return ONLY valid JSON (no markdown, no comments), following the field names and
the 0-12 score range of the transcript-driven pass exactly:
{{
  "shorts": [
    {{
      "start": <number in seconds>,
      "end": <number in seconds>,
      "predicted_score": <0-12>,
      "video_description_for_tiktok": "<description + hashtags>",
      "video_description_for_instagram": "<description + hashtags>",
      "video_title_for_youtube_short": "<title, 100 chars max>",
      "viral_hook_text": "<overlay text, max 10 words, in {language}>"
    }}
  ]
}}
"""


def _upload_video_for_vision(client, path, timeout=300):
    """Upload a local video to the Files API and wait for it to go ACTIVE.

    Uploaded by open handle, never by path: handed a path the SDK copies the
    basename into the X-Goog-Upload-File-Name header, and httpx encodes header
    values as ASCII, so a download named after a non-Latin title died before a
    byte left the container. The readable name still travels as ``display_name``
    in the JSON body, which is UTF-8 all the way.

    Returns the file handle, or None — never raises, because a video that
    cannot be watched is a video with no clips, not a failed job.
    """
    import mimetypes
    guessed = mimetypes.guess_type(path)[0] or ""
    # Every caller uploads a source video; an extension the stdlib does not
    # know must not reach the API as a type it refuses.
    if not guessed.startswith(("video/", "audio/", "image/")):
        guessed = "video/mp4"
    with open(path, "rb") as fh:
        file_upload = client.files.upload(
            file=fh,
            config={"mime_type": guessed, "display_name": os.path.basename(path)})
    deadline = time.time() + timeout
    while True:
        info = client.files.get(name=file_upload.name)
        state = str(getattr(getattr(info, "state", info), "name", "") or "").upper()
        if state == "ACTIVE":
            return file_upload
        if state == "FAILED":
            print("   ❌ Gemini could not process the video.")
            return None
        if time.time() > deadline:
            print("   ❌ Gemini video processing timed out.")
            return None
        time.sleep(2)


def get_visual_clips(video_path, video_duration, api_key, language="en",
                     content_type='general', min_duration=15.0, max_duration=60.0,
                     clip_count=None, exclusion_block=""):
    """Clip a video with too little speech by WATCHING it (Gemini vision).

    Returns ``{"shorts": [...], "usage": usage_metadata}`` in the same shape
    the transcript detail pass produces, so the caller folds the result into the
    same list and the same cost report, or None on any failure at all.

    Boundaries come from the model watching frames, so they are NOT snapped to
    word timestamps here: there are no words to snap to, and the handful this
    video has would drag a correct visual cut onto a stray syllable.
    """
    if not video_path or not os.path.exists(video_path):
        print(f"   ⚠️ Visual clip picking skipped: no readable file at '{video_path}'.")
        return None

    # A transcript saved without a duration (or a hand-made one) would clamp
    # every proposed clip to 0s and drop the lot; the file knows the truth.
    try:
        video_duration = float(video_duration or 0.0) or get_video_duration(video_path)
    except (TypeError, ValueError):
        video_duration = 0.0
    if video_duration <= 0:
        print("   ⚠️ Visual clip picking skipped: unknown video duration.")
        return None

    min_secs = max(5.0, float(min_duration or 15.0))
    max_secs = max(min_secs + 5.0, min(180.0, float(max_duration or 60.0)))
    # The vision pass has no scoring windows to derive a count from, so an
    # explicit request applies as-is; otherwise ask for the classic band.
    if clip_count and int(clip_count) > 0:
        v_min_clips = v_max_clips = int(clip_count)
    else:
        v_min_clips, v_max_clips = 3, 10

    client = genai.Client(api_key=api_key)
    print(f"👀 No speech to clip by — watching {os.path.basename(video_path)} "
          f"with {CLIP_SELECTION_MODEL} instead...")
    file_upload = None
    try:
        print("   📤 Uploading video to Gemini File API...")
        file_upload = _upload_video_for_vision(client, video_path)
        if file_upload is None:
            return None
        print("   ⏳ Video processed — looking for visual moments...")
        prompt = VISUAL_CLIP_PROMPT.format(
            content_type=content_type, language=language,
            video_duration=video_duration, min_clips=v_min_clips,
            max_clips=v_max_clips, min_secs=min_secs, max_secs=max_secs)
        if exclusion_block:
            prompt = prompt + "\n" + exclusion_block + "\n"
        response = client.models.generate_content(
            model=CLIP_SELECTION_MODEL, contents=[file_upload, prompt])
        usage = getattr(response, 'usage_metadata', None)
        # A whole-video block is a verdict on the footage, not a window that
        # bisecting could isolate: drop it with the real reason rather than
        # uploading and asking again.
        raise_if_blocked(response)
        shorts = json.loads(_clean_json_text(response.text)).get("shorts") or []
        clean = []
        for clip in shorts:
            try:
                start = max(0.0, float(clip.get("start", 0.0)))
                end = min(video_duration, float(clip.get("end", 0.0)))
            except (TypeError, ValueError, AttributeError):
                continue
            if end - start < 1.0:
                continue
            clip["start"], clip["end"] = round(start, 3), round(end, 3)
            clean.append(clip)
        if not clean:
            print("   ⚠️ Vision pass returned no usable clips.")
            return None
        return {"shorts": clean, "usage": usage}
    except GeminiBlockedError as e:
        print(f"   🚫 {e}")
        return None
    except Exception as e:
        print(f"   ❌ Gemini vision error: {type(e).__name__}: {e}")
        return None
    finally:
        if file_upload is not None:
            try:
                client.files.delete(name=file_upload.name)
            except Exception:
                pass


def detect_clips_windowed(transcripts, dossiers, custom_prompt, api_key, content_type='general',
                          used_moments=None, clip_count=None, min_duration=15.0, max_duration=60.0,
                          videos=None):
    """Windowed two-pass clip detection (the default clip path).

    Pass 1 — score: split each video into ~90s transcript windows aligned to
    Whisper segment boundaries, score every window 0-12, take the global top-N.
    A single call over a whole transcript clusters picks near the start;
    scoring windows first forces full-video coverage.
    Pass 2 — detail: run the standard clip prompt over the shortlisted windows
    only (words + dossier + exclusions), then snap/dedupe/trim.
    Videos with <=3 windows skip pass 1 and go straight to detail.

    Both passes bisect their batch on a policy block (see _bisect_on_block),
    and a video with too little speech to clip by words, or one whose windows
    all came back blocked, falls back to Gemini-vision clip picking. That
    fallback watches the footage in ``videos[video_index]``, so pass the source
    paths to get it; without them the stage behaves as it did before.
    """
    from itertools import zip_longest

    print(f"🪟 Windowed clip detection ({len(transcripts)} video(s), 3.8-flash both passes)...")
    client = genai.Client(api_key=api_key)
    model_name = CLIP_SELECTION_MODEL
    used_moments = list(used_moments or [])  # None-safe: exclusion helpers iterate this
    INPUT_PRICE_PER_MILLION, OUTPUT_PRICE_PER_MILLION = CLIP_SELECTION_PRICE_PER_MILLION
    video_paths = list(videos or [])
    visual_tried = set()   # one vision pass per video, however many chances
    exhausted = set()      # every window already clipped in an earlier job

    try:
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "prompts", "score_windows.txt"), "r", encoding="utf-8") as f:
            scoring_tmpl = f.read()
    except Exception as e:
        print(f"❌ Could not load scoring prompt: {e}")
        return None

    total_cost_data = {
        "input_tokens":  0,
        "output_tokens": 0,
        "input_cost":    0.0,
        "output_cost":   0.0,
        "total_cost":    0.0,
        "model":         model_name,
        "video_count":   len(transcripts),
    }

    def _track_cost(usage):
        try:
            if usage:
                pi = usage.prompt_token_count or 0
                po = usage.candidates_token_count or 0
                total_cost_data["input_tokens"]  += pi
                total_cost_data["output_tokens"] += po
                total_cost_data["input_cost"]    += (pi / 1_000_000) * INPUT_PRICE_PER_MILLION
                total_cost_data["output_cost"]   += (po / 1_000_000) * OUTPUT_PRICE_PER_MILLION
                total_cost_data["total_cost"]     = total_cost_data["input_cost"] + total_cost_data["output_cost"]
                return pi, po
        except Exception:
            pass
        return 0, 0

    def _score_batch(batch):
        """Score one batch of windows. Returns {window_id: (score, why)}.

        A policy block propagates so the caller can bisect the batch; any other
        failure stays soft and scores the batch 0, as it always has."""
        lines = [f"{w['id']} [{w['start']:.1f}-{w['end']:.1f}]: {w['text']}" for w in batch]
        prompt = scoring_tmpl.format(content_type=content_type,
                                     n_windows=len(batch),
                                     windows="\n".join(lines))
        try:
            response = client.models.generate_content(model=model_name, contents=prompt)
            _track_cost(getattr(response, 'usage_metadata', None))
            raise_if_blocked(response)
            data = json.loads(_clean_json_text(response.text))
            items = data.get("scores", data) if isinstance(data, dict) else data
            out = {}
            for item in items or []:
                try:
                    out[str(item.get("id", ""))] = (float(item.get("score", 0) or 0.0),
                                                    str(item.get("why", ""))[:160])
                except (TypeError, ValueError, AttributeError):
                    continue
            return out
        except GeminiBlockedError:
            raise
        except Exception as e:
            print(f"   ⚠️ Scoring batch failed ({e}) — those windows score 0")
            return {}

    def _detail_call(video_index, window_entries, words, duration, dossier, extra_exclusions=None):
        """Run the standard clip prompt over shortlisted windows. Returns shorts list."""
        win_lines = [f"{w['id']} [{w['start']:.1f}-{w['end']:.1f}] (score {score:g}/12): {w['text']}"
                     for w, score, _why in window_entries]
        # Words scoped to the shortlisted span (padded); full list kept for snapping
        lo = max(0.0, min(w['start'] for w, _s, _y in window_entries) - 2.0)
        hi = min(duration, max(w['end'] for w, _s, _y in window_entries) + 2.0)
        scoped = [x for x in words if x['e'] >= lo and x['s'] <= hi]

        user_prompt_str = ""
        if custom_prompt:
            user_prompt_str = f"USER DETECTION PROMPT / INSTRUCTIONS:\n{custom_prompt}\n"

        input_data_section  = f"=== VIDEO INDEX {video_index} ===\n"
        input_data_section += f"VIDEO_DURATION_SECONDS: {duration}\n"
        input_data_section += ("CANDIDATE WINDOWS (pre-scored — select clips ONLY from these "
                               "windows, nowhere else):\n" + "\n".join(win_lines) + "\n")
        input_data_section += f"WORDS_JSON (candidate regions only):\n{json.dumps(scoped)}\n"
        if dossier:
            input_data_section += f"VISUAL DOSSIER:\n{dossier}\n"
        excl_block = build_used_moments_block(video_index, used_moments)
        if excl_block:
            input_data_section += "\n" + excl_block
        if extra_exclusions:
            fmt = ", ".join(f"[{r[0]:.1f}-{r[1]:.1f}]" for r in sorted(extra_exclusions))
            input_data_section += f"\n⚠️ ADDITIONAL HARD EXCLUSIONS (rejected as duplicates): {fmt}\n"

        prompt = get_clipping_prompt(input_data_section, user_detection_prompt=user_prompt_str,
                                     content_type=content_type, clip_count=clip_count,
                                     min_duration=min_duration, max_duration=max_duration)
        response = client.models.generate_content(model=model_name, contents=prompt)
        pi, po = _track_cost(getattr(response, 'usage_metadata', None))
        print(f"   💰 Detail call: {pi:,} in / {po:,} out → ${(pi/1_000_000)*INPUT_PRICE_PER_MILLION + (po/1_000_000)*OUTPUT_PRICE_PER_MILLION:.6f}")
        raise_if_blocked(response)
        data = json.loads(_clean_json_text(response.text))
        shorts = data.get("shorts", [])
        for clip in shorts:
            clip["video_index"] = video_index
            s, e = snap_clip_to_words(clip.get('start', 0.0), clip.get('end', 0.0),
                                      words, duration,
                                      min_duration=min_duration, max_duration=max_duration)
            clip['start'], clip['end'] = s, e
        return shorts

    def _detail_call_bisected(video_index, window_entries, words, duration, dossier,
                              extra_exclusions=None):
        """_detail_call, but a blocked shortlist is split instead of lost.

        This is the call that used to take a whole video with it: the prompt
        carried every shortlisted window at once, so one blocked window dropped
        every other candidate in the video with it. Bisecting keeps the
        innocent windows and costs at most a few extra calls."""
        label = f"detail(video {video_index + 1})"
        return _bisect_on_block(
            window_entries,
            lambda entries: _detail_call(video_index, entries, words, duration,
                                         dossier, extra_exclusions=extra_exclusions),
            label, describe=lambda entry: f"window {entry[0].get('id')}")

    def _video_words(trans):
        w = [{'w': wd.get('word', ''), 's': wd.get('start', 0.0), 'e': wd.get('end', 0.0)}
             for seg in trans.get('segments', []) for wd in seg.get('words', [])]
        return compact_words(w)

    def _finish(shorts, n_candidates):
        """Dedupe and cap one video's clips, whichever pass produced them."""
        shorts = dedupe_overlapping(shorts)
        _lo_n, hi_n = clip_count_targets(max(1, int(n_candidates or 1)))
        cap = int(clip_count) if clip_count and int(clip_count) > 0 else hi_n
        return trim_to_best(shorts, cap)

    def _visual_fallback(video_index, duration, trans):
        """Watch this video's footage instead of clipping it by its words.

        Returns its clips, or [] — never raises, and never runs twice for the
        same video, and never for one whose moments are all already clipped."""
        if video_index in visual_tried or video_index in exhausted:
            return []
        path = video_paths[video_index] if video_index < len(video_paths) else None
        if not path:
            return []
        visual_tried.add(video_index)
        print(f"   🔇 Nothing to clip by words in video {video_index + 1} — "
              f"looking for visual moments instead.")
        result = get_visual_clips(
            path, duration, api_key,
            language=str((trans or {}).get("language") or "en"),
            content_type=content_type, min_duration=min_duration,
            max_duration=max_duration, clip_count=clip_count,
            exclusion_block=build_used_moments_block(video_index, used_moments) or "")
        if not result:
            print(f"   ⚠️ No clips from the footage of video {video_index + 1} either.")
            return []
        shorts = result.get("shorts") or []
        for clip in shorts:
            clip["video_index"] = video_index
        pi, po = _track_cost(result.get("usage"))
        print(f"   💰 Vision pass: {pi:,} in / {po:,} out")
        return _finish(shorts, len(shorts))

    all_shorts   = []
    rejected     = []
    video_entries = {}  # video_index -> shortlisted entries (for repair re-calls)

    for video_index, (trans, doss) in enumerate(zip_longest(transcripts, dossiers, fillvalue="")):
        if trans == "":
            continue
        duration = float(trans.get('duration_seconds', 0.0) or 0.0)
        # A transcript saved without a duration would divide by ~0 and read as
        # dense speech; the file itself knows the truth.
        if duration <= 0 and video_index < len(video_paths):
            duration = get_video_duration(video_paths[video_index])
        words = _video_words(trans)

        # Too little speech to clip by: scoring a handful of stray words used
        # to return no clips and end the job. The footage is the signal here.
        if speech_is_sparse(trans, duration):
            print(f"\n📹 Video {video_index + 1}/{len(transcripts)}: "
                  f"{sum(len((sg.get('text') or '').split()) for sg in trans.get('segments', []))} "
                  f"word(s) in {duration:.0f}s")
            visual = _visual_fallback(video_index, duration, trans)
            if visual:
                print(f"   ✅ {len(visual)} clip(s) after dedupe/trim")
                all_shorts.extend(visual)
            continue

        windows = build_transcript_windows(trans, duration)
        # Drop windows fully inside already-used moments — no need to score them
        my_used = [u for u in (used_moments or []) if u.get("video_index") == video_index]
        if my_used:
            windows = [w for w in windows
                       if not any(u['start'] - 1.0 <= w['start'] and w['end'] <= u['end'] + 1.0
                                  for u in my_used)]
            # Every window of this video is already clipped: watching the
            # footage cannot produce a moment that is not already taken.
            if not windows:
                exhausted.add(video_index)

        print(f"\n📹 Video {video_index + 1}/{len(transcripts)}: {len(windows)} window(s)")

        if len(windows) <= 3:
            entries = [(w, 12.0, "short video: all windows shortlisted") for w in windows]
        else:
            scores = {}
            for batch in score_batches(windows, 10):
                print(f"   🔍 Scoring {len(batch)} window(s)...")
                # A blocked batch is bisected, not written off: scored 0 it
                # would fall out of the shortlist, and a block is a verdict on
                # one COMBINATION of windows, not on each of them.
                scores.update(_bisect_on_block(
                    batch, _score_batch, "score",
                    merge=lambda a, b: {**a, **b},
                    describe=lambda w: f"window {w.get('id')}"))
            ranked = sorted(windows, key=lambda w: (-scores.get(w['id'], (0.0, ""))[0], w['start']))
            short = sorted(ranked[:shortlist_target(duration)], key=lambda w: w['start'])
            entries = [(w, scores.get(w['id'], (0.0, ""))[0],
                        scores.get(w['id'], (0.0, ""))[1]) for w in short]
            print(f"   ✅ Shortlisted {len(entries)} window(s)")
        video_entries[video_index] = (entries, words, duration, doss)

        if not entries:
            print("   ⚠️ No windows to detail — trying the footage instead")
            visual = _visual_fallback(video_index, duration, trans)
            if visual:
                print(f"   ✅ {len(visual)} clip(s) after dedupe/trim")
                all_shorts.extend(visual)
            continue
        try:
            shorts = _detail_call_bisected(video_index, entries, words, duration, doss)
        except Exception as e:
            print(f"   ❌ Detail call failed on video {video_index + 1}: {e}")
            shorts = []
        if not shorts:
            # Every window blocked, or the call answered with nothing. The one
            # second opinion left is the footage itself, so the video is not
            # lost with them.
            shorts = _visual_fallback(video_index, duration, trans)
        if shorts:
            shorts = _finish(shorts, len(entries))
            print(f"   ✅ {len(shorts)} clip(s) after dedupe/trim")
            all_shorts.extend(shorts)

    # Nothing at all came back: give every video still unvisited one look with
    # the eyes rather than ending the job on a transcript that had nothing in
    # it. Videos that already had their vision pass are skipped, and the
    # exclusion filter below still applies to anything recovered here.
    if not all_shorts:
        for video_index, trans in enumerate(transcripts):
            if not isinstance(trans, dict) or video_index in visual_tried:
                continue
            recovered = _visual_fallback(
                video_index, float(trans.get('duration_seconds', 0.0) or 0.0), trans)
            if recovered:
                print(f"   ♻️ Recovered {len(recovered)} clip(s) from video {video_index + 1}.")
                all_shorts.extend(recovered)
        if all_shorts:
            print(f"✅ Recovered {len(all_shorts)} clip(s) by watching the footage.")

    # ── Overlap post-filter + auto-repair against previously-clipped moments ──
    if used_moments:
        accepted = []
        need_repair = {}
        for clip in all_shorts:
            vi = clip.get('video_index', 0)
            s, e = clip.get('start', 0.0), clip.get('end', 0.0)
            ranges = [(u['start'], u['end']) for u in used_moments if u.get("video_index") == vi]
            if not ranges:
                accepted.append(clip)
                continue
            if overlaps_used(s, e, ranges):
                trimmed = trim_to_used(s, e, ranges)
                if trimmed and trimmed != (s, e) and not overlaps_used(trimmed[0], trimmed[1], ranges):
                    clip['start'], clip['end'] = trimmed
                    accepted.append(clip)
                    print(f"   ✂️ Trimmed clip [{s:.1f}-{e:.1f}] → [{trimmed[0]:.1f}-{trimmed[1]:.1f}]")
                else:
                    rejected.append(clip)
                    need_repair.setdefault(vi, []).append((s, e))
                    print(f"   ⛔ Rejected clip [{s:.1f}-{e:.1f}] (overlaps previous moments)")
            else:
                accepted.append(clip)

        if rejected:
            print(f"\n🔧 Auto-repair: requesting replacements for {len(rejected)} rejected clip(s)...")
            for vi in sorted(need_repair):
                if vi not in video_entries:
                    continue
                entries, words, duration, doss = video_entries[vi]
                try:
                    reps = _detail_call_bisected(vi, entries, words, duration, doss,
                                                 extra_exclusions=need_repair[vi])
                    for clip in reps:
                        s, e = clip.get('start', 0.0), clip.get('end', 0.0)
                        ranges = [(u['start'], u['end']) for u in used_moments
                                  if u.get("video_index") == vi]
                        if overlaps_used(s, e, ranges):
                            rejected.append(clip)
                            print(f"   ⛔ Replacement [{s:.1f}-{e:.1f}] also overlaps — discarding")
                        else:
                            accepted.append(clip)
                            print(f"   ✅ Replacement [{s:.1f}-{e:.1f}] accepted")
                except Exception as e:
                    print(f"   ❌ Auto-repair failed for video {vi + 1}: {e}")
        all_shorts = accepted

        if rejected:
            print(f"\n   ⚠️ {len(rejected)} clip(s) rejected for overlapping previous clips "
                  f"(kept in 'rejected_clips').")

    if not all_shorts:
        print("❌ No clips detected across any videos.")
        return None

    if len(transcripts) > 1:
        print(f"\n💰 Total cost across {len(transcripts)} videos:")
        print(f"   - Input tokens:  {total_cost_data['input_tokens']:,}  (${total_cost_data['input_cost']:.6f})")
        print(f"   - Output tokens: {total_cost_data['output_tokens']:,} (${total_cost_data['output_cost']:.6f})")
        print(f"   - Grand total:   ${total_cost_data['total_cost']:.6f}")

    return {
        "shorts":         all_shorts,
        "rejected_clips": rejected,
        "cost_analysis":  total_cost_data,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="AutoCrop-Vertical with Stage-Based Platform.")
    
    # Modes
    parser.add_argument('--analyze', action='store_true', help="Stage 1: Analyze video (transcription + optional dossier)")
    parser.add_argument('--clip', action='store_true', help="Stage 2: Generate clips from analysis")
    
    # Inputs
    parser.add_argument('-i', '--input', type=str, nargs='*', help="Path to input video file(s).")
    parser.add_argument('-u', '--url', type=str, help="YouTube URL to download and process (only for analyze mode).")
    
    # Outputs
    parser.add_argument('-o', '--output', type=str, help="Output directory or file.")
    
    # Flags & Config
    parser.add_argument('--dossier', type=str, nargs='*', help="Dossier file(s) for clipping, or use as boolean flag in analyze mode.")
    parser.add_argument('--transcript', type=str, nargs='*', help="Transcript JSON file(s) for clipping mode.")
    parser.add_argument('--prompt', type=str, default="", help="Custom prompt for clip detection.")
    parser.add_argument('--exclude', type=str, default="", help="JSON file with already-clipped [start,end] ranges per video to avoid repeats.")
    parser.add_argument('--render-single', type=str, default="", help="Render one clip (JSON: {\"input\":path,\"start\":s,\"end\":e,\"output\":path}) then exit.")
    parser.add_argument('--custom-prompt', type=str, default="", help="Custom instructions/prompt for dossier generation in analyze mode.")
    parser.add_argument('--content-type', type=str, default="general", help="Domain/content type template to use (general, sports, podcast, lecture, gaming, interview).")
    parser.add_argument('--clip-count', type=int, default=None, help="Target number of clips to extract per video (e.g. 3, 5, 10).")
    parser.add_argument('--min-duration', type=float, default=15.0, help="Minimum clip duration in seconds.")
    parser.add_argument('--max-duration', type=float, default=60.0, help="Maximum clip duration in seconds.")
    parser.add_argument('--keep-original', action='store_true', help="Keep downloaded YouTube video (legacy mode).")
    parser.add_argument('--skip-analysis', action='store_true', help="Skip AI analysis and convert whole video (legacy mode).")
    
    args = parser.parse_args()

    script_start_time = time.time()
    
    def _ensure_dir(path: str) -> str:
        """Create directory if missing and return the same path."""
        if path:
            os.makedirs(path, exist_ok=True)
        return path

    # Render a single clip from its source video (used by rejected-clip "Keep").
    if args.render_single:
        import json as _json
        spec = _json.loads(args.render_single)
        input_video = spec.get("input")
        output_path = spec.get("output")
        start = float(spec.get("start", 0))
        end = float(spec.get("end", 0))
        if not input_video or not output_path:
            print("❌ --render-single requires {\"input\",\"output\",\"start\",\"end\"}.")
            sys.exit(1)
        if not os.path.exists(input_video):
            print(f"❌ Input video not found: {input_video}")
            sys.exit(1)
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        temp_path = os.path.join(os.path.dirname(output_path), f"temp_{os.path.basename(output_path)}")
        cut_command = [
            'ffmpeg', '-y',
            '-ss', str(start),
            '-to', str(end),
            '-i', input_video,
            '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
            '-pix_fmt', 'yuv420p',
            '-c:a', 'aac',
            temp_path
        ]
        subprocess.run(cut_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        success = process_video_to_vertical(temp_path, output_path)
        if os.path.exists(temp_path):
            os.remove(temp_path)
        if success:
            print(f"✅ Rendered single clip: {output_path}")
            sys.exit(0)
        else:
            print("❌ Failed to render single clip.")
            sys.exit(1)

    if args.analyze:
        print("🔍 Running in Stage 1: Analyze mode...")
        if not args.url and (not args.input or len(args.input) == 0):
            print("❌ Analyze mode requires either -u/--url or -i/--input.")
            sys.exit(1)
            
        if not args.output:
            print("❌ Analyze mode requires -o/--output directory.")
            sys.exit(1)
            
        output_dir = _ensure_dir(args.output)
        
        # 1. Get Input Video
        if args.url:
            input_video, video_title = download_youtube_video(args.url, output_dir)
        else:
            input_video = args.input[0]
            video_title = os.path.splitext(os.path.basename(input_video))[0]
            
        if not os.path.exists(input_video):
            print(f"❌ Input file not found: {input_video}")
            sys.exit(1)
            
        # 2. Transcribe (duration first so progress can be reported)
        duration = get_video_duration(input_video)
        transcript = transcribe_video(input_video, duration=duration)
        transcript['duration_seconds'] = duration
        
        # Save transcript.json
        transcript_file = os.path.join(output_dir, "transcript.json")
        with open(transcript_file, 'w') as f:
            json.dump(transcript, f, indent=2)
        print(f"   Saved transcript to {transcript_file}")
        
        # 3. Dossier (optional)
        generate_dossier_flag = args.dossier is not None
        if generate_dossier_flag:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                print("❌ Error: GEMINI_API_KEY not found in environment variables.")
                sys.exit(1)
            dossier_text = generate_dossier(input_video, api_key, args.content_type, custom_prompt=args.custom_prompt)
            dossier_file = os.path.join(output_dir, "dossier.md")
            with open(dossier_file, 'w') as f:
                f.write(dossier_text)
            print(f"   Saved dossier to {dossier_file}")
            
        print("✅ Analyze mode finished.")
        sys.exit(0)

    elif args.clip:
        print("✂️ Running in Stage 2: Clip generation mode...")
        if not args.output:
            print("❌ Clip mode requires -o/--output directory.")
            sys.exit(1)
            
        if not args.transcript or len(args.transcript) == 0:
            print("❌ Clip mode requires --transcript file(s).")
            sys.exit(1)
            
        if not args.input or len(args.input) == 0:
            print("❌ Clip mode requires -i/--input video file(s).")
            sys.exit(1)
            
        output_dir = _ensure_dir(args.output)
        
        # Load all transcripts
        transcripts = []
        for trans_path in args.transcript:
            if not os.path.exists(trans_path):
                print(f"❌ Transcript file not found: {trans_path}")
                sys.exit(1)
            with open(trans_path, 'r') as f:
                transcripts.append(json.load(f))
                
        # Load all dossiers
        dossiers = []
        if args.dossier and len(args.dossier) > 0:
            for doss_path in args.dossier:
                if os.path.exists(doss_path):
                    with open(doss_path, 'r') as f:
                        dossiers.append(f.read())
                else:
                    dossiers.append("")
        else:
            for trans_path in args.transcript:
                parent_dir = os.path.dirname(trans_path)
                doss_path = os.path.join(parent_dir, "dossier.md")
                if os.path.exists(doss_path):
                    with open(doss_path, 'r') as f:
                        dossiers.append(f.read())
                else:
                    dossiers.append("")
                    
        # Load previously-clipped ranges to avoid repeats (per video)
        used_moments = []  # list of {video_index, start, end}
        if args.exclude and os.path.exists(args.exclude):
            try:
                with open(args.exclude, 'r') as f:
                    excl = json.load(f)
                vid_ids = excl.get("video_ids", [])
                used_map = excl.get("used", {})
                for vid, ranges in used_map.items():
                    idx = vid_ids.index(vid) if vid in vid_ids else -1
                    if idx < 0:
                        continue
                    for (s, e) in ranges:
                        used_moments.append({"video_index": idx, "start": s, "end": e})
                print(f"   ⚠️ Loaded {len(used_moments)} previously-clipped moment(s) to exclude from selection.")
            except Exception as e:
                print(f"   ⚠️ Failed to load exclude ranges: {e}")
                used_moments = []

        # 1. Run Gemini for clip detection
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("❌ Error: GEMINI_API_KEY not found in environment variables.")
            sys.exit(1)
            
        # videos= lets the stage fall back to watching the footage when a
        # transcript is too thin to clip by (see detect_clips_windowed).
        clips_data = detect_clips_windowed(transcripts, dossiers, args.prompt, api_key, args.content_type, used_moments=used_moments, clip_count=args.clip_count, min_duration=args.min_duration, max_duration=args.max_duration, videos=args.input)
        
        if not clips_data or 'shorts' not in clips_data:
            print("❌ Failed to identify clips.")
            sys.exit(1)
            
        print(f"🔥 Found {len(clips_data['shorts'])} viral clips!")
        
        if transcripts:
            clips_data['transcript'] = transcripts[0]
            
        metadata_file = os.path.join(output_dir, "clips_metadata.json")
        with open(metadata_file, 'w') as f:
            json.dump(clips_data, f, indent=2)
        print(f"   Saved metadata to {metadata_file}")
        
        # 2. Process each clip
        for i, clip in enumerate(clips_data['shorts']):
            video_idx = clip.get('video_index', 0)
            if video_idx >= len(args.input):
                print(f"⚠️ Warning: video_index {video_idx} out of range for clip {i+1}. Defaulting to index 0.")
                video_idx = 0
            
            input_video = args.input[video_idx]
            video_title = os.path.splitext(os.path.basename(input_video))[0]
            
            start = clip['start']
            end = clip['end']
            print(f"\n🎬 Processing Clip {i+1} from Video {video_idx} ({video_title}): {start}s - {end}s")
            print(f"   Title: {clip.get('video_title_for_youtube_short', 'No Title')}")
            
            # Cut clip — use output dir name as base for consistent naming
            dir_name = os.path.basename(output_dir)
            clip_filename = f"{dir_name}_clip_{i+1}.mp4"
            clip_temp_path = os.path.join(output_dir, f"temp_{clip_filename}")
            clip_final_path = os.path.join(output_dir, clip_filename)
            
            # ffmpeg cut
            cut_command = [
                'ffmpeg', '-y', 
                '-ss', str(start), 
                '-to', str(end), 
                '-i', input_video,
                '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                '-pix_fmt', 'yuv420p',
                '-c:a', 'aac',
                clip_temp_path
            ]
            subprocess.run(cut_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            
            # Process vertical
            success = process_video_to_vertical(clip_temp_path, clip_final_path)

            # Which stretches used which layout (sidecar -> clip metadata, so
            # /api/subtitle finds it after the sidecar is gone). The hook was
            # written from the transcript alone: when the render put this
            # clip's meaning on the screen, rewrite hook and title from its
            # frames before the metadata below is served to the dashboard.
            clip['layout_ranges'] = layout_ranges.read(clip_final_path)
            if success:
                try:
                    if hook_grounding.wanted(clip['layout_ranges'], end - start):
                        src_transcript = (transcripts[video_idx]
                                          if 0 <= video_idx < len(transcripts)
                                          else clips_data.get('transcript'))
                        hook_grounding.reground(clip_final_path, clip,
                                                src_transcript, start, end)
                except Exception as e:
                    print(f"   ⚠️ Hook grounding skipped ({e})")

            if success:
                print(f"   ✅ Clip {i+1} ready: {clip_final_path}")

            # Clean up temp cut
            if os.path.exists(clip_temp_path):
                os.remove(clip_temp_path)

        # Persist regrounded hooks (and layout ranges) back to the metadata
        # file: app.py run_job builds the dashboard result from this file.
        if any('hook_grounding' in c for c in clips_data['shorts']):
            with open(metadata_file, 'w') as f:
                json.dump(clips_data, f, indent=2)
            print("   🪝 Saved regrounded hooks to metadata.")

        print("✅ Clip mode finished.")
        sys.exit(0)

    else:
        # Legacy pipeline mode (both analyze and clip at once)
        # 1. Get Input Video
        if args.url:
            if args.output and not args.skip_analysis:
                output_dir = _ensure_dir(args.output)
            else:
                if args.output and os.path.isdir(args.output):
                    output_dir = args.output
                elif args.output and not os.path.isdir(args.output):
                    output_dir = os.path.dirname(args.output) or "."
                else:
                    output_dir = "."
            
            input_video, video_title = download_youtube_video(args.url, output_dir)
        else:
            input_video = args.input[0] if isinstance(args.input, list) else args.input
            video_title = os.path.splitext(os.path.basename(input_video))[0]
            
            if args.output and not args.skip_analysis:
                output_dir = _ensure_dir(args.output)
            else:
                if args.output and os.path.isdir(args.output):
                    output_dir = args.output
                elif args.output and not os.path.isdir(args.output):
                    output_dir = os.path.dirname(args.output) or os.path.dirname(input_video)
                else:
                    output_dir = os.path.dirname(input_video)

        if not os.path.exists(input_video):
            print(f"❌ Input file not found: {input_video}")
            exit(1)

        # 2. Decision: Analyze clips or process whole?
        if args.skip_analysis:
            print("⏩ Skipping analysis, processing entire video...")
            output_file = args.output if args.output else os.path.join(output_dir, f"{video_title}_vertical.mp4")
            process_video_to_vertical(input_video, output_file)
        else:
            # 3. Transcribe
            transcript = transcribe_video(input_video)
            duration = get_video_duration(input_video)

            # 4. Gemini Analysis
            clips_data = get_viral_clips(transcript, duration, args.content_type)
            
            if not clips_data or 'shorts' not in clips_data:
                print("❌ Failed to identify clips. Converting whole video as fallback.")
                output_file = os.path.join(output_dir, f"{video_title}_vertical.mp4")
                process_video_to_vertical(input_video, output_file)
            else:
                print(f"🔥 Found {len(clips_data['shorts'])} viral clips!")
                
                # Save metadata
                clips_data['transcript'] = transcript
                metadata_file = os.path.join(output_dir, f"{video_title}_metadata.json")
                with open(metadata_file, 'w') as f:
                    json.dump(clips_data, f, indent=2)
                print(f"   Saved metadata to {metadata_file}")

                # 5. Process each clip
                for i, clip in enumerate(clips_data['shorts']):
                    start = clip['start']
                    end = clip['end']
                    print(f"\n🎬 Processing Clip {i+1}: {start}s - {end}s")
                    print(f"   Title: {clip.get('video_title_for_youtube_short', 'No Title')}")
                    
                    # Cut clip
                    clip_filename = f"{video_title}_clip_{i+1}.mp4"
                    clip_temp_path = os.path.join(output_dir, f"temp_{clip_filename}")
                    clip_final_path = os.path.join(output_dir, clip_filename)
                    
                    # ffmpeg cut
                    cut_command = [
                        'ffmpeg', '-y', 
                        '-ss', str(start), 
                        '-to', str(end), 
                        '-i', input_video,
                        '-c:v', 'libx264', '-crf', '18', '-preset', 'fast',
                        '-pix_fmt', 'yuv420p',
                        '-c:a', 'aac',
                        clip_temp_path
                    ]
                    subprocess.run(cut_command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                    
                    # Process vertical
                    success = process_video_to_vertical(clip_temp_path, clip_final_path)

                    # Same hook-grounding pass as clip mode above: record the
                    # layout ranges, then rewrite hook/title from frames when
                    # the clip's meaning is on the screen.
                    clip['layout_ranges'] = layout_ranges.read(clip_final_path)
                    if success:
                        try:
                            if hook_grounding.wanted(clip['layout_ranges'], end - start):
                                hook_grounding.reground(clip_final_path, clip,
                                                        transcript, start, end)
                        except Exception as e:
                            print(f"   ⚠️ Hook grounding skipped ({e})")

                    if success:
                        print(f"   ✅ Clip {i+1} ready: {clip_final_path}")

                    # Clean up temp cut
                    if os.path.exists(clip_temp_path):
                        os.remove(clip_temp_path)

                # Persist regrounded hooks (and layout ranges) back to the
                # metadata file the dashboard reads.
                if any('hook_grounding' in c for c in clips_data['shorts']):
                    with open(metadata_file, 'w') as f:
                        json.dump(clips_data, f, indent=2)
                    print("   🪝 Saved regrounded hooks to metadata.")

        # Clean up original if requested
        if args.url and not args.keep_original and os.path.exists(input_video):
            os.remove(input_video)
            print(f"🗑️  Cleaned up downloaded video.")

        total_time = time.time() - script_start_time
        print(f"\n⏱️  Total execution time: {total_time:.2f}s")

