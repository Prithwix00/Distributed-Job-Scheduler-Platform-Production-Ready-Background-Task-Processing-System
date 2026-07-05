from datetime import datetime, timedelta, timezone

from app.models import Organization, Project, Queue, Job, ScheduledJob, Worker
from app.models.enums import JobState, JobType
from app.services import scheduling, job_service


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _worker(db):
    w = Worker(hostname="test", queues=[])
    db.add(w); db.commit(); db.refresh(w)
    return w.id


def _queue(db):
    org = Organization(name="o", slug=f"o-{id(db)}")
    db.add(org); db.flush()
    proj = Project(organization_id=org.id, name="p", slug="p")
    db.add(proj); db.flush()
    q = Queue(project_id=proj.id, name="default", concurrency_limit=100)
    db.add(q); db.commit(); db.refresh(q)
    return q


def test_promote_due_scheduled(db):
    q = _queue(db)
    db.add(Job(queue_id=q.id, task_name="echo", state=JobState.SCHEDULED,
               run_at=_now() - timedelta(seconds=1)))
    db.add(Job(queue_id=q.id, task_name="echo", state=JobState.SCHEDULED,
               run_at=_now() + timedelta(hours=1)))
    db.commit()

    promoted = scheduling.promote_due_scheduled(db)
    assert promoted == 1


def test_cron_fires_and_advances(db):
    q = _queue(db)
    sched = ScheduledJob(
        queue_id=q.id, name="nightly", task_name="echo", payload={},
        cron_expression="* * * * *",  # every minute
        next_fire_at=_now() - timedelta(seconds=1),
    )
    db.add(sched); db.commit()

    fired = scheduling.fire_due_cron(db)
    assert fired == 1
    db.refresh(sched)
    assert sched.next_fire_at > _now()
    assert sched.last_fired_at is not None

    materialised = db.query(Job).filter_by(queue_id=q.id).all()
    assert len(materialised) == 1
    assert materialised[0].job_type == JobType.RECURRING


def test_dependency_releases_on_parent_complete(db):
    q = _queue(db)
    parent = job_service.create_job(db, queue=q, task_name="echo", payload={})
    child = job_service.create_job(db, queue=q, task_name="echo", payload={},
                                   depends_on_job_id=parent.id)
    assert child.state == JobState.SCHEDULED  # blocked on parent

    # promotion should NOT release it while the dependency stands
    scheduling.promote_due_scheduled(db)
    db.refresh(child)
    assert child.state == JobState.SCHEDULED

    # complete the parent
    from app.services import claiming
    wid = _worker(db)
    p = claiming.claim_jobs(db, worker_id=wid, queue_ids=[q.id], limit=10, lease_seconds=30)
    p = next(j for j in p if j.id == parent.id)
    ex = job_service.start_execution(db, p, wid)
    job_service.complete_job(db, p, ex, None)

    db.refresh(child)
    assert child.state == JobState.QUEUED  # released
