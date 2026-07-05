"""Scheduler tick logic: promote due jobs, fire cron schedules, reap dead workers.

Runs in a dedicated single-instance process (the scheduler). Keeping promotion
out of the workers means workers stay simple pollers and there is one clear
owner of time-based transitions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from croniter import croniter
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Job, Queue, ScheduledJob, Worker
from ..models.enums import JobState, JobType, WorkerStatus
from .job_service import create_job


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def promote_due_scheduled(db: Session, now: datetime | None = None) -> int:
    """Move SCHEDULED jobs whose run_at has arrived (and with no unmet
    dependency) into QUEUED so workers can claim them."""
    now = now or _now()
    result = db.execute(
        update(Job)
        .where(
            Job.state == JobState.SCHEDULED,
            Job.run_at <= now,
            Job.depends_on_job_id.is_(None),
        )
        .values(state=JobState.QUEUED, updated_at=now)
    )
    db.commit()
    return result.rowcount


def fire_due_cron(db: Session, now: datetime | None = None) -> int:
    """Materialise a Job for each recurring definition whose next_fire_at passed,
    then advance the schedule to the following fire time."""
    now = now or _now()
    due = db.execute(
        select(ScheduledJob).where(
            ScheduledJob.is_active.is_(True),
            ScheduledJob.next_fire_at <= now,
        )
    ).scalars().all()

    fired = 0
    for sched in due:
        queue = db.get(Queue, sched.queue_id)
        if queue is None:
            continue
        create_job(
            db, queue=queue, task_name=sched.task_name, payload=sched.payload,
            job_type=JobType.RECURRING, run_at=now, commit=False,
        )
        itr = croniter(sched.cron_expression, now)
        sched.last_fired_at = now
        sched.next_fire_at = itr.get_next(datetime)
        fired += 1

    db.commit()
    return fired


def reap_dead_workers(db: Session, now: datetime | None = None) -> int:
    """Mark workers whose heartbeat expired as DEAD. Their in-flight jobs are
    recovered separately by lease reaping in the claiming service."""
    now = now or _now()
    cutoff = now - timedelta(seconds=settings.heartbeat_timeout_seconds)
    result = db.execute(
        update(Worker)
        .where(
            Worker.status != WorkerStatus.DEAD,
            Worker.last_heartbeat_at < cutoff,
        )
        .values(status=WorkerStatus.DEAD)
    )
    db.commit()
    return result.rowcount
