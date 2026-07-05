from __future__ import annotations

from datetime import datetime, timezone

from croniter import croniter
from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session, selectinload

from ..core import NotFoundError, ConflictError, AppError
from ..database import get_db
from ..deps import get_current_user, get_scoped_queue, Pagination
from ..models import Job, Queue, ScheduledJob, DeadLetterEntry, User
from ..models.enums import JobState, JobType, TERMINAL_STATES
from ..schemas.common import Page
from ..schemas.job import (
    JobCreate, JobOut, JobDetail, BatchCreate,
    ScheduledJobCreate, ScheduledJobOut, DeadLetterOut,
)
from ..services import job_service

router = APIRouter(tags=["jobs"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/queues/{queue_id}/jobs", response_model=JobOut, status_code=201)
def create_job(queue_id: str, body: JobCreate, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)

    if body.cron_expression:
        try:
            croniter(body.cron_expression)
        except (ValueError, KeyError):
            raise AppError("Invalid cron expression", code="invalid_cron")

    overrides = body.retry.model_dump(exclude_unset=True) if body.retry else None

    job = job_service.create_job(
        db, queue=queue, task_name=body.task_name, payload=body.payload,
        job_type=body.job_type, run_at=body.run_at, delay_seconds=body.delay_seconds,
        cron_expression=body.cron_expression, timezone_name=body.timezone_name,
        priority=body.priority, idempotency_key=body.idempotency_key,
        depends_on_job_id=body.depends_on_job_id, overrides=overrides,
    )
    return job


@router.post("/queues/{queue_id}/batches", response_model=list[JobOut], status_code=201)
def create_batch(queue_id: str, body: BatchCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)
    _, jobs = job_service.create_batch(
        db, queue=queue, task_name=body.task_name, items=body.items, priority=body.priority
    )
    return jobs


@router.get("/queues/{queue_id}/jobs", response_model=Page[JobOut])
def list_jobs(
    queue_id: str,
    state: JobState | None = Query(None),
    job_type: JobType | None = Query(None),
    task_name: str | None = Query(None),
    pg: Pagination = Depends(),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    queue = get_scoped_queue(queue_id, db, user)

    filters = [Job.queue_id == queue.id]
    if state:
        filters.append(Job.state == state)
    if job_type:
        filters.append(Job.job_type == job_type)
    if task_name:
        filters.append(Job.task_name == task_name)

    total = db.execute(select(func.count(Job.id)).where(*filters)).scalar_one()
    rows = db.execute(
        select(Job).where(*filters)
        .order_by(Job.created_at.desc())
        .offset(pg.offset).limit(pg.page_size)
    ).scalars().all()

    pages = (total + pg.page_size - 1) // pg.page_size
    return Page[JobOut](items=rows, total=total, page=pg.page, page_size=pg.page_size, pages=pages)


@router.get("/jobs/{job_id}", response_model=JobDetail)
def get_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.execute(
        select(Job).options(selectinload(Job.executions), selectinload(Job.logs))
        .where(Job.id == job_id)
    ).scalar_one_or_none()
    if not job:
        raise NotFoundError("Job not found")
    # tenancy check
    get_scoped_queue(job.queue_id, db, user)
    return job


@router.post("/jobs/{job_id}/cancel", response_model=JobOut)
def cancel_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Job not found")
    get_scoped_queue(job.queue_id, db, user)
    if job.state in TERMINAL_STATES:
        raise ConflictError(f"Job already {job.state.value}")
    job.state = JobState.CANCELLED
    job.finished_at = _now()
    db.commit()
    db.refresh(job)
    return job


@router.post("/jobs/{job_id}/retry", response_model=JobOut)
def retry_job(job_id: str, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Manually requeue a failed/dead job, resetting its attempt counter."""
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Job not found")
    get_scoped_queue(job.queue_id, db, user)
    if job.state not in (JobState.DEAD, JobState.CANCELLED, JobState.COMPLETED):
        raise ConflictError("Only dead, cancelled or completed jobs can be manually retried")
    job.state = JobState.QUEUED
    job.attempts = 0
    job.run_at = _now()
    job.last_error = None
    job.claimed_by_worker_id = None
    job.claimed_at = None
    job.finished_at = None
    db.commit()
    db.refresh(job)
    return job


# -------- recurring schedules --------

@router.post("/queues/{queue_id}/schedules", response_model=ScheduledJobOut, status_code=201)
def create_schedule(queue_id: str, body: ScheduledJobCreate, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)
    try:
        first = croniter(body.cron_expression, _now()).get_next(datetime)
    except (ValueError, KeyError):
        raise AppError("Invalid cron expression", code="invalid_cron")

    sched = ScheduledJob(
        queue_id=queue.id, name=body.name, task_name=body.task_name, payload=body.payload,
        cron_expression=body.cron_expression, timezone_name=body.timezone_name,
        next_fire_at=first,
    )
    db.add(sched)
    db.commit()
    db.refresh(sched)
    return sched


@router.get("/queues/{queue_id}/schedules", response_model=list[ScheduledJobOut])
def list_schedules(queue_id: str, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)
    return db.execute(
        select(ScheduledJob).where(ScheduledJob.queue_id == queue.id)
    ).scalars().all()


@router.post("/schedules/{schedule_id}/toggle", response_model=ScheduledJobOut)
def toggle_schedule(schedule_id: str, db: Session = Depends(get_db),
                    user: User = Depends(get_current_user)):
    sched = db.get(ScheduledJob, schedule_id)
    if not sched:
        raise NotFoundError("Schedule not found")
    get_scoped_queue(sched.queue_id, db, user)
    sched.is_active = not sched.is_active
    db.commit()
    db.refresh(sched)
    return sched


# -------- dead letter queue --------

@router.get("/queues/{queue_id}/dead-letters", response_model=Page[DeadLetterOut])
def list_dead_letters(queue_id: str, pg: Pagination = Depends(), db: Session = Depends(get_db),
                      user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)
    total = db.execute(
        select(func.count(DeadLetterEntry.id)).where(DeadLetterEntry.queue_id == queue.id)
    ).scalar_one()
    rows = db.execute(
        select(DeadLetterEntry).where(DeadLetterEntry.queue_id == queue.id)
        .order_by(DeadLetterEntry.created_at.desc())
        .offset(pg.offset).limit(pg.page_size)
    ).scalars().all()
    pages = (total + pg.page_size - 1) // pg.page_size
    return Page[DeadLetterOut](items=rows, total=total, page=pg.page,
                               page_size=pg.page_size, pages=pages)


@router.post("/dead-letters/{entry_id}/replay", response_model=JobOut)
def replay_dead_letter(entry_id: str, db: Session = Depends(get_db),
                       user: User = Depends(get_current_user)):
    entry = db.get(DeadLetterEntry, entry_id)
    if not entry:
        raise NotFoundError("Dead letter entry not found")
    get_scoped_queue(entry.queue_id, db, user)
    return job_service.replay_dead_letter(db, entry)
