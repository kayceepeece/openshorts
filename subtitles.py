import os
import subprocess


def transcribe_audio(video_path):
    """
    Transcribe audio from a video file using faster-whisper.
    Returns transcript in the same format as main.py for compatibility.
    """
    from faster_whisper import WhisperModel

    print(f"🎙️  Transcribing audio from: {video_path}")

    # Run on CPU with INT8 quantization for speed
    model = WhisperModel("base", device="cpu", compute_type="int8")

    segments, info = model.transcribe(video_path, word_timestamps=True)

    transcript = {
        "segments": [],
        "language": info.language
    }

    for segment in segments:
        seg_data = {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "words": []
        }
        if segment.words:
            for word in segment.words:
                seg_data["words"].append({
                    "word": word.word.strip(),
                    "start": word.start,
                    "end": word.end
                })
        transcript["segments"].append(seg_data)

    print(f"✅ Transcription complete. Language: {info.language}")
    return transcript


def generate_srt_from_video(video_path, output_path, max_chars=20, max_duration=2.0):
    """
    Transcribe a video and generate SRT directly.
    Used for dubbed videos that don't have a pre-existing transcript.
    """
    transcript = transcribe_audio(video_path)

    # Get video duration to use as clip_end
    import cv2
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration = frame_count / fps if fps else 0
    cap.release()

    return generate_srt(transcript, 0, duration, output_path, max_chars, max_duration)


def generate_srt(transcript, clip_start, clip_end, output_path, max_chars=20, max_duration=2.0):
    """
    Generates an SRT file from the transcript for a specific time range.
    Groups words into short lines suitable for vertical video.
    """
    
    words = []
    # 1. Extract and flatten words within range
    for segment in transcript.get('segments', []):
        for word_info in segment.get('words', []):
            # Check overlap
            if word_info['end'] > clip_start and word_info['start'] < clip_end:
                words.append(word_info)
    
    if not words:
        return False

    srt_content = ""
    index = 1
    
    current_block = []
    block_start = None
    
    for i, word in enumerate(words):
        # Adjust times relative to clip
        start = max(0, word['start'] - clip_start)
        end = max(0, word['end'] - clip_start)
        
        # Clip to video duration logic handled by ffmpeg usually, but good to be safe
        
        if not current_block:
            current_block.append(word)
            block_start = start
        else:
            # Decide whether to close block
            current_text_len = sum(len(w['word']) + 1 for w in current_block)
            duration = end - block_start
            
            if current_text_len + len(word['word']) > max_chars or duration > max_duration:
                # Finalize current block
                # End time of block is start of this word (gap) or end of last word?
                # Usually end of last word.
                block_end = current_block[-1]['end'] - clip_start
                
                text = " ".join([w['word'] for w in current_block]).strip()
                srt_content += format_srt_block(index, block_start, block_end, text)
                index += 1
                
                current_block = [word]
                block_start = start
            else:
                current_block.append(word)
    
    # Final block
    if current_block:
        block_end = current_block[-1]['end'] - clip_start
        text = " ".join([w['word'] for w in current_block]).strip()
        srt_content += format_srt_block(index, block_start, block_end, text)
        
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(srt_content)
        
    return True

