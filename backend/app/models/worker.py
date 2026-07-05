"""Worker registry and heartbeat history."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import String, DateTime, Integer, Enum, ForeignKey, Index, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..database import Base
from .enums import WorkerStatus
from .types import JSONType


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Worker(Base):
    __tablename__ = "workers"
    __table_args__ = (Index("ix_worker_status_seen", "status", "last_heartbeat_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    hostname: Mapped[str] = mapped_column(String(200), nullable=False)
    pid: Mapped[int] = mapped_column(Integer, default=0)
    # Which queues this worker services. Empty list => all queues in scope.
    queues: Mapped[list] = mapped_column(JSONType, default=list)
    concurrency: Mapped[int] = mapped_column(Integer, default=4)

    status: Mapped[WorkerStatus] = mapped_column(
        Enum(WorkerStatus, native_enum=False), default=WorkerStatus.ALIVE
    )
    active_jobs: Mapped[int] = mapped_column(Integer, default=0)

    registered_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)
    last_heartbeat_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    # Lifetime counters for the dashboard.
    total_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_failed: Mapped[int] = mapped_column(Integer, default=0)

    heartbeats: Mapped[list["WorkerHeartbeat"]] = relationship(
        back_populates="worker", cascade="all, delete-orphan"
    )


class WorkerHeartbeat(Base):
    """Append-only heartbeat samples for liveness and load monitoring."""

    __tablename__ = "worker_heartbeats"
    __table_args__ = (Index("ix_hb_worker_ts", "worker_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=_uuid)
    worker_id: Mapped[str] = mapped_column(
        ForeignKey("workers.id", ondelete="CASCADE"), nullable=False
    )
    active_jobs: Mapped[int] = mapped_column(Integer, default=0)
    cpu_percent: Mapped[float] = mapped_column(Float, default=0.0)
    memory_mb: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime(), default=_now)

    worker: Mapped[Worker] = relationship(back_populates="heartbeats")
