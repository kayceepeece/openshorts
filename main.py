import time
import cv2
import subprocess
import argparse
import re
import sys
from scenedetect import open_video, SceneManager
from scenedetect.detectors import ContentDetector
from ultralytics import YOLO
import torch
import os
import numpy as np
from tqdm import tqdm
import yt_dlp
import mediapipe as mp
# import whisper (replaced by faster_whisper inside function)
from google import genai
from dotenv import load_dotenv
import json

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module='google.protobuf')

# Load environment variables
load_dotenv()

# --- Constants ---
ASPECT_RATIO = 9 / 16

# Load helper to build clipping prompt dynamically based on content type
def get_clipping_prompt(input_data_section, user_detection_prompt="", content_type='general'):
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

    prompt = f"""You are a senior short-form video editor. Read the ENTIRE transcript and visual dossier for the input video(s) to choose the 3–15 MOST VIRAL moments for TikTok/IG Reels/YouTube Shorts. Each clip must be between 15 and 60 seconds long.

⚠️ FFMPEG TIME CONTRACT — STRICT REQUIREMENTS:
- Return timestamps in ABSOLUTE SECONDS from the start of the video (usable in: ffmpeg -ss <start> -to <end> -i <input> ...).
- Only NUMBERS with decimal point, up to 3 decimals (examples: 0, 1.250, 17.350).
- Ensure 0 ≤ start < end ≤ VIDEO_DURATION_SECONDS.
- Each clip between 15 and 60 s (inclusive).
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
- No clips < 15 s or > 60 s.

OUTPUT — RETURN ONLY VALID JSON (no markdown, no comments). Order clips by predicted performance (best to worst). Write descriptions that are natural to the content type and optimised for each platform:
{{
  "shorts": [
    {{
      "video_index": <0-based index of the video this clip is from, e.g., 0 if only one video is provided>,
      "start": <number in seconds, e.g., 12.340>,
      "end": <number in seconds, e.g., 37.900>,
      "video_description_for_tiktok": "<description for TikTok oriented to get views>",
      "video_description_for_instagram": "<description for Instagram oriented to get views>",
      "video_title_for_youtube_short": "<title for YouTube Short oriented to get views 100 chars max>",
      "viral_hook_text": "<SHORT punchy text overlay (max 10 words). MUST BE IN THE SAME LANGUAGE AS THE VIDEO TRANSCRIPT. Examples: 'POV: You realized...', 'Did you know?', 'Stop doing this!'>"
    }}
  ]
}}
"""
    return prompt

# Load the YOLO model once (Keep for backup or scene analysis if needed)
YOLO_MODEL_PATH = os.environ.get("YOLO_MODEL_PATH", "yolov8n.pt")
model = YOLO(YOLO_MODEL_PATH)

# --- MediaPipe Setup ---
# Use standard Face Detection (BlazeFace) for speed
mp_face_detection = mp.solutions.face_detection
face_detection = mp_face_detection.FaceDetection(model_selection=1, min_detection_confidence=0.5)

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
    results = face_detection.process(rgb_frame)
    
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
    # Use the globally loaded model
    results = model(frame, verbose=False, classes=[0]) # class 0 is person
    
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

def detect_scenes(video_path):
    video = open_video(video_path)
    scene_manager = SceneManager()
    scene_manager.add_detector(ContentDetector())
    scene_manager.detect_scenes(video=video)
    scene_list = scene_manager.get_scene_list()
    fps = video.frame_rate
    return scene_list, fps

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

