from collections import defaultdict, deque
from datetime import datetime, timedelta
from threading import Lock


class FailedExchangeLimiter:
    def __init__(self, limit: int = 10, window: timedelta = timedelta(minutes=1)) -> None:
        self._limit = limit
        self._window = window
        self._attempts: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = Lock()

    def record_and_allow(self, key: str, now: datetime) -> bool:
        with self._lock:
            attempts = self._attempts[key]
            cutoff = now - self._window
            while attempts and attempts[0] <= cutoff:
                attempts.popleft()
            attempts.append(now)
            return len(attempts) <= self._limit


failed_exchange_limiter = FailedExchangeLimiter()
