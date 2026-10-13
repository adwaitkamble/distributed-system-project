"""Tests for leader election correctness rules.

Verifies:
5. Stale Election and stale Coordinator messages are rejected.
6. Concurrent election attempts with different (term, initiator_id) converge on newer tuple.
7. Exactly one election starts per heartbeat-timeout incident.
8. Newly elected RECOVERING coordinator rejects votes.
9. Newly elected recovering coordinator sends heartbeats and followers do not re-trigger election.
10. Message counts equal logical sent Election, OK, and Coordinator messages only.
"""

import socket
import time
import pytest
import grpc
from unittest.mock import MagicMock
from node.config import NodeConfig, PeerInfo
from node.coordinator import CoordinatorState
from node.election import create_election_strategy
from node.generated import voting_pb2, voting_pb2_grpc
from node.heartbeat import HeartbeatMonitor, HeartbeatSender
from node.lamport import LamportClock
from node.lifecycle import NodeLifecycle
from node.models import NodeRole
from node.runtime import NodeRuntime
from node.vote_service import VoteService


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _create_node(
    node_id: int,
    ports: dict[int, int],
    tmp_path,
    algorithm: str = "bully",
    initial_coordinator_id: int = 1,
    heartbeat_interval_ms: int = 50,
    heartbeat_timeout_ms: int = 1500,
    election_timeout_ms: int = 1000,
) -> NodeRuntime:
    db_path = str(tmp_path / f"node_{node_id}.sqlite")
    peers = {
        pid: PeerInfo(pid, "127.0.0.1", port)
        for pid, port in ports.items()
    }
    config = NodeConfig(
        node_id=node_id,
        grpc_port=ports[node_id],
        election_algorithm=algorithm,
        peers=peers,
        heartbeat_interval_ms=heartbeat_interval_ms,
        heartbeat_timeout_ms=heartbeat_timeout_ms,
        election_timeout_ms=election_timeout_ms,
        replication_policy="all",
        initial_coordinator_id=initial_coordinator_id,
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="pwd",
        db_name="db",
        use_sqlite=True,
        sqlite_path=db_path,
        log_level="DEBUG",
        candidates=["Alice", "Bob", "Charlie"],
    )
    return NodeRuntime(config=config)


def _wait_cluster_ready(nodes: dict[int, NodeRuntime], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    for nid, node in nodes.items():
        ready = False
        while time.monotonic() < deadline:
            try:
                channel = grpc.insecure_channel(f"127.0.0.1:{node.config.grpc_port}")
                stub = voting_pb2_grpc.NodeServiceStub(channel)
                st = stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.2)
                channel.close()
                if st.this_node_id == nid:
                    ready = True
                    break
            except Exception:
                time.sleep(0.05)
        if not ready:
            raise TimeoutError(f"Node {nid} failed to become ready within {timeout}s")


