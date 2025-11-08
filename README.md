# QueueCTL - A Python Background Job Queue

QueueCTL is a minimal, production-grade, CLI-based background job queue system built in Python.

It uses **SQLite** for persistent, transactional job storage, **multiprocessing** for parallel worker execution, and is packaged with **Docker** for easy deployment and testing.

## Features

* **Persistent Storage:** Jobs are stored in a SQLite database (`queue.db`) and persist across restarts.

* **Parallel Workers:** Run multiple worker processes in parallel to process jobs concurrently.

* **Atomic Operations:** Workers use database-level locking (`BEGIN IMMEDIATE`) to prevent race conditions and ensure a job is only processed once.

* **Automatic Retries:** Failed jobs are automatically retried with exponential backoff (`delay = base ^ attempts`).

* **Dead Letter Queue (DLQ):** Jobs that exhaust their `max_retries` are moved to the DLQ for manual inspection.

* **Clean CLI:** All operations are managed through a `typer`-based CLI.

* **Dockerized:** Comes with a `docker-compose.yml` for a production-like and testable environment.

## Demo Video

[**https://drive.google.com/file/d/1FjFjJWnqG_BBvz0pDBPjLuiZI1IDtWIF/view**](https://drive.google.com/file/d/1FjFjJWnqG_BBvz0pDBPjLuiZI1IDtWIF/view)

## Project Structure

```
queuectl-project/
├── docker-compose.yml  # Defines all services (worker, cli, shell)
├── Dockerfile          # Recipe to build the container
├── pyproject.toml      # Build system configuration
├── setup.py            # Makes `queuectl` an installable package
├── requirements.txt    # Python dependencies
├── queuectl.py         # The main CLI application
├── test.sh         # The end-to-end test script
└── jobqueue/           # The core application logic (renamed from 'queue')
    ├── __init__.py
    ├── db.py           # Database logic (locking, fetching, updating)
    ├── models.py       # Job and JobState data models
    └── worker.py       # Worker class and job execution logic

```

## Design, Architecture, and Logic

This system is built on a "producer-consumer" model where the central SQLite database *is* the queue.

* **Producers (`queuectl` CLI):** Act as clients that add jobs to the database (the queue).

* **Consumers (`jobqueue/worker.py`):** Are separate processes that poll the database, lock and fetch jobs, and execute them.

### Core Components

1. **`queuectl` (CLI):** The user's entry point. It's a client whose only job is to add rows to the `jobs` table (e.g., `queuectl enqueue`) or read data (e.g., `queuectl status`).

2. **`jobqueue/db.py` (Database Layer):** It handles all state management and, most critically, manages concurrency. The database itself acts as the message broker.

3. **`jobqueue/worker.py` (Workers):** These are the "consumers." A worker runs in a continuous loop, constantly asking the database for a new job. When it gets one, it executes the command using `subprocess.run()`.

### The Job Lifecycle

The state of a job (defined in `jobqueue/models.py`) is the key to the entire system.

```
[ Enqueue ] -> (PENDING)
                 |
         (Worker Fetches Job)
                 |
           v
        (PROCESSING)
                 |
       +---------+---------+
       |                   |
 (Job command fails)  (Job command succeeds)
 (Exit Code != 0)      (Exit Code == 0)
       |                   |
       v                   v
    (FAILED)           (COMPLETED)
       |
+------+----------------+
|                       |
(Attempts >= Max)  (Attempts < Max)
|                       |
v                       v
(DEAD)            (State set to FAILED)
[In DLQ]          (Calculates 'run_at')
                    (Worker polls again
                    after 'run_at' time)

```

### Concurrency & The "Atomic Fetch"

This is the most critical piece of the design, solving the "race condition" problem.

**Problem:** How do you prevent two workers (Worker A and Worker B), both polling for jobs at the same time, from grabbing the *same* `PENDING` job?

**Solution:** An atomic fetch-and-lock mechanism in `jobqueue/db.py`'s `fetch_pending_job()` function.

The operation is atomic, meaning it *cannot* be interrupted. Here is the logic:

1. **`BEGIN IMMEDIATE`:** The worker requests an `IMMEDIATE` transaction from SQLite. This instantly acquires an **exclusive write-lock** on the database file. No other worker can write to the database (or begin their own `IMMEDIATE` transaction) until this one is finished.

2. **`SELECT...`:** The worker (now holding the lock) safely finds the next available job. This query is smart: it looks for `state = 'pending'` OR `(state = 'failed' AND run_at <= now())`.

3. **`UPDATE...`:** The worker *immediately* updates that job's state to `processing` and gets its details.

4. **`COMMIT`:** The transaction is committed, and the lock on the database is released.

**Result:** The entire "find a job and mark it as mine" operation happens in one uninterruptible step. By the time Worker B gets its lock, Worker A has already marked the job as `processing`, so Worker B won't see it. This guarantees that a job is only ever processed by **one worker at a time**.

### Retry & Exponential Backoff Logic

The retry mechanism is also managed by the database state.

1. When a worker executes a job and gets a non-zero exit code, it calls `db.update_job_failure()`.

2. This function increments the `attempts` counter.

3. It calculates the backoff: `delay = backoff_base ** attempts`.

4. It sets the job's `run_at` timestamp to `now + delay`.

5. It sets the job's state to `FAILED`.

6. The job is now "sleeping." It is ignored by workers until the `run_at` timestamp is in the past, at which point the `fetch_pending_job()` query will see it again as eligible for a retry.

7. If `attempts` exceeds `max_retries`, the state is set to `DEAD`, and it will never be picked up again (unless manually re-queued with `dlq retry`).


##This project is designed to be run entirely from within a single, interactive Docker shell.

### Step 1: Build the Image

First, build the Docker image. This will install all dependencies and use `setup.py` to install `queuectl` as a command inside the container.

```bash
docker-compose build
```

### Step 2: Start the Interactive Shell

This is the main command. It will start a new container, drop you into a `/bin/bash` prompt, and keep you there.

```bash
docker-compose run --rm shell
```

### Step 3: Use the Application (Inside the Shell)

You are now inside the container (your prompt is `root@...:/app#`). All commands are run from here.

**A) Start Your Workers**

