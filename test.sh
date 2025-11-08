#!/bin/bash
set -e

echo "--- QueueCTL Test Script (Detailed) ---"
echo "This script will test all core functionality, including retries and the DLQ."
echo

# Use the environment variable for the DB path, or default to 'queue.db'
DB_FILE=${QUEUECTL_DB_PATH:-queue.db}

# --- 0. Cleanup ---
echo "--- [STEP 0] CLEANUP ---"
echo "Cleaning up old database at $DB_FILE..."
rm -f "$DB_FILE"
echo "Cleanup complete."
echo

# --- 1. Set Configuration ---
echo "--- [STEP 1] SET CONFIGURATION ---"
echo "Running: queuectl config set max_retries 2"
queuectl config set max_retries 2
echo "Running: queuectl config set backoff_base 2"
queuectl config set backoff_base 2
echo "Running: queuectl config list"
queuectl config list
echo "Configuration set."
echo

# --- 2. Enqueue Jobs ---
echo "--- [STEP 2] ENQUEUE JOBS ---"
echo "Running: queuectl enqueue '{\"id\":\"job-success\", \"command\":\"echo Job 1: Success\"}'"
queuectl enqueue '{"id":"job-success", "command":"echo Job 1: Success"}'
echo "Running: queuectl enqueue '{\"id\":\"job-fail\", \"command\":\"exit 1\"}'"
queuectl enqueue '{"id":"job-fail", "command":"exit 1"}'
echo "Running: queuectl enqueue '{\"id\":\"job-long\", \"command\":\"sleep 3 && echo Job 3: Long job complete\"}'"
queuectl enqueue '{"id":"job-long", "command":"sleep 3 && echo Job 3: Long job complete"}'
echo "Running: queuectl enqueue '{\"id\":\"job-invalid\", \"command\":\"not_a_real_command\"}'"
queuectl enqueue '{"id":"job-invalid", "command":"not_a_real_command"}'
echo "All jobs enqueued."
echo

# --- 3. Check Initial Status ---
echo "--- [STEP 3] CHECK INITIAL STATUS ---"
echo "Running: queuectl status (Should show 4 pending jobs)"
queuectl status
echo "Running: queuectl list --state pending"
queuectl list --state pending
echo "Initial status checked."
echo

# --- 4. Start Workers ---
echo "--- [STEP 4] START WORKERS ---"
echo "Running: queuectl worker start --count 2 --foreground &"
queuectl worker start --count 2 --foreground &
WORKER_PID=$!
echo "Worker manager process started with PID: $WORKER_PID"
sleep 2 # Give workers a moment to start up
echo "Workers started."
echo

# --- 5. Wait for Jobs to Process ---
echo "--- [STEP 5] WAITING FOR JOBS TO PROCESS ---"
echo "Waiting 10 seconds for jobs to complete, fail, and retry..."
echo "(Job 1/3 should complete. Job 2/4 should fail, retry, and move to DLQ)."
sleep 10
echo "Wait complete."
echo

# --- 6. Check Final Status & Verify ---
echo "--- [STEP 6] CHECK FINAL STATUS & VERIFY ---"
echo "Running: queuectl status (Should show 2 completed, 2 dead)"
queuectl status

echo "Verifying 'completed' jobs..."
echo "Running: queuectl list --state completed"
COMPLETED_JOBS=$(queuectl list --state completed)
echo "$COMPLETED_JOBS"
if ! echo "$COMPLETED_JOBS" | grep -q "job-success"; then
    echo "TEST FAILED: 'job-success' did not complete."
    exit 1
fi
if ! echo "$COMPLETED_JOBS" | grep -q "job-long"; then
    echo "TEST FAILED: 'job-long' did not complete."
    exit 1
fi
echo "Verified: 'job-success' and 'job-long' are COMPLETED."

echo "Verifying 'dead' (DLQ) jobs..."
echo "Running: queuectl dlq list"
DEAD_JOBS=$(queuectl dlq list)
echo "$DEAD_JOBS"
if ! echo "$DEAD_JOBS" | grep -q "job-fail"; then
    echo "TEST FAILED: 'job-fail' did not move to DLQ."
    exit 1
fi
if ! echo "$DEAD_JOBS" | grep -q "job-invalid"; then
    echo "TEST FAILED: 'job-invalid' did not move to DLQ."
    exit 1
fi
echo "Verified: 'job-fail' and 'job-invalid' are DEAD."
echo "Verification complete."
echo

# --- 7. Test DLQ Retry ---
echo "--- [STEP 7] TEST DLQ RETRY ---"
echo "Running: queuectl dlq retry job-fail"
queuectl dlq retry job-fail

