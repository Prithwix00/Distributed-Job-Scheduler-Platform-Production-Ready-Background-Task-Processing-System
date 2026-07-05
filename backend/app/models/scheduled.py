"""Recurring job definitions. The scheduler materialises Job rows from these."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, ForeignKey, Boolean, Index
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base
from .types import JSONType


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class ScheduledJob(Base):
    """A cron definition. Distinct from a Job so the schedule survives across
    the individual materialised runs and can be paused independently."""

    __tablename__ = "scheduled_jobs"
    __table_args__ = (Index("ix_sched_next_fire", "is_active", "next_fire_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    queue_id: Mapped[str] = mapped_column(ForeignKey("queues.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    task_name: Mapped[str] = mapped_column(String(120), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)

    cron_expression: Mapped[str] = mapped_column(String(120), nullable=False)
    timezone_name: Mapped[str] = mapped_column(String(64), default="UTC")

    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    next_fire_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
