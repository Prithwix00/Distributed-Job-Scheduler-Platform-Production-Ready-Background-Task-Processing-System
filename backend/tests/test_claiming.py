import threading
from datetime import datetime, timedelta, timezone

from app.database import SessionLocal
from app.models import Organization, Project, Queue, Job
from app.models.enums import JobState
from app.services import claiming


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _make_queue(db, concurrency=1000, priority=0):
    org = Organization(name="o", slug=f"o-{id(db)}-{priority}")
    db.add(org); db.flush()
    proj = Project(organization_id=org.id, name="p", slug="p")
    db.add(proj); db.flush()
    q = Queue(project_id=proj.id, name="default", concurrency_limit=concurrency, priority=priority)
    db.add(q); db.commit(); db.refresh(q)
    return q


def _seed_jobs(db, queue, n, state=JobState.QUEUED):
    for i in range(n):
        db.add(Job(queue_id=queue.id, task_name="echo", payload={"i": i},
                   state=state, run_at=_now(), priority=0))
    db.commit()


def test_single_worker_claims_up_to_limit(db):
    q = _make_queue(db, concurrency=1000)
    _seed_jobs(db, q, 5)
    claimed = claiming.claim_jobs(db, worker_id="w1", queue_ids=[q.id], limit=10, lease_seconds=30)
    assert len(claimed) == 5
    assert all(j.state == JobState.CLAIMED for j in claimed)
    assert all(j.claimed_by_worker_id == "w1" for j in claimed)


def test_concurrency_limit_caps_claims(db):
    q = _make_queue(db, concurrency=3)
    _seed_jobs(db, q, 10)
    claimed = claiming.claim_jobs(db, worker_id="w1", queue_ids=[q.id], limit=100, lease_seconds=30)
    # Only 3 slots available because concurrency_limit == 3.
    assert len(claimed) == 3


def test_paused_queue_yields_nothing(db):
    q = _make_queue(db)
    q.is_paused = True
    db.commit()
    _seed_jobs(db, q, 5)
    claimed = claiming.claim_jobs(db, worker_id="w1", queue_ids=[q.id], limit=10, lease_seconds=30)
    assert claimed == []


def test_future_jobs_not_claimed(db):
    q = _make_queue(db)
    db.add(Job(queue_id=q.id, task_name="echo", state=JobState.QUEUED,
               run_at=_now() + timedelta(hours=1)))
    db.commit()
    claimed = claiming.claim_jobs(db, worker_id="w1", queue_ids=[q.id], limit=10, lease_seconds=30)
    assert claimed == []


def test_no_double_claim_under_concurrency(db):
    """The core correctness property: many workers, no job claimed twice."""
    q = _make_queue(db, concurrency=10000)
    _seed_jobs(db, q, 200)

    all_claimed: list[str] = []
    lock = threading.Lock()

    def worker(wid):
        s = SessionLocal()
        try:
            while True:
                got = claiming.claim_jobs(s, worker_id=wid, queue_ids=[q.id],
                                          limit=5, lease_seconds=30)
                if not got:
                    break
                with lock:
                    all_claimed.extend(j.id for j in got)
        finally:
            s.close()

    threads = [threading.Thread(target=worker, args=(f"w{i}",)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Every job claimed exactly once, and all 200 were claimed.
    assert len(all_claimed) == 200
    assert len(set(all_claimed)) == 200


def test_lease_reaping_requeues_dead_worker_jobs(db):
    q = _make_queue(db)
    job = Job(queue_id=q.id, task_name="echo", state=JobState.RUNNING,
              claimed_by_worker_id="dead", claimed_at=_now(),
              lease_expires_at=_now() - timedelta(seconds=1))
    db.add(job); db.commit()

    requeued = claiming.reap_expired_leases(db)
    assert requeued == 1
    db.refresh(job)
    assert job.state == JobState.QUEUED
    assert job.claimed_by_worker_id is None


def test_priority_ordering(db):
    q = _make_queue(db, concurrency=1000)
    db.add(Job(queue_id=q.id, task_name="echo", state=JobState.QUEUED, priority=1, run_at=_now()))
    db.add(Job(queue_id=q.id, task_name="echo", state=JobState.QUEUED, priority=9, run_at=_now()))
    db.commit()
    claimed = claiming.claim_jobs(db, worker_id="w1", queue_ids=[q.id], limit=1, lease_seconds=30)
    assert len(claimed) == 1
    assert claimed[0].priority == 9  # higher priority first
