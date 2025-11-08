import subprocess
import time
import os
import signal
import sqlite3
from typing import Optional
import multiprocessing

from . import db
from .models import Job

class Worker:
    """
    A Worker process that fetches and executes jobs.
    """
    def __init__(self):
        self.pid = os.getpid()
        self.running = True
        self.current_job: Optional[Job] = None
        
    def setup_signal_handlers(self):
        """Sets up graceful shutdown handlers."""
        signal.signal(signal.SIGINT, self.handle_shutdown)
        signal.signal(signal.SIGTERM, self.handle_shutdown)

    def handle_shutdown(self, signum, frame):
        """Handles graceful shutdown."""
        if self.current_job:
            print(f"[Worker {self.pid}] Shutdown signal. Finishing job {self.current_job.id}...")
        else:
            print(f"[Worker {self.pid}] Shutdown signal received. Exiting...")
        self.running = False

    def run(self):
        """The main worker loop."""
        self.setup_signal_handlers()
        db.register_worker(self.pid)
        print(f"[Worker {self.pid}] Started and registered.")
        
        try:
            while self.running:
                job = db.fetch_pending_job()
                
                if job:
                    self.current_job = job
                    print(f"[Worker {self.pid}] Processing job {job.id}: {job.command}")
                    self.execute_job(job)
                    self.current_job = None
                else:
                    if self.running:
                        time.sleep(1) 
            
        except Exception as e:
            print(f"[Worker {self.pid}] Error in main loop: {e}")
        finally:
            db.unregister_worker(self.pid)
            print(f"[Worker {self.pid}] Stopped and unregistered.")

    def execute_job(self, job: Job):
        """Executes the job's command using subprocess."""
        try:
            result = subprocess.run(
                job.command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                print(f"[Worker {self.pid}] Job {job.id} completed successfully.")
                db.update_job_success(job.id)
            else:
                print(f"[Worker {self.pid}] Job {job.id} failed (exit code {result.returncode}).")
                db.update_job_failure(job)
                
        except subprocess.TimeoutExpired:
            print(f"[Worker {self.pid}] Job {job.id} timed out.")
            db.update_job_failure(job)
        except Exception as e:
            print(f"[Worker {self.pid}] Job {job.id} execution error: {e}")
            db.update_job_failure(job)


def start_worker_process():
    """Entry point for the multiprocessing.Process."""
    # Each process must have its own DB connection.
    db.local_storage.connection = sqlite3.connect(db.DB_PATH, timeout=10)
    
    worker = Worker()
    worker.run()

def run_workers_foreground(count: int):
    """
    Starts and manages 'count' worker processes in the foreground.
    This function is designed to be the main process in a container.
    """
    print(f"[Manager] Starting {count} worker(s) in foreground mode...")
    processes: list[multiprocessing.Process] = []
    
    for _ in range(count):
        p = multiprocessing.Process(target=start_worker_process)
        p.start()
        processes.append(p)
        print(f"[Manager] Started worker PID: {p.pid}")

    def shutdown_gracefully(signum, frame):
        print(f"[Manager] Shutdown signal received. Terminating {len(processes)} workers...")
        for p in processes:
            p.terminate() # Sends SIGTERM to child
        for p in processes:
            p.join() # Waits for child to exit
        print("[Manager] All workers shut down. Exiting.")
        exit(0)

    signal.signal(signal.SIGINT, shutdown_gracefully)
    signal.signal(signal.SIGTERM, shutdown_gracefully)

    # Keep this main process alive to monitor children
    try:
        while True:
            # Check if any worker died unexpectedly and restart them
            for p in processes:
                if not p.is_alive():
                    print(f"[Manager] Worker {p.pid} died unexpectedly. Restarting...")
                    processes.remove(p)
                    new_p = multiprocessing.Process(target=start_worker_process)
                    new_p.start()
                    processes.append(new_p)
                    print(f"[Manager] Started new worker PID: {new_p.pid}")
            time.sleep(5) # Poll every 5 seconds
    except KeyboardInterrupt:
        pass # Will be caught by signal handler