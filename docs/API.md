# API Reference

Base path: `/api/v1`. All times are UTC ISO-8601. Interactive OpenAPI docs are
served at `/docs` when the API is running.

## Authentication

Register or log in to receive a JWT. Send it as `Authorization: Bearer <token>`
on every authenticated request. Tokens are scoped to a single organization, so
a user only ever sees their own org's projects, queues and jobs.

Errors use a consistent JSON body:

```json
{ "error": "NotFoundError", "detail": "Queue not found", "code": "not_found" }
```

Validation errors return `422` with a `detail` array describing each field.

### `POST /auth/register`

Creates an organization and its first owner user.

```json
{ "organization_name": "Acme", "email": "you@acme.com", "password": "password123", "full_name": "You" }
```

Returns `201` with `{ "access_token": "...", "token_type": "bearer" }`.

### `POST /auth/login`

Body `{ "email", "password" }`. Returns a token.

### `GET /auth/me`

Returns the current user profile.

---

## Projects

### `POST /projects`

`{ "name": "Payments", "slug": "payments", "description": "" }`. Slug is unique
per organization and must match `^[a-z0-9-]+$`.

### `GET /projects`

Lists projects in the caller's organization.

### `GET /projects/{project_id}`

Returns one project.

---

## Queues

### `POST /projects/{project_id}/queues`

```json
{
  "name": "emails",
  "priority": 5,
  "concurrency_limit": 8,
  "rate_limit_per_sec": 0,
  "retry_policy": {
    "strategy": "exponential",
    "max_attempts": 4,
    "base_delay_seconds": 2,
    "max_delay_seconds": 3600,
    "backoff_factor": 2,
    "jitter": 0.2
  }
}
```

`strategy` is one of `fixed`, `linear`, `exponential`. `retry_policy` is
optional; omitting it uses sensible defaults.

### `GET /projects/{project_id}/queues`

Lists queues ordered by priority.

### `GET /queues/{queue_id}` and `PATCH /queues/{queue_id}`

Read or update a queue. The `PATCH` body accepts any subset of `description`,
`priority`, `concurrency_limit`, `rate_limit_per_sec`, `is_paused`,
`retry_policy`.

### `POST /queues/{queue_id}/pause` and `POST /queues/{queue_id}/resume`

Pause stops workers from claiming new jobs on the queue. In-flight jobs finish.

### `GET /queues/{queue_id}/stats`

Returns per-state counts for the queue plus pause state and concurrency limit.

---

## Jobs

### `POST /queues/{queue_id}/jobs`

Creates one job. The shape varies by `job_type`.

Immediate:

```json
{ "task_name": "send_email", "payload": { "to": "a@b.com" } }
```

Delayed (runs after N seconds):

```json
{ "task_name": "send_email", "payload": {}, "job_type": "delayed", "delay_seconds": 300 }
```

Scheduled (runs at a specific time):

```json
{ "task_name": "report", "payload": {}, "job_type": "scheduled", "run_at": "2026-01-01T09:00:00Z" }
```

Recurring (cron):

```json
{ "task_name": "cleanup", "payload": {}, "job_type": "recurring", "cron_expression": "0 * * * *" }
```

Optional fields on any job: `priority`, `idempotency_key` (dedupes per queue),
`depends_on_job_id` (waits for a parent to complete) and a `retry` object that
overrides the queue policy for this job.

Returns `201` with the created job.

### `POST /queues/{queue_id}/batches`

Creates many sibling jobs sharing one `batch_id`.

```json
{ "task_name": "send_email", "items": [ { "to": "a@b.com" }, { "to": "c@d.com" } ], "priority": 0 }
```

### `GET /queues/{queue_id}/jobs`

Paginated, filterable job list. Query parameters: `state`, `job_type`,
`task_name`, `page`, `page_size`. Returns a page envelope:

```json
{ "items": [ ... ], "total": 128, "page": 1, "page_size": 25, "pages": 6 }
```

### `GET /jobs/{job_id}`

Full job detail including its ordered execution history and logs.

### `POST /jobs/{job_id}/cancel`

Cancels a non-terminal job.

### `POST /jobs/{job_id}/retry`

Requeues a dead, cancelled or completed job with the attempt counter reset.

---

## Recurring schedules

### `POST /queues/{queue_id}/schedules`

```json
{ "name": "hourly-report", "task_name": "report", "payload": {}, "cron_expression": "0 * * * *" }
```

### `GET /queues/{queue_id}/schedules`

Lists cron definitions for the queue.

### `POST /schedules/{schedule_id}/toggle`

Activates or deactivates a schedule.

---

## Dead Letter Queue

### `GET /queues/{queue_id}/dead-letters`

Paginated list of jobs that exhausted their retries.

### `POST /dead-letters/{entry_id}/replay`

Re-enqueues a dead-lettered job as a fresh job.

---

## Workers (internal contract)

These endpoints are called by the worker process. They are documented so the
worker can be reimplemented in any language.

### `POST /workers/register`

`{ "hostname", "pid", "queues": [ ... ], "concurrency" }`. Returns the worker
record including its `id`. An empty `queues` list means the worker services all
queues.

### `POST /workers/{worker_id}/heartbeat`

`{ "active_jobs", "cpu_percent", "memory_mb" }`. Records liveness and renews the
lease on every job the worker still owns.

### `POST /workers/{worker_id}/claim`

`{ "worker_id", "limit", "lease_seconds" }`. Atomically claims up to `limit`
eligible jobs and returns them. Respects queue pause state and concurrency
limits.

### `POST /workers/{worker_id}/jobs/{job_id}/start`

Transitions a claimed job to `RUNNING` and opens an execution row. Returns
`{ "execution_id", "attempt_number" }`.

### `POST /workers/{worker_id}/jobs/{job_id}/result`

`{ "execution_id", "success", "result", "error" }`. Completes the job on
success, or schedules a retry / dead-letters it on failure.

### `GET /workers`

Lists all workers with liveness and lifetime counters (for the dashboard).

---

## Dashboard

### `GET /dashboard/overview`

Aggregate job counts by state, worker liveness, dead letter total, success rate
and a health flag.

### `GET /dashboard/throughput`

Query `minutes` and `bucket_seconds`. Returns succeeded and failed execution
counts bucketed over time for the throughput chart.
