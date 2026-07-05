from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select, func
from sqlalchemy.orm import Session

from ..core import ConflictError, NotFoundError, ForbiddenError
from ..database import get_db
from ..deps import get_current_user, get_scoped_project, get_scoped_queue
from ..models import Project, Queue, RetryPolicy, User, Job
from ..models.enums import JobState, UserRole
from ..schemas.project import (
    ProjectCreate, ProjectOut, QueueCreate, QueueUpdate, QueueOut, QueueStats,
)

router = APIRouter(tags=["projects"])


# -------- projects --------

@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, db: Session = Depends(get_db),
                   user: User = Depends(get_current_user)):
    dupe = db.execute(
        select(Project).where(
            Project.organization_id == user.organization_id, Project.slug == body.slug
        )
    ).scalar_one_or_none()
    if dupe:
        raise ConflictError("Project slug already exists")
    project = Project(
        organization_id=user.organization_id,
        name=body.name, slug=body.slug, description=body.description,
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return db.execute(
        select(Project).where(Project.organization_id == user.organization_id)
        .order_by(Project.created_at.desc())
    ).scalars().all()


@router.get("/projects/{project_id}", response_model=ProjectOut)
def get_project(project_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    return get_scoped_project(project_id, db, user)


# -------- queues --------

def _build_retry_policy(db: Session, body) -> RetryPolicy | None:
    if body is None:
        return None
    policy = RetryPolicy(
        strategy=body.strategy, max_attempts=body.max_attempts,
        base_delay_seconds=body.base_delay_seconds, max_delay_seconds=body.max_delay_seconds,
        backoff_factor=body.backoff_factor, jitter=body.jitter,
    )
    db.add(policy)
    db.flush()
    return policy


@router.post("/projects/{project_id}/queues", response_model=QueueOut, status_code=201)
def create_queue(project_id: str, body: QueueCreate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    project = get_scoped_project(project_id, db, user)
    dupe = db.execute(
        select(Queue).where(Queue.project_id == project.id, Queue.name == body.name)
    ).scalar_one_or_none()
    if dupe:
        raise ConflictError("Queue name already exists in this project")

    policy = _build_retry_policy(db, body.retry_policy)
    queue = Queue(
        project_id=project.id, name=body.name, description=body.description,
        priority=body.priority, concurrency_limit=body.concurrency_limit,
        rate_limit_per_sec=body.rate_limit_per_sec,
        retry_policy_id=policy.id if policy else None,
    )
    db.add(queue)
    db.commit()
    db.refresh(queue)
    return queue


@router.get("/projects/{project_id}/queues", response_model=list[QueueOut])
def list_queues(project_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    project = get_scoped_project(project_id, db, user)
    return db.execute(
        select(Queue).where(Queue.project_id == project.id).order_by(Queue.priority.desc())
    ).scalars().all()


@router.get("/queues/{queue_id}", response_model=QueueOut)
def get_queue(queue_id: str, db: Session = Depends(get_db),
              user: User = Depends(get_current_user)):
    return get_scoped_queue(queue_id, db, user)


@router.patch("/queues/{queue_id}", response_model=QueueOut)
def update_queue(queue_id: str, body: QueueUpdate, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)
    if user.role == UserRole.VIEWER:
        raise ForbiddenError("Viewers cannot modify queues")

    data = body.model_dump(exclude_unset=True)
    if "retry_policy" in data:
        policy = _build_retry_policy(db, body.retry_policy)
        queue.retry_policy_id = policy.id if policy else None
        data.pop("retry_policy")
    for field, value in data.items():
        setattr(queue, field, value)
    db.commit()
    db.refresh(queue)
    return queue


@router.post("/queues/{queue_id}/pause", response_model=QueueOut)
def pause_queue(queue_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)
    queue.is_paused = True
    db.commit()
    db.refresh(queue)
    return queue


@router.post("/queues/{queue_id}/resume", response_model=QueueOut)
def resume_queue(queue_id: str, db: Session = Depends(get_db),
                 user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)
    queue.is_paused = False
    db.commit()
    db.refresh(queue)
    return queue


@router.get("/queues/{queue_id}/stats", response_model=QueueStats)
def queue_stats(queue_id: str, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    queue = get_scoped_queue(queue_id, db, user)

    counts = dict(
        db.execute(
            select(Job.state, func.count(Job.id))
            .where(Job.queue_id == queue.id)
            .group_by(Job.state)
        ).all()
    )

    def c(state: JobState) -> int:
        return int(counts.get(state, 0))

    return QueueStats(
        queue_id=queue.id,
        queued=c(JobState.QUEUED),
        scheduled=c(JobState.SCHEDULED),
        running=c(JobState.RUNNING) + c(JobState.CLAIMED),
        completed=c(JobState.COMPLETED),
        dead=c(JobState.DEAD),
        failed_recent=c(JobState.FAILED),
        is_paused=queue.is_paused,
        concurrency_limit=queue.concurrency_limit,
    )
