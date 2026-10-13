"""Thread-safe Lamport logical clock.

Rules (Lamport 1978):
  - Local event : L ← L + 1
  - Send        : L ← L + 1; attach L to message
  - Receive(Lm) : L ← max(L, Lm) + 1
"""

import threading


class LamportClock:
    """Monotonically increasing logical clock, safe for concurrent use."""

    def __init__(self, initial: int = 0) -> None:
        self._counter: int = initial
        self._lock = threading.Lock()

    # ── Read ─────────────────────────────────────────────────────

    @property
    def value(self) -> int:
        """Current clock value (snapshot)."""
        with self._lock:
            return self._counter

    # ── Mutators ─────────────────────────────────────────────────

    def increment(self) -> int:
        """Increment for a local event.  Returns the new value."""
        with self._lock:
            self._counter += 1
            return self._counter

    # Alias used in higher-level code for readability.
    tick = increment

    def send(self) -> int:
        """Increment for a send event.  Returns the timestamp to attach."""
        return self.increment()

    def receive(self, received_ts: int) -> int:
        """Update on receiving a message carrying *received_ts*.

        Returns the new local clock value.
        """
        with self._lock:
            self._counter = max(self._counter, received_ts) + 1
            return self._counter

    def set(self, value: int) -> int:
        """Advance the clock to at least *value* monotonically."""
        with self._lock:
            self._counter = max(self._counter, value)
            return self._counter

    # ── Representation ───────────────────────────────────────────

    def __repr__(self) -> str:
        return f"LamportClock(value={self.value})"
