import os
import uuid
import subprocess
import threading
import json
import shutil
import glob
import time
import asyncio
import sqlite3
from dotenv import load_dotenv
from typing import Dict, Optional, List
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from s3_uploader import upload_job_artifacts, list_all_clips, upload_actor_to_s3, list_actor_gallery, upload_video_to_gallery, list_video_gallery

load_dotenv()

# Constants
UPLOAD_DIR = "uploads"
OUTPUT_DIR = "output"
DB_PATH = "data/openshorts.db"
os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("data", exist_ok=True)

# Configuration
# Default to 1 if not set, but user can set higher for powerful servers
MAX_CONCURRENT_JOBS = int(os.environ.get("MAX_CONCURRENT_JOBS", "5"))
MAX_FILE_SIZE_MB = 2048  # 2GB limit
JOB_RETENTION_SECONDS = 7 * 24 * 3600  # 7 days retention
DISABLE_YOUTUBE_URL = os.environ.get("DISABLE_YOUTUBE_URL", "false").lower() in ("1", "true", "yes")

# ── Database ──────────────────────────────────────────────────────────────

def _db_conn():
    """Get a SQLite connection (row_factory enabled)."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Create the projects, videos, and clip_jobs tables if they don't exist.
    Also migrates old jobs data if present."""
    conn = _db_conn()
    conn.execute("PRAGMA foreign_keys = ON;")
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            dossier_enabled BOOLEAN DEFAULT 0,
            retention_days INTEGER DEFAULT 7,
            content_type TEXT DEFAULT 'general',
            custom_instructions TEXT,
            created_at REAL
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            source_type TEXT,
            source_url TEXT,
            source_filename TEXT,
            status TEXT,
            transcript_json TEXT,
            dossier_text TEXT,
            duration_seconds REAL,
            created_at REAL,
            completed_at REAL,
            error TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    
    conn.execute("""
        CREATE TABLE IF NOT EXISTS clip_jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            video_ids TEXT NOT NULL,
            clip_count INTEGER DEFAULT 0,
            status TEXT,
            result_json TEXT,
            created_at REAL,
            completed_at REAL,
            error TEXT,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        )
    """)
    
    # Add new columns to existing projects tables (safe migration for existing deployments)
    for col_def in [
        ("content_type", "TEXT DEFAULT 'general'"),
        ("custom_instructions", "TEXT"),
    ]:
        col_name, col_type = col_def
        try:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {col_name} {col_type}")
            print(f"📦 Migrated projects table: added column '{col_name}'")
        except sqlite3.OperationalError:
            pass  # Column already exists

    # Check if we need to migrate from old 'jobs' table
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='jobs'")
    has_old_jobs = cursor.fetchone()
    if has_old_jobs:
        print("📦 Found old 'jobs' table. Migrating data...")
        default_project_id = "default-project"
        
        # Insert default project
        existing_project = conn.execute("SELECT id FROM projects WHERE id = ?", (default_project_id,)).fetchone()
        if not existing_project:
            conn.execute(
                "INSERT INTO projects (id, name, dossier_enabled, retention_days, created_at) VALUES (?, ?, ?, ?, ?)",
                (default_project_id, "Default Project", 0, 7, time.time())
            )
            
        old_jobs = conn.execute("SELECT * FROM jobs").fetchall()
        for job in old_jobs:
            job_dict = dict(job)
            job_id = job_dict["id"]
            
            # Map to videos table
            video_exists = conn.execute("SELECT id FROM videos WHERE id = ?", (job_id,)).fetchone()
            if not video_exists:
                video_status = 'ready' if job_dict['status'] == 'completed' else ('failed' if job_dict['status'] == 'failed' else 'analyzing')
                transcript_json = None
                dossier_text = None
                
                # Try to read transcript from result_json first
                if job_dict.get('result_json'):
                    try:
                        res = json.loads(job_dict['result_json'])
                        if isinstance(res, dict) and 'transcript' in res:
                            transcript_json = json.dumps(res['transcript'])
                    except Exception:
                        pass
                
                # If not in result_json, try to read from disk
                if not transcript_json:
                    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
                    transcript_path = os.path.join(job_output_dir, "transcript.json")
                    if os.path.exists(transcript_path):
                        try:
                            with open(transcript_path, 'r') as f:
                                transcript_json = f.read()
                        except Exception:
                            pass
                
                # Try to read dossier from disk
                job_output_dir = os.path.join(OUTPUT_DIR, job_id)
                dossier_path = os.path.join(job_output_dir, "dossier.md")
                if os.path.exists(dossier_path):
                    try:
                        with open(dossier_path, 'r') as f:
                            dossier_text = f.read()
                    except Exception:
                        pass
                
                conn.execute("""
                    INSERT INTO videos (id, project_id, source_type, source_url, source_filename, status, transcript_json, dossier_text, created_at, completed_at, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_id,
                    default_project_id,
                    job_dict.get('source_type'),
                    job_dict.get('source_url'),
                    job_dict.get('source_filename'),
                    video_status,
                    transcript_json,
                    dossier_text,
                    job_dict.get('created_at'),
                    job_dict.get('completed_at'),
                    job_dict.get('error')
                ))
                
            # Map to clip_jobs table
            clip_job_exists = conn.execute("SELECT id FROM clip_jobs WHERE id = ?", (job_id,)).fetchone()
            if not clip_job_exists:
                conn.execute("""
                    INSERT INTO clip_jobs (id, project_id, video_ids, clip_count, status, result_json, created_at, completed_at, error)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    job_id,
                    default_project_id,
                    json.dumps([job_id]),
                    job_dict.get('clip_count', 0),
                    job_dict.get('status'),
                    job_dict.get('result_json'),
                    job_dict.get('created_at'),
                    job_dict.get('completed_at'),
                    job_dict.get('error')
                ))
        
        conn.execute("ALTER TABLE jobs RENAME TO old_jobs_backup")
        print("📦 Migration complete. Old 'jobs' table renamed to 'old_jobs_backup'.")
        
    conn.commit()
    conn.close()
    print("📦 Database initialized.")

def save_job(job_id: str, source_type: str = None, source_url: str = None,
             source_filename: str = None, status: str = None, created_at: float = None,
             completed_at: float = None, clip_count: int = None, result_json: str = None,
             error: str = None):
    # This is a compatibility wrapper.
    # It updates whichever table contains job_id.
    conn = _db_conn()
    is_clip = conn.execute("SELECT id FROM clip_jobs WHERE id = ?", (job_id,)).fetchone()
    if is_clip:
        updates = []
        params = []
        for field, value in [("status", status), ("completed_at", completed_at),
                             ("clip_count", clip_count), ("result_json", result_json),
                             ("error", error)]:
            if value is not None:
                updates.append(f"{field} = ?")
                params.append(value)
        if updates:
            params.append(job_id)
            conn.execute(f"UPDATE clip_jobs SET {', '.join(updates)} WHERE id = ?", params)
    else:
        is_video = conn.execute("SELECT id FROM videos WHERE id = ?", (job_id,)).fetchone()
        if is_video:
            updates = []
            params = []
            for field, value in [("status", status), ("completed_at", completed_at),
                                 ("error", error)]:
                if value is not None:
                    if field == "status" and value == "completed":
                        value = "ready"
                    updates.append(f"{field} = ?")
                    params.append(value)
            if updates:
                params.append(job_id)
                conn.execute(f"UPDATE videos SET {', '.join(updates)} WHERE id = ?", params)
    conn.commit()
    conn.close()

def get_job(job_id: str) -> Optional[dict]:
    # Check clip_jobs first
    conn = _db_conn()
    row = conn.execute("SELECT * FROM clip_jobs WHERE id = ?", (job_id,)).fetchone()
    if row:
        conn.close()
        r = dict(row)
        try:
            vids = json.loads(r["video_ids"])
            if vids:
                conn2 = _db_conn()
                vrow = conn2.execute("SELECT source_type, source_url, source_filename FROM videos WHERE id = ?", (vids[0],)).fetchone()
                conn2.close()
                if vrow:
                    vdict = dict(vrow)
                    r.update(vdict)
        except Exception:
            pass
        return r
        
    # Check videos
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (job_id,)).fetchone()
    if row:
        conn.close()
        r = dict(row)
        if r["status"] == "ready":
            r["status"] = "completed"
        return r
        
    conn.close()
    return None

