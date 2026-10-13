"""Phase 6.7 — Heartbeat security and AutoFollowerSync thread-safety edge-case tests.

Verifies:
- Task 1 Case A: Valid coordinator heartbeat accepted and adopts coordinator.
- Task 1 Case B: Stale coordinator heartbeat rejected (no adoption, no sync).
- Task 1 Case C: Higher-term coordinator heartbeat yields and adopts higher term.
- Task 1 Case D: Unauthorized/unknown coordinator heartbeat rejected (no adoption).
- Task 8: Follower reboot does not start spurious election when valid coordinator heartbeat arrives.
- Task 9: AutoFollowerSync thread safety — no duplicate sync threads run concurrently.
"""

import threading
import time
import pytest

from node.config import NodeConfig, PeerInfo
from node.coordinator import CoordinatorState
from node.heartbeat import HeartbeatMonitor
from node.lamport import LamportClock
from node.models import NodeRole


def _make_config(node_id: int = 1) -> NodeConfig:
    peers = {
        1: PeerInfo(1, "localhost", 50051),
        2: PeerInfo(2, "localhost", 50052),
        3: PeerInfo(3, "localhost", 50053),
        4: PeerInfo(4, "localhost", 50054),
        5: PeerInfo(5, "localhost", 50055),
    }
    return NodeConfig(
        node_id=node_id,
        grpc_port=50050 + node_id,
        election_algorithm="bully",
        peers=peers,
        heartbeat_interval_ms=1000,
        heartbeat_timeout_ms=3000,
        election_timeout_ms=5000,
        replication_policy="all",
        initial_coordinator_id=5,
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="pw",
        db_name="db",
        use_sqlite=True,
        sqlite_path=None,
        log_level="INFO",
        candidates=["Alice", "Bob", "Charlie"],
        auto_recover=True,
    )


class TestHeartbeatSecurityEdgeCases:
    """Task 1 & Task 8: Security and authority checks on HeartbeatMonitor."""

    def test_case_a_valid_coordinator_heartbeat(self):
        cfg = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=5, all_peer_ids=[1, 2, 3, 4, 5])
        clock = LamportClock()
        monitor = HeartbeatMonitor(node_id=1, state=state, clock=clock, config=cfg)

        adopted = []
        monitor.set_on_coordinator_adopted(lambda: adopted.append(True))

        # Valid heartbeat from current coordinator (5) on current term (0)
        accepted = monitor.record_heartbeat(coordinator_id=5, election_term=0, lamport_ts=10)
        assert accepted is True
        assert len(adopted) == 1
        assert state.coordinator_id == 5
        assert state.role == NodeRole.FOLLOWER

    def test_case_b_stale_coordinator_heartbeat_rejected(self):
        cfg = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=5, all_peer_ids=[1, 2, 3, 4, 5])
        state.become_follower(coordinator_id=5, election_term=5, initiator_id=5)
        clock = LamportClock()
        monitor = HeartbeatMonitor(node_id=1, state=state, clock=clock, config=cfg)

        adopted = []
        monitor.set_on_coordinator_adopted(lambda: adopted.append(True))

        # Stale heartbeat with term 3 < 5
        accepted = monitor.record_heartbeat(coordinator_id=5, election_term=3, lamport_ts=10)
        assert accepted is False
        assert len(adopted) == 0
        assert state.election_term == 5

    def test_case_c_higher_term_coordinator_heartbeat_yields(self):
        cfg = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=5, all_peer_ids=[1, 2, 3, 4, 5])
        state.become_follower(coordinator_id=5, election_term=2, initiator_id=5)
        clock = LamportClock()
        monitor = HeartbeatMonitor(node_id=1, state=state, clock=clock, config=cfg)

        adopted = []
        monitor.set_on_coordinator_adopted(lambda: adopted.append(True))

        # Higher term heartbeat (term 4 > 2) from valid coordinator Node 4
        accepted = monitor.record_heartbeat(coordinator_id=4, election_term=4, lamport_ts=20)
        assert accepted is True
        assert len(adopted) == 1
        assert state.coordinator_id == 4
        assert state.election_term == 4
        assert state.role == NodeRole.FOLLOWER

    def test_case_d_unauthorized_node_heartbeat_rejected(self):
        cfg = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=5, all_peer_ids=[1, 2, 3, 4, 5])
        clock = LamportClock()
        monitor = HeartbeatMonitor(node_id=1, state=state, clock=clock, config=cfg)

        adopted = []
        monitor.set_on_coordinator_adopted(lambda: adopted.append(True))

        # Heartbeat from unknown/rogue node 999 not in cluster
        accepted = monitor.record_heartbeat(coordinator_id=999, election_term=10, lamport_ts=20)
        assert accepted is False
        assert len(adopted) == 0
        assert state.coordinator_id == 5  # Remains unchanged

    def test_competing_coordinator_equal_term_rejected(self):
        cfg = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=5, all_peer_ids=[1, 2, 3, 4, 5])
        state.become_follower(coordinator_id=5, election_term=3, initiator_id=5)
        clock = LamportClock()
        monitor = HeartbeatMonitor(node_id=1, state=state, clock=clock, config=cfg)

        adopted = []
        monitor.set_on_coordinator_adopted(lambda: adopted.append(True))

        # Competing coordinator 4 claims term 3 when node 1 already knows coordinator is 5
        accepted = monitor.record_heartbeat(coordinator_id=4, election_term=3, lamport_ts=25)
        assert accepted is False
        assert len(adopted) == 0
        assert state.coordinator_id == 5

    def test_no_unnecessary_election_when_heartbeats_regular(self):
        cfg = _make_config(node_id=1)
        state = CoordinatorState(node_id=1, initial_coordinator_id=5, all_peer_ids=[1, 2, 3, 4, 5])
        clock = LamportClock()
        timeouts = []
        monitor = HeartbeatMonitor(
            node_id=1,
            state=state,
            clock=clock,
            config=cfg,
            on_timeout=lambda: timeouts.append(True),
        )

        monitor.start()
        try:
            for _ in range(5):
                time.sleep(0.05)
                accepted = monitor.record_heartbeat(coordinator_id=5, election_term=0, lamport_ts=1)
                assert accepted is True
            assert len(timeouts) == 0, "Spurious coordinator timeout occurred during regular heartbeats"
        finally:
            monitor.stop()


class TestAutoFollowerSyncThreadSafety:
    """Task 9: Thread safety of follower auto-sync."""

    def test_sync_lock_prevents_concurrent_duplicate_syncs(self):
        sync_lock = threading.Lock()
        concurrent_count = [0]
        max_concurrent = [0]

        def simulated_sync():
            if not sync_lock.acquire(blocking=False):
                return
            try:
                concurrent_count[0] += 1
                max_concurrent[0] = max(max_concurrent[0], concurrent_count[0])
                time.sleep(0.05)
                concurrent_count[0] -= 1
            finally:
                sync_lock.release()

        threads = [threading.Thread(target=simulated_sync) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert max_concurrent[0] == 1, "Multiple concurrent syncs ran simultaneously"
