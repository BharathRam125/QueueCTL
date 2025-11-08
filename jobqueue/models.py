import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime

class JobState(str, enum.Enum):
    """Enumeration of possible job states."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"

@dataclass
class Job:
    """Dataclass representing a job."""
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    command: str = ""
    state: JobState = JobState.PENDING
    attempts: int = 0
    max_retries: int = 3
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    run_at: str | None = None  # For scheduled retries

    def to_row(self):
        """Converts the Job object to a tuple for database insertion."""
        return (
            self.id, self.command, self.state.value, self.attempts,
            self.max_retries, self.created_at, self.updated_at, self.run_at
        )

    @staticmethod
    def from_row(row: tuple):
        """Creates a Job object from a database row tuple."""
        return Job(
            id=row[0],
            command=row[1],
            state=JobState(row[2]),
            attempts=row[3],
            max_retries=row[4],
            created_at=row[5],
            updated_at=row[6],
            run_at=row[7]
        )