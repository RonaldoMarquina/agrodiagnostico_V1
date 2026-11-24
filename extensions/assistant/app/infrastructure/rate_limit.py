"""In-memory per-identity sliding-window rate limiter (ADR-0015 D6)."""
from collections import deque
import math
import threading
import time
from typing import Callable, Deque, Dict, Optional, Tuple


class InMemoryRateLimiter:
    """Thread-safe per-identity sliding-window rate limiter without external dependencies."""

    def __init__(
        self,
        max_requests: int = 20,
        window_seconds: int = 60,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_requests < 1 or window_seconds < 1:
            raise ValueError("Rate limit parameters must be positive")
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._buckets: Dict[str, Deque[float]] = {}

    def check_and_record(self, identity_key: str) -> Tuple[bool, int]:
        """Return (allowed, retry_after_seconds) for the given identity key."""
        now = self._clock()
        cutoff = now - self.window_seconds
        with self._lock:
            bucket = self._buckets.get(identity_key)
            if bucket is None:
                bucket = deque()
                self._buckets[identity_key] = bucket

            while bucket and bucket[0] <= cutoff:
                bucket.popleft()

            if len(bucket) >= self.max_requests:
                oldest = bucket[0]
                retry_after = max(1, int(math.ceil((oldest + self.window_seconds) - now)))
                return False, retry_after

            bucket.append(now)
            return True, 0

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()


_GLOBAL_LIMITER: Optional[InMemoryRateLimiter] = None


def get_rate_limiter(max_requests: int, window_seconds: int) -> InMemoryRateLimiter:
    global _GLOBAL_LIMITER
    if (
        _GLOBAL_LIMITER is None
        or _GLOBAL_LIMITER.max_requests != max_requests
        or _GLOBAL_LIMITER.window_seconds != window_seconds
    ):
        _GLOBAL_LIMITER = InMemoryRateLimiter(
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
    return _GLOBAL_LIMITER


def set_rate_limiter(limiter: Optional[InMemoryRateLimiter]) -> None:
    global _GLOBAL_LIMITER
    _GLOBAL_LIMITER = limiter
