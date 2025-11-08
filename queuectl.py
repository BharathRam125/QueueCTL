#!/usr/bin/env python

import typer
import json
import os
import sys
import signal
import multiprocessing
import time
from typing import Optional
from rich.console import Console
from rich.table import Table

# The `sys.path.append` logic has been removed.
# These imports will work because `setup.py`
# has already added the '/app' directory to the path.
from jobqueue import db, worker
from jobqueue.models import Job, JobState


app = typer.Typer(help="queuectl - A minimal job queue system.")
worker_app = typer.Typer(name="worker", help="Manage worker processes.")
dlq_app = typer.Typer(name="dlq", help="Manage the Dead Letter Queue (DLQ).")
config_app = typer.Typer(name="config", help="Manage system configuration.")

app.add_typer(worker_app)
app.add_typer(dlq_app)
app.add_typer(config_app)

console = Console()


@app.callback()
def main():
    """Initialize the database on every command."""
    db.init_db()

# --- Enqueue ---

@app.command()
def enqueue(job_json: str = typer.Argument(..., help="Job specification in JSON format.")):
    """Add a new job to the queue."""
    try:
        data = json.loads(job_json)
        if "command" not in data:
            console.print("Error: 'command' field is required in JSON.", style="bold red")
            raise typer.Exit(code=1)
        
        job = Job(
            id=data.get('id', Job().id),
            command=data['command'],
            max_retries=data.get('max_retries', 3)
        )
        
        db.add_job(job)
        console.print(f"Job {job.id} enqueued: {job.command}")

    except json.JSONDecodeError:
        console.print("Error: Invalid JSON provided.", style="bold red")
        raise typer.Exit(code=1)
    except Exception as e:
        console.print(f"Error: {e}", style="bold red")
        raise typer.Exit(code=1)

# --- Worker Commands ---

@worker_app.command("start")
def worker_start(
    count: int = typer.Option(1, "--count", "-c", help="Number of workers to start."),
    foreground: bool = typer.Option(False, "--foreground", help="Run workers in the foreground (for containers).")
):
    """Start one or more worker processes."""
    if foreground:
        # This will block and run as the main container process
        worker.run_workers_foreground(count)
    else:
        # This will daemonize and exit, for local/dev use
        console.print(f"Attempting to start {count} worker(s) in the background...")
        for _ in range(count):
            p = multiprocessing.Process(
                target=worker.start_worker_process,
                daemon=True
            )
            p.start()
            console.print(f"Worker started with PID: {p.pid}")

@worker_app.command("stop")
def worker_stop():
    """Stop all running worker processes gracefully."""
    pids = db.get_active_workers()
    if not pids:
        console.print("No active workers found in database.")
        return

    console.print(f"Sending graceful shutdown (SIGTERM) to {len(pids)} worker(s)...")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
            console.print(f"Sent SIGTERM to worker PID: {pid}")
        except ProcessLookupError:
            console.print(f"Worker PID {pid} not found. Cleaning up from DB.")
            db.unregister_worker(pid)
        except Exception as e:
            console.print(f"Error stopping {pid}: {e}", style="bold red")
            
    time.sleep(2)
    remaining_pids = db.get_active_workers()
    if remaining_pids:
        console.print(f"Warning: {len(remaining_pids)} workers still running.", style="bold yellow")
    else:
        console.print("All workers stopped successfully.")

# --- Status & Listing ---

@app.command()
def status():
    """Show a summary of all job states & active workers."""
    stats = db.get_job_stats()
    workers = db.get_active_workers()

    table = Table(title="QueueCTL Status")
    table.add_column("State", style="cyan")
    table.add_column("Count", justify="right", style="magenta")
    
    for state, count in stats.items():
        table.add_row(state.capitalize(), str(count))
        
    console.print(table)
    console.print(f"Active Workers: {len(workers)} {workers}")

@app.command("list")
def list_jobs(state: JobState = typer.Option(JobState.PENDING, "--state", "-s", help="List jobs by state.")):
    """List jobs by their current state."""
    jobs = db.list_jobs(state)
    
    if not jobs:
        console.print(f"No jobs found with state: {state.value}")
        return
        
    table = Table(title=f"{state.value.capitalize()} Jobs")
    table.add_column("Job ID", style="cyan")
    table.add_column("Command", style="yellow")
    table.add_column("Attempts", style="magenta")
    table.add_column("Updated At", style="dim")
    
    for job in jobs:
        table.add_row(job.id, job.command, str(job.attempts), job.updated_at)
        
    console.print(table)

# --- DLQ Commands ---

@dlq_app.command("list")
def dlq_list():
    """View all jobs in the Dead Letter Queue."""
    list_jobs(state=JobState.DEAD)

@dlq_app.command("retry")
def dlq_retry(job_id: str = typer.Argument(..., help="The ID of the 'dead' job to retry.")):
    """Move a specific job from the DLQ back to 'pending'."""
    if db.requeue_job(job_id):
        console.print(f"Job {job_id} moved from DLQ to 'pending'.")
    else:
        console.print(f"Error: Job {job_id} not found in DLQ.", style="bold red")

# --- Config Commands ---

@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Configuration key (e.g., 'max_retries', 'backoff_base')."),
    value: str = typer.Argument(..., help="Configuration value.")
):
    """Set a system configuration value."""
    db.set_config(key, value)
    console.print(f"Config updated: {key} = {value}")

@config_app.command("get")
def config_get(key: str = typer.Argument(..., help="Configuration key to view.")):
    """Get a system configuration value."""
    value = db.get_config(key)
    if value:
        console.print(f"{key}: {value}")
    else:
        console.print(f"Config key {key} not set.")

@config_app.command("list")
def config_list():
    """List all system configuration values."""
    with db.get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM config")
        rows = cursor.fetchall()
        
    if not rows:
        console.print("No configuration values set.")
        return
        
    table = Table(title="System Configuration")
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    
    for key, value in rows:
        table.add_row(key, value)
    
    console.print(table)


if __name__ == "__main__":
    app()