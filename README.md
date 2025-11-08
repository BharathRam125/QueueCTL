QueueCTL - Background Job Queuequeuectl is a CLI-based background job queue system built in Python. It uses SQLite for persistent storage and multiprocessing for parallel worker execution.FeaturesPersistent job queue (SQLite)Multiple parallel worker processesAutomatic job retries with exponential backoffDead Letter Queue (DLQ) for permanently failed jobsGraceful worker shutdownCLI-based management for all featuresSetup InstructionsClone the repository:git clone <your-repo-link>
cd <repository-name>
Create a virtual environment (recommended):python3 -m venv venv
source venv/bin/activate
Install dependencies:pip install -r requirements.txt
Make the CLI executable:chmod +x queuectl.py
Initialize the database:The database file queue.db will be created automatically in the directory when you run your first command../queuectl.py status
Usage ExamplesEnqueue a JobJobs are added as JSON strings. A command is required.# A simple job
./queuectl.py enqueue '{"id":"job1", "command":"echo Hello World"}'

# A job that will fail
./queuectl.py enqueue '{"command":"ls /nonexistent-directory"}'

# A job with custom retries
./queuectl.py enqueue '{"command":"exit 1", "max_retries": 5}'
Manage WorkersWorkers run as background processes.# Start 3 workers
./queuectl.py worker start --count 3

# Stop all running workers gracefully
# Workers will finish their current job before exiting.
./queuectl.py worker stop
Check StatusGet a summary of all job states and active workers../queuectl.py status
Example Output:┏━━━━━━━━━━━━━ QueueCTL Status ━━━━━━━━━━━━━┓
┃ State     │ Count                         ┃
┠───────────┼───────────────────────────────┨
┃ pending   │ 0                             ┃
┃ processing│ 0                             ┃
┃ completed │ 2                             ┃
┃ failed    │ 0                             ┃
┃ dead      │ 1                             ┃
┗━━━━━━━━━━━┷━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┛
Active Workers: 0 []
List JobsList jobs by their current state.# List all pending jobs (default)
./queuectl.py list
./queuectl.py list --state pending

# List all completed jobs
./queuectl.py list --state completed
Manage Dead Letter Queue (DLQ)View or retry permanently failed jobs.# List all permanently failed jobs
./queuectl.py dlq list

# Retry a specific job from the DLQ
./queuectl.py dlq retry <job-id>
ConfigurationManage internal settings, which are stored in the database.# Set the default max retries for new jobs
./queuectl.py config set max_retries 3

# Set the base for exponential backoff (delay = base ^ attempts)
./queuectl.py config set backoff_base 2

# View all configs
./queuectl.py config list
Architecture OverviewPersistence: SQLite is used as the data store (queue.db). It provides transactional, persistent, and process-safe storage for jobs, configuration, and worker process IDs.Concurrency:Workers: Implemented as separate OS processes using Python's multiprocessing module.Job Locking: To prevent duplicate job execution, the fetch_pending_job() function uses a BEGIN IMMEDIATE transaction in SQLite. This acquires an immediate database lock, ensuring that finding a pending job and marking it as 'processing' is a single atomic operation.Job Lifecycle:pending: A job is added via enqueue.processing: A worker atomically fetches the job.completed: The job's command exits with code 0.failed: The command exits with a non-zero code or times out.(Retry): If attempts < max_retries, the job state is set to failed and run_at is set to a future time based on exponential backoff (delay = base ^ attempts). It will be picked up again after this delay.dead: If attempts >= max_retries, the job is moved to the DLQ.Graceful Shutdown: Workers listen for SIGTERM (sent by worker stop). A running flag is set to False, and the worker exits its main loop after its current job is complete.Assumptions & Trade-offsshell=True: Job commands are executed with subprocess.run(..., shell=True). This is required to interpret commands like echo 'Hello' but can be a security risk if untrusted input can be enqueued. A production system might tokenize commands or run them in a sandboxed environment.SQLite Concurrency: SQLite locks the entire database file on writes. This is perfectly acceptable for this assignment's scale, but a high-throughput system would require a database server like PostgreSQL or Redis that supports row-level locking.Worker Management: Worker PIDs are stored in the DB. If a worker is hard-killed (kill -9), its PID may be left in the workers table, requiring manual cleanup. A more robust system would use a heartbeat mechanism.Testing InstructionsA validation script is provided to test all core functionality.Ensure you have followed the Setup Instructions.Run the script:./validate.sh
This script will:Clean the database.Set configuration.Enqueue successful, failing, and long-running jobs.Start workers and wait for jobs to be processed.Verify that jobs have moved to the correct final states (completed or dead).Test the dlq retry command.Stop all workers.