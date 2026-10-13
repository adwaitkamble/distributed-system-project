"""Tests for heartbeat subsystem: broadcaster, monitor, monotonic timeout detection, and term validation."""

import time
import threading
from unittest.mock import MagicMock
import pytest

from node.config import NodeConfig, PeerInfo
from node.coordinator import CoordinatorState
from node.heartbeat import HeartbeatMonitor, HeartbeatSender
from node.lamport import LamportClock
from node.models import NodeRole
from node.generated import voting_pb2


def _make_config(node_id: int = 1, timeout_ms: int = 200, interval_ms: int = 50) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        grpc_port=50050 + node_id,
        election_algorithm="bully",
        peers={
            1: PeerInfo(1, "localhost", 50051),
            2: PeerInfo(2, "localhost", 50052),
            3: PeerInfo(3, "localhost", 50053),
        },
        heartbeat_interval_ms=interval_ms,
        heartbeat_timeout_ms=timeout_ms,
        election_timeout_ms=500,
        replication_policy="all",
        initial_coordinator_id=1,
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="pwd",
        db_name="db",
        use_sqlite=True,
        sqlite_path=None,
        log_level="DEBUG",
        candidates=["Alice", "Bob", "Charlie"],
    )


class TestHeartbeatSender:
    """Tests for HeartbeatSender (coordinator ping broadcast)."""

    def test_single_round_all_success(self):
        config = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=1)
        clock = LamportClock()

        c2 = MagicMock()
        c2.send_heartbeat.return_value = voting_pb2.HeartbeatPong(node_id=2, lamport_ts=15)
        c3 = MagicMock()
        c3.send_heartbeat.return_value = voting_pb2.HeartbeatPong(node_id=3, lamport_ts=20)

        sender = HeartbeatSender(
            node_id=1,
            state=state,
            clock=clock,
            peer_clients={2: c2, 3: c3},
            config=config,
        )

        results = sender.send_single_round()
        assert results == {2: True, 3: True}
        assert state.active_peers == {2, 3}
        assert clock.value >= 20  # Clock merged higher remote ts

    def test_single_round_peer_failure_marks_inactive(self):
        config = _make_config(node_id=1, timeout_ms=200)
        state = CoordinatorState(node_id=1, initial_coordinator_id=1)
        # Pre-seed active peers
        state.mark_peer_active(2)
        state.mark_peer_active(3)
        clock = LamportClock()

        c2 = MagicMock()
        c2.send_heartbeat.return_value = voting_pb2.HeartbeatPong(node_id=2, lamport_ts=5)
        c3 = MagicMock()
        c3.send_heartbeat.return_value = None  # Failed

        sender = HeartbeatSender(
            node_id=1,
            state=state,
            clock=clock,
            peer_clients={2: c2, 3: c3},
            config=config,
        )

        # First round: sender just started, so peer 3 last_ack is fresh
        # Do not mark peer inactive immediately on first failed heartbeat (Req 4)
        results = sender.send_single_round()
        assert results == {2: True, 3: False}
        assert 2 in state.active_peers
        assert 3 in state.active_peers

        # After timeout duration elapses, subsequent failure marks peer 3 inactive
        sender._last_ack_monotonic[3] = time.monotonic() - 1.0
        results2 = sender.send_single_round()
        assert results2 == {2: True, 3: False}
        assert 2 in state.active_peers
        assert 3 not in state.active_peers

    def test_each_heartbeat_send_has_distinct_lamport_ts(self):
        """Each outbound heartbeat ping must increment clock and have distinct Lamport timestamp."""
        config = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=1)
        clock = LamportClock()

        c2 = MagicMock()
        c2.send_heartbeat.return_value = voting_pb2.HeartbeatPong(node_id=2, lamport_ts=1)
        c3 = MagicMock()
        c3.send_heartbeat.return_value = voting_pb2.HeartbeatPong(node_id=3, lamport_ts=1)

        sender = HeartbeatSender(
            node_id=1,
            state=state,
            clock=clock,
            peer_clients={2: c2, 3: c3},
            config=config,
        )

        sender.send_single_round()
        assert c2.send_heartbeat.called
        assert c3.send_heartbeat.called

        ts2 = c2.send_heartbeat.call_args[1]["lamport_ts"]
        ts3 = c3.send_heartbeat.call_args[1]["lamport_ts"]
        assert ts2 > 0
        assert ts3 > 0
        assert ts2 != ts3  # Must be distinct timestamps for each peer outbound RPC

    def test_sender_background_thread_start_stop(self):
        config = _make_config(node_id=1, interval_ms=50)
        state = CoordinatorState(node_id=1, initial_coordinator_id=1)
        clock = LamportClock()

        c2 = MagicMock()
        c2.send_heartbeat.return_value = voting_pb2.HeartbeatPong(node_id=2, lamport_ts=1)

        sender = HeartbeatSender(
            node_id=1,
            state=state,
            clock=clock,
            peer_clients={2: c2},
            config=config,
        )

        sender.start()
        time.sleep(0.15)  # Allow ~2-3 rounds
        sender.stop()

        assert c2.send_heartbeat.call_count >= 2


