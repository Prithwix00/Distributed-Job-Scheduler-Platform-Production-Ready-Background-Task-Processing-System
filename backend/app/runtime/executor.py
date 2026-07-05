"""Task registry and the built-in demo handlers.

A handler is any callable taking a payload dict and returning a JSON-serialisable
dict. Register real tasks here (or via `register`) in a production deployment.

Handlers should be idempotent wherever possible: because a job can be retried,
or re-run after a worker crash mid-execution, running the same payload twice
must not corrupt state. The demo handlers below are pure and therefore safe.
"""
from __future__ import annotations

import time
from collections.abc import Callable

Handler = Callable[[dict], dict]

_REGISTRY: dict[str, Handler] = {}


def register(name: str):
    def deco(fn: Handler) -> Handler:
        _REGISTRY[name] = fn
        return fn
    return deco


def get_handler(name: str) -> Handler:
    if name not in _REGISTRY:
        raise KeyError(f"No handler registered for task '{name}'")
    return _REGISTRY[name]


# ---------------- built-in demo handlers ----------------

@register("echo")
def echo(payload: dict) -> dict:
    return {"echoed": payload}


@register("sleep")
def sleep(payload: dict) -> dict:
    seconds = float(payload.get("seconds", 1))
    time.sleep(min(seconds, 60))
    return {"slept": seconds}


@register("add")
def add(payload: dict) -> dict:
    return {"sum": float(payload.get("a", 0)) + float(payload.get("b", 0))}


@register("fail")
def always_fail(payload: dict) -> dict:
    raise RuntimeError(payload.get("reason", "intentional failure"))


@register("flaky")
def flaky(payload: dict) -> dict:
    """Fails until attempt >= succeed_on, to exercise the retry pipeline."""
    attempt = int(payload.get("_attempt", 1))
    succeed_on = int(payload.get("succeed_on", 3))
    if attempt < succeed_on:
        raise RuntimeError(f"flaky failure on attempt {attempt}")
    return {"ok": True, "attempt": attempt}


@register("send_email")
def send_email(payload: dict) -> dict:
    # Stand-in for a real side-effecting task. Idempotent on message_id.
    time.sleep(0.05)
    return {"delivered_to": payload.get("to"), "message_id": payload.get("message_id")}
