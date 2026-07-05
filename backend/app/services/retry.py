"""Retry backoff computation.

Pure functions so they are trivially unit-testable and identical whether called
from the API, the worker or a test.
"""
from __future__ import annotations

import random

from ..models.enums import RetryStrategy


def compute_backoff_seconds(
    *,
    strategy: RetryStrategy,
    attempt: int,
    base_delay: float,
    backoff_factor: float,
    max_delay: float,
    jitter: float,
    rng: random.Random | None = None,
) -> float:
    """Return the delay (seconds) before the given attempt should run.

    `attempt` is 1-based: attempt=1 is the delay before the first retry (i.e.
    after the initial attempt failed).

    FIXED:        base_delay every time.
    LINEAR:       base_delay * attempt.
    EXPONENTIAL:  base_delay * backoff_factor ** (attempt - 1).

    A symmetric jitter fraction is then applied and the result is clamped to
    max_delay. Jitter prevents many jobs that failed together from retrying in
    lockstep (the thundering herd problem).
    """
    if attempt < 1:
        attempt = 1

    if strategy == RetryStrategy.FIXED:
        delay = base_delay
    elif strategy == RetryStrategy.LINEAR:
        delay = base_delay * attempt
    else:  # EXPONENTIAL
        delay = base_delay * (backoff_factor ** (attempt - 1))

    delay = min(delay, max_delay)

    if jitter > 0:
        r = rng or random
        # +/- jitter fraction around the computed delay
        spread = delay * jitter
        delay = delay + r.uniform(-spread, spread)

    return max(0.0, delay)
