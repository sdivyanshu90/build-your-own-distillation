"""Unit tests for the in-memory rate limiter."""

from __future__ import annotations

import pytest

from distillery.infrastructure.security.rate_limit import InMemoryRateLimiter

pytestmark = pytest.mark.unit


def test_allows_up_to_limit_then_blocks() -> None:
    limiter = InMemoryRateLimiter(limit_per_minute=3)
    decisions = [limiter.check("client") for _ in range(4)]
    assert [d.allowed for d in decisions] == [True, True, True, False]
    assert decisions[0].remaining == 2
    assert decisions[-1].remaining == 0


def test_independent_keys() -> None:
    limiter = InMemoryRateLimiter(limit_per_minute=1)
    assert limiter.check("a").allowed
    assert limiter.check("b").allowed  # different key, own bucket
    assert not limiter.check("a").allowed


def test_decision_metadata() -> None:
    limiter = InMemoryRateLimiter(limit_per_minute=10)
    d = limiter.check("c")
    assert d.limit == 10
    assert 0 < d.reset_seconds <= 60
