"""Scheduler process.

A single-instance loop that owns all time-based transitions:
  - promote SCHEDULED jobs that are due into QUEUED
  - fire recurring (cron) schedules
  - reap dead workers and requeue jobs whose leases expired

Kept as one process so there is exactly one clock authority. If it dies, jobs
are simply not promoted until it restarts; nothing is lost or duplicated.

Run:  python -m app.runtime.scheduler
"""
from __future__ import annotations

import signal
import threading
import time

from ..core import configure_logging, get_logger
from ..config import settings
from ..database import SessionLocal, Base, engine
from ..services import scheduling, claiming

log = get_logger("scheduler")
_stop = threading.Event()


def tick() -> dict:
    """Run one scheduler pass. Returns counters for observability/tests."""
    db = SessionLocal()
    try:
        promoted = scheduling.promote_due_scheduled(db)
        fired = scheduling.fire_due_cron(db)
        reaped_workers = scheduling.reap_dead_workers(db)
        requeued = claiming.reap_expired_leases(db)
        return {
            "promoted": promoted, "cron_fired": fired,
            "dead_workers": reaped_workers, "requeued_leases": requeued,
        }
    finally:
        db.close()


def run() -> None:
    configure_logging()
    Base.metadata.create_all(bind=engine)
    log.info("scheduler.started")
    while not _stop.is_set():
        try:
            counts = tick()
            if any(counts.values()):
                log.info("scheduler.tick", extra={"extra_fields": counts})
        except Exception as exc:  # noqa: BLE001
            log.error("scheduler.tick_failed", extra={"extra_fields": {"err": str(exc)}})
        _stop.wait(settings.scheduler_tick_seconds)
    log.info("scheduler.stopped")


def _stop_handler(*_):
    _stop.set()


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _stop_handler)
    signal.signal(signal.SIGINT, _stop_handler)
    run()
