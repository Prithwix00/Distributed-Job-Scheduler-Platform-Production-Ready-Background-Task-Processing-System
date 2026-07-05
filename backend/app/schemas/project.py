from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from ..models.enums import RetryStrategy


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9-]+$")
    description: str = ""


class ProjectOut(BaseModel):
    id: str
    name: str
    slug: str
    description: str
    created_at: datetime
    model_config = {"from_attributes": True}


class RetryPolicyIn(BaseModel):
    strategy: RetryStrategy = RetryStrategy.EXPONENTIAL
    max_attempts: int = Field(3, ge=1, le=50)
    base_delay_seconds: float = Field(5.0, ge=0)
    max_delay_seconds: float = Field(3600.0, ge=0)
    backoff_factor: float = Field(2.0, ge=1)
    jitter: float = Field(0.1, ge=0, le=1)


class RetryPolicyOut(RetryPolicyIn):
    id: str
    model_config = {"from_attributes": True}


class QueueCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str = ""
    priority: int = 0
    concurrency_limit: int = Field(10, ge=1, le=10000)
    rate_limit_per_sec: float = Field(0.0, ge=0)
    retry_policy: RetryPolicyIn | None = None


class QueueUpdate(BaseModel):
    description: str | None = None
    priority: int | None = None
    concurrency_limit: int | None = Field(None, ge=1, le=10000)
    rate_limit_per_sec: float | None = Field(None, ge=0)
    is_paused: bool | None = None
    retry_policy: RetryPolicyIn | None = None


class QueueOut(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    priority: int
    concurrency_limit: int
    rate_limit_per_sec: float
    is_paused: bool
    created_at: datetime
    retry_policy: RetryPolicyOut | None = None
    model_config = {"from_attributes": True}


class QueueStats(BaseModel):
    queue_id: str
    queued: int
    scheduled: int
    running: int
    completed: int
    dead: int
    failed_recent: int
    is_paused: bool
    concurrency_limit: int
