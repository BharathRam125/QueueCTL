QueueCTL - A Python Background Job QueueQueueCTL is a minimal, production-grade, CLI-based background job queue system built in Python.It uses SQLite for persistent, transactional job storage, multiprocessing for parallel worker execution, and is packaged with Docker for easy deployment and testing.FeaturesPersistent Storage: Jobs are stored in a SQLite database (queue.db) and persist across restarts.Parallel Workers: Run multiple worker processes in parallel to process jobs concurrently.* Atomic Operations: Workers use database-level locking (BEGIN IMMEDIATE) to prevent race conditions and ensure a job is only processed once.Automatic Retries: Failed jobs are automatically retried with exponential backoff (delay = base ^ attempts).Dead Letter Queue (DLQ): Jobs that exhaust their max_retries are moved to the DLQ for manual inspection.Clean CLI: All operations are managed through a typer-based CLI.Dockerized: Comes with a docker-compose.yml for a production-like and testable environment.Project Structure```queuectl-project/├── docker-compose.yml  # Defines all services (worker, cli, shell)├── Dockerfile          # Recipe to build the container├── pyproject.toml      # Build system configuration├── setup.py            # Makes queuectl an installable package├── requirements.txt    # Python dependencies├── queuectl.py         # The main CLI application├── validate.sh         # The end-to-end test script└── jobqueue/           # The core application logic (renamed from 'queue')├── init.py├── db.py           # Database logic (locking, fetching, updating)├── models.py       # Job and JobState data models└── worker.py       # Worker class and job execution logic
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


docker-compose up -d worker
**In Terminal 2: Send Commands**

Use `docker-compose run --rm queuectl` to run any `queuectl` command. This creates a new, temporary container that connects to the same database.


Check the status of the queuedocker-compose run --rm queuectl statusEnqueue a new jobdocker-compose run --rm queuectl enqueue '{"command":"echo Hello from Docker"}'List all pending jobsdocker-compose run --rm queuectl list --state pending
### Step 3: View Worker Logs

To see the output from your running workers in Terminal 1, run:


docker-compose logs -f worker
You will see jobs being picked up, processed, and completed here in real-time.

### Step 4: Stop Everything

When you are finished, this command will stop and remove the worker container and network.


docker-compose down
*(Your data is safe, as it's stored in the `queue_data` Docker volume).*

## How to Test

This project includes a detailed end-to-end test script, `validate.sh`. The easiest way to run it is by using the `shell` service defined in `docker-compose.yml`.

### Step 1: Start the Interactive Shell

This command will start a new container and drop you into a `/bin/bash` prompt *inside* that container.


docker-compose run --rm shell
### Step 2: Run the Testing Script

Your terminal prompt will change (e.g., `root@...:/app#`). You are now inside the container, and `queuectl` is an available command.

Run the test script:


./validate.sh
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


exit
## CLI Command Reference

Once inside the `shell`, you can get help for any command.


Get all top-level commandsqueuectl --helpGet help for a subcommand (e.g., worker)queuectl worker --help
  * **`queuectl enqueue '{"cmd":...}'`**: Adds a new job.

  * **`queuectl status`**: Shows a summary of job states and active workers.

  * **`queuectl list --state <state>`**: Lists all jobs in a specific state.

  * **`queuectl worker start --count <n>`**: Starts worker processes.

  * **`queuectl worker stop`**: Stops all registered workers.

  * **`queuectl dlq list`**: Lists all jobs in the Dead Letter Queue.

  * **`queuectl dlq retry <job-id>`**: Re-queues a dead job.

  * **`queuectl config set <key> <value>`**: Sets a config value (e.g., `max_retries`).

  * **`queuectl config get <key>`**: Retrieves a config value.



