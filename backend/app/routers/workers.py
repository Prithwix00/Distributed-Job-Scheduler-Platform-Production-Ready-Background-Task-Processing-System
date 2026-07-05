from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from datetime import timedelta

from sqlalchemy import update

from ..config import settings
from ..core import NotFoundError, ConflictError
from ..database import get_db
from ..deps import get_current_user
from ..models import Worker, WorkerHeartbeat, Job, JobExecution, User
from ..models.enums import WorkerStatus, JobState, ACTIVE_STATES
from ..schemas.job import (
    WorkerRegister, WorkerOut, ClaimRequest, HeartbeatRequest, ExecutionResult, JobOut,
)
from ..services import claiming, job_service

router = APIRouter(prefix="/workers", tags=["workers"])


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


@router.post("/register", response_model=WorkerOut, status_code=201)
def register_worker(body: WorkerRegister, db: Session = Depends(get_db)):
    worker = Worker(
        hostname=body.hostname, pid=body.pid, queues=body.queues,
        concurrency=body.concurrency, status=WorkerStatus.ALIVE,
        last_heartbeat_at=_now(),
    )
    db.add(worker)
    db.commit()
    db.refresh(worker)
    return worker


@router.post("/{worker_id}/heartbeat", response_model=WorkerOut)
def heartbeat(worker_id: str, body: HeartbeatRequest, db: Session = Depends(get_db)):
    worker = db.get(Worker, worker_id)
    if not worker:
        raise NotFoundError("Worker not registered")
    now = _now()
    worker.last_heartbeat_at = now
    worker.active_jobs = body.active_jobs
    if worker.status == WorkerStatus.DEAD:
        worker.status = WorkerStatus.ALIVE  # resurrected

    # Renew the lease on every job this worker still owns, so a live worker
    # never has its in-flight jobs reaped, while a dead worker's leases expire.
    lease_until = now + timedelta(seconds=settings.heartbeat_timeout_seconds)
    db.execute(
        update(Job)
        .where(
            Job.claimed_by_worker_id == worker.id,
            Job.state.in_(list(ACTIVE_STATES)),
        )
        .values(lease_expires_at=lease_until)
    )

    db.add(WorkerHeartbeat(
        worker_id=worker.id, active_jobs=body.active_jobs,
        cpu_percent=body.cpu_percent, memory_mb=body.memory_mb,
    ))
    db.commit()
    db.refresh(worker)
    return worker


@router.post("/{worker_id}/claim", response_model=list[JobOut])
def claim(worker_id: str, body: ClaimRequest, db: Session = Depends(get_db)):
    worker = db.get(Worker, worker_id)
    if not worker:
        raise NotFoundError("Worker not registered")
    queue_ids = worker.queues or None
    jobs = claiming.claim_jobs(
        db, worker_id=worker.id, queue_ids=queue_ids,
        limit=body.limit, lease_seconds=body.lease_seconds,
    )
    return jobs


@router.post("/{worker_id}/jobs/{job_id}/start", response_model=dict)
def start_job(worker_id: str, job_id: str, db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Job not found")
    if job.claimed_by_worker_id != worker_id or job.state != JobState.CLAIMED:
        raise ConflictError("Job is not claimed by this worker")
    execution = job_service.start_execution(db, job, worker_id)
    return {"execution_id": execution.id, "attempt_number": execution.attempt_number}


@router.post("/{worker_id}/jobs/{job_id}/result", response_model=JobOut)
def report_result(worker_id: str, job_id: str, body: ExecutionResult,
                  db: Session = Depends(get_db)):
    job = db.get(Job, job_id)
    if not job:
        raise NotFoundError("Job not found")
    execution = db.get(JobExecution, body.execution_id)
    if not execution or execution.job_id != job.id:
        raise NotFoundError("Execution not found")

    worker = db.get(Worker, worker_id)
    if body.success:
        job_service.complete_job(db, job, execution, body.result)
        if worker:
            worker.total_processed += 1
    else:
        job_service.fail_job(db, job, execution, body.error or "unknown error")
        if worker:
            worker.total_failed += 1
    if worker:
        db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[WorkerOut])
def list_workers(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.execute(
        select(Worker).order_by(Worker.last_heartbeat_at.desc())
    ).scalars().all()