def process_video_to_vertical(input_video, final_output_video):
    """
    Core logic to convert horizontal video to vertical using scene detection and Active Speaker Tracking (MediaPipe).
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
    
    frame_number = 0
    current_scene_index = 0
    
    # Pre-calculate scene boundaries
    scene_boundaries = []
    for s_start, s_end in scenes:
        scene_boundaries.append((s_start.get_frames(), s_end.get_frames()))

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
            
            # Apply Strategy
            if current_strategy == 'GENERAL':
                # "Plano General" -> Blur Background + Fit Width
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

    # Clean up temp files
    if os.path.exists(temp_video_output): os.remove(temp_video_output)
    if os.path.exists(temp_audio_output): os.remove(temp_audio_output)
    
    return True

def transcribe_video(video_path):
    print("🎙️  Transcribing video with Faster-Whisper (CPU Optimized)...")
    from faster_whisper import WhisperModel
    
    cpu_threads = int(os.environ.get("WHISPER_CPU_THREADS", "2"))
    
    # Run on CPU with INT8 quantization for speed. cpu_threads is capped low to
    # bound peak memory on small VPS boxes (each decode thread allocates buffers).
    model = WhisperModel("base", device="cpu", compute_type="int8", cpu_threads=cpu_threads)
    
    # vad_filter skips long silent stretches (large memory+time win on long videos),
    # beam_size=1 (greedy) keeps the decoder's working set minimal vs beam search.
    segments, info = model.transcribe(
        video_path,
        word_timestamps=True,
        vad_filter=True,
        beam_size=1,
        condition_on_previous_text=True,
        vad_parameters={"min_silence_duration_ms": 500}
    )
    
    print(f"   Detected language '{info.language}' with probability {info.language_probability:.2f}")
    
    # Convert to openai-whisper compatible format
    transcript_segments = []
    full_text = ""
    
    for segment in segments:
        # Print progress to keep user informed (and prevent timeouts feeling)
        print(f"   [{segment.start:.2f}s -> {segment.end:.2f}s] {segment.text}")
        
        seg_dict = {
            'text': segment.text,
            'start': segment.start,
            'end': segment.end,
            'words': []
        }
        
        if segment.words:
            for word in segment.words:
                seg_dict['words'].append({
                    'word': word.word,
                    'start': word.start,
                    'end': word.end,
                    'probability': word.probability
                })
        
        transcript_segments.append(seg_dict)
        full_text += segment.text + " "
        
    return {
        'text': full_text.strip(),
        'segments': transcript_segments,
        'language': info.language
    }

def get_viral_clips(transcript_result, video_duration, content_type='general'):
    print("🤖  Analyzing with Gemini...")
    
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ Error: GEMINI_API_KEY not found in environment variables.")
        return None


    client = genai.Client(api_key=api_key)
    
    # We use gemini-3.5-flash (GA May 2026, current production standard).
    model_name = 'gemini-3.5-flash'
    
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
                # Gemini 3.5 Flash Pricing (June 2026)
                # Input: $1.50 per 1M tokens
                # Output: $9.00 per 1M tokens
                
                input_price_per_million = 1.50
                output_price_per_million = 9.00
                
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
            model='gemini-3.5-flash',
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

def detect_clips_stage2(transcripts, dossiers, custom_prompt, api_key, content_type='general'):
    """Process each video as its own isolated Gemini API call.

    Each video = one upload + one clip-detection call. Multi-video jobs
    accumulate results across calls rather than concatenating everything
    into one massive prompt. This prevents quality degradation on long/many
    videos and keeps token payloads bounded.
    """
    from itertools import zip_longest

    print(f"🤖 Analyzing with Gemini for Clip Detection ({len(transcripts)} video(s))...")
    client = genai.Client(api_key=api_key)
    model_name = 'gemini-3.5-flash'

    # Gemini 3.5 Flash pricing (June 2026)
    INPUT_PRICE_PER_MILLION  = 1.50
    OUTPUT_PRICE_PER_MILLION = 9.00

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

    for video_index, (trans, doss) in enumerate(zip_longest(transcripts, dossiers, fillvalue="")):
        if trans == "":
            # Dossiers list was longer — skip phantom entry
            continue

        print(f"\n📹 Processing video {video_index + 1}/{len(transcripts)}...")

        # ── Build word list ──────────────────────────────────────────────
        words = []
        for segment in trans.get('segments', []):
            for word in segment.get('words', []):
                words.append({
                    'w': word['word'],
                    's': word['start'],
                    'e': word['end']
                })

        duration = trans.get('duration_seconds', 0.0)

        # ── Build per-video input section ────────────────────────────────
        # When called per-video, video_index in the prompt is always 0
        # so the model uses video_index=0 in its JSON output.
        # We remap to the real index when merging results below.
        input_data_section  = "=== VIDEO INDEX 0 ===\n"
        input_data_section += f"VIDEO_DURATION_SECONDS: {duration}\n"
        input_data_section += f"TRANSCRIPT_TEXT:\n{json.dumps(trans.get('text', ''))}\n"
        input_data_section += f"WORDS_JSON:\n{json.dumps(words)}\n"
        if doss:
            input_data_section += f"VISUAL DOSSIER:\n{doss}\n"

        # ── Pre-flight token estimate ────────────────────────────────────
        raw_payload = input_data_section + user_prompt_str
        estimated_tokens = len(raw_payload) // TOKEN_ESTIMATE_DIVISOR
        print(f"   📊 Estimated input tokens: ~{estimated_tokens:,}")
        if estimated_tokens > TOKEN_WARN_THRESHOLD:
            print(f"   ⚠️  Large payload detected ({estimated_tokens:,} tokens > {TOKEN_WARN_THRESHOLD:,} threshold).")
            print(f"   ⚠️  Consider splitting videos longer than ~1 hour for best quality.")

        prompt = get_clipping_prompt(input_data_section, user_detection_prompt=user_prompt_str, content_type=content_type)

        # ── Gemini API call ──────────────────────────────────────────────
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt
            )

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

            # Parse response
            text = response.text
            if text.startswith("```json"):
                text = text[7:]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

            video_result = json.loads(text)
            shorts = video_result.get("shorts", [])

            # Remap video_index=0 → real index in the multi-video result set
            for clip in shorts:
                clip["video_index"] = video_index

            all_shorts.extend(shorts)
            print(f"   ✅ Found {len(shorts)} clip(s) for video {video_index + 1}")

        except Exception as e:
            print(f"   ❌ Gemini error on video {video_index + 1}: {e}")
            # Continue processing remaining videos rather than aborting entire job
            continue

    if not all_shorts:
        print("❌ No clips detected across any videos.")
        return None

    # Print cumulative cost summary for multi-video jobs
    if len(transcripts) > 1:
        print(f"\n💰 Total cost across {len(transcripts)} videos:")
        print(f"   - Input tokens:  {total_cost_data['input_tokens']:,}  (${total_cost_data['input_cost']:.6f})")
        print(f"   - Output tokens: {total_cost_data['output_tokens']:,} (${total_cost_data['output_cost']:.6f})")
        print(f"   - Grand total:   ${total_cost_data['total_cost']:.6f}")

    return {
        "shorts":        all_shorts,
        "cost_analysis": total_cost_data,
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
    parser.add_argument('--custom-prompt', type=str, default="", help="Custom instructions/prompt for dossier generation in analyze mode.")
    parser.add_argument('--content-type', type=str, default="general", help="Domain/content type template to use (general, sports, podcast, lecture, gaming, interview).")
    parser.add_argument('--keep-original', action='store_true', help="Keep downloaded YouTube video (legacy mode).")
    parser.add_argument('--skip-analysis', action='store_true', help="Skip AI analysis and convert whole video (legacy mode).")
    
    args = parser.parse_args()

    script_start_time = time.time()
    
    def _ensure_dir(path: str) -> str:
        """Create directory if missing and return the same path."""
        if path:
            os.makedirs(path, exist_ok=True)
        return path

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
            
        # 2. Transcribe
        transcript = transcribe_video(input_video)
        duration = get_video_duration(input_video)
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
                    
        # 1. Run Gemini for clip detection
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("❌ Error: GEMINI_API_KEY not found in environment variables.")
            sys.exit(1)
            
        clips_data = detect_clips_stage2(transcripts, dossiers, args.prompt, api_key, args.content_type)
        
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
            
            if success:
                print(f"   ✅ Clip {i+1} ready: {clip_final_path}")
            
            # Clean up temp cut
            if os.path.exists(clip_temp_path):
                os.remove(clip_temp_path)
                
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
                    
                    if success:
                        print(f"   ✅ Clip {i+1} ready: {clip_final_path}")
                    
                    # Clean up temp cut
                    if os.path.exists(clip_temp_path):
                        os.remove(clip_temp_path)

        # Clean up original if requested
        if args.url and not args.keep_original and os.path.exists(input_video):
            os.remove(input_video)
            print(f"🗑️  Cleaned up downloaded video.")

        total_time = time.time() - script_start_time
        print(f"\n⏱️  Total execution time: {total_time:.2f}s")

