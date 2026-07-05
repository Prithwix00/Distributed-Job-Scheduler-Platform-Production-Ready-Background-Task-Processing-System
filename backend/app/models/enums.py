"""Enumerations shared across the domain models."""
import enum


class JobState(str, enum.Enum):
    """Full job lifecycle.

    QUEUED     -> ready to be claimed now
    SCHEDULED  -> waiting for run_at (delayed / scheduled / next cron fire)
    CLAIMED    -> a worker has atomically taken ownership, not yet executing
    RUNNING    -> handler is executing
    COMPLETED  -> finished successfully
    FAILED     -> attempt failed, awaiting retry backoff (transient state)
    DEAD       -> retries exhausted, moved to the Dead Letter Queue
    CANCELLED  -> cancelled by a user before completion
    """

    QUEUED = "queued"
    SCHEDULED = "scheduled"
    CLAIMED = "claimed"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"
    CANCELLED = "cancelled"


TERMINAL_STATES = {JobState.COMPLETED, JobState.DEAD, JobState.CANCELLED}
ACTIVE_STATES = {JobState.CLAIMED, JobState.RUNNING}


class JobType(str, enum.Enum):
    IMMEDIATE = "immediate"
    DELAYED = "delayed"
    SCHEDULED = "scheduled"
    RECURRING = "recurring"  # cron driven
    BATCH = "batch"          # child job of a batch


class ExecutionStatus(str, enum.Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    LOST = "lost"  # worker died mid execution (heartbeat expired)


class RetryStrategy(str, enum.Enum):
    FIXED = "fixed"
    LINEAR = "linear"
    EXPONENTIAL = "exponential"


class WorkerStatus(str, enum.Enum):
    ALIVE = "alive"
    DRAINING = "draining"  # graceful shutdown in progress
    DEAD = "dead"          # heartbeat expired


class LogLevel(str, enum.Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class UserRole(str, enum.Enum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"
