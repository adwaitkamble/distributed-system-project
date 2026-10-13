"""Tests for Bully leader election algorithm.

Verifies:
1. Bully election with 3 nodes: highest live node wins.
2. Bully election with highest configured node unavailable: next-highest live node wins.
3. Message counts equal logical sent Election, OK, and Coordinator messages only.
4. Election duration and observability records.
"""

import time
import socket
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
    algorithm: str = "bully",
    initial_coordinator_id: int = 3,
    heartbeat_interval_ms: int = 50,
    heartbeat_timeout_ms: int = 1500,
    election_timeout_ms: int = 800,
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


class TestBullyElection:
    """Test suite for Bully leader election."""

    def test_bully_election_three_nodes_highest_wins(self, tmp_path):
        """Test 1: Bully election with 3 live nodes. Highest live node (Node 3) wins."""
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        nodes = {}
        for nid in [3, 2, 1]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="bully", initial_coordinator_id=3)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # Node 1 starts election
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

            # Verify persistent DB events on Node 3
            won_events = nodes[3].db.get_election_events("ELECTION_WON")
            assert len(won_events) >= 1

            announced_events = nodes[3].db.get_election_events("COORDINATOR_ANNOUNCED")
            assert len(announced_events) >= 1

            # Verify message counts on Node 3
            counts3 = nodes[3].election_strategy.get_message_counts()
            assert counts3["coordinator"] >= 2  # announced to peers 1 and 2

        finally:
            for n in nodes.values():
                n.stop()

    def test_bully_election_highest_node_down_next_highest_wins(self, tmp_path):
        """Test 2: Bully election with highest configured node (Node 3) down.
        Next highest live node (Node 2) wins.
        """
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        # Do not start Node 3!
        nodes = {}
        for nid in [2, 1]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="bully", initial_coordinator_id=3)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # Node 1 initiates election
            nodes[1].election_strategy.start_election(blocking=False)

            # Wait for election to converge
            deadline = time.monotonic() + 3.0
            while time.monotonic() < deadline:
                if nodes[2].state.role in (NodeRole.RECOVERING, NodeRole.COORDINATOR):
                    if nodes[1].state.coordinator_id == 2:
                        break
                time.sleep(0.05)

            # Verify winner is Node 2
            assert nodes[2].state.role in (NodeRole.RECOVERING, NodeRole.COORDINATOR)
            assert nodes[2].state.coordinator_id == 2
            assert nodes[1].state.coordinator_id == 2

            # Node 3 is inactive in Node 2's state
            assert 3 not in nodes[2].state.active_peers

            # Verify Node 2 logged ELECTION_WON
            events2 = nodes[2].db.get_election_events("ELECTION_WON")
            assert len(events2) >= 1

            # Verify message counts: Node 1 sent election to 2 and 3; Node 2 sent OK to 1, election to 3, announced to 1
            counts1 = nodes[1].election_strategy.get_message_counts()
            assert counts1["election"] >= 1  # sent election to 2 (and possibly 3)

            counts2 = nodes[2].election_strategy.get_message_counts()
            assert counts2["ok"] >= 1  # sent OK reply to 1
            assert counts2["coordinator"] >= 1  # announced to reachable peer 1

        finally:
            for n in nodes.values():
                n.stop()

    def test_bully_election_metrics_and_message_counts(self, tmp_path):
        """Test 10: Logical message counts equal sent Election, OK, Coordinator only."""
        ports = {1: _find_free_port(), 2: _find_free_port(), 3: _find_free_port()}
        nodes = {}
        for nid in [1, 2, 3]:
            nodes[nid] = _create_node(nid, ports, tmp_path, algorithm="bully", initial_coordinator_id=1)
            nodes[nid].start()

        _wait_cluster_ready(nodes)

        try:
            # Node 3 initiates directly
            nodes[3].election_strategy.start_election(blocking=True)

            # Node 3 is highest node, so it sends 0 election messages to higher nodes
            # It announces coordinator to peers 1 and 2 (2 coordinator messages)
            counts3 = nodes[3].election_strategy.get_message_counts()
            assert counts3["election"] == 0
            assert counts3["ok"] == 0
            assert counts3["coordinator"] == 2

            metrics = nodes[3].election_strategy.get_last_election_metrics()
            assert metrics["duration_ms"] >= 0.0
            assert metrics["coordinator_sent"] == 2
            assert metrics["election_sent"] == 0
            assert metrics["ok_sent"] == 0

        finally:
            for n in nodes.values():
                n.stop()