class TestElectionCorrectness:
    """Correctness rules verification suite."""

    def test_stale_election_and_coordinator_messages_rejected(self, tmp_path):
        """Test 5: Stale Election and stale Coordinator messages are rejected.
        Also conflicting coordinator announcements on equal terms are rejected.
        """
        ports = {1: _find_free_port()}
        node = _create_node(1, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)
        node.start()

        try:
            # Advance node state to term 10, initiator 1
            node.state.enter_election(10, 1)
            accepted, reason = node.state.accept_coordinator(coordinator_id=1, election_term=10, initiator_id=1)
            assert accepted is True

            # 1. Stale Election message (term 9 < term 10)
            ok, nid, ts = node.election_strategy.on_election_message(
                sender_id=2,
                candidate_id=2,
                election_term=9,
                initiator_id=1,
                msg_lamport_ts=100,
            )
            assert ok is False
            stale_events = node.db.get_election_events("STALE_ELECTION_REJECTED")
            assert len(stale_events) >= 1
            assert stale_events[-1]["details"].get("reason") == "stale_tuple"

            # 2. Stale Coordinator message (term 8 < term 10)
            accepted2 = node.election_strategy.on_coordinator_announcement(
                coordinator_id=2,
                election_term=8,
                initiator_id=1,
                msg_lamport_ts=105,
            )
            assert accepted2 is False
            stale_events = node.db.get_election_events("STALE_ELECTION_REJECTED")
            assert stale_events[-1]["election_term"] == 8

            # 3. Conflicting coordinator on equal term (term 10, initiator 1 already accepted coordinator 1)
            accepted3 = node.election_strategy.on_coordinator_announcement(
                coordinator_id=2,
                election_term=10,
                initiator_id=1,
                msg_lamport_ts=110,
            )
            assert accepted3 is False
            stale_events = node.db.get_election_events("STALE_ELECTION_REJECTED")
            assert "conflicting_coordinator" in stale_events[-1]["details"].get("reason")

        finally:
            node.stop()

    def test_concurrent_elections_converge_on_newer_tuple(self, tmp_path):
        """Test 6: Concurrent election attempts with different (term, initiator_id)
        converge on the newer tuple.
        """
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        nodes = {}
        for nid in [1, 2, 3]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # Node 1 and Node 2 start elections nearly concurrently
            nodes[1].election_strategy.start_election(blocking=False)
            time.sleep(0.01)
            nodes[2].election_strategy.start_election(blocking=False)

            # Wait for convergence: both should converge on Node 3 winning the highest term
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if (
                    nodes[3].state.role == NodeRole.RECOVERING
                    and nodes[1].state.coordinator_id == 3
                    and nodes[2].state.coordinator_id == 3
                    and nodes[1].state.election_term == nodes[3].state.election_term
                    and nodes[2].state.election_term == nodes[3].state.election_term
                ):
                    break
                time.sleep(0.05)

            assert nodes[3].state.role == NodeRole.RECOVERING
            assert nodes[3].state.coordinator_id == 3
            assert nodes[1].state.coordinator_id == 3
            assert nodes[2].state.coordinator_id == 3
            assert nodes[1].state.election_term == nodes[3].state.election_term
            assert nodes[2].state.election_term == nodes[3].state.election_term

        finally:
            for n in nodes.values():
                n.stop()

    def test_exactly_one_election_per_timeout_incident(self, tmp_path):
        """Test 7: Exactly one election starts per heartbeat-timeout incident."""
        ports = {1: _find_free_port(), 2: _find_free_port()}
        node = _create_node(1, ports, tmp_path, algorithm="bully", initial_coordinator_id=2)
        # Manually verify latching on HeartbeatMonitor
        callback_count = 0

        def on_timeout():
            nonlocal callback_count
            callback_count += 1

        monitor = HeartbeatMonitor(
            node_id=1,
            state=node.state,
            clock=node.clock,
            config=node.config,
            on_timeout=on_timeout,
        )

        # Force timeout condition
        monitor._last_heartbeat_monotonic = time.monotonic() - 10.0

        # First check triggers callback
        t1 = monitor.check_timeout()
        assert t1 is True
        assert callback_count == 1

        # Second check: latched, callback does NOT fire again
        t2 = monitor.check_timeout()
        assert t2 is True
        assert callback_count == 1

        # Third check: still 1
        t3 = monitor.check_timeout()
        assert t3 is True
        assert callback_count == 1

        # Reset latch only after valid heartbeat from accepted coordinator
        node.state.accept_coordinator(coordinator_id=2, election_term=1, initiator_id=2)
        monitor.record_heartbeat(coordinator_id=2, election_term=1, lamport_ts=10)
        assert monitor._timeout_latched is False

        # Concurrency guard on election strategy: duplicate start_election is suppressed
        node.election_strategy._election_in_progress = True
        node.election_strategy.start_election(blocking=True)
        # Verified it didn't throw and suppressed duplicate start

    def test_recovering_coordinator_rejects_votes(self, tmp_path):
        """Test 8: Newly elected RECOVERING coordinator rejects votes."""
        ports = {1: _find_free_port()}
        node = _create_node(1, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)
        node.start()

        try:
            # Win election to enter RECOVERING role
            node.state.win_election(election_term=5, initiator_id=1)
            assert node.state.role == NodeRole.RECOVERING
            assert node.state.coordinator_id == 1
            assert node.state.is_accepting_votes() is False

            # Attempt SubmitVote via gRPC
            channel = grpc.insecure_channel(f"127.0.0.1:{node.config.grpc_port}")
            stub = voting_pb2_grpc.NodeServiceStub(channel)

            req = voting_pb2.VoteRequest(
                client_id="voter_rec_1",
                choice="Alice",
            )

            with pytest.raises(grpc.RpcError) as exc_info:
                stub.SubmitVote(req, timeout=1.0)

            channel.close()
            assert exc_info.value.code() == grpc.StatusCode.FAILED_PRECONDITION
            assert "not_coordinator" in exc_info.value.details() or "recovering" in exc_info.value.details()

        finally:
            node.stop()

    def test_recovering_coordinator_sends_heartbeats_followers_dont_retrigger(self, tmp_path):
        """Test 9: Newly elected recovering coordinator sends heartbeats
        and followers do not re-trigger election.
        """
        ports = {1: _find_free_port(), 2: _find_free_port()}
        nodes = {}
        for nid in [1, 2]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # Elect Node 2 as recovering coordinator
            nodes[2].state.win_election(election_term=5, initiator_id=2)
            nodes[2].lifecycle.apply_role()
            nodes[2].election_strategy._announce_coordinator_to_peers(5, 2)

            assert nodes[2].state.role == NodeRole.RECOVERING
            assert nodes[1].state.coordinator_id == 2
            assert nodes[1].state.role == NodeRole.FOLLOWER

            # Wait a few heartbeat intervals (heartbeat_interval=50ms)
            time.sleep(0.3)

            # Node 1 monitor must have received heartbeats from recovering coordinator 2
            # and must NOT have timed out or latched
            assert nodes[1].heartbeat_monitor._timeout_latched is False
            assert time.monotonic() - nodes[1].heartbeat_monitor.last_heartbeat_time < 0.2

        finally:
            for n in nodes.values():
                n.stop()

    def test_message_counts_equal_logical_sent_messages_only(self, tmp_path):
        """Test 10: Message counts equal sent Election, OK, Coordinator only.
        Incoming received messages must not increment overhead totals.
        """
        ports = {1: _find_free_port()}
        node = _create_node(1, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)

        strategy = node.election_strategy
        assert strategy.get_message_counts() == {"election": 0, "ok": 0, "coordinator": 0}

        # Receiving election message does NOT increment sent counts
        strategy.on_election_message(
            sender_id=2,
            candidate_id=0,  # lower than node 1, so node 1 sends OK
            election_term=1,
            initiator_id=2,
            msg_lamport_ts=5,
        )
        counts = strategy.get_message_counts()
        assert counts["election"] == 0
        assert counts["ok"] == 1  # 1 OK reply sent
        assert counts["coordinator"] == 0

        # Receiving coordinator announcement does NOT increment counts
        strategy.on_coordinator_announcement(
            coordinator_id=3,
            election_term=2,
            initiator_id=3,
            msg_lamport_ts=10,
        )
        counts2 = strategy.get_message_counts()
        assert counts2["coordinator"] == 0  # 0 coordinator announcements sent by node 1

    def test_sequential_elections_isolate_per_election_metrics(self, tmp_path):
        """Test: Consecutive elections on the same node report only their own sent messages,
        not cumulative totals, while preserving lifetime counts separately.
        """
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        nodes = {}
        for nid in [1, 2, 3]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # ── Election 1 ──
            nodes[3].election_strategy.start_election(blocking=True)
            counts_e1 = nodes[3].election_strategy.get_message_counts()
            assert counts_e1["coordinator"] == 2
            assert counts_e1["election"] == 0
            assert counts_e1["ok"] == 0

            metrics_e1 = nodes[3].election_strategy.get_last_election_metrics()
            assert metrics_e1["coordinator_sent"] == 2
            assert metrics_e1["total_logical_sent"] == 2
            assert metrics_e1["election_sent"] == 0
            assert metrics_e1["ok_sent"] == 0
            assert metrics_e1["election_term"] > 0
            assert metrics_e1["initiator_id"] == 3

            # ── Election 2 (consecutive on the same cluster) ──
            # Give a small pause for any in-flight heartbeats
            time.sleep(0.1)
            nodes[3].election_strategy.start_election(blocking=True)

            counts_e2 = nodes[3].election_strategy.get_message_counts()
            # Must reflect ONLY Election 2 sent messages, not 2 + 2 = 4
            assert counts_e2["coordinator"] == 2
            assert counts_e2["election"] == 0
            assert counts_e2["ok"] == 0

            metrics_e2 = nodes[3].election_strategy.get_last_election_metrics()
            assert metrics_e2["coordinator_sent"] == 2
            assert metrics_e2["total_logical_sent"] == 2
            assert metrics_e2["election_sent"] == 0
            assert metrics_e2["ok_sent"] == 0
            assert metrics_e2["election_term"] > metrics_e1["election_term"]
            assert metrics_e2["initiator_id"] == 3

            # Lifetime counter tracks cumulative across all elections
            lifetime = nodes[3].election_strategy.get_lifetime_message_counts()
            assert lifetime["coordinator"] == 4
            assert lifetime["election"] == 0
            assert lifetime["ok"] == 0

        finally:
            for n in nodes.values():
                n.stop()

    def test_suppressed_duplicate_start_preserves_active_metrics(self, tmp_path):
        """Test: Suppressed duplicate start_election() does NOT reset or corrupt active metrics."""
        ports = {1: _find_free_port()}
        node = _create_node(1, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)

        strategy = node.election_strategy
        # Simulate active election in progress with sent messages
        with strategy._election_lock:
            strategy._election_in_progress = True
        strategy._count_sent("election")
        strategy._count_sent("ok")

        counts_before = strategy.get_message_counts()
        assert counts_before == {"election": 1, "ok": 1, "coordinator": 0}

        # Attempt start_election while election is active
        strategy.start_election(blocking=True)

        # Confirm counters were NOT reset to 0
        counts_after = strategy.get_message_counts()
        assert counts_after == {"election": 1, "ok": 1, "coordinator": 0}

        # Clear active flag
        with strategy._election_lock:
            strategy._election_in_progress = False

    def test_ring_sequential_elections_isolate_per_election_metrics(self, tmp_path):
        """Test: Ring election consecutive runs isolate per-election metrics on the winner."""
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        nodes = {}
        for nid in [1, 2, 3]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="ring", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # ── Ring Election 1 ──
            nodes[1].election_strategy.start_election(blocking=False)
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if nodes[3].state.role == NodeRole.RECOVERING and nodes[3].state.election_term > 0:
                    break
                time.sleep(0.05)

            time.sleep(0.1)
            m1 = nodes[3].election_strategy.get_last_election_metrics()
            assert m1["coordinator_sent"] == 2
            assert m1["total_logical_sent"] >= 2
            assert m1["election_term"] > 0

            term1 = m1["election_term"]

            # ── Ring Election 2 ──
            nodes[1].election_strategy.start_election(blocking=False)
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if nodes[3].state.election_term > term1 and nodes[3].state.role == NodeRole.RECOVERING:
                    break
                time.sleep(0.05)

            time.sleep(0.1)
            m2 = nodes[3].election_strategy.get_last_election_metrics()
            # Stored metrics for Election 2 contain only Election 2's sent coordinator announcements (2, not 4)
            assert m2["coordinator_sent"] == 2
            assert m2["election_term"] > term1

            # Lifetime coordinator sent is cumulative (4)
            lifetime3 = nodes[3].election_strategy.get_lifetime_message_counts()
            assert lifetime3["coordinator"] == 4

        finally:
            for n in nodes.values():
                n.stop()
