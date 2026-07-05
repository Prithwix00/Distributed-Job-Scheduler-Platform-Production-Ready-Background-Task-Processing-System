"""FastAPI dependencies: current user resolution, pagination, tenancy scoping."""
from __future__ import annotations

from fastapi import Depends, Header, Query
from sqlalchemy.orm import Session

from .config import settings
from .core import AuthError, NotFoundError, ForbiddenError
from .database import get_db
from .models import User, Project, Queue
from .models.enums import UserRole
from .security import decode_token


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    claims = decode_token(token)
    if not claims:
        raise AuthError("Invalid or expired token")
    user = db.get(User, claims.get("sub"))
    if not user or not user.is_active:
        raise AuthError("User not found or inactive")
    return user


def require_role(*roles: UserRole):
    def checker(user: User = Depends(get_current_user)) -> User:
        if roles and user.role not in roles:
            raise ForbiddenError("Insufficient role for this action")
        return user
    return checker


class Pagination:
    def __init__(
        self,
        page: int = Query(1, ge=1),
        page_size: int = Query(settings.default_page_size, ge=1, le=settings.max_page_size),
    ):
        self.page = page
        self.page_size = page_size

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size


def get_scoped_project(project_id: str, db: Session, user: User) -> Project:
    project = db.get(Project, project_id)
    if not project or project.organization_id != user.organization_id:
        raise NotFoundError("Project not found")
    return project


def get_scoped_queue(queue_id: str, db: Session, user: User) -> Queue:
    queue = db.get(Queue, queue_id)
    if not queue:
        raise NotFoundError("Queue not found")
    project = db.get(Project, queue.project_id)
    if not project or project.organization_id != user.organization_id:
        raise NotFoundError("Queue not found")
    return queue