def format_srt_block(index, start, end, text):
    def format_time(seconds):
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        millis = int((seconds - int(seconds)) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
        
    return f"{index}\n{format_time(start)} --> {format_time(end)}\n{text}\n\n"

def hex_to_ass_color(hex_color, opacity=1.0):
    """Convert #RRGGBB to ASS &HAABBGGRR format. opacity: 0.0=transparent, 1.0=opaque"""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        hex_color = "FFFFFF"
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    alpha = round((1.0 - opacity) * 255)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


def _parse_srt_time(stamp):
    """Parse an SRT timestamp (HH:MM:SS,mmm) to seconds."""
    stamp = stamp.strip().replace('.', ',')
    try:
        hms, millis = stamp.split(',')
        h, m, s = hms.split(':')
        return int(h) * 3600 + int(m) * 60 + int(s) + int(millis) / 1000.0
    except (ValueError, AttributeError):
        return None


def _parse_srt_cues(srt_path):
    """Parse an SRT file into [(start, end, text), ...] with ASS newlines."""
    try:
        with open(srt_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except (OSError, UnicodeDecodeError):
        return []
    cues = []
    for block in content.replace('\r\n', '\n').split('\n\n'):
        lines = [ln.strip() for ln in block.strip().split('\n') if ln.strip()]
        if len(lines) < 2:
            continue
        # First line may be the numeric index; find the timing line.
        timing = None
        text_lines = []
        for ln in lines:
            if '-->' in ln and timing is None:
                timing = ln
            elif timing is not None:
                text_lines.append(ln)
        if timing is None or not text_lines:
            continue
        try:
            start_s, end_s = timing.split('-->')
            start, end = _parse_srt_time(start_s), _parse_srt_time(end_s)
        except ValueError:
            continue
        if start is None or end is None or end <= start:
            continue
        cues.append((start, end, '\\N'.join(text_lines)))
    return cues


def _ass_time(seconds):
    """Format seconds as ASS timestamp H:MM:SS.cc (centiseconds)."""
    seconds = max(0, seconds)
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    centis = int(round((seconds - int(seconds)) * 100))
    if centis >= 100:
        centis = 99
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def _escape_ass_text(text):
    """Neutralize characters that would start ASS override blocks."""
    return str(text).replace('\\', '/').replace('{', '(').replace('}', ')')


def build_seam_ass(srt_path, split_ranges, ass_path, alignment=2, fontsize=16,
                   font_name="Verdana", font_color="#FFFFFF",
                   border_color="#000000", border_width=2,
                   bg_color="#000000", bg_opacity=0.0):
    """Convert an SRT file to ASS, anchoring cues inside SPLIT stretches on
    the seam between the two stacked speakers (inline {\\an5}).

    On a SPLIT scene the two speakers sit one above the other and the seam
    (exactly mid-frame) is the emptiest place in the frame, so captions go
    there; everywhere else the requested alignment rules. ``split_ranges``
    is a list of (start, end) in clip seconds (layout_ranges.split_ranges).
    Returns True when the ASS file was written with at least one event.
    """
    cues = _parse_srt_cues(srt_path)
    if not cues:
        return False

    ass_alignment = 2
    align_lower = str(alignment).lower()
    if align_lower == 'top':
        ass_alignment = 6
    elif align_lower == 'middle':
        ass_alignment = 10
    elif align_lower == 'bottom':
        ass_alignment = 2

    final_fontsize = int(fontsize * 0.85)
    if final_fontsize < 10:
        final_fontsize = 10

    primary_colour = hex_to_ass_color(font_color, 1.0)
    if bg_opacity > 0:
        border_style = 3
        outline_colour = hex_to_ass_color(bg_color, bg_opacity)
        outline_width = 1
    else:
        border_style = 1
        outline_colour = hex_to_ass_color(border_color, 1.0)
        outline_width = max(1, border_width)
    back_colour = hex_to_ass_color("#000000", 0.0)

    seam_ranges = []
    for r in split_ranges or []:
        try:
            seam_ranges.append((float(r[0]), float(r[1])))
        except (TypeError, ValueError, IndexError):
            continue

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "WrapStyle: 0\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_name},{final_fontsize},{primary_colour},{primary_colour},"
        f"{outline_colour},{back_colour},1,0,0,0,100,100,0,0,{border_style},"
        f"{outline_width},0,{ass_alignment},10,10,25,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    )

    events = []
    for start, end, text in cues:
        prefix = "{\\an5}" if any(a <= start < b for a, b in seam_ranges) else ""
        events.append(
            f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Default,,0,0,0,,"
            f"{prefix}{_escape_ass_text(text)}"
        )
    if not events:
        return False

    with open(ass_path, 'w', encoding='utf-8') as f:
        f.write(header + "\n".join(events) + "\n")
    return True


def burn_subtitles(video_path, srt_path, output_path, alignment=2, fontsize=16,
                   font_name="Verdana", font_color="#FFFFFF",
                   border_color="#000000", border_width=2,
                   bg_color="#000000", bg_opacity=0.0, split_ranges=None):
    """
    Burns subtitles into the video using FFmpeg.
    Supports two modes:
    - Outline mode (bg_opacity=0): Text with colored outline/border
    - Box mode (bg_opacity>0): Text with semi-transparent background box

    split_ranges: optional [(start, end), ...] in clip seconds rendered with
    the SPLIT layout (layout_ranges.split_ranges); cues there are anchored
    on the seam between the two stacked speakers instead of the bottom.
    """
    # Position mapping
    ass_alignment = 2
    align_lower = str(alignment).lower()
    if align_lower == 'top':
        ass_alignment = 6
    elif align_lower == 'middle':
        ass_alignment = 10
    elif align_lower == 'bottom':
        ass_alignment = 2

    # Font size scaling for ASS virtual resolution (PlayResY=288 default)
    # For vertical 1080x1920 video, we need larger text for readability
    final_fontsize = int(fontsize * 0.85)
    if final_fontsize < 10:
        final_fontsize = 10

    # Path handling for FFmpeg filter syntax
    safe_srt_path = srt_path.replace('\\', '/').replace(':', '\\:')

    # SPLIT stretches put their captions on the seam via a generated ASS file
    # (SRT burns carry one alignment for the whole file, so they cannot move
    # the text with the cut). No split ranges: the plain SRT path, unchanged.
    ass_path = None
    filter_path = safe_srt_path
    filter_name = "subtitles"
    if split_ranges:
        ass_path = os.path.join(
            os.path.dirname(os.path.abspath(output_path)),
            f"seam_{int(__import__('time').time())}_{os.getpid()}.ass")
        try:
            if build_seam_ass(srt_path, split_ranges, ass_path,
                              alignment=alignment, fontsize=fontsize,
                              font_name=font_name, font_color=font_color,
                              border_color=border_color, border_width=border_width,
                              bg_color=bg_color, bg_opacity=bg_opacity):
                filter_path = ass_path.replace('\\', '/').replace(':', '\\:')
                filter_name = "ass"
            else:
                ass_path = None
        except OSError:
            ass_path = None

    # Convert colors to ASS format and build style
    primary_colour = hex_to_ass_color(font_color, 1.0)

    if bg_opacity > 0:
        # Box mode: opaque background box
        border_style = 3
        outline_colour = hex_to_ass_color(bg_color, bg_opacity)
        outline_width = 1
    else:
        # Outline mode: text border/outline
        border_style = 1
        outline_colour = hex_to_ass_color(border_color, 1.0)
        outline_width = max(1, border_width)

    back_colour = hex_to_ass_color("#000000", 0.0)

    style_string = (
        f"Alignment={ass_alignment},"
        f"Fontname={font_name},"
        f"Fontsize={final_fontsize},"
        f"PrimaryColour={primary_colour},"
        f"OutlineColour={outline_colour},"
        f"BackColour={back_colour},"
        f"BorderStyle={border_style},"
        f"Outline={outline_width},"
        f"Shadow=0,"
        f"MarginV=25,"
        f"Bold=1"
    )

    cmd = [
        'ffmpeg', '-y',
        '-i', video_path,
        '-vf', f"{filter_name}='{filter_path}':force_style='{style_string}'" if filter_name == "subtitles"
               else f"{filter_name}='{filter_path}'",
        '-c:a', 'copy',
        '-c:v', 'libx264', '-preset', 'fast', '-crf', '23',
        '-pix_fmt', 'yuv420p',
        output_path
    ]

    print(f"🎬 Burning subtitles: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)

        if result.returncode != 0:
            print(f"❌ FFmpeg Subtitle Error: {result.stderr.decode()}")
            raise Exception(f"FFmpeg failed: {result.stderr.decode()}")
    finally:
        if ass_path and os.path.exists(ass_path):
            os.remove(ass_path)

    return True