class TestHeartbeatMonitor:
    """Tests for HeartbeatMonitor (follower monotonic timeout detector)."""

    def test_record_heartbeat_resets_monotonic_timer(self):
        config = _make_config(node_id=2, timeout_ms=200)
        state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        clock = LamportClock()

        monitor = HeartbeatMonitor(
            node_id=2,
            state=state,
            clock=clock,
            config=config,
        )

        t1 = monitor.last_heartbeat_time
        time.sleep(0.05)
        ok = monitor.record_heartbeat(coordinator_id=1, election_term=0, lamport_ts=5)
        assert ok is True
        t2 = monitor.last_heartbeat_time
        assert t2 > t1

    def test_reject_stale_heartbeat_term(self):
        config = _make_config(node_id=2, timeout_ms=200)
        state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        # Advance term to 3
        state.become_follower(coordinator_id=1, election_term=3, initiator_id=1)
        clock = LamportClock()

        monitor = HeartbeatMonitor(
            node_id=2,
            state=state,
            clock=clock,
            config=config,
        )

        # Heartbeat with term 2 < 3 must be rejected
        ok = monitor.record_heartbeat(coordinator_id=1, election_term=2, lamport_ts=5)
        assert ok is False

    def test_heartbeat_timeout_triggers_callback(self):
        """Follower detects silence beyond timeout threshold using time.monotonic()."""
        config = _make_config(node_id=2, timeout_ms=100)  # 100ms timeout
        state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        clock = LamportClock()

        timeout_called = threading.Event()

        def _on_timeout():
            timeout_called.set()

        monitor = HeartbeatMonitor(
            node_id=2,
            state=state,
            clock=clock,
            config=config,
            on_timeout=_on_timeout,
        )

        # Initially not timed out
        assert monitor.check_timeout() is False
        assert not timeout_called.is_set()

        # Wait past the 100ms threshold
        time.sleep(0.15)

        timed_out = monitor.check_timeout()
        assert timed_out is True
        assert timeout_called.is_set()

    def test_regular_heartbeats_prevent_timeout(self):
        """Continually receiving heartbeats prevents timeout from firing."""
        config = _make_config(node_id=2, timeout_ms=150)
        state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        clock = LamportClock()

        timeout_called = threading.Event()

        monitor = HeartbeatMonitor(
            node_id=2,
            state=state,
            clock=clock,
            config=config,
            on_timeout=lambda: timeout_called.set(),
        )

        # Send heartbeats every 40ms over 200ms total (well past the 150ms timeout)
        for _ in range(5):
            time.sleep(0.04)
            monitor.record_heartbeat(coordinator_id=1, election_term=0, lamport_ts=1)
            assert monitor.check_timeout() is False

        assert not timeout_called.is_set()

    def test_coordinator_never_times_out_itself(self):
        """Coordinator node must never trigger a heartbeat timeout on itself."""
        config = _make_config(node_id=1, timeout_ms=50)
        state = CoordinatorState(node_id=1, initial_coordinator_id=1)
        assert state.is_coordinator()

        monitor = HeartbeatMonitor(
            node_id=1,
            state=state,
            clock=LamportClock(),
            config=config,
            on_timeout=lambda: pytest.fail("Coordinator should never time out"),
        )

        time.sleep(0.1)
        assert monitor.check_timeout() is False

    def test_background_monitor_loop(self):
        """Background thread fires callback automatically upon timeout."""
        config = _make_config(node_id=2, timeout_ms=100)
        state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        clock = LamportClock()

        timeout_fired = threading.Event()

        monitor = HeartbeatMonitor(
            node_id=2,
            state=state,
            clock=clock,
            config=config,
            on_timeout=lambda: timeout_fired.set(),
        )

        monitor.start()
        # Wait up to 0.5s for the 100ms timeout to fire
        fired = timeout_fired.wait(timeout=0.5)
        monitor.stop()

        assert fired is True

    def test_timeout_callback_fires_exactly_once(self):
        """Stopping the coordinator causes follower timeout callback exactly once."""
        config = _make_config(node_id=2, timeout_ms=50)
        state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        clock = LamportClock()

        calls = []

        def _on_timeout():
            calls.append(time.monotonic())

        monitor = HeartbeatMonitor(
            node_id=2,
            state=state,
            clock=clock,
            config=config,
            on_timeout=_on_timeout,
        )

        time.sleep(0.15)
        assert monitor.check_timeout() is True
        assert len(calls) == 1

        # Additional checks while still timed out must NOT fire callback again
        for _ in range(5):
            assert monitor.check_timeout() is True
        assert len(calls) == 1

        # Valid heartbeat arrives: resets latch
        ok = monitor.record_heartbeat(coordinator_id=1, election_term=0, lamport_ts=10)
        assert ok is True
        assert monitor.check_timeout() is False
        assert len(calls) == 1

        # Silence occurs again: fires callback a second time
        time.sleep(0.15)
        assert monitor.check_timeout() is True
        assert len(calls) == 2

    def test_reject_competing_coordinator_on_equal_term(self):
        """For an equal election term, reject heartbeats from competing coordinators."""
        config = _make_config(node_id=2, timeout_ms=200)
        state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        clock = LamportClock()

        monitor = HeartbeatMonitor(
            node_id=2,
            state=state,
            clock=clock,
            config=config,
        )

        # Equal term (0) from known coordinator (1) -> accepted
        assert monitor.record_heartbeat(coordinator_id=1, election_term=0, lamport_ts=5) is True

        # Equal term (0) from competing coordinator (3) -> rejected
        assert monitor.record_heartbeat(coordinator_id=3, election_term=0, lamport_ts=6) is False

        # Higher term (1) from node 3 -> accepted (new term / new coordinator election result)
        assert monitor.record_heartbeat(coordinator_id=3, election_term=1, lamport_ts=7) is True

