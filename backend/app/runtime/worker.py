"""Worker service.

Polls the scheduler API, atomically claims jobs, executes them concurrently in a
thread pool, sends heartbeats (which also renew job leases) and shuts down
gracefully by draining in-flight work before exiting.

Run:  python -m app.runtime.worker --queues <id1,id2> --concurrency 4
"""
from __future__ import annotations

import argparse
import os
import signal
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx

from ..config import settings
from ..core import configure_logging, get_logger
from .executor import get_handler

log = get_logger("worker")


class Worker:
    def __init__(self, base_url: str, queues: list[str], concurrency: int):
        self.base_url = base_url.rstrip("/")
        self.api = f"{self.base_url}/api/v1"
        self.queues = queues
        self.concurrency = concurrency
        self.worker_id: str | None = None
        self.client = httpx.Client(timeout=30.0)
        self.pool = ThreadPoolExecutor(max_workers=concurrency)
        self._active = 0
        self._active_lock = threading.Lock()
        self._stop = threading.Event()

    # ---- lifecycle ----

    def register(self, max_wait_seconds: float = 60.0) -> None:
        # The API may not be up yet (start order, container boot). Retry the
        # registration until it responds or we give up, so callers never have to
        # sequence the processes by hand.
        deadline = time.time() + max_wait_seconds
        attempt = 0
        while not self._stop.is_set():
            attempt += 1
            try:
                resp = self.client.post(f"{self.api}/workers/register", json={
                    "hostname": socket.gethostname(),
                    "pid": os.getpid(),
                    "queues": self.queues,
                    "concurrency": self.concurrency,
                })
                resp.raise_for_status()
                self.worker_id = resp.json()["id"]
                log.info("worker.registered", extra={"extra_fields": {"worker_id": self.worker_id}})
                return
            except Exception as exc:  # noqa: BLE001
                if time.time() >= deadline:
                    raise
                if attempt == 1:
                    log.info("worker.waiting_for_api", extra={"extra_fields": {"api": self.api}})
                time.sleep(2.0)

    def _heartbeat_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.client.post(
                    f"{self.api}/workers/{self.worker_id}/heartbeat",
                    json={"active_jobs": self._active},
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("worker.heartbeat_failed", extra={"extra_fields": {"err": str(exc)}})
            self._stop.wait(settings.worker_heartbeat_interval_seconds)

    # ---- execution ----

    def _run_job(self, job: dict) -> None:
        job_id = job["id"]
        with self._active_lock:
            self._active += 1
        try:
            start = self.client.post(
                f"{self.api}/workers/{self.worker_id}/jobs/{job_id}/start"
            )
            if start.status_code != 200:
                return  # someone else grabbed it / state changed
            attempt = start.json()["attempt_number"]
            execution_id = start.json()["execution_id"]

            payload = dict(job.get("payload") or {})
            payload["_attempt"] = attempt

            success, result, error = True, None, None
            try:
                handler = get_handler(job["task_name"])
                result = handler(payload)
            except Exception as exc:  # noqa: BLE001
                success, error = False, f"{type(exc).__name__}: {exc}"

            self.client.post(
                f"{self.api}/workers/{self.worker_id}/jobs/{job_id}/result",
                json={
                    "execution_id": execution_id, "success": success,
                    "result": result, "error": error,
                },
            )
            log.info("worker.job_done", extra={"extra_fields": {
                "job_id": job_id, "task": job["task_name"], "success": success,
            }})
        except Exception as exc:  # noqa: BLE001
            log.error("worker.job_error", extra={"extra_fields": {"job_id": job_id, "err": str(exc)}})
        finally:
            with self._active_lock:
                self._active -= 1

    def _claim_and_dispatch(self) -> int:
        free = self.concurrency - self._active
        if free <= 0:
            return 0
        resp = self.client.post(
            f"{self.api}/workers/{self.worker_id}/claim",
            json={"worker_id": self.worker_id, "limit": min(free, settings.worker_claim_batch_size),
                  "lease_seconds": settings.heartbeat_timeout_seconds},
        )
        if resp.status_code != 200:
            return 0
        jobs = resp.json()
        for job in jobs:
            self.pool.submit(self._run_job, job)
        return len(jobs)

    def run(self) -> None:
        self.register()
        threading.Thread(target=self._heartbeat_loop, daemon=True).start()
        log.info("worker.started", extra={"extra_fields": {"concurrency": self.concurrency}})

        while not self._stop.is_set():
            try:
                dispatched = self._claim_and_dispatch()
            except Exception as exc:  # noqa: BLE001
                log.warning("worker.claim_failed", extra={"extra_fields": {"err": str(exc)}})
                dispatched = 0
            # Back off when idle, poll fast when busy.
            time.sleep(0 if dispatched else settings.worker_poll_interval_seconds)

        self._drain()

    def _drain(self) -> None:
        log.info("worker.draining")
        # Stop accepting new work and let in-flight jobs finish.
        self.pool.shutdown(wait=True)
        try:
            self.client.post(
                f"{self.api}/workers/{self.worker_id}/heartbeat",
                json={"active_jobs": 0},
            )
        except Exception:  # noqa: BLE001
            pass
        self.client.close()
        log.info("worker.stopped")

    def stop(self, *_):
        log.info("worker.stop_signal")
        self._stop.set()


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default=os.getenv("SCHEDULER_API_URL", "http://localhost:8000"))
    parser.add_argument("--queues", default=os.getenv("WORKER_QUEUES", ""),
                        help="comma separated queue ids; empty = all queues")
    parser.add_argument("--concurrency", type=int,
                        default=int(os.getenv("WORKER_CONCURRENCY", "4")))
    args = parser.parse_args()

    queues = [q for q in args.queues.split(",") if q.strip()]
    worker = Worker(args.base_url, queues, args.concurrency)

    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()


if __name__ == "__main__":
    main()
