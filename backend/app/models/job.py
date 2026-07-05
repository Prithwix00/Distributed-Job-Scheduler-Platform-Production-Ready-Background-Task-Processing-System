"""The Job model and its child tables."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    String, ForeignKey, DateTime, Integer, Enum, Text, Float, Index, UniqueConstraint
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import JobState, JobType, RetryStrategy
from .types import JSONType


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        # The single most important index: the worker claim query filters on
        # (queue_id, state) and orders by (priority, run_at). A composite index
        # keeps claiming O(log n) even with millions of terminal-state rows.
        Index("ix_jobs_claim", "queue_id", "state", "priority", "run_at"),
        Index("ix_jobs_state_runat", "state", "run_at"),
        Index("ix_jobs_batch", "batch_id"),
        # Idempotency: a caller-supplied key is unique per queue so duplicate
        # submissions collapse to one job.
        UniqueConstraint("queue_id", "idempotency_key", name="uq_job_idem"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    queue_id: Mapped[str] = mapped_column(
        ForeignKey("queues.id", ondelete="CASCADE"), nullable=False
    )

    # What to run. task_name maps to a registered handler; payload is its input.
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)

    job_type: Mapped[JobType] = mapped_column(Enum(JobType, native_enum=False), default=JobType.IMMEDIATE)
    state: Mapped[JobState] = mapped_column(
        Enum(JobState, native_enum=False), default=JobState.QUEUED, index=True
    )

    # Effective priority (defaults to the queue priority, overridable per job).
    priority: Mapped[int] = mapped_column(Integer, default=0)

    # When the job becomes eligible to run. For immediate jobs this is creation
    # time; for delayed/scheduled it is the target time; for recurring it is the
    # next cron fire time.
    run_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    # Idempotency and dedup
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Retry bookkeeping. Snapshotted from the queue policy at enqueue time so a
    # later policy change does not retroactively alter in-flight jobs.
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    retry_strategy: Mapped[RetryStrategy] = mapped_column(
        Enum(RetryStrategy, native_enum=False), default=RetryStrategy.EXPONENTIAL
    )
    base_delay_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    max_delay_seconds: Mapped[float] = mapped_column(Float, default=3600.0)
    backoff_factor: Mapped[float] = mapped_column(Float, default=2.0)
    jitter: Mapped[float] = mapped_column(Float, default=0.1)

    # Recurring (cron) jobs
    cron_expression: Mapped[str | None] = mapped_column(String(120), nullable=True)
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC")

    # Batch grouping. A batch job has a batch_id shared by its siblings.
    batch_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # Workflow dependency (bonus): this job stays SCHEDULED until the parent completes.
    depends_on_job_id: Mapped[str | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    # Ownership / concurrency-control fields set atomically at claim time.
    claimed_by_worker_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    # Fencing token / heartbeat used to detect a claim from a dead worker.
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    # Result / error surface
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(), default=_now, onupdate=_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    queue: Mapped["Queue"] = relationship(back_populates="jobs")  # noqa: F821
    executions: Mapped[list["JobExecution"]] = relationship(
        back_populates="job", cascade="all, delete-orphan", order_by="JobExecution.attempt_number"
    )
    logs: Mapped[list["JobLog"]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )


class JobExecution(Base):
    """One row per attempt. Preserves full retry history and metrics."""

    __tablename__ = "job_executions"
    __table_args__ = (
        Index("ix_exec_job", "job_id", "attempt_number"),
        Index("ix_exec_worker", "worker_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(
        ForeignKey("workers.id", ondelete="SET NULL"), nullable=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # ExecutionStatus

    started_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    result: Mapped[dict | None] = mapped_column(JSONType, nullable=True)

    job: Mapped[Job] = relationship(back_populates="executions")


class JobLog(Base):
    """Structured, timestamped log lines emitted during execution."""

    __tablename__ = "job_logs"
    __table_args__ = (Index("ix_joblog_job_ts", "job_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    execution_id: Mapped[str | None] = mapped_column(
        ForeignKey("job_executions.id", ondelete="CASCADE"), nullable=True
    )
    level: Mapped[str] = mapped_column(String(10), default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    context: Mapped[dict | None] = mapped_column(JSONType, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    job: Mapped[Job] = relationship(back_populates="logs")


class DeadLetterEntry(Base):
    """A job that exhausted its retries. Kept separate for operator triage."""

    __tablename__ = "dead_letter_queue"
    __table_args__ = (Index("ix_dlq_queue", "queue_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    job_id: Mapped[str] = mapped_column(ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False)
    queue_id: Mapped[str] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    total_attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Optional AI-generated summary (bonus feature).
    failure_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    replayed_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)
