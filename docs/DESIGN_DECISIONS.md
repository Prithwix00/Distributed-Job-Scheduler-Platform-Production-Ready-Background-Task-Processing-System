# Design Decisions

This document records the major trade-offs and the reasoning behind each. The
guiding principle throughout was correctness and clarity over feature count.

## 1. PostgreSQL as the queue, not a dedicated broker

**Decision.** Use Postgres as both the system of record and the job queue,
rather than pairing a database with Redis, RabbitMQ or Kafka.

**Why.** A database-backed queue gives transactional consistency between the job
and its metadata for free: enqueue, state change, execution record and Dead
Letter handoff all commit atomically in the same store. There is no dual-write
problem where the broker and the database can disagree after a partial failure.
For the throughput this system targets, `FOR UPDATE SKIP LOCKED` is a proven
pattern (it is how tools such as Que, Solid Queue and River work).

**Trade-off.** A dedicated broker scales to higher raw message rates and offers
push delivery. If claim throughput ever became the bottleneck, the next step is
queue sharding (below) or moving the hottest queues onto a streaming broker
while keeping the database as the record of truth. The schema and service
boundaries are structured so that swap would touch only the claiming service.

## 2. `FOR UPDATE SKIP LOCKED` for atomic claiming

**Decision.** Claim jobs by selecting candidate rows with
`SELECT ... FOR UPDATE SKIP LOCKED`, then flipping their state inside the same
transaction.

**Why.** This is the crux of correctness. `SKIP LOCKED` means each concurrent
worker locks a disjoint set of rows and skips anything another worker already
holds, so N workers claim in parallel with no coordination and no job is ever
handed to two workers. It avoids both the lost-update race of a naive
read-then-write and the throughput collapse of a coarse lock.

**Portability.** SQLite has no `SKIP LOCKED`. The claim is therefore also
expressed as a guarded `UPDATE ... WHERE state = 'queued'`; only the writer
whose update changes the row (rowcount one) has claimed it. On Postgres the lock
guarantees the win and the guard is belt-and-braces; on SQLite the guard is the
sole arbiter and SQLite's serialised writes make it correct. The same code path
is exercised by an eight-worker threaded test that asserts no double claim.

## 3. Workers reach the database through the API

**Decision.** Workers call HTTP endpoints (`claim`, `start`, `result`,
`heartbeat`) instead of opening their own database connections.

**Why.** One authorization and validation boundary, one place where invariants
are enforced. Workers can run anywhere with network reach to the API, in any
language, without database credentials. The worker process stays thin and easy
to reason about.

**Trade-off.** An extra network hop per operation versus a direct connection.
For background job execution the handler runtime dominates, so the hop is
negligible. If it ever mattered, the claim endpoint could be collapsed into a
worker library that talks to the database directly using the exact same service
function.

## 4. At-least-once execution with idempotent handlers

**Decision.** Target at-least-once execution recovered by leases and require
handlers to be idempotent, rather than chasing exactly-once.

**Why.** Exactly-once delivery is not achievable in a distributed system with
crashes. A worker can finish a job and die before recording the result and no
protocol removes that window. So the honest model is at-least-once: each claimed
job carries a lease that the worker renews on every heartbeat, a crashed worker
stops renewing and the scheduler requeues the job when the lease expires.
Correctness then depends on handlers being safe to re-run, which the demo
handlers are (pure functions or keyed on a message id).

**Trade-off.** Handler authors carry the idempotency burden. The
`idempotency_key` on submission and the keyed demo handlers show the intended
pattern.

## 5. Retry policy snapshotted onto the job

**Decision.** Copy the effective retry parameters from the queue policy onto the
job at enqueue time instead of reading the live policy on each failure.

**Why.** A job that is already retrying should keep the behaviour it started
with. If an operator tightens a queue's `max_attempts` while jobs are mid-flight,
those jobs should not suddenly dead-letter early. Snapshotting makes retry
behaviour deterministic per job and removes a join from the hot failure path.

