from datetime import datetime, timezone

from app.models import Organization, Project, Queue, RetryPolicy, Job, DeadLetterEntry, Worker
from app.models.enums import JobState, JobType, RetryStrategy
from app.services import claiming, job_service


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _worker(db):
    w = Worker(hostname="test", queues=[])
    db.add(w); db.commit(); db.refresh(w)
    return w.id


def _queue(db, max_attempts=3):
    org = Organization(name="o", slug=f"o-{id(db)}")
    db.add(org); db.flush()
    proj = Project(organization_id=org.id, name="p", slug="p")
    db.add(proj); db.flush()
    policy = RetryPolicy(strategy=RetryStrategy.FIXED, max_attempts=max_attempts,
                         base_delay_seconds=0.0, jitter=0.0)
    db.add(policy); db.flush()
    q = Queue(project_id=proj.id, name="default", concurrency_limit=100,
              retry_policy_id=policy.id)
    db.add(q); db.commit(); db.refresh(q)
    return q


def test_happy_path_complete(db):
    q = _queue(db)
    wid = _worker(db)
    job = job_service.create_job(db, queue=q, task_name="echo", payload={"x": 1})
    assert job.state == JobState.QUEUED

    claimed = claiming.claim_jobs(db, worker_id=wid, queue_ids=[q.id], limit=1, lease_seconds=30)
    job = claimed[0]
    execution = job_service.start_execution(db, job, wid)
    assert job.state == JobState.RUNNING
    assert job.attempts == 1

    job_service.complete_job(db, job, execution, {"ok": True})
    db.refresh(job)
    assert job.state == JobState.COMPLETED
    assert job.result == {"ok": True}
    assert job.finished_at is not None


def test_retry_then_dead_letter(db):
    q = _queue(db, max_attempts=2)
    wid = _worker(db)
    job = job_service.create_job(db, queue=q, task_name="fail", payload={})

    # attempt 1 -> fail -> scheduled for retry
    job = claiming.claim_jobs(db, worker_id=wid, queue_ids=[q.id], limit=1, lease_seconds=30)[0]
    ex = job_service.start_execution(db, job, wid)
    job_service.fail_job(db, job, ex, "boom")
    db.refresh(job)
    assert job.state == JobState.SCHEDULED
    assert job.attempts == 1

    # promote back to queued (base_delay is 0 so it is immediately due)
    from app.services import scheduling
    scheduling.promote_due_scheduled(db)
    db.refresh(job)
    assert job.state == JobState.QUEUED

    # attempt 2 -> fail -> exhausted -> DEAD + DLQ entry
    job = claiming.claim_jobs(db, worker_id=wid, queue_ids=[q.id], limit=1, lease_seconds=30)[0]
    ex = job_service.start_execution(db, job, wid)
    job_service.fail_job(db, job, ex, "boom again")
    db.refresh(job)
    assert job.state == JobState.DEAD
    assert job.attempts == 2

    dlq = db.query(DeadLetterEntry).filter_by(job_id=job.id).one()
    assert dlq.total_attempts == 2
    assert dlq.last_error == "boom again"


def test_idempotency_key_collapses_duplicates(db):
    q = _queue(db)
    j1 = job_service.create_job(db, queue=q, task_name="echo", payload={}, idempotency_key="k1")
    j2 = job_service.create_job(db, queue=q, task_name="echo", payload={}, idempotency_key="k1")
    assert j1.id == j2.id


def test_delayed_job_starts_scheduled(db):
    q = _queue(db)
    job = job_service.create_job(db, queue=q, task_name="echo", payload={},
                                 job_type=JobType.DELAYED, delay_seconds=3600)
    assert job.state == JobState.SCHEDULED
    assert job.run_at > _now()


def test_batch_shares_batch_id(db):
    q = _queue(db)
    batch_id, jobs = job_service.create_batch(
        db, queue=q, task_name="echo", items=[{"i": 0}, {"i": 1}, {"i": 2}])
    assert len(jobs) == 3
    assert all(j.batch_id == batch_id for j in jobs)


def test_replay_dead_letter(db):
    q = _queue(db)
    entry = DeadLetterEntry(job_id="x", queue_id=q.id, task_name="echo",
                            payload={"a": 1}, total_attempts=3, last_error="e")
    # need a real job for FK-free sqlite; create one to satisfy shape
    j = job_service.create_job(db, queue=q, task_name="echo", payload={})
    entry.job_id = j.id
    db.add(entry); db.commit(); db.refresh(entry)

    new_job = job_service.replay_dead_letter(db, entry)
    assert new_job.state == JobState.QUEUED
    db.refresh(entry)
    assert entry.replayed_at is not None
