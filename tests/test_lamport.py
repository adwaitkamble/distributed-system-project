"""Unit tests for node.lamport.LamportClock.

Invariant INV-8: Lamport monotonicity.
"""

import threading


class TestLamportIncrement:
    """Clock increments on every local event."""

    def test_starts_at_zero(self, lamport_clock):
        assert lamport_clock.value == 0

    def test_increment_returns_new_value(self, lamport_clock):
        v = lamport_clock.increment()
        assert v == 1
        assert lamport_clock.value == 1

    def test_tick_is_alias_for_increment(self, lamport_clock):
        v = lamport_clock.tick()
        assert v == 1

    def test_successive_increments_are_monotonic(self, lamport_clock):
        vals = [lamport_clock.increment() for _ in range(10)]
        assert vals == list(range(1, 11))


class TestLamportSend:
    """Send = increment + return value for message."""

    def test_send_increments(self, lamport_clock):
        ts = lamport_clock.send()
        assert ts == 1
        assert lamport_clock.value == 1

    def test_multiple_sends_are_monotonic(self, lamport_clock):
        t1 = lamport_clock.send()
        t2 = lamport_clock.send()
        t3 = lamport_clock.send()
        assert t1 < t2 < t3


class TestLamportReceive:
    """Receive: counter = max(local, received) + 1."""

    def test_receive_with_higher_remote(self, lamport_clock):
        new = lamport_clock.receive(100)
        assert new == 101
        assert lamport_clock.value == 101

    def test_receive_with_lower_remote(self, lamport_clock):
        lamport_clock.increment()  # local = 1
        lamport_clock.increment()  # local = 2
        new = lamport_clock.receive(0)
        assert new == 3  # max(2, 0) + 1

    def test_receive_with_equal_remote(self, lamport_clock):
        lamport_clock.increment()  # local = 1
        new = lamport_clock.receive(1)
        assert new == 2  # max(1, 1) + 1

    def test_receive_then_send_preserves_monotonicity(self, lamport_clock):
        lamport_clock.receive(50)  # local = 51
        ts = lamport_clock.send()
        assert ts == 52


class TestLamportThreadSafety:
    """Concurrent increments must not lose updates."""

    def test_concurrent_increments(self, lamport_clock):
        n_threads = 10
        increments_per_thread = 100
        barrier = threading.Barrier(n_threads)

        def worker():
            barrier.wait()
            for _ in range(increments_per_thread):
                lamport_clock.increment()

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        expected = n_threads * increments_per_thread
        assert lamport_clock.value == expected


class TestLamportRepr:
    def test_repr_includes_value(self, lamport_clock):
        lamport_clock.increment()
        assert "1" in repr(lamport_clock)
