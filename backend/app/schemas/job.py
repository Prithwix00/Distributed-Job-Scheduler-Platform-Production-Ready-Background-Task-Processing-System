from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from ..models.enums import JobState, JobType, RetryStrategy, WorkerStatus


class RetryOverride(BaseModel):
    max_attempts: int | None = Field(None, ge=1, le=50)
    retry_strategy: RetryStrategy | None = None
    base_delay_seconds: float | None = Field(None, ge=0)
    max_delay_seconds: float | None = Field(None, ge=0)
    backoff_factor: float | None = Field(None, ge=1)
    jitter: float | None = Field(None, ge=0, le=1)


class JobCreate(BaseModel):
    task_name: str = Field(min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)
    job_type: JobType = JobType.IMMEDIATE

    # scheduling controls (mutually informative; validated below)
    run_at: datetime | None = None
    delay_seconds: float | None = Field(None, ge=0)
    cron_expression: str | None = None
    timezone_name: str = "UTC"

    priority: int | None = None
    idempotency_key: str | None = Field(None, max_length=200)
    depends_on_job_id: str | None = None
    retry: RetryOverride | None = None

    @model_validator(mode="after")
    def _validate_type(self):
        if self.job_type == JobType.DELAYED and self.delay_seconds is None and self.run_at is None:
            raise ValueError("delayed jobs require delay_seconds or run_at")
        if self.job_type == JobType.SCHEDULED and self.run_at is None:
            raise ValueError("scheduled jobs require run_at")
        if self.job_type == JobType.RECURRING and not self.cron_expression:
            raise ValueError("recurring jobs require cron_expression")
        return self


class BatchCreate(BaseModel):
    task_name: str = Field(min_length=1, max_length=120)
    items: list[dict] = Field(min_length=1, max_length=10000)
    priority: int | None = None


class ExecutionOut(BaseModel):
    id: str
    attempt_number: int
    status: str
    worker_id: str | None
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int | None
    error: str | None
    model_config = {"from_attributes": True}


class JobLogOut(BaseModel):
    id: str
    level: str
    message: str
    context: dict | None
    created_at: datetime
    model_config = {"from_attributes": True}


class JobOut(BaseModel):
    id: str
    queue_id: str
    task_name: str
    payload: dict
    job_type: JobType
    state: JobState
    priority: int
    run_at: datetime
    attempts: int
    max_attempts: int
    retry_strategy: RetryStrategy
    cron_expression: str | None
    batch_id: str | None
    depends_on_job_id: str | None
    claimed_by_worker_id: str | None
    last_error: str | None
    result: dict | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    model_config = {"from_attributes": True}


class JobDetail(JobOut):
    executions: list[ExecutionOut] = []
    logs: list[JobLogOut] = []


class ScheduledJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    task_name: str = Field(min_length=1, max_length=120)
    payload: dict = Field(default_factory=dict)
    cron_expression: str = Field(min_length=1, max_length=120)
    timezone_name: str = "UTC"


class ScheduledJobOut(BaseModel):
    id: str
    queue_id: str
    name: str
    task_name: str
    cron_expression: str
    is_active: bool
    next_fire_at: datetime
    last_fired_at: datetime | None
    model_config = {"from_attributes": True}


class DeadLetterOut(BaseModel):
    id: str
    job_id: str
    queue_id: str
    task_name: str
    total_attempts: int
    last_error: str | None
    failure_summary: str | None
    created_at: datetime
    replayed_at: datetime | None
    model_config = {"from_attributes": True}


# ---- worker facing ----

class WorkerRegister(BaseModel):
    hostname: str
    pid: int = 0
    queues: list[str] = Field(default_factory=list)
    concurrency: int = Field(4, ge=1, le=1000)


class WorkerOut(BaseModel):
    id: str
    hostname: str
    pid: int
    queues: list
    concurrency: int
    status: WorkerStatus
    active_jobs: int
    total_processed: int
    total_failed: int
    registered_at: datetime
    last_heartbeat_at: datetime
    model_config = {"from_attributes": True}


class ClaimRequest(BaseModel):
    worker_id: str
    limit: int = Field(5, ge=1, le=100)
    lease_seconds: int = Field(30, ge=5, le=3600)


class HeartbeatRequest(BaseModel):
    active_jobs: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0


class ExecutionResult(BaseModel):
    execution_id: str
    success: bool
    result: dict | None = None
    error: str | None = None
