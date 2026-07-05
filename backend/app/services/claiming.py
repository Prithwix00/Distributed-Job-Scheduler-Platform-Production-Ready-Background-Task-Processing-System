"""Atomic job claiming.

This is the core correctness property of the whole system: a queued job must be
executed by exactly one worker. We achieve that with row-level locking.

On PostgreSQL we use `SELECT ... FOR UPDATE SKIP LOCKED`, the standard pattern
for a database-backed queue: each worker locks a disjoint set of rows and skips
rows another worker already holds, so N workers scale without contention and
without ever handing the same row to two workers.

Because SQLite has no SKIP LOCKED, the claim is also expressed as a guarded
`UPDATE ... WHERE state = 'queued'`. Only the transaction whose update actually
changes the row (rowcount == 1) has claimed it; the loser sees rowcount == 0.
That makes the claim correct on both engines.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, func, update
from sqlalchemy.orm import Session

from ..config import settings
from ..models import Job, Queue
from ..models.enums import JobState, ACTIVE_STATES


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _active_count(db: Session, queue_id: str) -> int:
    """Jobs currently occupying a concurrency slot (claimed or running)."""
    return db.execute(
        select(func.count(Job.id)).where(
            Job.queue_id == queue_id,
            Job.state.in_(list(ACTIVE_STATES)),
        )
    ).scalar_one()


def claim_jobs(
    db: Session,
    *,
    worker_id: str,
    queue_ids: list[str] | None,
    limit: int,
    lease_seconds: int,
    now: datetime | None = None,
) -> list[Job]:
    """Atomically claim up to `limit` eligible jobs for a worker.

    Eligibility: state == QUEUED, run_at <= now, queue not paused and the
    queue's active count is below its concurrency_limit. Higher queue priority
    and higher job priority are served first.

    Returns the list of Job rows now owned by this worker.
    """
    now = now or _now()
    lease_until = now + timedelta(seconds=lease_seconds)
    is_pg = not settings.is_sqlite

    # Resolve candidate queues, honouring pause state and priority ordering.
    q = select(Queue).where(Queue.is_paused.is_(False))
    if queue_ids:
        q = q.where(Queue.id.in_(queue_ids))
    q = q.order_by(Queue.priority.desc())
    queues = db.execute(q).scalars().all()

    claimed: list[Job] = []

    for queue in queues:
        if len(claimed) >= limit:
            break

        capacity = queue.concurrency_limit - _active_count(db, queue.id)
        if capacity <= 0:
            continue

        take = min(limit - len(claimed), capacity)

        candidate_stmt = (
            select(Job)
            .where(
                Job.queue_id == queue.id,
                Job.state == JobState.QUEUED,
                Job.run_at <= now,
            )
            .order_by(Job.priority.desc(), Job.run_at.asc())
            .limit(take)
        )
        if is_pg:
            # Lock and skip rows already held by other workers.
            candidate_stmt = candidate_stmt.with_for_update(skip_locked=True)

        candidates = db.execute(candidate_stmt).scalars().all()

        for job in candidates:
            # Guarded update: the WHERE state == QUEUED clause is the arbiter.
            # On Postgres it always wins (row is locked); on SQLite it is what
            # prevents a double claim.
            result = db.execute(
                update(Job)
                .where(Job.id == job.id, Job.state == JobState.QUEUED)
                .values(
                    state=JobState.CLAIMED,
                    claimed_by_worker_id=worker_id,
                    claimed_at=now,
                    lease_expires_at=lease_until,
                    updated_at=now,
                )
            )
            if result.rowcount == 1:
                db.refresh(job)
                claimed.append(job)
                if len(claimed) >= limit:
                    break

    db.commit()
    return claimed


def reap_expired_leases(db: Session, now: datetime | None = None) -> int:
    """Requeue jobs whose owning worker died (lease expired while CLAIMED/RUNNING).

    This is the recovery half of the reliability story: a worker that crashes
    mid-job stops renewing its lease and this returns the job to QUEUED so
    another worker can pick it up. Idempotent handlers make that safe.
    """
    now = now or _now()
    result = db.execute(
        update(Job)
        .where(
            Job.state.in_([JobState.CLAIMED, JobState.RUNNING]),
            Job.lease_expires_at.is_not(None),
            Job.lease_expires_at < now,
        )
        .values(
            state=JobState.QUEUED,
            claimed_by_worker_id=None,
            claimed_at=None,
            lease_expires_at=None,
            updated_at=now,
        )
    )
    db.commit()
    return result.rowcount
