import logging

from src.security import SecretRedactionFilter, SlidingWindowLimiter


def test_sliding_window_limiter_blocks_after_limit() -> None:
    limiter = SlidingWindowLimiter(limit=2, window_seconds=60)
    assert limiter.allow("user") == (True, 0)
    assert limiter.allow("user") == (True, 0)
    allowed, retry_after = limiter.allow("user")
    assert allowed is False
    assert retry_after > 0


def test_sliding_window_limiter_isolated_by_identity() -> None:
    limiter = SlidingWindowLimiter(limit=1, window_seconds=60)
    assert limiter.allow("first")[0] is True
    assert limiter.allow("second")[0] is True


def test_secret_redaction_filter_removes_credentials() -> None:
    record = logging.LogRecord(
        "test", logging.INFO, __file__, 1, "token=%s", ("super-secret",), None
    )
    assert SecretRedactionFilter().filter(record) is True
    assert "super-secret" not in record.getMessage()
    assert "[REDACTED]" in record.getMessage()
