import random

from app.models.enums import RetryStrategy
from app.services.retry import compute_backoff_seconds


def _d(strategy, attempt, **kw):
    defaults = dict(base_delay=5.0, backoff_factor=2.0, max_delay=3600.0, jitter=0.0)
    defaults.update(kw)
    return compute_backoff_seconds(strategy=strategy, attempt=attempt, **defaults)


def test_fixed_is_constant():
    assert _d(RetryStrategy.FIXED, 1) == 5.0
    assert _d(RetryStrategy.FIXED, 5) == 5.0


def test_linear_scales_with_attempt():
    assert _d(RetryStrategy.LINEAR, 1) == 5.0
    assert _d(RetryStrategy.LINEAR, 3) == 15.0


def test_exponential_grows():
    assert _d(RetryStrategy.EXPONENTIAL, 1) == 5.0
    assert _d(RetryStrategy.EXPONENTIAL, 2) == 10.0
    assert _d(RetryStrategy.EXPONENTIAL, 3) == 20.0
    assert _d(RetryStrategy.EXPONENTIAL, 4) == 40.0


def test_max_delay_clamps():
    assert _d(RetryStrategy.EXPONENTIAL, 20, max_delay=100.0) == 100.0


def test_jitter_within_bounds():
    rng = random.Random(42)
    for _ in range(200):
        d = compute_backoff_seconds(
            strategy=RetryStrategy.EXPONENTIAL, attempt=3, base_delay=5.0,
            backoff_factor=2.0, max_delay=3600.0, jitter=0.1, rng=rng,
        )
        # 20 +/- 10%
        assert 18.0 <= d <= 22.0


def test_never_negative():
    assert _d(RetryStrategy.FIXED, 1, base_delay=0.0) == 0.0
