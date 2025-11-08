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

## How to Run (Docker)

This is the recommended way to run and test the application.

### Prerequisites

* Docker

* Docker Compose

### Step 1: Build the Image

First, build the Docker image. This will install all dependencies and use `setup.py` to install `queuectl` as a command inside the container.

```
docker-compose build

```

### Step 2: Run the System (Two-Terminal Workflow)

You need two terminals: one for the (background) worker service and one to send (client) commands.

**In Terminal 1: Start the Workers**

This command starts the `worker` service in the background. It will automatically run 2 workers (as defined in `docker-compose.yml`) and continuously watch the database for new jobs.

```
docker-compose up -d worker

```

**In Terminal 2: Send Commands**

Use `docker-compose run --rm queuectl` to run any `queuectl` command. This creates a new, temporary container that connects to the same database.

```
# Check the status of the queue
docker-compose run --rm queuectl status

# Enqueue a new job
docker-compose run --rm queuectl enqueue '{"command":"echo Hello from Docker"}'

# List all pending jobs
docker-compose run --rm queuectl list --state pending

```

### Step 3: View Worker Logs

To see the output from your running workers in Terminal 1, run:

```
docker-compose logs -f worker

```

You will see jobs being picked up, processed, and completed here in real-time.

### Step 4: Stop Everything

When you are finished, this command will stop and remove the worker container and network.

```
docker-compose down

```

*(Your data is safe, as it's stored in the `queue_data` Docker volume).*

## How to Test

This project includes a detailed end-to-end test script, `validate.sh`. The easiest way to run it is by using the `shell` service defined in `docker-compose.yml`.

### Step 1: Start the Interactive Shell

This command will start a new container and drop you into a `/bin/bash` prompt *inside* that container.

```
docker-compose run --rm shell

```

### Step 2: Run the Testing Script

Your terminal prompt will change (e.g., `root@...:/app#`). You are now inside the container, and `queuectl` is an available command.

Run the test script:

```
./test.sh

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