echo "Running: queuectl status (Should show 1 pending)"
queuectl status
echo "Running: queuectl list --state pending (Should show 'job-fail')"
PENDING_JOBS=$(queuectl list --state pending)
echo "$PENDING_JOBS"
if ! echo "$PENDING_JOBS" | grep -q "job-fail"; then
    echo "TEST FAILED: 'job-fail' was not requeued to pending."
    exit 1
fi
echo "Verified: 'job-fail' is PENDING."
echo

# --- 8. Wait for DLQ Job to Fail Again ---
echo "--- [STEP 8] WAITING FOR DLQ JOB TO FAIL ---"
echo "Waiting 5 seconds for 'job-fail' to be processed and fail again..."
sleep 5

echo "Running: queuectl dlq list (Should show 'job-fail' back in DLQ)"
FINAL_DLQ=$(queuectl dlq list)
echo "$FINAL_DLQ"
if ! echo "$FINAL_DLQ" | grep -q "job-fail"; then
    echo "TEST FAILED: 'job-fail' did not return to DLQ."
    exit 1
fi
echo "Verified: 'job-fail' is DEAD again."
echo

# --- 9. Stop Workers ---
echo "--- [STEP 9] STOP WORKERS ---"
echo "Stopping worker manager (PID $WORKER_PID)..."
kill -s TERM $WORKER_PID
sleep 2 # Wait for it to shut down
echo "Workers stopped."
echo

# --- 10. Final Status Check ---
echo "--- [STEP 10] FINAL STATUS CHECK ---"
echo "Running: queuectl status (Should show 0 active workers)"
queuectl status
echo

# --- 11. Test for Race Conditions ---
echo "--- [STEP 11] TEST FOR RACE CONDITIONS ---"
echo "This test will start 5 workers to try and grab 1 job at the same time."

# 11a. Cleanup
echo "Cleaning up old database at $DB_FILE..."
rm -f "$DB_FILE"
echo "Running: queuectl status (Should show 0 jobs)"
queuectl status

# 11b. Enqueue one job
echo "Running: queuectl enqueue '{\"id\":\"job-race-test\", \"command\":\"sleep 2 && echo Race test job complete\"}'"
queuectl enqueue '{"id":"job-race-test", "command":"sleep 2 && echo Race test job complete"}'
echo "Running: queuectl list --state pending (Should show 1 job)"
queuectl list --state pending

# 11c. Start many workers
echo "Running: queuectl worker start --count 5 --foreground &"
queuectl worker start --count 5 --foreground &
WORKER_PID_2=$!
echo "Worker manager (Race Test) started with PID: $WORKER_PID_2"
sleep 2 # Give workers a moment to start up

# 11d. Wait for job to process
echo "Waiting 5 seconds for the single job to be processed..."
sleep 5

# 11e. Verify results
echo "Verifying results (Expect 1 completed job, 0 pending/failed/dead)"
echo "Running: queuectl status"
queuectl status

echo "Checking 'completed' list..."
COMPLETED_JOBS_RACE=$(queuectl list --state completed)
echo "$COMPLETED_JOBS_RACE"
if ! echo "$COMPLETED_JOBS_RACE" | grep -q "job-race-test"; then
    echo "TEST FAILED: 'job-race-test' did not complete."
    exit 1
fi
# Check that ONLY one job is completed
COMPLETED_COUNT=$(echo "$COMPLETED_JOBS_RACE" | grep -c "job-race-test" || true)
if [ "$COMPLETED_COUNT" -ne 1 ]; then
    echo "TEST FAILED: 'job-race-test' was processed $COMPLETED_COUNT times! Race condition occurred."
    exit 1
fi
echo "Verified: 'job-race-test' is COMPLETED."

echo "Checking 'pending' list..."
# The '|| true' ensures the command doesn't fail if grep finds nothing
PENDING_COUNT=$(queuectl list --state pending | grep -c "job-race-test" || true)
if [ "$PENDING_COUNT" -ne 0 ]; then
    echo "TEST FAILED: 'job-race-test' is still pending."
    exit 1
fi
echo "Verified: 'job-race-test' is not PENDING."

echo "Checking 'dead' list..."
DEAD_COUNT=$(queuectl dlq list | grep -c "job-race-test" || true)
if [ "$DEAD_COUNT" -ne 0 ]; then
    echo "TEST FAILED: 'job-race-test' is in DLQ."
    exit 1
fi
echo "Verified: 'job-race-test' is not DEAD."
echo "Verified: Job was processed exactly once by 5 workers."

# 11f. Cleanup
echo "Stopping worker manager (PID $WORKER_PID_2)..."
kill -s TERM $WORKER_PID_2
sleep 2
echo "Race condition test complete."
echo

echo "--- Test Complete ---"