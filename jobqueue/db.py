import sqlite3
import os
import threading
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from .models import Job, JobState

local_storage = threading.local()

DB_PATH = os.environ.get("QUEUECTL_DB_PATH", "queue.db")

@contextmanager
def get_db_connection():
    """
    Provides a transactional database connection.
    """
    if not hasattr(local_storage, "connection"):
        local_storage.connection = sqlite3.connect(DB_PATH, timeout=10)
    
    try:
        yield local_storage.connection
    except Exception:
        local_storage.connection.rollback()
        raise

def init_db():
    """Initializes the database schema."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            state TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_retries INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            run_at TEXT
        )
        """)
        
        cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_jobs_fetch
        ON jobs (state, run_at)
        WHERE state IN ('pending', 'failed')
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS config (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """)
        
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS workers (
            pid INTEGER PRIMARY KEY,
            started_at TEXT NOT NULL
        )
        """)
        conn.commit()

# --- Config ---

def set_config(key: str, value: str):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO config (key, value) VALUES (?, ?)",
            (key, value)
        )
        conn.commit()

def get_config(key: str, default: Optional[str] = None) -> Optional[str]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row[0] if row else default

# --- Workers ---

def register_worker(pid: int):
    with get_db_connection() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO workers (pid, started_at) VALUES (?, ?)",
            (pid, datetime.utcnow().isoformat())
        )
        conn.commit()

def unregister_worker(pid: int):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM workers WHERE pid = ?", (pid,))
        conn.commit()

def get_active_workers() -> List[int]:
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT pid FROM workers")
        return [row[0] for row in cursor.fetchall()]

# --- Jobs ---

def add_job(job: Job) -> Job:
    """Adds a new job to the queue."""
    with get_db_connection() as conn:
        job.max_retries = int(get_config("max_retries", job.max_retries))
        conn.execute(
            """
            INSERT INTO jobs (id, command, state, attempts, max_retries, created_at, updated_at, run_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            job.to_row()
        )
        conn.commit()
    return job

def fetch_pending_job() -> Optional[Job]:
    """
    Atomically fetches an available job and marks it as 'processing'.
    """
    now = datetime.utcnow().isoformat()
    
    with get_db_connection() as conn:
        # Use an IMMEDIATE transaction to acquire a write lock immediately
        conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT id FROM jobs
                WHERE (state = ? OR (state = ? AND run_at <= ?))
                ORDER BY created_at ASC
                LIMIT 1
                """,
                (JobState.PENDING.value, JobState.FAILED.value, now)
            )
            row = cursor.fetchone()
            
            if not row:
                conn.commit()
                return None
                
            job_id = row[0]
            
            cursor.execute(
                """
                UPDATE jobs
                SET state = ?, updated_at = ?
                WHERE id = ?
                RETURNING *
                """,
                (JobState.PROCESSING.value, now, job_id)
            )
            job_row = cursor.fetchone()
            conn.commit()
            
            return Job.from_row(job_row)
            
        except Exception:
            conn.rollback()
            raise

def update_job_success(job_id: str):
    """Marks a job as 'completed'."""
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE jobs SET state = ?, updated_at = ? WHERE id = ?",
            (JobState.COMPLETED.value, datetime.utcnow().isoformat(), job_id)
        )
        conn.commit()

def update_job_failure(job: Job):
    """Handles a failed job, incrementing attempts and setting up for retry or DLQ."""
    job.attempts += 1
    job.updated_at = datetime.utcnow().isoformat()
    
    backoff_base = int(get_config("backoff_base", "2"))
    
    if job.attempts >= job.max_retries:
        job.state = JobState.DEAD
        job.run_at = None
    else:
        job.state = JobState.FAILED
        delay_seconds = backoff_base ** job.attempts
        job.run_at = (datetime.utcnow() + timedelta(seconds=delay_seconds)).isoformat()
        
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE jobs
            SET state = ?, attempts = ?, updated_at = ?, run_at = ?
            WHERE id = ?
            """,
            (job.state.value, job.attempts, job.updated_at, job.run_at, job.id)
        )
        conn.commit()

def requeue_job(job_id: str) -> bool:
    """Resets a 'dead' job back to 'pending' to be retried."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE jobs
            SET state = ?, attempts = 0, updated_at = ?, run_at = NULL
            WHERE id = ? AND state = ?
            """,
            (JobState.PENDING.value, datetime.utcnow().isoformat(), job_id, JobState.DEAD.value)
        )
        conn.commit()
        return cursor.rowcount > 0

# --- Stats & Listing ---

def get_job_stats() -> Dict[str, int]:
    """Gets a count of jobs by state."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT state, COUNT(*) FROM jobs GROUP BY state")
        
        stats = {state.value: 0 for state in JobState}
        stats.update(dict(cursor.fetchall()))
        return stats

def list_jobs(state: JobState) -> List[Job]:
    """Lists all jobs with a given state."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM jobs WHERE state = ? ORDER BY created_at ASC",
            (state.value,)
        )
        return [Job.from_row(row) for row in cursor.fetchall()]