First, start your workers in the background. The `&` is important.

```bash
# Start 2 workers in the background
queuectl worker start --count 2 --foreground &
```

**B) Manage Your Queue**

Now, you can enqueue jobs and check the status. The workers you just started will process them.

```bash
# Check the status (you should see 2 active workers)
queuectl status

# Enqueue a new job
queuectl enqueue '{"command":"echo Hello from my queue"}'

# Wait a second and check the status again
sleep 2
queuectl status

# List completed jobs
queuectl list --state completed
```

**C) Stop Your Workers**

To stop the background workers you started, run:

```bash
# This will find and stop all registered workers
queuectl worker stop
```

### Step 4: Run the Full Test Script

The easiest way to test everything is to run the built-in test script. You can run this from inside the interactive shell.

```bash
# This will clean the DB, start workers, run all tests, and stop the workers.
./test.sh
```

### Step 5: Exit

When you are finished, just exit the shell. This will stop the container.

```bash
exit
```

This script will automatically:

1.  Clean the database.

2.  Set config values (`max_retries=2`).

3.  Enqueue successful, failing, and long-running jobs.

4.  Start 2 workers in the background.

5.  Wait and verify that jobs correctly move to `completed` or `dead`.

6.  Test the `dlq retry` functionality.

7.  Run a **race condition test** (1 job, 5 workers) to ensure the job is processed exactly once.

8.  Clean up all processes.

### Step 3: Exit the Shell

When the script is finished, just type `exit` to return to your normal terminal.

```
exit

```

## CLI Command Reference

Once inside the `shell`, you can get help for any command.

```
# Get all top-level commands
queuectl --help

# Get help for a subcommand (e.g., worker)
queuectl worker --help

```

* **`queuectl enqueue '{"cmd":...}'`**: Adds a new job.

* **`queuectl status`**: Shows a summary of job states and active workers.

* **`queuectl list --state <state>`**: Lists all jobs in a specific state.

* **`queuectl worker start --count <n>`**: Starts worker processes.

* **`queuectl worker stop`**: Stops all registered workers.

* **`queuectl dlq list`**: Lists all jobs in the Dead Letter Queue.