**Trade-off.** Policy edits apply only to newly enqueued jobs. That is the
desired semantics here; a bulk re-apply could be added if needed.

## 6. A single scheduler process

**Decision.** Run exactly one scheduler that owns promotion, cron firing and
reaping.

**Why.** Time-based transitions want a single clock authority. One scheduler
means no two processes disagree about what is due. It is a small, stateless loop
whose only failure mode is that promotion pauses until it restarts, with no data
loss and no duplication.

**Trade-off.** It is a single point for time-based work. It is cheap to run
under a process supervisor that restarts it. For high availability, a leader
election (advisory lock in Postgres) would let a standby take over; the tick
logic is already idempotent, so that upgrade is low risk.

## 7. Polling over WebSockets for the dashboard

**Decision.** The dashboard polls the API on short intervals rather than
subscribing over WebSockets.

**Why.** Polling is stateless on the server, trivial to reason about, resilient
to reconnects and entirely adequate for an operations console refreshing every
few seconds. It kept the API stateless and the frontend simple.

**Trade-off.** Slightly higher request volume and a few seconds of latency
versus instant push. For a dashboard that is a good trade. WebSocket live
updates are noted as a natural extension.

## 8. UUID primary keys

**Decision.** String UUIDs for every primary key.

**Why.** Ids are opaque and non sequential, so they leak neither record counts
nor an enumeration surface. They can be generated on the client or across shards
without a central sequence, which matters for the sharding path.

**Trade-off.** Wider keys than integers and non-monotonic inserts. The composite
claim index keeps the hot path fast regardless and the operational benefits
outweigh the storage cost here.

## 9. One codebase, SQLite for dev and Postgres for production

**Decision.** The same application runs on SQLite locally and Postgres in
production through a dialect-aware engine and claim.

**Why.** Zero-setup local development and a fast, dependency-free test suite,
without a second implementation to keep in sync. Contributors run `pytest` with
no database server; production gets real row-level locking.

**Trade-off.** The claim carries two code paths. They are small, share the same
guarded update and are both covered by tests, so the maintenance cost is low.

## 10. Thread pool for worker concurrency

**Decision.** Each worker runs jobs in a `ThreadPoolExecutor` sized to its
concurrency.

**Why.** Background job handlers are typically IO-bound (network calls, database
writes), where threads give real concurrency simply. It also lets handlers be
ordinary synchronous functions, which is the most common shape for real tasks.

**Trade-off.** CPU-bound handlers would be limited by the GIL. For those,
workers scale out as separate processes (the compose file runs two by default
and scales further), which is the horizontal model the whole system is built
around anyway.

## Testing strategy

Tests target the parts where a bug is most costly, not line coverage for its own
sake.

- **Retry maths** are pure functions, tested exhaustively across strategies,
  clamping and jitter bounds.
- **Atomic claiming** has a threaded test with eight concurrent workers claiming
  two hundred jobs, asserting every job is claimed exactly once. Separate tests
  cover concurrency-limit capping, pause, future-dated jobs, priority ordering
  and lease reaping of dead workers.
- **Lifecycle** is driven end to end: create, claim, start, complete; and the
  failure path through retry into the Dead Letter Queue, asserting attempt
  counts, execution history and the DLQ entry.
- **Scheduling** covers promotion of due jobs, cron firing with schedule
  advancement and dependency release on parent completion.
- **The REST surface** is tested through a `TestClient`, including a full
  worker pipeline (register, claim, start, result) that exercises the exact
  endpoints the worker process calls.

Run with `cd backend && python -m pytest`.

## What was deliberately left out

Given the priority on engineering quality, several bonus features were scoped as
clean extension points rather than half-built. Workflow dependencies and the
Dead Letter Queue are implemented. Rate limiting has a field on the queue and a
natural home in the claim. Distributed locking for scheduler HA, queue sharding,
event-driven push, WebSocket updates and AI failure summaries (there is a
`failure_summary` column ready for it) are documented as next steps rather than
rushed in.
