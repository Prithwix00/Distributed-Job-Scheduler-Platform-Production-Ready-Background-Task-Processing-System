"""Queues and their retry policies."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, ForeignKey, DateTime, Integer, Boolean, UniqueConstraint, Enum, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import RetryStrategy


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class RetryPolicy(Base):
    """Reusable retry configuration. Owned by a queue but overridable per job."""

    __tablename__ = "retry_policies"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    strategy: Mapped[RetryStrategy] = mapped_column(
        Enum(RetryStrategy, native_enum=False), default=RetryStrategy.EXPONENTIAL
    )
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    base_delay_seconds: Mapped[float] = mapped_column(Float, default=5.0)
    max_delay_seconds: Mapped[float] = mapped_column(Float, default=3600.0)
    # multiplier for exponential; ignored by fixed. e.g. 2.0 -> 5, 10, 20, 40 ...
    backoff_factor: Mapped[float] = mapped_column(Float, default=2.0)
    # jitter fraction (0..1) applied to computed delay to avoid thundering herds
    jitter: Mapped[float] = mapped_column(Float, default=0.1)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)


class Queue(Base):
    __tablename__ = "queues"
    __table_args__ = (
        UniqueConstraint("project_id", "name", name="uq_queue_project_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    project_id: Mapped[str] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(String(500), default="")

    # Higher number runs first. Used as the primary claim ordering key.
    priority: Mapped[int] = mapped_column(Integer, default=0)
    # Max number of jobs allowed RUNNING at once across all workers for this queue.
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=10)
    # Optional token-bucket rate limit. 0 disables it.
    rate_limit_per_sec: Mapped[float] = mapped_column(Float, default=0.0)

    is_paused: Mapped[bool] = mapped_column(Boolean, default=False)

    retry_policy_id: Mapped[str] = mapped_column(
        ForeignKey("retry_policies.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    project: Mapped["Project"] = relationship(back_populates="queues")  # noqa: F821
    retry_policy: Mapped[RetryPolicy | None] = relationship()
    jobs: Mapped[list["Job"]] = relationship(  # noqa: F821
        back_populates="queue", cascade="all, delete-orphan"
    )