def list_jobs(limit: int = 50, offset: int = 0) -> list:
    conn = _db_conn()
    rows = conn.execute("SELECT * FROM clip_jobs ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
    conn.close()
    res = []
    for row in rows:
        r = dict(row)
        try:
            vids = json.loads(r["video_ids"])
            if vids:
                conn2 = _db_conn()
                vrow = conn2.execute("SELECT source_type, source_url, source_filename FROM videos WHERE id = ?", (vids[0],)).fetchone()
                conn2.close()
                if vrow:
                    vdict = dict(vrow)
                    r.update(vdict)
        except Exception:
            pass
        res.append(r)
    return res

# ── Projects, Videos, Clip Jobs CRUD Helper Functions ─────────────────────

def create_project(name: str, dossier_enabled: bool, retention_days: int, content_type: str = 'general', custom_instructions: Optional[str] = None) -> dict:
    project_id = str(uuid.uuid4())
    conn = _db_conn()
    conn.execute(
        "INSERT INTO projects (id, name, dossier_enabled, retention_days, content_type, custom_instructions, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, name, int(dossier_enabled), retention_days, content_type, custom_instructions, time.time())
    )
    conn.commit()
    conn.close()
    return get_project(project_id)

def list_projects() -> list:
    conn = _db_conn()
    rows = conn.execute("""
        SELECT p.*, 
               (SELECT COUNT(*) FROM videos v WHERE v.project_id = p.id) as video_count,
               (SELECT COUNT(*) FROM clip_jobs c WHERE c.project_id = p.id) as clip_count
        FROM projects p
        ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_project(project_id: str) -> Optional[dict]:
    conn = _db_conn()
    row = conn.execute("""
        SELECT p.*, 
               (SELECT COUNT(*) FROM videos v WHERE v.project_id = p.id) as video_count,
               (SELECT COUNT(*) FROM clip_jobs c WHERE c.project_id = p.id) as clip_count
        FROM projects p
        WHERE p.id = ?
    """, (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_project(project_id: str, **fields) -> Optional[dict]:
    conn = _db_conn()
    updates = []
    params = []
    for field, val in fields.items():
        if field in ("name", "dossier_enabled", "retention_days", "content_type", "custom_instructions"):
            updates.append(f"{field} = ?")
            if field == "dossier_enabled":
                params.append(int(val))
            else:
                params.append(val)
    if updates:
        params.append(project_id)
        conn.execute(f"UPDATE projects SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()
    return get_project(project_id)

def delete_project(project_id: str):
    vids = list_videos(project_id)
    for vid in vids:
        delete_video_files(vid["id"])
    cjs = list_clip_jobs(project_id)
    for cj in cjs:
        delete_clip_job_files(cj["id"])
        
    conn = _db_conn()
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()

def create_video(project_id: str, source_type: str, source_url: Optional[str], source_filename: Optional[str]) -> dict:
    video_id = str(uuid.uuid4())
    conn = _db_conn()
    conn.execute("""
        INSERT INTO videos (id, project_id, source_type, source_url, source_filename, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (video_id, project_id, source_type, source_url, source_filename, "analyzing", time.time()))
    conn.commit()
    conn.close()
    return get_video(video_id)

def list_videos(project_id: str) -> list:
    conn = _db_conn()
    rows = conn.execute("SELECT * FROM videos WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_video(video_id: str) -> Optional[dict]:
    conn = _db_conn()
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (video_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_video(video_id: str, **fields) -> Optional[dict]:
    conn = _db_conn()
    updates = []
    params = []
    for field, val in fields.items():
        if field in ("status", "transcript_json", "dossier_text", "duration_seconds", "completed_at", "error"):
            updates.append(f"{field} = ?")
            params.append(val)
    if updates:
        params.append(video_id)
        conn.execute(f"UPDATE videos SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()
    return get_video(video_id)

def delete_video_files(video_id: str):
    video_dir = os.path.join(OUTPUT_DIR, video_id)
    if os.path.isdir(video_dir):
        shutil.rmtree(video_dir, ignore_errors=True)
    for f in os.listdir(UPLOAD_DIR):
        if f.startswith(video_id):
            try:
                os.remove(os.path.join(UPLOAD_DIR, f))
            except Exception:
                pass

def delete_video(video_id: str):
    delete_video_files(video_id)
    conn = _db_conn()
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("DELETE FROM videos WHERE id = ?", (video_id,))
    conn.commit()
    conn.close()

def create_clip_job(project_id: str, video_ids: list) -> dict:
    clip_job_id = str(uuid.uuid4())
    conn = _db_conn()
    conn.execute("""
        INSERT INTO clip_jobs (id, project_id, video_ids, status, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, (clip_job_id, project_id, json.dumps(video_ids), "queued", time.time()))
    conn.commit()
    conn.close()
    return get_clip_job(clip_job_id)

def list_clip_jobs(project_id: str) -> list:
    conn = _db_conn()
    rows = conn.execute("SELECT * FROM clip_jobs WHERE project_id = ? ORDER BY created_at DESC", (project_id,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_clip_job(clip_job_id: str) -> Optional[dict]:
    conn = _db_conn()
    row = conn.execute("SELECT * FROM clip_jobs WHERE id = ?", (clip_job_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def update_clip_job(clip_job_id: str, **fields) -> Optional[dict]:
    conn = _db_conn()
    updates = []
    params = []
    for field, val in fields.items():
        if field in ("status", "clip_count", "result_json", "completed_at", "error"):
            updates.append(f"{field} = ?")
            params.append(val)
    if updates:
        params.append(clip_job_id)
        conn.execute(f"UPDATE clip_jobs SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()
    return get_clip_job(clip_job_id)

def delete_clip_job_files(clip_job_id: str):
    job_dir = os.path.join(OUTPUT_DIR, clip_job_id)
    if os.path.isdir(job_dir):
        shutil.rmtree(job_dir, ignore_errors=True)

def get_video_file_path(video_id: str) -> Optional[str]:
    upload_pattern = os.path.join(UPLOAD_DIR, f"{video_id}_*")
    upload_files = glob.glob(upload_pattern)
    if upload_files:
        return upload_files[0]
    video_dir = os.path.join(OUTPUT_DIR, video_id)
    if os.path.isdir(video_dir):
        mp4_files = [f for f in os.listdir(video_dir) if f.endswith(".mp4")]
        if mp4_files:
            return os.path.join(video_dir, mp4_files[0])
    return None

def ensure_job_in_memory(job_id: str) -> bool:
    if job_id in jobs:
        return True
    
    conn = _db_conn()
    row = conn.execute("SELECT * FROM clip_jobs WHERE id = ?", (job_id,)).fetchone()
    if row:
        row_dict = dict(row)
        result = None
        if row_dict.get("result_json"):
            try:
                result = json.loads(row_dict["result_json"])
            except Exception:
                pass
        
        jobs[job_id] = {
            'status': row_dict.get('status'),
            'logs': [f"Job {job_id} loaded from database."],
            'result': result,
            'output_dir': os.path.join(OUTPUT_DIR, job_id)
        }
        conn.close()
        return True
        
    row = conn.execute("SELECT * FROM videos WHERE id = ?", (job_id,)).fetchone()
    if row:
        row_dict = dict(row)
        transcript = None
        if row_dict.get("transcript_json"):
            try:
                transcript = json.loads(row_dict["transcript_json"])
            except Exception:
                pass
        jobs[job_id] = {
            'status': row_dict.get('status'),
            'logs': [f"Video analysis {job_id} loaded from database."],
            'result': {'transcript': transcript},
            'output_dir': os.path.join(OUTPUT_DIR, job_id)
        }
        conn.close()
        return True
    
    conn.close()
    return False

# ── Atomic Writes & Per-Job Locks ────────────────────────────────────────
# Ported from PR #34 (Claude Opus 4.7) — prevents metadata corruption
# when concurrent requests hit the same job.

_JOB_LOCKS: Dict[str, threading.Lock] = {}
_JOB_LOCKS_GUARD = threading.Lock()

def _job_lock(job_id: str) -> threading.Lock:
    """Return the per-job lock, creating it lazily."""
    with _JOB_LOCKS_GUARD:
        lock = _JOB_LOCKS.get(job_id)
        if lock is None:
            lock = threading.Lock()
            _JOB_LOCKS[job_id] = lock
        return lock

def _atomic_write_json(path: str, data: dict) -> None:
    """Write data to path atomically via tmp file + os.replace.

    If the process crashes mid-write, the old file is still intact.
    """
    tmp_path = f"{path}.tmp-{os.getpid()}-{threading.get_ident()}"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, path)

def _persist_clip_url(job_id: str, clip_index: int, new_filename: str) -> None:
    """Update clip URL in both in-memory jobs[] and metadata.json on disk.

    Holds the per-job lock for the entire read-modify-write so concurrent
    callers serialize. Writes via atomic-rename so a crashed process can
    never leave a half-written metadata.json on disk.
    """
    new_url = f"/videos/{job_id}/{new_filename}"
    with _job_lock(job_id):
        # Update in-memory
        job = jobs.get(job_id)
        if job and job.get('result') and 0 <= clip_index < len(job['result'].get('clips', [])):
            job['result']['clips'][clip_index]['video_url'] = new_url

        # Update on-disk metadata.json
        try:
            json_files = glob.glob(os.path.join(OUTPUT_DIR, job_id, "*_metadata.json"))
            if json_files:
                with open(json_files[0], 'r') as f:
                    data = json.load(f)
                clips = data.get('shorts', [])
                if 0 <= clip_index < len(clips):
                    clips[clip_index]['video_url'] = new_url
                    data['shorts'] = clips
                    _atomic_write_json(json_files[0], data)
        except Exception as exc:
            print(f"⚠️ Failed to update metadata.json for clip url: {exc}")

# ── Application State ─────────────────────────────────────────────────────
job_queue = asyncio.Queue()
class JobsDict(dict):
    def __contains__(self, key):
        if dict.__contains__(self, key):
            return True
        return ensure_job_in_memory(key)
        
    def get(self, key, default=None):
        if key in self:
            return dict.__getitem__(self, key)
        return default
        
    def __getitem__(self, key):
        if key in self:
            return dict.__getitem__(self, key)
        raise KeyError(key)

jobs = JobsDict()
thumbnail_sessions: Dict[str, Dict] = {}
publish_jobs: Dict[str, Dict] = {}  # {publish_id: {status, result, error}}
# Semester to limit concurrency to MAX_CONCURRENT_JOBS
concurrency_semaphore = asyncio.Semaphore(MAX_CONCURRENT_JOBS)

def _relocate_root_job_artifacts(job_id: str, job_output_dir: str) -> bool:
    """
    Backward-compat rescue:
    If main.py accidentally wrote metadata/clips into OUTPUT_DIR root (e.g. output/<jobid>_...),
    move them into output/<job_id>/ so the API can find and serve them.
    """
    try:
        os.makedirs(job_output_dir, exist_ok=True)
        root = OUTPUT_DIR
        pattern = os.path.join(root, f"{job_id}_*_metadata.json")
        meta_candidates = sorted(glob.glob(pattern), key=lambda p: os.path.getmtime(p), reverse=True)
        if not meta_candidates:
            return False

        # Move the newest metadata and its associated clips.
        metadata_path = meta_candidates[0]
        base_name = os.path.basename(metadata_path).replace("_metadata.json", "")

        # Move metadata
        dest_metadata = os.path.join(job_output_dir, os.path.basename(metadata_path))
        if os.path.abspath(metadata_path) != os.path.abspath(dest_metadata):
            shutil.move(metadata_path, dest_metadata)

        # Move any clips that match the same base_name into the job folder
        clip_pattern = os.path.join(root, f"{base_name}_clip_*.mp4")
        for clip_path in glob.glob(clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        # Also move any temp_ clips that might remain
        temp_clip_pattern = os.path.join(root, f"temp_{base_name}_clip_*.mp4")
        for clip_path in glob.glob(temp_clip_pattern):
            dest_clip = os.path.join(job_output_dir, os.path.basename(clip_path))
            if os.path.abspath(clip_path) != os.path.abspath(dest_clip):
                shutil.move(clip_path, dest_clip)

        return True
    except Exception:
        return False
async def cleanup_jobs():
    """Background task to remove old files based on project retention settings."""
    print("🧹 Cleanup task started.")
    while True:
        try:
            await asyncio.sleep(300) # Check every 5 minutes
            now = time.time()
            
            conn = _db_conn()
            projects = conn.execute("SELECT * FROM projects").fetchall()
            
            for proj in projects:
                proj_dict = dict(proj)
                retention_seconds = proj_dict.get("retention_days", 7) * 24 * 3600
                cutoff = now - retention_seconds
                
                # Cleanup videos in this project
                vids = conn.execute("SELECT id FROM videos WHERE project_id = ? AND created_at < ?", (proj_dict["id"], cutoff)).fetchall()
                for vid in vids:
                    vid_id = vid["id"]
                    # Delete MP4 files in video output dir
                    video_dir = os.path.join(OUTPUT_DIR, vid_id)
                    if os.path.isdir(video_dir):
                        for f in os.listdir(video_dir):
                            if f.endswith(".mp4"):
                                try:
                                    os.remove(os.path.join(video_dir, f))
                                    print(f"🧹 Cleaned up video file: {f}")
                                except Exception:
                                    pass
                    # Delete files in UPLOAD_DIR
                    for filename in os.listdir(UPLOAD_DIR):
                        if filename.startswith(vid_id) and filename.endswith(".mp4"):
                            try:
                                os.remove(os.path.join(UPLOAD_DIR, filename))
                                print(f"🧹 Cleaned up upload file: {filename}")
                            except Exception:
                                pass
                                
                # Cleanup clip jobs in this project
                cjs = conn.execute("SELECT id FROM clip_jobs WHERE project_id = ? AND created_at < ?", (proj_dict["id"], cutoff)).fetchall()
                for cj in cjs:
                    cj_id = cj["id"]
                    job_dir = os.path.join(OUTPUT_DIR, cj_id)
                    if os.path.isdir(job_dir):
                        for f in os.listdir(job_dir):
                            if f.endswith(".mp4"):
                                try:
                                    os.remove(os.path.join(job_dir, f))
                                    print(f"🧹 Cleaned up clip file: {f}")
                                except Exception:
                                    pass

            # Cleanup SaaSShorts jobs from memory
            try:
                saas_expired = [
                    jid for jid, jdata in list(saas_jobs.items())
                    if jdata.get("status") in ("completed", "failed")
                    and jdata.get("output_dir")
                    and os.path.isdir(jdata["output_dir"])
                    and now - os.path.getmtime(jdata["output_dir"]) > JOB_RETENTION_SECONDS
                ]
                for jid in saas_expired:
                    del saas_jobs[jid]
            except NameError:
                pass

            conn.close()
        except Exception as e:
            print(f"⚠️ Cleanup error: {e}")

async def process_queue():
    """Background worker to process jobs from the queue with concurrency limit."""
    print(f"🚀 Job Queue Worker started with {MAX_CONCURRENT_JOBS} concurrent slots.")
    while True:
        try:
            # Wait for a job
            job_id = await job_queue.get()
            
            # Acquire semaphore slot (waits if max jobs are running)
            await concurrency_semaphore.acquire()
            print(f"🔄 Acquired slot for job: {job_id}")

            # Process in background task to not block the loop (allowing other slots to fill)
            asyncio.create_task(run_job_wrapper(job_id))
            
        except Exception as e:
            print(f"❌ Queue dispatch error: {e}")
            await asyncio.sleep(1)

async def run_job_wrapper(job_id):
    """Wrapper to run job and release semaphore"""
    try:
        job = jobs.get(job_id)
        if job:
            await run_job(job_id, job)
    except Exception as e:
         print(f"❌ Job wrapper error {job_id}: {e}")
    finally:
        # Always release semaphore and mark queue task done
        concurrency_semaphore.release()
        job_queue.task_done()
        print(f"✅ Released slot for job: {job_id}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    init_db()
    # Start worker and cleanup
    worker_task = asyncio.create_task(process_queue())
    cleanup_task = asyncio.create_task(cleanup_jobs())
    yield

app = FastAPI(lifespan=lifespan)

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files for serving videos
app.mount("/videos", StaticFiles(directory=OUTPUT_DIR), name="videos")

# Mount static files for serving thumbnails
THUMBNAILS_DIR = os.path.join(OUTPUT_DIR, "thumbnails")
os.makedirs(THUMBNAILS_DIR, exist_ok=True)
app.mount("/thumbnails", StaticFiles(directory=THUMBNAILS_DIR), name="thumbnails")

class ProcessRequest(BaseModel):
    url: str

def enqueue_output(out, job_id):
    """Reads output from a subprocess and appends it to jobs logs."""
    try:
        for line in iter(out.readline, b''):
            decoded_line = line.decode('utf-8').strip()
            if decoded_line:
                print(f"📝 [Job Output] {decoded_line}")
                if job_id in jobs:
                    jobs[job_id]['logs'].append(decoded_line)
    except Exception as e:
        print(f"Error reading output for job {job_id}: {e}")
    finally:
        out.close()

async def run_job(job_id, job_data):
    """Executes the subprocess for a specific job."""
    
    cmd = job_data['cmd']
    env = job_data['env']
    output_dir = job_data['output_dir']
    job_type = job_data.get('type', 'legacy')
    
    jobs[job_id]['status'] = 'processing'
    jobs[job_id]['logs'].append("Job started by worker.")
    
    if job_type == 'video_analysis':
        update_video(job_id, status='analyzing')
    elif job_type == 'clip_generation':
        update_clip_job(job_id, status='processing')
    else:
        save_job(job_id, status='processing')
        
    print(f"🎬 [run_job] Executing command for {job_id} ({job_type}): {' '.join(cmd)}")
    
    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, # Merge stderr to stdout
            env=env,
            cwd=os.getcwd()
        )
        
        t_log = threading.Thread(target=enqueue_output, args=(process.stdout, job_id))
        t_log.daemon = True
        t_log.start()
        
        while process.poll() is None:
            await asyncio.sleep(2)
            
            # Legacy/Clips progress updates
            if job_type == 'clip_generation' or job_type == 'legacy':
                try:
                    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
                    if json_files:
                        target_json = json_files[0]
                        if os.path.getsize(target_json) > 0:
                            with open(target_json, 'r') as f:
                                data = json.load(f)
                                
                            clips = data.get('shorts', [])
                            cost_analysis = data.get('cost_analysis')
                            
                            ready_clips = []
                            for i, clip in enumerate(clips):
                                 # clip_generation uses {job_id}_clip_{i+1}.mp4
                                 # legacy uses {base_name}_clip_{i+1}.mp4
                                 if job_type == 'clip_generation':
                                     clip_filename = f"{job_id}_clip_{i+1}.mp4"
                                 else:
                                     base_name = os.path.basename(target_json).replace('_metadata.json', '')
                                     clip_filename = f"{base_name}_clip_{i+1}.mp4"
                                 clip_path = os.path.join(output_dir, clip_filename)
                                 if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
                                     clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
                                     ready_clips.append(clip)
                            
                            if ready_clips:
                                 jobs[job_id]['result'] = {'clips': ready_clips, 'cost_analysis': cost_analysis}
                except Exception:
                    pass

        returncode = process.returncode
        
        if returncode == 0:
            if job_type == 'video_analysis':
                transcript_json = None
                dossier_text = None
                duration_seconds = 0.0
                
                transcript_path = os.path.join(output_dir, "transcript.json")
                if os.path.exists(transcript_path):
                    try:
                        with open(transcript_path, 'r') as f:
                            transcript_data = json.load(f)
                            transcript_json = json.dumps(transcript_data)
                            duration_seconds = transcript_data.get("duration_seconds", 0.0)
                    except Exception as ex:
                        print(f"Error reading transcript: {ex}")
                
                dossier_path = os.path.join(output_dir, "dossier.md")
                if os.path.exists(dossier_path):
                    try:
                        with open(dossier_path, 'r') as f:
                            dossier_text = f.read()
                    except Exception as ex:
                        print(f"Error reading dossier: {ex}")
                
                update_video(job_id, status='ready', completed_at=time.time(),
                             transcript_json=transcript_json, dossier_text=dossier_text,
                             duration_seconds=duration_seconds)
                
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['result'] = {
                    'transcript': json.loads(transcript_json) if transcript_json else None,
                    'dossier': dossier_text
                }
                jobs[job_id]['logs'].append("Analysis finished successfully.")
                
            elif job_type == 'clip_generation':
                json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
                if json_files:
                    target_json = json_files[0]
                    try:
                        with open(target_json, 'r') as f:
                            data = json.load(f)
                        clips = data.get('shorts', [])
                        cost_analysis = data.get('cost_analysis')
                        # Clip files are named {job_id}_clip_{i+1}.mp4 by main.py
                        for i, clip in enumerate(clips):
                            clip_filename = f"{job_id}_clip_{i+1}.mp4"
                            clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
                        
                        update_clip_job(job_id, status='completed', completed_at=time.time(),
                                        clip_count=len(clips), result_json=json.dumps({'clips': clips, 'cost_analysis': cost_analysis}))
                        
                        jobs[job_id]['status'] = 'completed'
                        jobs[job_id]['result'] = {'clips': clips, 'cost_analysis': cost_analysis}
                        jobs[job_id]['logs'].append("Clipping finished successfully.")
                    except Exception as ex:
                        update_clip_job(job_id, status='failed', error=str(ex))
                        jobs[job_id]['status'] = 'failed'
                        jobs[job_id]['logs'].append(f"Error parsing metadata: {str(ex)}")
                else:
                    update_clip_job(job_id, status='failed', error="No metadata file generated.")
                    jobs[job_id]['status'] = 'failed'
                    jobs[job_id]['logs'].append("No metadata file generated.")
                    
            else:
                jobs[job_id]['status'] = 'completed'
                jobs[job_id]['logs'].append("Process finished successfully.")
                
                loop = asyncio.get_event_loop()
                loop.run_in_executor(None, upload_job_artifacts, output_dir, job_id)
                
                json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
                if not json_files:
                    if _relocate_root_job_artifacts(job_id, output_dir):
                        json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
                if json_files:
                    target_json = json_files[0] 
                    with open(target_json, 'r') as f:
                        data = json.load(f)
                    
                    base_name = os.path.basename(target_json).replace('_metadata.json', '')
                    clips = data.get('shorts', [])
                    cost_analysis = data.get('cost_analysis')

                    for i, clip in enumerate(clips):
                         clip_filename = f"{base_name}_clip_{i+1}.mp4"
                         clip['video_url'] = f"/videos/{job_id}/{clip_filename}"
                    
                    jobs[job_id]['result'] = {'clips': clips, 'cost_analysis': cost_analysis}
                    save_job(job_id, status='completed', completed_at=time.time(),
                             clip_count=len(clips), result_json=json.dumps({'clips': clips, 'cost_analysis': cost_analysis}))
                else:
                     jobs[job_id]['status'] = 'failed'
                     jobs[job_id]['logs'].append("No metadata file generated.")
                     save_job(job_id, status='failed', error="No metadata file generated.")
        else:
            if job_type == 'video_analysis':
                update_video(job_id, status='failed', error=f"Exit code {returncode}")
            elif job_type == 'clip_generation':
                update_clip_job(job_id, status='failed', error=f"Exit code {returncode}")
            else:
                save_job(job_id, status='failed', error=f"Exit code {returncode}")
                
            jobs[job_id]['status'] = 'failed'
            jobs[job_id]['logs'].append(f"Process failed with exit code {returncode}")
            
    except Exception as e:
        if job_type == 'video_analysis':
            update_video(job_id, status='failed', error=str(e))
        elif job_type == 'clip_generation':
            update_clip_job(job_id, status='failed', error=str(e))
        else:
            save_job(job_id, status='failed', error=str(e))
            
        jobs[job_id]['status'] = 'failed'
        save_job(job_id, status='failed', error=str(e))

@app.get("/api/config")
async def get_config():
    return {"youtubeUrlEnabled": not DISABLE_YOUTUBE_URL}

@app.get("/api/jobs")
async def list_jobs_endpoint(limit: int = 50, offset: int = 0):
    """List all jobs (newest first) with pagination."""
    jobs_list = list_jobs(limit=limit, offset=offset)
    # Parse result_json back to dict for each job
    for j in jobs_list:
        if j.get("result_json"):
            try:
                j["result"] = json.loads(j["result_json"])
            except json.JSONDecodeError:
                j["result"] = None
        # Check if output files still exist on disk
        job_dir = os.path.join(OUTPUT_DIR, j["id"])
        j["files_exist"] = os.path.isdir(job_dir) and len(os.listdir(job_dir)) > 0
    return {"jobs": jobs_list, "total": len(jobs_list)}

@app.get("/api/jobs/{job_id}")
async def get_job_endpoint(job_id: str):
    """Get full details for a single job."""
    job = get_job(job_id)
    if not job:
        # Fall back to in-memory dict for very recent jobs not yet persisted
        if job_id in jobs:
            mem_job = jobs[job_id]
            return {
                "id": job_id,
                "status": mem_job.get("status"),
                "logs": mem_job.get("logs", [])[-20:],  # Last 20 log lines
                "result": mem_job.get("result"),
                "files_exist": os.path.isdir(mem_job.get("output_dir", "")),
            }
        raise HTTPException(status_code=404, detail="Job not found")
    
    if job.get("result_json"):
        try:
            job["result"] = json.loads(job["result_json"])
        except json.JSONDecodeError:
            job["result"] = None
    
    # Check if files still exist
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    job["files_exist"] = os.path.isdir(job_dir) and len(os.listdir(job_dir)) > 0
    
    # Add recent logs from in-memory if available
    if job_id in jobs:
        job["logs"] = jobs[job_id].get("logs", [])[-20:]
    
    return job

@app.post("/api/process")
async def process_endpoint(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    acknowledged: Optional[str] = Form(None)
):
    api_key = request.headers.get("X-Gemini-Key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    ack_flag = str(acknowledged).lower() in ("1", "true", "yes")

    # Handle JSON body manually for URL payload
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        url = body.get("url")
        ack_flag = bool(body.get("acknowledged"))

    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    if not ack_flag:
        raise HTTPException(status_code=400, detail="You must confirm you own the content or have rights to process it.")

    if url and DISABLE_YOUTUBE_URL:
        raise HTTPException(status_code=403, detail="YouTube URL ingest is disabled on this deployment. Please upload a file you own.")

    # Capture attestation context for legal record (IP + timestamp + UA)
    client_ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        client_ip = fwd.split(",")[0].strip()
    user_agent = request.headers.get("user-agent", "")
    attestation = {
        "acknowledged": True,
        "ip": client_ip,
        "user_agent": user_agent,
        "timestamp": time.time(),
        "source": "url" if url else "file",
    }

    job_id = str(uuid.uuid4())
    job_output_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_output_dir, exist_ok=True)

    # Prepare Command
    cmd = ["python", "-u", "main.py"] # -u for unbuffered
    env = os.environ.copy()
    env["GEMINI_API_KEY"] = api_key # Override with key from request

    if url:
        cmd.extend(["-u", url])
    else:
        # Save uploaded file with size limit check
        input_path = os.path.join(UPLOAD_DIR, f"{job_id}_{file.filename}")

        # Read file in chunks to check size
        size = 0
        limit_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

        with open(input_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # Read 1MB chunks
                size += len(content)
                if size > limit_bytes:
                    os.remove(input_path)
                    shutil.rmtree(job_output_dir)
                    raise HTTPException(status_code=413, detail=f"File too large. Max size {MAX_FILE_SIZE_MB}MB")
                buffer.write(content)

        cmd.extend(["-i", input_path])

    cmd.extend(["-o", job_output_dir])

    print(f"[attestation] job={job_id} ip={attestation['ip']} source={attestation['source']} ack=true")

    # Enqueue Job
    jobs[job_id] = {
        'status': 'queued',
        'logs': [f"Job {job_id} queued."],
        'cmd': cmd,
        'env': env,
        'output_dir': job_output_dir,
        'attestation': attestation
    }

    # Persist to database
    save_job(
        job_id,
        source_type=attestation['source'],
        source_url=url,
        source_filename=file.filename if file else None,
        status='queued',
        created_at=attestation['timestamp']
    )

    await job_queue.put(job_id)

    return {"job_id": job_id, "status": "queued"}

@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[job_id]
    return {
        "status": job['status'],
        "logs": job['logs'],
        "result": job.get('result')
    }

class ProjectCreate(BaseModel):
    name: str
    dossier_enabled: bool = False
    retention_days: int = 7
    content_type: str = 'general'
    custom_instructions: Optional[str] = None

class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    dossier_enabled: Optional[bool] = None
    retention_days: Optional[int] = None
    content_type: Optional[str] = None
    custom_instructions: Optional[str] = None

class ClipJobCreate(BaseModel):
    video_ids: List[str]
    detection_prompt: Optional[str] = None

@app.post("/api/projects")
async def api_create_project(project: ProjectCreate):
    return create_project(
        project.name,
        project.dossier_enabled,
        project.retention_days,
        project.content_type,
        project.custom_instructions
    )

@app.get("/api/projects")
async def api_list_projects():
    return {"projects": list_projects()}

@app.get("/api/projects/{project_id}")
async def api_get_project(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    return p

@app.put("/api/projects/{project_id}")
async def api_update_project(project_id: str, proj: ProjectUpdate):
    p = get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    fields = {k: v for k, v in proj.dict().items() if v is not None}
    return update_project(project_id, **fields)

@app.delete("/api/projects/{project_id}")
async def api_delete_project(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    delete_project(project_id)
    return {"status": "success"}

@app.post("/api/projects/{project_id}/videos")
async def api_analyze_video(
    project_id: str,
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    acknowledged: Optional[str] = Form(None)
):
    p = get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
        
    api_key = request.headers.get("X-Gemini-Key")
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    ack_flag = str(acknowledged).lower() in ("1", "true", "yes")
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        body = await request.json()
        url = body.get("url")
        ack_flag = bool(body.get("acknowledged"))

    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    if not ack_flag:
        raise HTTPException(status_code=400, detail="You must confirm you own the content or have rights to process it.")

    if url and DISABLE_YOUTUBE_URL:
        raise HTTPException(status_code=403, detail="YouTube URL ingest is disabled on this deployment. Please upload a file you own.")

    # Capture attestation context for legal record (IP + timestamp + UA)
    client_ip = request.client.host if request.client else "unknown"
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        client_ip = fwd.split(",")[0].strip()
    user_agent = request.headers.get("user-agent", "")
    attestation = {
        "acknowledged": True,
        "ip": client_ip,
        "user_agent": user_agent,
        "timestamp": time.time(),
        "source": "url" if url else "file",
    }

    video_id = str(uuid.uuid4())
    video_output_dir = os.path.join(OUTPUT_DIR, video_id)
    os.makedirs(video_output_dir, exist_ok=True)

    # Prepare Command
    cmd = ["python", "-u", "main.py", "--analyze"]
    env = os.environ.copy()
    env["GEMINI_API_KEY"] = api_key # Override with key from request

    if url:
        cmd.extend(["-u", url])
    else:
        # Save uploaded file with size limit check
        input_path = os.path.join(UPLOAD_DIR, f"{video_id}_{file.filename}")

        # Read file in chunks to check size
        size = 0
        limit_bytes = MAX_FILE_SIZE_MB * 1024 * 1024

        with open(input_path, "wb") as buffer:
            while content := await file.read(1024 * 1024): # Read 1MB chunks
                size += len(content)
                if size > limit_bytes:
                    os.remove(input_path)
                    shutil.rmtree(video_output_dir)
                    raise HTTPException(status_code=413, detail=f"File too large. Max size {MAX_FILE_SIZE_MB}MB")
                buffer.write(content)

        cmd.extend(["-i", input_path])

    cmd.extend(["-o", video_output_dir])
    if p["dossier_enabled"]:
        cmd.append("--dossier")
    if p.get("content_type"):
        cmd.extend(["--content-type", p["content_type"]])

    # Create the database record
    conn = _db_conn()
    conn.execute("""
        INSERT INTO videos (id, project_id, source_type, source_url, source_filename, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (video_id, project_id, attestation["source"], url, file.filename if file else None, "analyzing", time.time()))
    conn.commit()
    conn.close()

    # Enqueue Job
    jobs[video_id] = {
        'type': 'video_analysis',
        'status': 'queued',
        'logs': [f"Video analysis queued for {video_id}."],
        'cmd': cmd,
        'env': env,
        'output_dir': video_output_dir,
        'attestation': attestation
    }

    await job_queue.put(video_id)
    return {"video_id": video_id, "status": "queued"}

@app.get("/api/projects/{project_id}/videos")
async def api_list_project_videos(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    vids = list_videos(project_id)
    for v in vids:
        vid_id = v["id"]
        if vid_id in jobs:
            v["logs"] = jobs[vid_id].get("logs", [])[-10:]
            if v["status"] == "analyzing":
                v["status"] = jobs[vid_id].get("status", "analyzing")
    return {"videos": vids}

@app.get("/api/projects/{project_id}/videos/{video_id}/status")
async def get_video_status(project_id: str, video_id: str):
    vid = get_video(video_id)
    if not vid:
        raise HTTPException(status_code=404, detail="Video not found")
    
    logs = []
    if video_id in jobs:
        logs = jobs[video_id].get("logs", [])[-20:]
        status = jobs[video_id].get("status", vid["status"])
    else:
        status = vid["status"]
        logs = [f"Analysis {status}."]
    
    return {
        "status": status,
        "logs": logs,
        "video": vid
    }

@app.get("/api/videos/{video_id}")
async def api_get_video_detail(video_id: str):
    vid = get_video(video_id)
    if not vid:
        raise HTTPException(status_code=404, detail="Video not found")
    
    if vid.get("transcript_json"):
        try:
            vid["transcript"] = json.loads(vid["transcript_json"])
        except Exception:
            vid["transcript"] = None
    else:
        vid["transcript"] = None
        
    return vid

@app.get("/api/videos/{video_id}/transcript")
async def api_get_video_transcript(video_id: str):
    vid = get_video(video_id)
    if not vid or not vid.get("transcript_json"):
        raise HTTPException(status_code=404, detail="Transcript not found")
    return json.loads(vid["transcript_json"])

@app.get("/api/videos/{video_id}/dossier")
async def api_get_video_dossier(video_id: str):
    vid = get_video(video_id)
    if not vid or not vid.get("dossier_text"):
        raise HTTPException(status_code=404, detail="Dossier not found")
    return {"dossier": vid["dossier_text"]}

@app.delete("/api/videos/{video_id}")
async def api_delete_video(video_id: str):
    vid = get_video(video_id)
    if not vid:
        raise HTTPException(status_code=404, detail="Video not found")
    delete_video(video_id)
    return {"status": "success"}

@app.post("/api/projects/{project_id}/clip")
async def generate_clips(project_id: str, req: ClipJobCreate, request: Request):
    p = get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
        
    api_key = request.headers.get("X-Gemini-Key") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing Gemini API Key")

    video_paths = []
    transcript_paths = []
    dossier_paths = []
    
    for vid_id in req.video_ids:
        vid = get_video(vid_id)
        if not vid:
            raise HTTPException(status_code=404, detail=f"Video {vid_id} not found")
        if vid["status"] != "ready":
            raise HTTPException(status_code=400, detail=f"Video {vid_id} is not analyzed yet (status: {vid['status']})")
            
        vpath = get_video_file_path(vid_id)
        if not vpath or not os.path.exists(vpath):
            raise HTTPException(status_code=404, detail=f"Video file for {vid_id} not found on disk")
            
        video_paths.append(vpath)
        
        tpath = os.path.join(OUTPUT_DIR, vid_id, "transcript.json")
        if not os.path.exists(tpath):
            raise HTTPException(status_code=404, detail=f"Transcript file for {vid_id} not found on disk")
        transcript_paths.append(tpath)
        
        dpath = os.path.join(OUTPUT_DIR, vid_id, "dossier.md")
        if os.path.exists(dpath):
            dossier_paths.append(dpath)

    clip_job = create_clip_job(project_id, req.video_ids)
    clip_job_id = clip_job["id"]
    
    clip_output_dir = os.path.join(OUTPUT_DIR, clip_job_id)
    os.makedirs(clip_output_dir, exist_ok=True)
    
    cmd = ["python", "-u", "main.py", "--clip"]
    env = os.environ.copy()
    env["GEMINI_API_KEY"] = api_key
    
    cmd.extend(["-o", clip_output_dir])
    
    cmd.append("-i")
    cmd.extend(video_paths)
    
    cmd.append("--transcript")
    cmd.extend(transcript_paths)
    
    if dossier_paths:
        cmd.append("--dossier")
        cmd.extend(dossier_paths)

    if p.get("content_type"):
        cmd.extend(["--content-type", p["content_type"]])

    # Build the final prompt: project custom_instructions first, then per-job detection_prompt
    prompt_parts = []
    if p.get("custom_instructions"):
        prompt_parts.append(p["custom_instructions"].strip())
    if req.detection_prompt:
        prompt_parts.append(req.detection_prompt.strip())
    if prompt_parts:
        cmd.extend(["--prompt", "\n\n".join(prompt_parts)])

    jobs[clip_job_id] = {
        'type': 'clip_generation',
        'status': 'queued',
        'logs': [f"Clip job {clip_job_id} queued."],
        'cmd': cmd,
        'env': env,
        'output_dir': clip_output_dir
    }
    
    await job_queue.put(clip_job_id)
    return {"clip_job_id": clip_job_id, "status": "queued"}

@app.get("/api/projects/{project_id}/clips")
async def api_list_project_clips(project_id: str):
    p = get_project(project_id)
    if not p:
        raise HTTPException(status_code=404, detail="Project not found")
    cjs = list_clip_jobs(project_id)
    for cj in cjs:
        cj_id = cj["id"]
        if cj_id in jobs:
            cj["logs"] = jobs[cj_id].get("logs", [])[-10:]
            if cj["status"] == "queued" or cj["status"] == "processing":
                cj["status"] = jobs[cj_id].get("status", cj["status"])
        if cj.get("result_json"):
            try:
                cj["result"] = json.loads(cj["result_json"])
            except Exception:
                cj["result"] = None
    return {"clip_jobs": cjs}

@app.get("/api/clip-jobs/{clip_job_id}")
async def api_get_clip_job_detail(clip_job_id: str):
    cj = get_clip_job(clip_job_id)
    if not cj:
        if clip_job_id in jobs:
            mem_job = jobs[clip_job_id]
            return {
                "id": clip_job_id,
                "status": mem_job.get("status"),
                "logs": mem_job.get("logs", [])[-20:],
                "result": mem_job.get("result"),
                "files_exist": os.path.isdir(mem_job.get("output_dir", ""))
            }
        raise HTTPException(status_code=404, detail="Clip job not found")
    
    if cj.get("result_json"):
        try:
            cj["result"] = json.loads(cj["result_json"])
        except Exception:
            cj["result"] = None
            
    job_dir = os.path.join(OUTPUT_DIR, clip_job_id)
    cj["files_exist"] = os.path.isdir(job_dir) and len(os.listdir(job_dir)) > 0
    
    if clip_job_id in jobs:
        cj["logs"] = jobs[clip_job_id].get("logs", [])[-20:]
        cj["status"] = jobs[clip_job_id].get("status", cj["status"])
        if jobs[clip_job_id].get("result"):
            cj["result"] = jobs[clip_job_id].get("result")
    else:
        cj["logs"] = [f"Clip job {cj['status']}."]
        
    return cj

@app.get("/api/clip-jobs/{clip_job_id}/clips")
async def api_get_clip_job_clips(clip_job_id: str):
    cj = get_clip_job(clip_job_id)
    result = None
    if cj and cj.get("result_json"):
        try:
            result = json.loads(cj["result_json"])
        except Exception:
            pass
    elif clip_job_id in jobs and jobs[clip_job_id].get("result"):
        result = jobs[clip_job_id]["result"]
        
    if not result or not result.get("clips"):
        raise HTTPException(status_code=404, detail="Clips not found or job not completed yet")
        
    return result

from editor import VideoEditor
from subtitles import generate_srt, burn_subtitles, generate_srt_from_video
from hooks import add_hook_to_video
from translate import translate_video, get_supported_languages
from thumbnail import analyze_video_for_titles, refine_titles, generate_thumbnail, generate_youtube_description

class EditRequest(BaseModel):
    job_id: str
    clip_index: int
    api_key: Optional[str] = None
    input_filename: Optional[str] = None

@app.post("/api/edit")
async def edit_clip(
    req: EditRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    # Determine API Key
    final_api_key = req.api_key or x_gemini_key or os.environ.get("GEMINI_API_KEY")
    
    if not final_api_key:
        raise HTTPException(status_code=400, detail="Missing Gemini API Key (Header or Body)")

    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[req.job_id]
    if 'result' not in job or 'clips' not in job['result']:
        raise HTTPException(status_code=400, detail="Job result not available")
        
    try:
        # Resolve Input Path: Prefer explict input_filename from frontend (chaining edits)
        if req.input_filename:
            # Security: Ensure just a filename, no paths
            safe_name = os.path.basename(req.input_filename)
            input_path = os.path.join(OUTPUT_DIR, req.job_id, safe_name)
            filename = safe_name
        else:
            # Fallback to original clip
            clip = job['result']['clips'][req.clip_index]
            filename = clip['video_url'].split('/')[-1]
            input_path = os.path.join(OUTPUT_DIR, req.job_id, filename)
        
        if not os.path.exists(input_path):
             raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

        # Define output path for edited video
        edited_filename = f"edited_{filename}"
        output_path = os.path.join(OUTPUT_DIR, req.job_id, edited_filename)
        
        # Run editing in a thread to avoid blocking main loop
        # Since VideoEditor uses blocking calls (subprocess, API wait)
        def run_edit():
            editor = VideoEditor(api_key=final_api_key)
            
            # SAFE FILE RENAMING STRATEGY (Avoid UnicodeEncodeError in Docker)
            # Create a safe ASCII filename in the same directory
            safe_filename = f"temp_input_{req.job_id}.mp4"
            safe_input_path = os.path.join(OUTPUT_DIR, req.job_id, safe_filename)
            
            # Copy original file to safe path
            # (Copy is safer than rename if something crashes, we keep original)
            shutil.copy(input_path, safe_input_path)
            
            try:
                # 1. Upload (using safe path)
                vid_file = editor.upload_video(safe_input_path)
                
                # 2. Get duration
                import cv2
                cap = cv2.VideoCapture(safe_input_path)
                fps = cap.get(cv2.CAP_PROP_FPS)
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                duration = frame_count / fps if fps else 0
                cap.release()
                
                # Load transcript from metadata
                transcript = None
                try:
                    meta_files = glob.glob(os.path.join(OUTPUT_DIR, req.job_id, "*_metadata.json"))
                    if meta_files:
                        with open(meta_files[0], 'r') as f:
                            data = json.load(f)
                            transcript = data.get('transcript')
                except Exception as e:
                    print(f"⚠️ Could not load transcript for editing context: {e}")

                # 3. Get Plan (Filter String)
                filter_data = editor.get_ffmpeg_filter(vid_file, duration, fps=fps, width=width, height=height, transcript=transcript)
                
                # 4. Apply
                # Use safe output name first
                safe_output_path = os.path.join(OUTPUT_DIR, req.job_id, f"temp_output_{req.job_id}.mp4")
                editor.apply_edits(safe_input_path, safe_output_path, filter_data)
                
                # Move result to final destination (rename works even if dest name has unicode if filesystem supports it, 
                # but python might still struggle if locale is broken? No, os.rename usually handles it better than subprocess args)
                # Actually, output_path is defined above: f"edited_{filename}"
                # If filename has unicode, output_path has unicode.
                # Let's hope shutil.move / os.rename works.
                if os.path.exists(safe_output_path):
                    shutil.move(safe_output_path, output_path)
                
                return filter_data
            finally:
                # Cleanup temp safe input
                if os.path.exists(safe_input_path):
                    os.remove(safe_input_path)

        # Run in thread pool
        loop = asyncio.get_event_loop()
        plan = await loop.run_in_executor(None, run_edit)
        
        # Update clip URL in the job result? 
        # Or return new URL and let frontend handle it?
        # Updating job result allows persistence if page refreshes.
        
        new_video_url = f"/videos/{req.job_id}/{edited_filename}"
        
        # Start a new "edited" clip entry or just update the current one?
        # Let's update the current one's video_url but keep backup?
        # Or return the new URL to the frontend to display.
        
        return {
            "success": True, 
            "new_video_url": new_video_url,
            "edit_plan": plan
        }

    except Exception as e:
        print(f"❌ Edit Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class SubtitleRequest(BaseModel):
    job_id: str
    clip_index: int
    position: str = "bottom" # top, middle, bottom
    font_size: int = 16
    font_name: str = "Verdana"
    font_color: str = "#FFFFFF"
    border_color: str = "#000000"
    border_width: int = 2
    bg_color: str = "#000000"
    bg_opacity: float = 0.0
    input_filename: Optional[str] = None


@app.get("/api/clip/{job_id}/{clip_index}/transcript")
async def get_clip_transcript(job_id: str, clip_index: int):
    """Return word-level captions for a specific clip, formatted for Remotion."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    output_dir = os.path.join(OUTPUT_DIR, job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))

    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")

    with open(json_files[0], 'r') as f:
        data = json.load(f)

    transcript = data.get('transcript')
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript not found in metadata")

    clips = data.get('shorts', [])
    if clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[clip_index]
    clip_start = clip_data.get('start', 0)
    clip_end = clip_data.get('end', 0)

    # Extract words within clip range and convert to CaptionWord format
    captions = []
    for segment in transcript.get('segments', []):
        for word_info in segment.get('words', []):
            if word_info['end'] > clip_start and word_info['start'] < clip_end:
                captions.append({
                    "text": word_info.get('word', '').strip(),
                    "startMs": int((max(0, word_info['start'] - clip_start)) * 1000),
                    "endMs": int((max(0, word_info['end'] - clip_start)) * 1000),
                })

    duration_sec = clip_end - clip_start

    return {
        "captions": captions,
        "durationSec": duration_sec,
        "language": transcript.get('language', 'en'),
    }


# --- Remotion Render Proxy ---
RENDER_SERVICE_URL = os.getenv("RENDER_SERVICE_URL", "http://renderer:3100")

@app.post("/api/render")
async def proxy_render(request: Request):
    """Proxy render requests to the Node.js Remotion render service."""
    import httpx
    body = await request.json()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{RENDER_SERVICE_URL}/render", json=body)
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Render service unavailable: {e}")

@app.get("/api/render/{render_id}")
async def proxy_render_status(render_id: str):
    """Proxy render status polling to the Node.js Remotion render service."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{RENDER_SERVICE_URL}/render/{render_id}")
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Render service unavailable: {e}")


class EffectsGenerateRequest(BaseModel):
    job_id: str
    clip_index: int
    input_filename: Optional[str] = None

@app.post("/api/effects/generate")
async def generate_effects_config(
    req: EffectsGenerateRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Generate structured EffectsConfig JSON for Remotion rendering via Gemini AI."""
    final_api_key = x_gemini_key or os.environ.get("GEMINI_API_KEY")

    if not final_api_key:
        raise HTTPException(status_code=400, detail="Missing Gemini API Key (Header)")

    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[req.job_id]
    if 'result' not in job or 'clips' not in job['result']:
        raise HTTPException(status_code=400, detail="Job result not available")

    try:
        # Resolve input path
        if req.input_filename:
            safe_name = os.path.basename(req.input_filename)
            input_path = os.path.join(OUTPUT_DIR, req.job_id, safe_name)
        else:
            clip = job['result']['clips'][req.clip_index]
            filename = clip['video_url'].split('/')[-1]
            input_path = os.path.join(OUTPUT_DIR, req.job_id, filename)

        if not os.path.exists(input_path):
            raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

        def run_effects_generation():
            editor = VideoEditor(api_key=final_api_key)

            # Create safe ASCII filename to avoid encoding issues
            safe_filename = f"temp_effects_{req.job_id}.mp4"
            safe_input_path = os.path.join(OUTPUT_DIR, req.job_id, safe_filename)
            shutil.copy(input_path, safe_input_path)

            try:
                # Upload video to Gemini
                vid_file = editor.upload_video(safe_input_path)

                # Get video metadata via ffprobe
                probe_cmd = [
                    'ffprobe', '-v', 'error',
                    '-select_streams', 'v:0',
                    '-show_entries', 'stream=width,height,r_frame_rate,duration',
                    '-show_entries', 'format=duration',
                    '-of', 'json',
                    safe_input_path
                ]
                probe_result = subprocess.check_output(probe_cmd).decode().strip()
                probe_data = json.loads(probe_result)

                stream = probe_data.get('streams', [{}])[0]
                width = int(stream.get('width', 1080))
                height = int(stream.get('height', 1920))

                # Parse fps from r_frame_rate (e.g. "30/1")
                r_frame_rate = stream.get('r_frame_rate', '30/1')
                num, den = r_frame_rate.split('/')
                fps = round(int(num) / int(den), 2)

                # Get duration from stream or format
                duration = float(stream.get('duration', 0))
                if duration == 0:
                    duration = float(probe_data.get('format', {}).get('duration', 0))

                # Load transcript from metadata
                transcript = None
                try:
                    meta_files = glob.glob(os.path.join(OUTPUT_DIR, req.job_id, "*_metadata.json"))
                    if meta_files:
                        with open(meta_files[0], 'r') as f:
                            data = json.load(f)
                            transcript = data.get('transcript')
                except Exception as e:
                    print(f"⚠️ Could not load transcript for effects config: {e}")

                # Generate effects config
                effects_config = editor.get_effects_config(
                    vid_file, duration, fps=fps, width=width, height=height, transcript=transcript
                )

                return effects_config
            finally:
                if os.path.exists(safe_input_path):
                    os.remove(safe_input_path)

        loop = asyncio.get_event_loop()
        effects_config = await loop.run_in_executor(None, run_effects_generation)

        if effects_config is None:
            raise HTTPException(status_code=500, detail="Failed to generate effects config from Gemini")

        return {"effects": effects_config}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Effects Generation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/subtitle")
async def add_subtitles(req: SubtitleRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    # Reload job data from disk just in case metadata was updated
    job = jobs[req.job_id]
    
    # We need to access metadata.json to get the transcript
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    
    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")
        
    with open(json_files[0], 'r') as f:
        data = json.load(f)
        
    transcript = data.get('transcript')
    if not transcript:
        raise HTTPException(status_code=400, detail="Transcript not found in metadata. Please process a new video.")
        
    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")
        
    clip_data = clips[req.clip_index]
    
    # Video Path
    if req.input_filename:
        # Use chained file
        filename = os.path.basename(req.input_filename)
    else:
        # Fallback to standard naming
        filename = clip_data.get('video_url', '').split('/')[-1]
        if not filename:
             base_name = os.path.basename(json_files[0]).replace('_metadata.json', '')
             filename = f"{base_name}_clip_{req.clip_index+1}.mp4"
         
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        # Try looking for edited version if url implied it?
        # Just fail if not found.
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")
        
    # Define outputs
    srt_filename = f"subs_{req.clip_index}_{int(time.time())}.srt"
    srt_path = os.path.join(output_dir, srt_filename)
    
    # Output video
    # We create a new file "subtitled_..."
    output_filename = f"subtitled_{filename}"
    output_path = os.path.join(output_dir, output_filename)
    
    try:
        # 1. Generate SRT
        # Check if this is a dubbed video - if so, transcribe it fresh
        is_dubbed = filename.startswith("translated_")

        if is_dubbed:
            print(f"🎙️ Dubbed video detected, transcribing audio for subtitles...")
            def run_transcribe_srt():
                return generate_srt_from_video(input_path, srt_path)

            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(None, run_transcribe_srt)
        else:
            success = generate_srt(transcript, clip_data['start'], clip_data['end'], srt_path)

        if not success:
             raise HTTPException(status_code=400, detail="No words found for this clip range.")

        # 2. Burn Subtitles
        # Run in thread pool
        def run_burn():
             burn_subtitles(input_path, srt_path, output_path,
                           alignment=req.position, fontsize=req.font_size,
                           font_name=req.font_name, font_color=req.font_color,
                           border_color=req.border_color, border_width=req.border_width,
                           bg_color=req.bg_color, bg_opacity=req.bg_opacity)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_burn)
        
    except Exception as e:
        print(f"❌ Subtitle Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    # 3. Update Result and Metadata
    # Update InMemory Jobs
    if req.clip_index < len(job['result']['clips']):
         job['result']['clips'][req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
    
    # Update Metadata on Disk (Persistence)
    try:
        if req.clip_index < len(clips):
            clips[req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
            # Update the main data structure
            data['shorts'] = clips
            
            # Write back atomically
            _atomic_write_json(json_files[0], data)
            print(f"✅ Metadata updated with subtitled video for clip {req.clip_index}")
    except Exception as e:
        print(f"⚠️ Failed to update metadata.json: {e}")
        # Non-critical, but good for persistence

    return {
        "success": True,
        "new_video_url": f"/videos/{req.job_id}/{output_filename}"
    }

class HookRequest(BaseModel):
    job_id: str
    clip_index: int
    text: str
    input_filename: Optional[str] = None
    position: Optional[str] = "top" # top, center, bottom
    size: Optional[str] = "M" # S, M, L

@app.post("/api/hook")
async def add_hook(req: HookRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[req.job_id]
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))
    
    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")
        
    with open(json_files[0], 'r') as f:
        data = json.load(f)
        
    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")
        
    clip_data = clips[req.clip_index]
    
    # Video Path
    if req.input_filename:
        filename = os.path.basename(req.input_filename)
    else:
        filename = clip_data.get('video_url', '').split('/')[-1]
        if not filename:
             base_name = os.path.basename(json_files[0]).replace('_metadata.json', '')
             filename = f"{base_name}_clip_{req.clip_index+1}.mp4"
         
    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")
        
    # Output video
    output_filename = f"hook_{filename}"
    output_path = os.path.join(output_dir, output_filename)
    
    # Map Size to Scale
    size_map = {"S": 0.8, "M": 1.0, "L": 1.3}
    font_scale = size_map.get(req.size, 1.0)
    
    try:
        # Run in thread pool
        def run_hook():
             add_hook_to_video(input_path, req.text, output_path, position=req.position, font_scale=font_scale)
        
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_hook)
        
    except Exception as e:
        print(f"❌ Hook Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
        
    # Update Persistence (Same logic as subtitles)
    # Update InMemory Jobs
    if req.clip_index < len(job['result']['clips']):
         job['result']['clips'][req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
    
    # Update Metadata on Disk
    try:
        if req.clip_index < len(clips):
            clips[req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
            data['shorts'] = clips
            _atomic_write_json(json_files[0], data)
            print(f"✅ Metadata updated with hook video for clip {req.clip_index}")
    except Exception as e:
        print(f"⚠️ Failed to update metadata.json: {e}")

    return {
        "success": True,
        "new_video_url": f"/videos/{req.job_id}/{output_filename}"
    }

class TranslateRequest(BaseModel):
    job_id: str
    clip_index: int
    target_language: str
    source_language: Optional[str] = None
    input_filename: Optional[str] = None

@app.get("/api/translate/languages")
async def get_languages():
    """Return supported languages for translation."""
    return {"languages": get_supported_languages()}

@app.post("/api/translate")
async def translate_clip(
    req: TranslateRequest,
    x_elevenlabs_key: Optional[str] = Header(None, alias="X-ElevenLabs-Key")
):
    """Translate a video clip to a different language using ElevenLabs dubbing."""
    if not x_elevenlabs_key:
        raise HTTPException(status_code=400, detail="Missing X-ElevenLabs-Key header")

    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = jobs[req.job_id]
    output_dir = os.path.join(OUTPUT_DIR, req.job_id)
    json_files = glob.glob(os.path.join(output_dir, "*_metadata.json"))

    if not json_files:
        raise HTTPException(status_code=404, detail="Metadata not found")

    with open(json_files[0], 'r') as f:
        data = json.load(f)

    clips = data.get('shorts', [])
    if req.clip_index >= len(clips):
        raise HTTPException(status_code=404, detail="Clip not found")

    clip_data = clips[req.clip_index]

    # Video Path
    if req.input_filename:
        filename = os.path.basename(req.input_filename)
    else:
        filename = clip_data.get('video_url', '').split('/')[-1]
        if not filename:
             base_name = os.path.basename(json_files[0]).replace('_metadata.json', '')
             filename = f"{base_name}_clip_{req.clip_index+1}.mp4"

    input_path = os.path.join(output_dir, filename)
    if not os.path.exists(input_path):
        raise HTTPException(status_code=404, detail=f"Video file not found: {input_path}")

    # Output video with language suffix
    base, ext = os.path.splitext(filename)
    output_filename = f"translated_{req.target_language}_{base}{ext}"
    output_path = os.path.join(output_dir, output_filename)

    try:
        # Run translation in thread pool (blocking API calls)
        def run_translate():
            return translate_video(
                video_path=input_path,
                output_path=output_path,
                target_language=req.target_language,
                api_key=x_elevenlabs_key,
                source_language=req.source_language,
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, run_translate)

    except Exception as e:
        print(f"❌ Translation Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

    # Update InMemory Jobs
    if req.clip_index < len(job['result']['clips']):
         job['result']['clips'][req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"

    # Update Metadata on Disk
    try:
        if req.clip_index < len(clips):
            clips[req.clip_index]['video_url'] = f"/videos/{req.job_id}/{output_filename}"
            data['shorts'] = clips
            _atomic_write_json(json_files[0], data)
            print(f"✅ Metadata updated with translated video for clip {req.clip_index}")
    except Exception as e:
        print(f"⚠️ Failed to update metadata.json: {e}")

    return {
        "success": True,
        "new_video_url": f"/videos/{req.job_id}/{output_filename}"
    }

class SocialPostRequest(BaseModel):
    job_id: str
    clip_index: int
    api_key: str
    user_id: str
    platforms: List[str] # ["tiktok", "instagram", "youtube"]
    # Optional overrides if frontend wants to edit them
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[str] = None # ISO-8601 string
    timezone: Optional[str] = "UTC"

import httpx

@app.post("/api/social/post")
async def post_to_socials(req: SocialPostRequest):
    if req.job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = jobs[req.job_id]
    if 'result' not in job or 'clips' not in job['result']:
        raise HTTPException(status_code=400, detail="Job result not available")
        
    try:
        clip = job['result']['clips'][req.clip_index]
        # Video URL is relative /videos/..., we need absolute file path
        # clip['video_url'] is like "/videos/{job_id}/{filename}"
        # We constructed it as: f"/videos/{job_id}/{clip_filename}"
        # And file is at f"{OUTPUT_DIR}/{job_id}/{clip_filename}"
        
        filename = clip['video_url'].split('/')[-1]
        file_path = os.path.join(OUTPUT_DIR, req.job_id, filename)
        
        if not os.path.exists(file_path):
             raise HTTPException(status_code=404, detail=f"Video file not found: {file_path}")

        # Construct parameters for Upload-Post API
        # Fallbacks
        final_title = req.title or clip.get('title', 'Viral Short')
        final_description = req.description or clip.get('video_description_for_instagram') or clip.get('video_description_for_tiktok') or "Check this out!"
        
        # Prepare form data
        url = "https://api.upload-post.com/api/upload"
        headers = {
            "Authorization": f"Apikey {req.api_key}"
        }
        
        # Prepare data as dict (httpx handles lists for multiple values)
        data_payload = {
            "user": req.user_id,
            "title": final_title,
            "platform[]": req.platforms, # Pass list directly
            "async_upload": "true"  # Enable async upload
        }

        # Add scheduling if present
        if req.scheduled_date:
            data_payload["scheduled_date"] = req.scheduled_date
            if req.timezone:
                data_payload["timezone"] = req.timezone
        
        # Add Platform specifics
        if "tiktok" in req.platforms:
             data_payload["tiktok_title"] = final_description
             
        if "instagram" in req.platforms:
             data_payload["instagram_title"] = final_description
             data_payload["media_type"] = "REELS"

        if "youtube" in req.platforms:
             yt_title = req.title or clip.get('video_title_for_youtube_short', final_title)
             data_payload["youtube_title"] = yt_title
             data_payload["youtube_description"] = final_description
             data_payload["privacyStatus"] = "public"

        # Send File
        # httpx AsyncClient requires async file reading or bytes. 
        # Since we have MAX_FILE_SIZE_MB, reading into memory is safe-ish.
        with open(file_path, "rb") as f:
            file_content = f.read()
            
        files = {
            "video": (filename, file_content, "video/mp4")
        }

        # Switch to synchronous Client to avoid "sync request with AsyncClient" error with multipart/files
        with httpx.Client(timeout=120.0) as client:
            print(f"📡 Sending to Upload-Post for platforms: {req.platforms}")
            response = client.post(url, headers=headers, data=data_payload, files=files)
            
        if response.status_code not in [200, 201, 202]: # Added 201
             print(f"❌ Upload-Post Error: {response.text}")
             raise HTTPException(status_code=response.status_code, detail=f"Vendor API Error: {response.text}")

        return response.json()

    except Exception as e:
        print(f"❌ Social Post Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/social/user")
async def get_social_user(api_key: str = Header(..., alias="X-Upload-Post-Key")):
    """Proxy to fetch user ID from Upload-Post"""
    if not api_key:
         raise HTTPException(status_code=400, detail="Missing X-Upload-Post-Key header")
         
    url = "https://api.upload-post.com/api/uploadposts/users"
    print(f"🔍 Fetching User ID from: {url}")
    headers = {"Authorization": f"Apikey {api_key}"}
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                print(f"❌ Upload-Post User Fetch Error: {resp.text}")
                raise HTTPException(status_code=resp.status_code, detail=f"Failed to fetch user: {resp.text}")
            
            data = resp.json()
            print(f"🔍 Upload-Post User Response: {data}")
            
            user_id = None
            # The structure is {'success': True, 'profiles': [{'username': '...'}, ...]}
            profiles_list = []
            if isinstance(data, dict):
                 raw_profiles = data.get('profiles', [])
                 if isinstance(raw_profiles, list):
                     for p in raw_profiles:
                         username = p.get('username')
                         if username:
                             # Determine connected platforms
                             socials = p.get('social_accounts', {})
                             connected = []
                             # Check typical platforms
                             for platform in ['tiktok', 'instagram', 'youtube']:
                                 account_info = socials.get(platform)
                                 # If it's a dict and typically has data, or just not empty string
                                 if isinstance(account_info, dict):
                                     connected.append(platform)
                             
                             profiles_list.append({
                                 "username": username,
                                 "connected": connected
                             })
            
            if not profiles_list:
                # Fallback if no profiles found
                return {"profiles": [], "error": "No profiles found"}
                
            return {"profiles": profiles_list}
            
            
        except Exception as e:
             raise HTTPException(status_code=500, detail=str(e))

# --- Thumbnail Studio Endpoints ---

@app.post("/api/thumbnail/upload")
async def thumbnail_upload(
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
):
    """Upload video and start background Whisper transcription immediately."""
    if not url and not file:
        raise HTTPException(status_code=400, detail="Must provide URL or File")

    session_id = str(uuid.uuid4())
    transcript_event = asyncio.Event()

    # Save file if uploaded directly
    video_path = None
    if file:
        video_path = os.path.join(UPLOAD_DIR, f"thumb_{session_id}_{file.filename}")
        with open(video_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)

    # Initialize session
    thumbnail_sessions[session_id] = {
        "video_path": video_path,
        "transcript_event": transcript_event,
        "transcript_ready": False,
        "transcript": None,
        "transcript_segments": [],
        "video_duration": 0,
        "language": "en",
        "context": "",
        "titles": [],
        "conversation": [],
        "_url": url,  # Store URL for deferred download
    }

    async def run_background_whisper():
        try:
            vpath = video_path
            # Download YouTube video if URL was provided
            if not vpath and url:
                from main import download_youtube_video
                loop = asyncio.get_event_loop()
                vpath, _ = await loop.run_in_executor(None, download_youtube_video, url, UPLOAD_DIR)
                thumbnail_sessions[session_id]["video_path"] = vpath

            from main import transcribe_video
            loop = asyncio.get_event_loop()
            transcript = await loop.run_in_executor(None, transcribe_video, vpath)
            segments = transcript.get("segments", [])
            duration = segments[-1]["end"] if segments else 0

            thumbnail_sessions[session_id].update({
                "transcript_ready": True,
                "transcript": transcript,
                "transcript_segments": segments,
                "video_duration": duration,
                "language": transcript.get("language", "en"),
            })
            print(f"✅ [Thumbnail] Background Whisper complete for session {session_id}")
        except Exception as e:
            print(f"❌ [Thumbnail] Background Whisper failed: {e}")
            thumbnail_sessions[session_id]["transcript_error"] = str(e)
        finally:
            transcript_event.set()

    asyncio.create_task(run_background_whisper())

    return {"session_id": session_id}


@app.post("/api/thumbnail/analyze")
async def thumbnail_analyze(
    request: Request,
    file: Optional[UploadFile] = File(None),
    url: Optional[str] = Form(None),
    session_id: Optional[str] = Form(None),
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Analyze a video and suggest viral YouTube titles."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    pre_transcript = None

    # Check for pre-existing session with background Whisper
    if session_id and session_id in thumbnail_sessions:
        session = thumbnail_sessions[session_id]

        # Wait for background Whisper to complete
        transcript_event = session.get("transcript_event")
        if transcript_event:
            print(f"⏳ [Thumbnail] Waiting for background Whisper to finish...")
            await transcript_event.wait()

        if session.get("transcript_error"):
            raise HTTPException(status_code=500, detail=f"Transcription failed: {session['transcript_error']}")

        video_path = session["video_path"]
        if not video_path or not os.path.exists(video_path):
            raise HTTPException(status_code=404, detail="Video file not found in session")

        if session.get("transcript_ready"):
            pre_transcript = session["transcript"]
    else:
        # No pre-existing session — need file or URL
        if not url and not file:
            raise HTTPException(status_code=400, detail="Must provide URL, File, or session_id")

        session_id = str(uuid.uuid4())

        if url:
            from main import download_youtube_video
            video_path, _ = download_youtube_video(url, UPLOAD_DIR)
        else:
            video_path = os.path.join(UPLOAD_DIR, f"thumb_{session_id}_{file.filename}")
            with open(video_path, "wb") as buffer:
                content = await file.read()
                buffer.write(content)

    try:
        # Run analysis in thread pool (skips Whisper if pre_transcript is available)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, analyze_video_for_titles, api_key, video_path, pre_transcript)

        # Store/update session context
        if session_id not in thumbnail_sessions:
            thumbnail_sessions[session_id] = {}

        thumbnail_sessions[session_id].update({
            "context": result.get("transcript_summary", ""),
            "titles": result.get("titles", []),
            "language": result.get("language", "en"),
            "conversation": thumbnail_sessions[session_id].get("conversation", []),
            "video_path": video_path,
            "transcript_segments": result.get("segments", []),
            "video_duration": result.get("video_duration", 0)
        })

        return {
            "session_id": session_id,
            "titles": result.get("titles", []),
            "context": result.get("transcript_summary", ""),
            "language": result.get("language", "en"),
            "recommended": result.get("recommended", [])
        }

    except Exception as e:
        print(f"❌ Thumbnail Analyze Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ThumbnailTitlesRequest(BaseModel):
    session_id: Optional[str] = None
    message: Optional[str] = None
    title: Optional[str] = None

@app.post("/api/thumbnail/titles")
async def thumbnail_titles(
    req: ThumbnailTitlesRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Refine title suggestions or accept a manual title."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    # Manual title mode - just create a session with the user's title
    if req.title:
        session_id = req.session_id or str(uuid.uuid4())
        if session_id not in thumbnail_sessions:
            thumbnail_sessions[session_id] = {
                "context": "",
                "titles": [req.title],
                "language": "en",
                "conversation": []
            }
        return {"session_id": session_id, "titles": [req.title]}

    # Refinement mode
    if not req.session_id or req.session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    if not req.message:
        raise HTTPException(status_code=400, detail="Must provide message or title")

    session = thumbnail_sessions[req.session_id]

    # Add user message to conversation history
    session["conversation"].append({"role": "user", "content": req.message})

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            refine_titles,
            api_key,
            session["context"],
            req.message,
            session["conversation"]
        )

        new_titles = result.get("titles", [])
        session["titles"] = new_titles
        session["conversation"].append({"role": "assistant", "content": json.dumps(new_titles)})

        return {"titles": new_titles}

    except Exception as e:
        print(f"❌ Thumbnail Titles Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thumbnail/generate")
async def thumbnail_generate(
    request: Request,
    session_id: str = Form(...),
    title: str = Form(...),
    extra_prompt: str = Form(""),
    count: int = Form(3),
    face: Optional[UploadFile] = File(None),
    background: Optional[UploadFile] = File(None),
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Generate YouTube thumbnails with Gemini image generation."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    # Clamp count
    count = min(max(1, count), 6)

    # Save optional uploaded images
    face_path = None
    bg_path = None
    thumb_upload_dir = os.path.join(UPLOAD_DIR, f"thumb_{session_id}")
    os.makedirs(thumb_upload_dir, exist_ok=True)

    try:
        if face and face.filename:
            face_path = os.path.join(thumb_upload_dir, f"face_{face.filename}")
            with open(face_path, "wb") as f:
                f.write(await face.read())

        if background and background.filename:
            bg_path = os.path.join(thumb_upload_dir, f"bg_{background.filename}")
            with open(bg_path, "wb") as f:
                f.write(await background.read())

        # Get video context from session (transcript summary from analysis step)
        video_context = ""
        if session_id in thumbnail_sessions:
            video_context = thumbnail_sessions[session_id].get("context", "")

        # Run generation in thread pool
        loop = asyncio.get_event_loop()
        thumbnails = await loop.run_in_executor(
            None,
            generate_thumbnail,
            api_key,
            title,
            session_id,
            face_path,
            bg_path,
            extra_prompt,
            count,
            video_context
        )

        if not thumbnails:
            raise HTTPException(status_code=500, detail="Thumbnail generation failed. Please check your Gemini API key has access to image generation (gemini-3.1-flash-image-preview model).")

        return {"thumbnails": thumbnails}

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ Thumbnail Generate Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class ThumbnailDescribeRequest(BaseModel):
    session_id: str
    title: str

@app.post("/api/thumbnail/describe")
async def thumbnail_describe(
    req: ThumbnailDescribeRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key")
):
    """Generate a YouTube description with chapters from the transcript."""
    api_key = x_gemini_key
    if not api_key:
        raise HTTPException(status_code=400, detail="Missing X-Gemini-Key header")

    if req.session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = thumbnail_sessions[req.session_id]
    segments = session.get("transcript_segments", [])
    if not segments:
        raise HTTPException(status_code=400, detail="No transcript segments available. Please analyze a video first.")

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            generate_youtube_description,
            api_key,
            req.title,
            segments,
            session.get("language", "en"),
            session.get("video_duration", 0)
        )
        return {"description": result.get("description", "")}

    except Exception as e:
        print(f"❌ Thumbnail Describe Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/thumbnail/publish")
async def thumbnail_publish(
    background_tasks: BackgroundTasks,
    session_id: str = Form(...),
    title: str = Form(...),
    description: str = Form(...),
    thumbnail_url: str = Form(...),
    api_key: str = Form(...),
    user_id: str = Form(...),
):
    """Kick off a background upload to YouTube via Upload-Post and return immediately."""
    if session_id not in thumbnail_sessions:
        raise HTTPException(status_code=404, detail="Session not found")

    session = thumbnail_sessions[session_id]
    video_path = session.get("video_path")
    if not video_path or not os.path.exists(video_path):
        raise HTTPException(status_code=404, detail="Original video file not found")

    # Resolve thumbnail path from URL
    thumb_relative = thumbnail_url.lstrip("/")
    if thumb_relative.startswith("thumbnails/"):
        thumb_path = os.path.join(OUTPUT_DIR, thumb_relative)
    else:
        thumb_path = os.path.join(THUMBNAILS_DIR, thumb_relative)

    if not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail=f"Thumbnail file not found: {thumb_path}")

    # Generate a unique ID for this publish job so the frontend can poll
    publish_id = str(uuid.uuid4())
    publish_jobs[publish_id] = {"status": "uploading", "result": None, "error": None}

    def do_upload():
        """Runs in a thread via BackgroundTasks — does the actual multipart upload."""
        try:
            upload_url = "https://api.upload-post.com/api/upload"
            headers = {"Authorization": f"Apikey {api_key}"}
            data_payload = {
                "user": user_id,
                "platform[]": ["youtube"],
                "title": title,          # required base field (fallback)
                "async_upload": "true",
                "youtube_title": title,
                "youtube_description": description,
                "privacyStatus": "public",
            }
            video_filename = os.path.basename(video_path)
            thumb_filename = os.path.basename(thumb_path)

            print(f"📡 [Thumbnail] Publishing to YouTube via Upload-Post... (publish_id={publish_id})")
            with open(video_path, "rb") as vf, open(thumb_path, "rb") as tf:
                files = {
                    "video": (video_filename, vf.read(), "video/mp4"),
                    "thumbnail": (thumb_filename, tf.read(), "image/jpeg"),
                }

            # Use a long timeout — video uploads can take several minutes
            with httpx.Client(timeout=600.0) as client:
                response = client.post(upload_url, headers=headers, data=data_payload, files=files)

            if response.status_code not in [200, 201, 202]:
                err = f"Upload-Post API Error ({response.status_code}): {response.text}"
                print(f"❌ {err}")
                publish_jobs[publish_id]["status"] = "failed"
                publish_jobs[publish_id]["error"] = err
            else:
                print(f"✅ [Thumbnail] Published successfully (publish_id={publish_id})")
                publish_jobs[publish_id]["status"] = "done"
                publish_jobs[publish_id]["result"] = response.json()

        except Exception as e:
            err = str(e)
            print(f"❌ Thumbnail Publish Background Error: {err}")
            publish_jobs[publish_id]["status"] = "failed"
            publish_jobs[publish_id]["error"] = err

    background_tasks.add_task(do_upload)
    return {"publish_id": publish_id, "status": "uploading"}


@app.get("/api/thumbnail/publish/status/{publish_id}")
async def thumbnail_publish_status(publish_id: str):
    """Poll the status of a background publish job."""
    if publish_id not in publish_jobs:
        raise HTTPException(status_code=404, detail="Publish job not found")
    return publish_jobs[publish_id]


# @app.get("/api/gallery/clips")
# async def get_gallery_clips(limit: int = 20, offset: int = 0, refresh: bool = False):
#     """
#     Fetch clips from S3 for the gallery with pagination.
#
#     Args:
#         limit: Number of clips to return (default 20, max 100)
#         offset: Starting position for pagination
#         refresh: Force refresh cache
#     """
#     try:
#         # Clamp limit to reasonable values
#         limit = min(max(1, limit), 100)
#
#         # Get clips (uses cache internally)
#         all_clips = list_all_clips(limit=limit + offset, force_refresh=refresh)
#
#         # Apply offset for pagination
#         clips = all_clips[offset:offset + limit]
#
#         return {
#             "clips": clips,
#             "total": len(all_clips),
#             "limit": limit,
#             "offset": offset,
#             "has_more": len(all_clips) > offset + limit
#         }
#     except Exception as e:
#         print(f"❌ Gallery Error: {e}")
#         raise HTTPException(status_code=500, detail=str(e))


# ═══════════════════════════════════════════════════════════════════════
# SaaSShorts: AI UGC Video Generator for SaaS Products
# ═══════════════════════════════════════════════════════════════════════

from saasshorts import (
    scrape_website,
    research_saas_online,
    analyze_saas,
    generate_scripts,
    generate_full_video,
    generate_actor_images,
    get_elevenlabs_voices,
    DEFAULT_VOICES,
)

# State for SaaSShorts jobs (separate from video processing jobs)
saas_jobs: Dict[str, Dict] = {}


class SaaSAnalyzeRequest(BaseModel):
    url: Optional[str] = None
    description: Optional[str] = None  # Manual product/business description
    num_scripts: int = 3
    style: str = "ugc"
    language: str = "en"
    actor_gender: str = "female"


@app.post("/api/saasshorts/analyze")
async def saasshorts_analyze(
    req: SaaSAnalyzeRequest,
    x_gemini_key: Optional[str] = Header(None, alias="X-Gemini-Key"),
):
    """Analyze a URL or manual description and generate video scripts."""
    gemini_key = x_gemini_key or os.environ.get("GEMINI_API_KEY")
    if not gemini_key:
        raise HTTPException(status_code=400, detail="Missing Gemini API Key")

    if not req.url and not req.description:
        raise HTTPException(status_code=400, detail="Provide a URL or a product description")

    try:
        loop = asyncio.get_event_loop()

        def run_analysis():
            web_research = None

            if req.url and req.url.strip():
                # URL provided: full scrape + research pipeline
                scraped = scrape_website(req.url)
                web_research = research_saas_online(req.url, gemini_key)
                analysis = analyze_saas(scraped, gemini_key, web_research=web_research)
            else:
                # Manual description: build analysis from description
                analysis = {
                    "product_name": req.description.split(",")[0].strip()[:60] if req.description else "Product",
                    "description": req.description,
                    "value_proposition": req.description,
                    "target_audience": "general audience",
                    "key_features": [req.description],
                    "pain_points": [],
                    "tone": "casual and authentic",
                }

            scripts = generate_scripts(analysis, gemini_key, req.num_scripts, req.style, req.language, req.actor_gender)
            return {
                "analysis": analysis,
                "scripts": scripts,
                "web_research": web_research,
            }

        result = await loop.run_in_executor(None, run_analysis)
        return result

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SaaSActorRequest(BaseModel):
    actor_description: str
    num_options: int = 3
    product_description: Optional[str] = None


@app.post("/api/saasshorts/actor-upload")
async def saasshorts_actor_upload(file: UploadFile = File(...)):
    """Upload a custom actor image (stored locally only, not S3)."""
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        content = await file.read()

        # Validate minimum size
        if len(content) < 1000:
            raise HTTPException(status_code=400, detail="File too small to be a valid image")

        upload_id = uuid.uuid4().hex[:8]
        upload_dir = os.path.join(OUTPUT_DIR, "actor_uploads")
        os.makedirs(upload_dir, exist_ok=True)
        filename = f"custom_{upload_id}.png"
        file_path = os.path.join(upload_dir, filename)

        with open(file_path, "wb") as f:
            f.write(content)

        return {"url": f"/videos/actor_uploads/{filename}"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/saasshorts/actor-options")
async def saasshorts_actor_options(
    req: SaaSActorRequest,
    x_fal_key: Optional[str] = Header(None, alias="X-Fal-Key"),
):
    """Generate multiple actor image options for the user to choose from."""
    fal_key = x_fal_key
    if not fal_key:
        raise HTTPException(status_code=400, detail="Missing fal.ai API Key")

    try:
        job_id = str(uuid.uuid4())
        out_dir = os.path.join(OUTPUT_DIR, f"saas_actors_{job_id}")
        os.makedirs(out_dir, exist_ok=True)

        loop = asyncio.get_running_loop()
        import functools
        paths = await loop.run_in_executor(
            None,
            functools.partial(
                generate_actor_images,
                req.actor_description, fal_key, out_dir, "actor", req.num_options,
                product_description=req.product_description,
            ),
        )

        # Upload each actor image to public S3 with description
        desc = req.actor_description
        if req.product_description:
            desc += f" (holding {req.product_description})"
        urls = []
        for p in paths:
            s3_url = upload_actor_to_s3(p, description=desc)
            if s3_url:
                urls.append(s3_url)
            else:
                # Fallback to local URL if S3 fails
                urls.append(f"/videos/saas_actors_{job_id}/{os.path.basename(p)}")

        return {"images": urls}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/saasshorts/gallery")
async def saasshorts_video_gallery(limit: int = 50):
    """List all UGC videos from the public gallery."""
    try:
        loop = asyncio.get_running_loop()
        videos = await loop.run_in_executor(None, list_video_gallery, limit)
        return {"videos": videos, "total": len(videos)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SaaSPostRequest(BaseModel):
    job_id: str
    api_key: str
    user_id: str
    platforms: List[str]
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[str] = None
    timezone: Optional[str] = "UTC"


@app.post("/api/saasshorts/post")
async def saasshorts_post_to_socials(req: SaaSPostRequest):
    """Post an AI Shorts video to social media via Upload-Post."""
    if req.job_id not in saas_jobs:
        raise HTTPException(status_code=404, detail="Job not found")

    job = saas_jobs[req.job_id]
    result = job.get("result")
    if not result or not result.get("video_url"):
        raise HTTPException(status_code=400, detail="No video available for this job")

    try:
        # Resolve video file path
        video_url = result["video_url"]  # e.g. /videos/saas_xxx/slug_final.mp4
        rel_path = video_url.replace("/videos/", "")
        file_path = os.path.join(OUTPUT_DIR, rel_path)

        if not os.path.exists(file_path):
            raise HTTPException(status_code=404, detail=f"Video file not found")

        script = result.get("script", {})
        final_title = req.title or script.get("title", "AI Short")
        final_description = req.description or script.get("caption", "")
        if not final_description:
            final_description = script.get("full_narration", "Check this out!")

        url = "https://api.upload-post.com/api/upload"
        headers = {"Authorization": f"Apikey {req.api_key}"}

        data_payload = {
            "user": req.user_id,
            "title": final_title,
            "platform[]": req.platforms,
            "async_upload": "true",
        }

        if req.scheduled_date:
            data_payload["scheduled_date"] = req.scheduled_date
            if req.timezone:
                data_payload["timezone"] = req.timezone

        if "tiktok" in req.platforms:
            data_payload["tiktok_title"] = final_description
        if "instagram" in req.platforms:
            data_payload["instagram_title"] = final_description
            data_payload["media_type"] = "REELS"
        if "youtube" in req.platforms:
            data_payload["youtube_title"] = final_title
            data_payload["youtube_description"] = final_description
            data_payload["privacyStatus"] = "public"

        filename = os.path.basename(file_path)
        with open(file_path, "rb") as f:
            file_content = f.read()

        files = {"video": (filename, file_content, "video/mp4")}

        with httpx.Client(timeout=120.0) as client:
            print(f"📡 [AI Shorts] Sending to Upload-Post: {req.platforms}")
            response = client.post(url, headers=headers, data=data_payload, files=files)

        if response.status_code not in [200, 201, 202]:
            raise HTTPException(status_code=response.status_code, detail=f"Upload-Post Error: {response.text}")

        return response.json()

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [AI Shorts] Post Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/gallery", response_class=HTMLResponse)
async def gallery_html_page():
    """SEO gallery page with all generated UGC videos."""
    import html as html_mod
    loop = asyncio.get_running_loop()
    videos = await loop.run_in_executor(None, list_video_gallery, 100)

    cards_html = ""
    ld_items = []
    for i, v in enumerate(videos):
        title = html_mod.escape(v.get("title", "Untitled"))
        video_url = v.get("video_url", "")
        actor_url = v.get("actor_url", "")
        video_id = v.get("video_id", "")
        duration = v.get("duration", 0)
        mode = v.get("video_mode", "")
        product = html_mod.escape(v.get("product_name", ""))
        caption = html_mod.escape(v.get("caption", "")[:120])

        mode_badge = '<span style="background:#22c55e;color:#000;padding:2px 8px;border-radius:9999px;font-size:10px;font-weight:700">LOW COST</span>' if mode == "lowcost" else '<span style="background:#8b5cf6;color:#fff;padding:2px 8px;border-radius:9999px;font-size:10px;font-weight:700">PREMIUM</span>'

        cards_html += f'''
        <a href="/video/{video_id}" style="text-decoration:none;color:inherit">
          <div style="background:#18181b;border-radius:16px;overflow:hidden;border:1px solid #27272a;transition:transform 0.2s" onmouseover="this.style.transform='scale(1.02)'" onmouseout="this.style.transform='scale(1)'">
            <div style="position:relative;aspect-ratio:9/16;background:#000">
              <video src="{video_url}" poster="{actor_url}" muted playsinline preload="metadata"
                     onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0"
                     style="width:100%;height:100%;object-fit:cover"></video>
              <div style="position:absolute;top:8px;right:8px">{mode_badge}</div>
            </div>
            <div style="padding:12px">
              <h2 style="font-size:14px;font-weight:600;margin:0 0 4px 0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">{title}</h2>
              <p style="font-size:11px;color:#71717a;margin:0">{duration:.0f}s · {product}</p>
            </div>
          </div>
        </a>'''

        ld_items.append(f'{{"@type":"ListItem","position":{i+1},"url":"https://openshorts.app/video/{video_id}","name":"{title}"}}')

    ld_json = f'{{"@context":"https://schema.org","@type":"CollectionPage","name":"AI UGC Video Gallery","mainEntity":{{"@type":"ItemList","numberOfItems":{len(videos)},"itemListElement":[{",".join(ld_items)}]}}}}'

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI UGC Video Gallery | OpenShorts</title>
<meta name="description" content="Browse {len(videos)} AI-generated UGC marketing videos. Create viral TikTok and Instagram Reels for your SaaS product.">
<meta name="robots" content="index, follow">
<meta property="og:title" content="AI UGC Video Gallery | OpenShorts">
<meta property="og:type" content="website">
<meta property="og:description" content="Browse AI-generated UGC marketing videos for SaaS products.">
<script type="application/ld+json">{ld_json}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0c;color:#e4e4e7;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(220px,1fr));gap:20px;padding:20px;max-width:1400px;margin:0 auto}}
nav{{padding:20px 40px;border-bottom:1px solid #27272a;display:flex;align-items:center;justify-content:space-between}}
h1{{font-size:28px;font-weight:700;padding:40px 20px 0;text-align:center}}
.subtitle{{text-align:center;color:#71717a;font-size:14px;padding:8px 20px 20px}}
.cta{{display:inline-block;background:#8b5cf6;color:#fff;padding:10px 24px;border-radius:12px;text-decoration:none;font-weight:600;font-size:14px}}
</style>
</head>
<body>
<nav><strong style="font-size:18px">OpenShorts</strong><a href="/" class="cta">Create Your Video</a></nav>
<h1>AI-Generated UGC Videos</h1>
<p class="subtitle">{len(videos)} videos generated · Low Cost & Premium modes</p>
<div class="grid">{cards_html}</div>
<div style="text-align:center;padding:40px"><a href="/" class="cta">Create Your Own UGC Video</a></div>
</body></html>'''


@app.get("/video/{video_id}", response_class=HTMLResponse)
async def video_html_page(video_id: str):
    """SEO individual video page with og:video meta tags."""
    import html as html_mod
    loop = asyncio.get_running_loop()
    videos = await loop.run_in_executor(None, list_video_gallery, 200)
    meta = next((v for v in videos if v.get("video_id") == video_id), None)
    if not meta:
        raise HTTPException(status_code=404, detail="Video not found")

    title = html_mod.escape(meta.get("title", "Untitled"))
    caption = html_mod.escape(meta.get("caption", ""))
    narration = html_mod.escape(meta.get("full_narration", ""))
    video_url = meta.get("video_url", "")
    actor_url = meta.get("actor_url", "")
    duration = meta.get("duration", 0)
    mode = meta.get("video_mode", "")
    product = html_mod.escape(meta.get("product_name", ""))
    product_url = html_mod.escape(meta.get("product_url", ""))
    language = meta.get("language", "en")
    hashtags = " ".join(meta.get("hashtags", []))
    cost = meta.get("cost_estimate", {}).get("total", 0)
    created = meta.get("created_at", "")
    actor_desc = html_mod.escape(meta.get("actor_description", ""))

    ld_json = f'{{"@context":"https://schema.org","@type":"VideoObject","name":"{title}","description":"{caption}","thumbnailUrl":"{actor_url}","contentUrl":"{video_url}","uploadDate":"{created}","duration":"PT{int(duration)}S","width":1080,"height":1920,"inLanguage":"{language}"}}'

    mode_label = "Low Cost" if mode == "lowcost" else "Premium"

    return f'''<!DOCTYPE html>
<html lang="{language}">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} - AI UGC Video | OpenShorts</title>
<meta name="description" content="{caption} {hashtags}">
<meta property="og:type" content="video.other">
<meta property="og:title" content="{title}">
<meta property="og:description" content="{caption}">
<meta property="og:video" content="{video_url}">
<meta property="og:video:type" content="video/mp4">
<meta property="og:video:width" content="1080">
<meta property="og:video:height" content="1920">
<meta property="og:image" content="{actor_url}">
<meta name="twitter:card" content="player">
<meta name="twitter:title" content="{title}">
<meta name="twitter:image" content="{actor_url}">
<script type="application/ld+json">{ld_json}</script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{background:#0a0a0c;color:#e4e4e7;font-family:-apple-system,BlinkMacSystemFont,sans-serif}}
nav{{padding:20px 40px;border-bottom:1px solid #27272a;display:flex;align-items:center;gap:16px}}
nav a{{color:#a1a1aa;text-decoration:none;font-size:14px}}
.container{{max-width:1000px;margin:0 auto;padding:40px 20px;display:grid;grid-template-columns:1fr 1fr;gap:40px}}
@media(max-width:768px){{.container{{grid-template-columns:1fr}}}}
video{{width:100%;border-radius:16px;background:#000}}
h1{{font-size:22px;font-weight:700;margin-bottom:8px}}
.meta{{color:#71717a;font-size:13px;margin-bottom:20px}}
.section{{margin-bottom:20px}}
.section h2{{font-size:13px;color:#71717a;text-transform:uppercase;letter-spacing:1px;margin-bottom:6px}}
.section p{{font-size:14px;line-height:1.6}}
.badge{{display:inline-block;padding:3px 10px;border-radius:9999px;font-size:11px;font-weight:700}}
.cta{{display:inline-block;background:#8b5cf6;color:#fff;padding:10px 24px;border-radius:12px;text-decoration:none;font-weight:600;font-size:14px;margin-top:20px}}
</style>
</head>
<body>
<nav><strong>OpenShorts</strong><a href="/gallery">Gallery</a><span style="color:#3f3f46">›</span><span style="color:#e4e4e7;font-size:14px">{title}</span></nav>
<div class="container">
<div><video src="{video_url}" poster="{actor_url}" controls autoplay playsinline style="aspect-ratio:9/16;object-fit:cover"></video></div>
<div>
<h1>{title}</h1>
<p class="meta">{duration:.0f}s · {mode_label} · ${cost:.2f} · {product}</p>
<div class="section"><h2>Caption</h2><p>{caption}</p><p style="color:#8b5cf6;margin-top:4px">{hashtags}</p></div>
<div class="section"><h2>Script</h2><p>{narration}</p></div>
<div class="section"><h2>Actor</h2><p>{actor_desc}</p></div>
{f'<div class="section"><h2>Product</h2><p><a href="{product_url}" style="color:#8b5cf6" target="_blank">{product}</a></p></div>' if product_url else ''}
<a href="/gallery">← Back to Gallery</a>
<br><a href="/" class="cta">Create Your Own</a>
</div>
</div>
</body></html>'''


@app.get("/api/saasshorts/actor-gallery")
async def saasshorts_actor_gallery():
    """List all previously generated actor images from public S3."""
    try:
        loop = asyncio.get_running_loop()
        images = await loop.run_in_executor(None, list_actor_gallery)
        return {"images": images}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SaaSGenerateRequest(BaseModel):
    script: dict
    voice_id: Optional[str] = None
    actor_description: Optional[str] = None
    selected_actor_url: Optional[str] = None  # Pre-selected actor image URL
    retry_job_id: Optional[str] = None
    video_mode: str = "lowcost"  # "lowcost" or "premium"


@app.post("/api/saasshorts/generate")
async def saasshorts_generate(
    req: SaaSGenerateRequest,
    x_fal_key: Optional[str] = Header(None, alias="X-Fal-Key"),
    x_elevenlabs_key: Optional[str] = Header(None, alias="X-ElevenLabs-Key"),
):
    """Generate a SaaS UGC video from a script. Returns a job_id for polling."""
    fal_key = x_fal_key
    elevenlabs_key = x_elevenlabs_key

    if not fal_key:
        raise HTTPException(status_code=400, detail="Missing fal.ai API Key (X-Fal-Key header)")
    if not elevenlabs_key:
        raise HTTPException(status_code=400, detail="Missing ElevenLabs API Key (X-ElevenLabs-Key header)")

    # Support retry: reuse output_dir so cached assets (image, voice, head, broll) are kept
    reused = False
    if req.retry_job_id:
        # Check memory first, then disk
        old_dir = os.path.join(OUTPUT_DIR, f"saas_{req.retry_job_id}")
        if req.retry_job_id in saas_jobs:
            old_dir = saas_jobs[req.retry_job_id]["output_dir"]

        if os.path.isdir(old_dir):
            job_id = req.retry_job_id
            job_output_dir = old_dir
            reused = True
            # Clear the 0-byte final video so pipeline re-generates it
            for f in os.listdir(old_dir):
                fp = os.path.join(old_dir, f)
                if f.endswith("_final.mp4") and os.path.getsize(fp) == 0:
                    os.remove(fp)
            saas_jobs[job_id] = {
                "status": "processing",
                "logs": [f"Retrying job {job_id[:8]}... reusing cached assets from disk."],
                "result": None,
                "output_dir": job_output_dir,
            }

    if not reused:
        job_id = str(uuid.uuid4())
        job_output_dir = os.path.join(OUTPUT_DIR, f"saas_{job_id}")
        os.makedirs(job_output_dir, exist_ok=True)
        saas_jobs[job_id] = {
            "status": "processing",
            "logs": ["SaaSShorts job started."],
            "result": None,
            "output_dir": job_output_dir,
        }

    # If user selected a pre-generated actor, resolve it to a local path
    selected_actor_path = None
    if req.selected_actor_url:
        if req.selected_actor_url.startswith("http"):
            # Download from S3 public URL to job output dir
            import httpx
            try:
                actor_local = os.path.join(job_output_dir, "selected_actor.png")
                with httpx.Client(timeout=30.0) as client:
                    resp = client.get(req.selected_actor_url)
                    if resp.status_code == 200:
                        with open(actor_local, "wb") as f:
                            f.write(resp.content)
                        selected_actor_path = actor_local
            except Exception:
                pass
        else:
            src = os.path.join(OUTPUT_DIR, req.selected_actor_url.replace("/videos/", ""))
            if os.path.exists(src):
                selected_actor_path = src

    config = {
        "fal_key": fal_key,
        "elevenlabs_key": elevenlabs_key,
        "voice_id": req.voice_id or "21m00Tcm4TlvDq8ikWAM",
        "actor_description": req.actor_description,
        "selected_actor_path": selected_actor_path,
        "video_mode": req.video_mode,
    }

    async def run_generation():
        await concurrency_semaphore.acquire()
        try:
            loop = asyncio.get_running_loop()

            def log_msg(msg):
                print(f"[SaaSShorts Job {job_id[:8]}] {msg}")
                if job_id in saas_jobs:
                    saas_jobs[job_id]["logs"].append(msg)

            def run():
                return generate_full_video(req.script, config, job_output_dir, log_msg)

            result = await loop.run_in_executor(None, run)

            if job_id in saas_jobs:
                video_filename = result["video_filename"]
                saas_jobs[job_id]["status"] = "completed"
                saas_jobs[job_id]["result"] = {
                    "video_url": f"/videos/saas_{job_id}/{video_filename}",
                    "video_filename": video_filename,
                    "duration": result.get("duration", 0),
                    "cost_estimate": result.get("cost_estimate", {}),
                    "script": req.script,
                }
                saas_jobs[job_id]["logs"].append("Video generation completed!")

                # Upload to public gallery (non-blocking)
                try:
                    gallery_meta = {
                        "title": req.script.get("title", "Untitled"),
                        "hook_text": req.script.get("hook_text", ""),
                        "caption": req.script.get("caption", ""),
                        "hashtags": req.script.get("hashtags", []),
                        "full_narration": req.script.get("full_narration", ""),
                        "actor_description": req.script.get("actor_description", ""),
                        "style": req.script.get("style", "ugc"),
                        "language": req.script.get("language", "en"),
                        "duration": result.get("duration", 0),
                        "video_mode": req.video_mode,
                        "product_name": req.script.get("_product_name", ""),
                        "product_url": req.script.get("_product_url", ""),
                        "segments": req.script.get("segments", []),
                        "cost_estimate": result.get("cost_estimate", {}),
                    }
                    gallery_result = upload_video_to_gallery(
                        video_path=result["video_path"],
                        actor_image_path=result.get("actor_image", ""),
                        metadata=gallery_meta,
                        video_id=job_id[:8],
                    )
                    if gallery_result:
                        saas_jobs[job_id]["result"]["gallery_video_id"] = gallery_result["video_id"]
                        log_msg("📤 Uploaded to public gallery.")
                except Exception as gallery_err:
                    log_msg(f"⚠️ Gallery upload skipped: {gallery_err}")

        except Exception as e:
            print(f"[SaaSShorts] ❌ Job {job_id} failed: {e}")
            if job_id in saas_jobs:
                saas_jobs[job_id]["status"] = "failed"
                saas_jobs[job_id]["logs"].append(f"Error: {str(e)}")
        finally:
            concurrency_semaphore.release()

    asyncio.create_task(run_generation())

    return {"job_id": job_id, "status": "processing"}


@app.get("/api/saasshorts/status/{job_id}")
async def saasshorts_status(job_id: str):
    """Poll SaaSShorts job status."""
    if job_id not in saas_jobs:
        raise HTTPException(status_code=404, detail="SaaSShorts job not found")

    job = saas_jobs[job_id]
    return {
        "status": job["status"],
        "logs": job["logs"],
        "result": job.get("result"),
    }


@app.get("/api/saasshorts/voices")
async def saasshorts_voices(
    x_elevenlabs_key: Optional[str] = Header(None, alias="X-ElevenLabs-Key"),
):
    """List available ElevenLabs voices."""
    if x_elevenlabs_key:
        try:
            loop = asyncio.get_event_loop()
            voices = await loop.run_in_executor(
                None, get_elevenlabs_voices, x_elevenlabs_key
            )
            if voices:
                return {"voices": voices, "source": "elevenlabs"}
        except Exception:
            pass

    # Fallback to default voices
    return {
        "voices": [
            {"voice_id": vid, "name": name, "category": "default"}
            for name, vid in DEFAULT_VOICES.items()
        ],
        "source": "defaults",
    }