* **`queuectl dlq retry <job-id>`**: Re-queues a dead job.

* **`queuectl config set <key> <value>`**: Sets a config value (e.g., `max_retries`).

* **`queuectl config get <key>`**: Retrieves a config value.

## Test script logs
```
root@e44a726247d9:/app# ./test.sh
--- QueueCTL Test Script (Detailed) ---
This script will test all core functionality, including retries and the DLQ.

--- [STEP 0] CLEANUP ---
Cleaning up old database at /data/queue.db...
Cleanup complete.

--- [STEP 1] SET CONFIGURATION ---
Running: queuectl config set max_retries 2
Config updated: max_retries = 2
Running: queuectl config set backoff_base 2
Config updated: backoff_base = 2
Running: queuectl config list
  System Configuration  
┏━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Key          ┃ Value ┃
┡━━━━━━━━━━━━━━╇━━━━━━━┩
│ max_retries  │ 2     │
│ backoff_base │ 2     │
└──────────────┴───────┘
Configuration set.

--- [STEP 2] ENQUEUE JOBS ---
Running: queuectl enqueue '{"id":"job-success", "command":"echo Job 1: Success"}'
Job job-success enqueued: echo Job 1: Success
Running: queuectl enqueue '{"id":"job-fail", "command":"exit 1"}'
Job job-fail enqueued: exit 1
Running: queuectl enqueue '{"id":"job-long", "command":"sleep 3 && echo Job 3: Long job complete"}'
Job job-long enqueued: sleep 3 && echo Job 3: Long job complete
Running: queuectl enqueue '{"id":"job-invalid", "command":"not_a_real_command"}'
Job job-invalid enqueued: not_a_real_command
All jobs enqueued.

--- [STEP 3] CHECK INITIAL STATUS ---
Running: queuectl status (Should show 4 pending jobs)
   QueueCTL Status    
┏━━━━━━━━━━━━┳━━━━━━━┓
┃ State      ┃ Count ┃
┡━━━━━━━━━━━━╇━━━━━━━┩
│ Pending    │     4 │
│ Processing │     0 │
│ Completed  │     0 │
│ Failed     │     0 │
│ Dead       │     0 │
└────────────┴───────┘
Active Workers: 0 []
Running: queuectl list --state pending
                                         Pending Jobs                                         
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job ID      ┃ Command                              ┃ Attempts ┃ Updated At                 ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ job-success │ echo Job 1: Success                  │ 0        │ 2025-11-08T13:29:13.868428 │
│ job-fail    │ exit 1                               │ 0        │ 2025-11-08T13:29:13.994026 │
│ job-long    │ sleep 3 && echo Job 3: Long job      │ 0        │ 2025-11-08T13:29:14.120811 │
│             │ complete                             │          │                            │
│ job-invalid │ not_a_real_command                   │ 0        │ 2025-11-08T13:29:14.236377 │
└─────────────┴──────────────────────────────────────┴──────────┴────────────────────────────┘
Initial status checked.

--- [STEP 4] START WORKERS ---
Running: queuectl worker start --count 2 --foreground &
Worker manager process started with PID: 18
[Manager] Starting 2 worker(s) in foreground mode...
[Manager] Started worker PID: 20
[Manager] Started worker PID: 21
[Worker 20] Started and registered.
[Worker 20] Processing job job-success: echo Job 1: Success
[Worker 20] Job job-success completed successfully.
[Worker 20] Processing job job-fail: exit 1
[Worker 20] Job job-fail failed (exit code 1).
[Worker 20] Processing job job-long: sleep 3 && echo Job 3: Long job complete
[Worker 21] Started and registered.
[Worker 21] Processing job job-invalid: not_a_real_command
[Worker 21] Job job-invalid failed (exit code 127).
Workers started.

--- [STEP 5] WAITING FOR JOBS TO PROCESS ---
Waiting 10 seconds for jobs to complete, fail, and retry...
(Job 1/3 should complete. Job 2/4 should fail, retry, and move to DLQ).
[Worker 21] Processing job job-fail: exit 1
[Worker 21] Job job-fail failed (exit code 1).
[Worker 21] Processing job job-invalid: not_a_real_command
[Worker 21] Job job-invalid failed (exit code 127).
[Worker 20] Job job-long completed successfully.
Wait complete.

--- [STEP 6] CHECK FINAL STATUS & VERIFY ---
Running: queuectl status (Should show 2 completed, 2 dead)
   QueueCTL Status    
┏━━━━━━━━━━━━┳━━━━━━━┓
┃ State      ┃ Count ┃
┡━━━━━━━━━━━━╇━━━━━━━┩
│ Pending    │     0 │
│ Processing │     0 │
│ Completed  │     2 │
│ Failed     │     0 │
│ Dead       │     2 │
└────────────┴───────┘
Active Workers: 2 [20, 21]
Verifying 'completed' jobs...
Running: queuectl list --state completed
                                          Completed Jobs                                          
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job ID      ┃ Command                                  ┃ Attempts ┃ Updated At                 ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ job-success │ echo Job 1: Success                      │ 0        │ 2025-11-08T13:29:14.626789 │
│ job-long    │ sleep 3 && echo Job 3: Long job complete │ 0        │ 2025-11-08T13:29:17.654873 │
└─────────────┴──────────────────────────────────────────┴──────────┴────────────────────────────┘
Verified: 'job-success' and 'job-long' are COMPLETED.
Verifying 'dead' (DLQ) jobs...
Running: queuectl dlq list
                                 Dead Jobs                                  
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job ID      ┃ Command            ┃ Attempts ┃ Updated At                 ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ job-fail    │ exit 1             │ 2        │ 2025-11-08T13:29:16.693984 │
│ job-invalid │ not_a_real_command │ 2        │ 2025-11-08T13:29:16.707192 │
└─────────────┴────────────────────┴──────────┴────────────────────────────┘
Verified: 'job-fail' and 'job-invalid' are DEAD.
Verification complete.

--- [STEP 7] TEST DLQ RETRY ---
Running: queuectl dlq retry job-fail
Job job-fail moved from DLQ to 'pending'.
Running: queuectl status (Should show 1 pending)
   QueueCTL Status    
┏━━━━━━━━━━━━┳━━━━━━━┓
┃ State      ┃ Count ┃
┡━━━━━━━━━━━━╇━━━━━━━┩
│ Pending    │     1 │
│ Processing │     0 │
│ Completed  │     2 │
│ Failed     │     0 │
│ Dead       │     1 │
└────────────┴───────┘
Active Workers: 2 [20, 21]
Running: queuectl list --state pending (Should show 'job-fail')
                         Pending Jobs                         
┏━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job ID   ┃ Command ┃ Attempts ┃ Updated At                 ┃
┡━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ job-fail │ exit 1  │ 0        │ 2025-11-08T13:29:26.981786 │
└──────────┴─────────┴──────────┴────────────────────────────┘
Verified: 'job-fail' is PENDING.

--- [STEP 8] WAITING FOR DLQ JOB TO FAIL ---
Waiting 5 seconds for 'job-fail' to be processed and fail again...
[Worker 20] Processing job job-fail: exit 1
[Worker 20] Job job-fail failed (exit code 1).
[Worker 20] Processing job job-fail: exit 1
[Worker 20] Job job-fail failed (exit code 1).
Running: queuectl dlq list (Should show 'job-fail' back in DLQ)
                                 Dead Jobs                                  
┏━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job ID      ┃ Command            ┃ Attempts ┃ Updated At                 ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ job-fail    │ exit 1             │ 2        │ 2025-11-08T13:29:29.761998 │
│ job-invalid │ not_a_real_command │ 2        │ 2025-11-08T13:29:16.707192 │
└─────────────┴────────────────────┴──────────┴────────────────────────────┘
Verified: 'job-fail' is DEAD again.

--- [STEP 9] STOP WORKERS ---
Stopping worker manager (PID 18)...
[Manager] Shutdown signal received. Terminating 2 workers...
[Worker 20] Shutdown signal received. Exiting...
[Worker 21] Shutdown signal received. Exiting...
[Worker 20] Stopped and unregistered.
[Worker 21] Stopped and unregistered.
[Manager] All workers shut down. Exiting.
Workers stopped.

--- [STEP 10] FINAL STATUS CHECK ---
Running: queuectl status (Should show 0 active workers)
   QueueCTL Status    
┏━━━━━━━━━━━━┳━━━━━━━┓
┃ State      ┃ Count ┃
┡━━━━━━━━━━━━╇━━━━━━━┩
│ Pending    │     0 │
│ Processing │     0 │
│ Completed  │     2 │
│ Failed     │     0 │
│ Dead       │     2 │
└────────────┴───────┘
Active Workers: 0 []

--- [STEP 11] TEST FOR RACE CONDITIONS ---
This test will start 5 workers to try and grab 1 job at the same time.
Cleaning up old database at /data/queue.db...
Running: queuectl status (Should show 0 jobs)
   QueueCTL Status    
┏━━━━━━━━━━━━┳━━━━━━━┓
┃ State      ┃ Count ┃
┡━━━━━━━━━━━━╇━━━━━━━┩
│ Pending    │     0 │
│ Processing │     0 │
│ Completed  │     0 │
│ Failed     │     0 │
│ Dead       │     0 │
└────────────┴───────┘
Active Workers: 0 []
Running: queuectl enqueue '{"id":"job-race-test", "command":"sleep 2 && echo Race test job complete"}'
Job job-race-test enqueued: sleep 2 && echo Race test job complete
Running: queuectl list --state pending (Should show 1 job)
                                           Pending Jobs                                           
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job ID        ┃ Command                                ┃ Attempts ┃ Updated At                 ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ job-race-test │ sleep 2 && echo Race test job complete │ 0        │ 2025-11-08T13:29:34.798915 │
└───────────────┴────────────────────────────────────────┴──────────┴────────────────────────────┘
Running: queuectl worker start --count 5 --foreground &
Worker manager (Race Test) started with PID: 58
[Manager] Starting 5 worker(s) in foreground mode...
[Manager] Started worker PID: 60
[Manager] Started worker PID: 61
[Manager] Started worker PID: 62
[Manager] Started worker PID: 63
[Manager] Started worker PID: 64
[Worker 60] Started and registered.
[Worker 60] Processing job job-race-test: sleep 2 && echo Race test job complete
[Worker 61] Started and registered.
[Worker 62] Started and registered.
[Worker 63] Started and registered.
[Worker 64] Started and registered.
Waiting 5 seconds for the single job to be processed...
[Worker 60] Job job-race-test completed successfully.
Verifying results (Expect 1 completed job, 0 pending/failed/dead)
Running: queuectl status
   QueueCTL Status    
┏━━━━━━━━━━━━┳━━━━━━━┓
┃ State      ┃ Count ┃
┡━━━━━━━━━━━━╇━━━━━━━┩
│ Pending    │     0 │
│ Processing │     0 │
│ Completed  │     1 │
│ Failed     │     0 │
│ Dead       │     0 │
└────────────┴───────┘
Active Workers: 5 [60, 61, 62, 63, 64]
Checking 'completed' list...
                                          Completed Jobs                                          
┏━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Job ID        ┃ Command                                ┃ Attempts ┃ Updated At                 ┃
┡━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ job-race-test │ sleep 2 && echo Race test job complete │ 0        │ 2025-11-08T13:29:37.065122 │
└───────────────┴────────────────────────────────────────┴──────────┴────────────────────────────┘
Verified: 'job-race-test' is COMPLETED.
Checking 'pending' list...
Verified: 'job-race-test' is not PENDING.
Checking 'dead' list...
Verified: 'job-race-test' is not DEAD.
Verified: Job was processed exactly once by 5 workers.
Stopping worker manager (PID 58)...
[Manager] Shutdown signal received. Terminating 5 workers...
[Worker 61] Shutdown signal received. Exiting...
[Worker 63] Shutdown signal received. Exiting...
[Worker 60] Shutdown signal received. Exiting...
[Worker 62] Shutdown signal received. Exiting...
[Worker 64] Shutdown signal received. Exiting...
[Worker 60] Stopped and unregistered.
[Worker 63] Stopped and unregistered.
[Worker 61] Stopped and unregistered.
[Worker 64] Stopped and unregistered.
[Worker 62] Stopped and unregistered.
[Manager] All workers shut down. Exiting.
Race condition test complete.

--- Test Complete ---

```
