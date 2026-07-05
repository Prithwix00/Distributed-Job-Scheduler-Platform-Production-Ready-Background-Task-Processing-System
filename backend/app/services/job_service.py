"""Job creation and lifecycle transitions.

Every state change funnels through here so the invariants (attempt counting,
execution rows, DLQ handoff, timestamps) live in one place.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from croniter import croniter
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..models import (
    Job, Queue, RetryPolicy, JobExecution, JobLog, DeadLetterEntry,
)
from ..models.enums import JobState, JobType, ExecutionStatus, RetryStrategy
from .retry import compute_backoff_seconds


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _policy_defaults(db: Session, queue: Queue) -> dict:
    """Snapshot the effective retry policy for a queue into plain values."""
    policy: RetryPolicy | None = queue.retry_policy
    if policy is None:
        return dict(
            max_attempts=3,
            retry_strategy=RetryStrategy.EXPONENTIAL,
            base_delay_seconds=5.0,
            max_delay_seconds=3600.0,
            backoff_factor=2.0,
            jitter=0.1,
        )
    return dict(
        max_attempts=policy.max_attempts,
        retry_strategy=policy.strategy,
        base_delay_seconds=policy.base_delay_seconds,
        max_delay_seconds=policy.max_delay_seconds,
        backoff_factor=policy.backoff_factor,
        jitter=policy.jitter,
    )


def create_job(
    db: Session,
    *,
    queue: Queue,
    task_name: str,
    payload: dict,
    job_type: JobType = JobType.IMMEDIATE,
    run_at: datetime | None = None,
    delay_seconds: float | None = None,
    cron_expression: str | None = None,
    timezone_name: str = "UTC",
    priority: int | None = None,
    idempotency_key: str | None = None,
    batch_id: str | None = None,
    depends_on_job_id: str | None = None,
    overrides: dict | None = None,
    commit: bool = True,
) -> Job:
    """Create and enqueue a single job, snapshotting the retry policy."""
    now = _now()

    # Idempotency: collapse duplicate submissions per queue.
    if idempotency_key:
        existing = db.execute(
            select(Job).where(
                Job.queue_id == queue.id, Job.idempotency_key == idempotency_key
            )
        ).scalar_one_or_none()
        if existing:
            return existing

    # Resolve run_at and initial state from the job type.
    if delay_seconds is not None:
        run_at = now + timedelta(seconds=delay_seconds)
    if cron_expression:
        itr = croniter(cron_expression, now)
        run_at = itr.get_next(datetime)
    if run_at is None:
        run_at = now

    # Dependent jobs and future-dated jobs start SCHEDULED; the scheduler
    # promotes them to QUEUED when they become due.
    if depends_on_job_id:
        state = JobState.SCHEDULED
    elif run_at > now:
        state = JobState.SCHEDULED
    else:
        state = JobState.QUEUED

    defaults = _policy_defaults(db, queue)
    if overrides:
        defaults.update({k: v for k, v in overrides.items() if v is not None})

    job = Job(
        queue_id=queue.id,
        task_name=task_name,
        payload=payload or {},
        job_type=job_type,
        state=state,
        priority=priority if priority is not None else queue.priority,
        run_at=run_at,
        idempotency_key=idempotency_key,
        cron_expression=cron_expression,
        timezone_name=timezone_name,
        batch_id=batch_id,
        depends_on_job_id=depends_on_job_id,
        **defaults,
    )
    db.add(job)
    if commit:
        db.commit()
        db.refresh(job)
    else:
        db.flush()
    return job


def create_batch(
    db: Session, *, queue: Queue, task_name: str, items: list[dict], priority: int | None = None
) -> tuple[str, list[Job]]:
    """Create many sibling jobs sharing one batch_id."""
    batch_id = str(uuid.uuid4())
    jobs = [
        create_job(
            db, queue=queue, task_name=task_name, payload=item,
            job_type=JobType.BATCH, priority=priority, batch_id=batch_id, commit=False,
        )
        for item in items
    ]
    db.commit()
    for j in jobs:
        db.refresh(j)
    return batch_id, jobs


def add_log(db: Session, job_id: str, message: str, level: str = "info",
            execution_id: str | None = None, context: dict | None = None) -> None:
    db.add(JobLog(job_id=job_id, execution_id=execution_id, level=level,
                  message=message, context=context))


def start_execution(db: Session, job: Job, worker_id: str) -> JobExecution:
    """Transition CLAIMED -> RUNNING and open an execution record."""
    now = _now()
    job.attempts += 1
    job.state = JobState.RUNNING
    job.started_at = job.started_at or now
    job.updated_at = now

    execution = JobExecution(
        job_id=job.id,
        worker_id=worker_id,
        attempt_number=job.attempts,
        status=ExecutionStatus.RUNNING.value,
        started_at=now,
    )
    db.add(execution)
    add_log(db, job.id, f"Attempt {job.attempts} started on worker {worker_id}",
            execution_id=execution.id)
    db.commit()
    db.refresh(execution)
    return execution


def complete_job(db: Session, job: Job, execution: JobExecution, result: dict | None) -> None:
    now = _now()
    duration = int((now - execution.started_at).total_seconds() * 1000)

    execution.status = ExecutionStatus.SUCCEEDED.value
    execution.finished_at = now
    execution.duration_ms = duration
    execution.result = result

    job.state = JobState.COMPLETED
    job.finished_at = now
    job.result = result
    job.last_error = None
    job.lease_expires_at = None
    job.updated_at = now

    add_log(db, job.id, "Job completed", execution_id=execution.id)
    _release_dependents(db, job, now)
    db.commit()


def fail_job(db: Session, job: Job, execution: JobExecution, error: str) -> None:
    """Record a failed attempt and either schedule a retry or dead-letter it."""
    now = _now()
    duration = int((now - execution.started_at).total_seconds() * 1000)

    execution.status = ExecutionStatus.FAILED.value
    execution.finished_at = now
    execution.duration_ms = duration
    execution.error = error

    job.last_error = error
    job.lease_expires_at = None

    if job.attempts >= job.max_attempts:
        # Retries exhausted -> Dead Letter Queue.
        job.state = JobState.DEAD
        job.finished_at = now
        job.updated_at = now
        db.add(DeadLetterEntry(
            job_id=job.id,
            queue_id=job.queue_id,
            task_name=job.task_name,
            payload=job.payload,
            total_attempts=job.attempts,
            last_error=error,
        ))
        add_log(db, job.id, f"Job dead-lettered after {job.attempts} attempts",
                level="error", execution_id=execution.id)
    else:
        # Schedule a retry using the snapshotted backoff policy.
        delay = compute_backoff_seconds(
            strategy=job.retry_strategy,
            attempt=job.attempts,
            base_delay=job.base_delay_seconds,
            backoff_factor=job.backoff_factor,
            max_delay=job.max_delay_seconds,
            jitter=job.jitter,
        )
        job.run_at = now + timedelta(seconds=delay)
        job.state = JobState.SCHEDULED
        job.claimed_by_worker_id = None
        job.claimed_at = None
        job.updated_at = now
        add_log(
            db, job.id,
            f"Attempt {job.attempts} failed, retrying in {delay:.1f}s",
            level="warning", execution_id=execution.id,
        )

    db.commit()


def _release_dependents(db: Session, job: Job, now: datetime) -> None:
    """When a job completes, promote any jobs that depended on it."""
    dependents = db.execute(
        select(Job).where(
            Job.depends_on_job_id == job.id,
            Job.state == JobState.SCHEDULED,
        )
    ).scalars().all()
    for dep in dependents:
        if dep.run_at <= now:
            dep.state = JobState.QUEUED
        dep.depends_on_job_id = None
        dep.updated_at = now


def replay_dead_letter(db: Session, entry: DeadLetterEntry) -> Job:
    """Re-enqueue a dead-lettered job as a fresh job for operator retry."""
    queue = db.get(Queue, entry.queue_id)
    job = create_job(
        db, queue=queue, task_name=entry.task_name, payload=entry.payload,
        job_type=JobType.IMMEDIATE,
    )
    entry.replayed_at = _now()
    db.commit()
    return job
