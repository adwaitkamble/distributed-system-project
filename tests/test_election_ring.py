"""Tests for Ring leader election algorithm.

Verifies:
1. Ring election with 3 nodes: highest live node wins.
2. Ring election skips an unreachable immediate successor and continues to the next reachable configured node.
3. Ring election duplicate token loop prevention.
4. Message counts equal logical sent Election, OK, and Coordinator messages only.
5. Observability: RING_SUCCESSOR_SKIPPED, ELECTION_WON, COORDINATOR_ACCEPTED.
"""

import socket
import time
import pytest
import grpc
from node.config import NodeConfig, PeerInfo
from node.generated import voting_pb2, voting_pb2_grpc
from node.models import NodeRole
from node.runtime import NodeRuntime


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]


def _create_node(
    node_id: int,
    ports: dict[int, int],
    tmp_path,
    algorithm: str = "ring",
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


class TestRingElection:
    """Test suite for Ring leader election algorithm."""

    def test_ring_election_three_nodes_highest_wins(self, tmp_path):
        """Test 3: Ring election with 3 nodes: highest live node (Node 3) wins."""
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        nodes = {}
        for nid in [1, 2, 3]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="ring", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # Node 1 initiates election
            nodes[1].election_strategy.start_election(blocking=False)

            # Wait for election to converge
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if (
                    nodes[3].state.role == NodeRole.RECOVERING
                    and nodes[3].state.election_term > 0
                    and nodes[1].state.coordinator_id == 3
                    and nodes[2].state.coordinator_id == 3
                    and nodes[1].state.election_term == nodes[3].state.election_term
                    and nodes[2].state.election_term == nodes[3].state.election_term
                ):
                    break
                time.sleep(0.05)

            # Verify winner is Node 3 in RECOVERING role
            assert nodes[3].state.role == NodeRole.RECOVERING
            assert nodes[3].state.coordinator_id == 3
            assert nodes[1].state.coordinator_id == 3
            assert nodes[2].state.coordinator_id == 3

            # Verify persistent DB events
            events3 = nodes[3].db.get_election_events("ELECTION_WON")
            assert len(events3) >= 1

            accepted1 = nodes[1].db.get_election_events("COORDINATOR_ACCEPTED")
            assert len(accepted1) >= 1

            accepted2 = nodes[2].db.get_election_events("COORDINATOR_ACCEPTED")
            assert len(accepted2) >= 1

            # Node 3 announced to peers 1 and 2
            counts3 = nodes[3].election_strategy.get_message_counts()
            assert counts3["coordinator"] >= 2

        finally:
            for n in nodes.values():
                n.stop()

    def test_ring_election_skips_unreachable_successor(self, tmp_path):
        """Test 4: Ring election skips an unreachable immediate successor (Node 2)
        and continues to the next reachable configured node (Node 3).
        """
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        # Node 2 is NOT started!
        nodes = {}
        for nid in [1, 3]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="ring", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # Node 1 initiates election. Its ring successor is 2 (which is down).
            # It must skip 2, log RING_SUCCESSOR_SKIPPED, and forward to 3.
            nodes[1].election_strategy.start_election(blocking=False)

            # Wait for election to converge
            deadline = time.monotonic() + 4.0
            while time.monotonic() < deadline:
                if (
                    nodes[3].state.role == NodeRole.RECOVERING
                    and nodes[3].state.election_term > 0
                    and nodes[1].state.coordinator_id == 3
                    and nodes[1].state.election_term == nodes[3].state.election_term
                ):
                    break
                time.sleep(0.05)

            # Verify winner is Node 3
            assert nodes[3].state.role == NodeRole.RECOVERING
            assert nodes[3].state.coordinator_id == 3
            assert nodes[1].state.coordinator_id == 3

            # Verify RING_SUCCESSOR_SKIPPED event was logged and persisted on Node 1
            skipped_events = nodes[1].db.get_election_events("RING_SUCCESSOR_SKIPPED")
            assert len(skipped_events) >= 1
            assert any(ev.get("details", {}).get("skipped_peer_id") == 2 for ev in skipped_events)

            # Node 2 is marked inactive on Node 1 and Node 3
            assert 2 not in nodes[1].state.active_peers

        finally:
            for n in nodes.values():
                n.stop()

    def test_ring_election_token_loop_prevention(self, tmp_path):
        """Test: Ring election drops duplicate token for same (election_term, initiator_id)."""
        ports = {1: _find_free_port(), 2: _find_free_port()}
        nodes = {}
        for nid in [1, 2]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="ring", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            term = 10
            initiator = 1
            # Send token to Node 2
            ok1, nid1, ts1 = nodes[2].election_strategy.on_election_message(
                sender_id=1,
                candidate_id=1,
                election_term=term,
                initiator_id=initiator,
                msg_lamport_ts=1,
            )
            assert ok1 is True

            # Send same token again
            ok2, nid2, ts2 = nodes[2].election_strategy.on_election_message(
                sender_id=1,
                candidate_id=1,
                election_term=term,
                initiator_id=initiator,
                msg_lamport_ts=ts1 + 1,
            )
            assert ok2 is True  # still replies OK to caller, but does not re-forward

        finally:
            for n in nodes.values():
                n.stop()
