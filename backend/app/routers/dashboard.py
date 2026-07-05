from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..models import Job, Queue, Project, Worker, JobExecution, DeadLetterEntry, User
from ..models.enums import JobState, WorkerStatus

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _org_queue_ids(db: Session, org_id: str) -> list[str]:
    return list(
        db.execute(
            select(Queue.id).join(Project, Queue.project_id == Project.id)
            .where(Project.organization_id == org_id)
        ).scalars().all()
    )


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    queue_ids = _org_queue_ids(db, user.organization_id)
    if not queue_ids:
        state_counts: dict = {}
    else:
        state_counts = dict(
            db.execute(
                select(Job.state, func.count(Job.id))
                .where(Job.queue_id.in_(queue_ids))
                .group_by(Job.state)
            ).all()
        )

    def c(s: JobState) -> int:
        return int(state_counts.get(s, 0))

    now = _now()
    cutoff = now - timedelta(seconds=settings.heartbeat_timeout_seconds)
    workers = db.execute(select(Worker)).scalars().all()
    alive = sum(1 for w in workers if w.last_heartbeat_at >= cutoff and w.status != WorkerStatus.DEAD)

    dlq_total = 0
    if queue_ids:
        dlq_total = db.execute(
            select(func.count(DeadLetterEntry.id))
            .where(DeadLetterEntry.queue_id.in_(queue_ids))
        ).scalar_one()

    total_jobs = sum(state_counts.values())
    completed = c(JobState.COMPLETED)
    dead = c(JobState.DEAD)
    finished = completed + dead
    success_rate = (completed / finished) if finished else 1.0

    return {
        "jobs": {
            "queued": c(JobState.QUEUED),
            "scheduled": c(JobState.SCHEDULED),
            "running": c(JobState.RUNNING) + c(JobState.CLAIMED),
            "completed": completed,
            "dead": dead,
            "cancelled": c(JobState.CANCELLED),
            "total": total_jobs,
        },
        "workers": {"alive": alive, "total": len(workers)},
        "dead_letter_total": dlq_total,
        "success_rate": round(success_rate, 4),
        "health": "healthy" if alive > 0 else "no_workers",
    }


@router.get("/throughput")
def throughput(
    minutes: int = Query(60, ge=5, le=1440),
    bucket_seconds: int = Query(60, ge=10, le=3600),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Completed vs failed executions bucketed over time for charts."""
    queue_ids = _org_queue_ids(db, user.organization_id)
    since = _now() - timedelta(minutes=minutes)
    if not queue_ids:
        return {"buckets": [], "bucket_seconds": bucket_seconds}

    rows = db.execute(
        select(JobExecution.finished_at, JobExecution.status)
        .join(Job, JobExecution.job_id == Job.id)
        .where(
            Job.queue_id.in_(queue_ids),
            JobExecution.finished_at.is_not(None),
            JobExecution.finished_at >= since,
        )
    ).all()

    buckets: dict[int, dict] = {}
    for finished_at, status in rows:
        ts = finished_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        key = int(ts.timestamp() // bucket_seconds) * bucket_seconds
        b = buckets.setdefault(key, {"t": key, "succeeded": 0, "failed": 0})
        if status == "succeeded":
            b["succeeded"] += 1
        else:
            b["failed"] += 1

    ordered = [buckets[k] for k in sorted(buckets)]
    return {"buckets": ordered, "bucket_seconds": bucket_seconds}
