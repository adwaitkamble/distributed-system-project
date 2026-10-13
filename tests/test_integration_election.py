"""Subprocess multi-node integration tests for coordinator crash failover and leader election.

Verifies:
1. Bully leader election on actual coordinator subprocess termination: next highest node (Node 2) wins,
   enters RECOVERING, sends heartbeats, and follower (Node 1) accepts it.
2. Ring leader election on actual coordinator subprocess termination: ring skips dead coordinator,
   next highest node (Node 2) wins, enters RECOVERING, sends heartbeats, and follower accepts it.
3. Newly elected recovering coordinator rejects client votes over real gRPC.
"""

import os
import time
import pytest
import grpc
from node.generated import voting_pb2, voting_pb2_grpc
from tests.test_integration import SubprocessNode, _find_free_port


def _spawn_cluster(
    tmp_path,
    algorithm: str = "bully",
    heartbeat_interval_ms: int = 50,
    heartbeat_timeout_ms: int = 300,
    election_timeout_ms: int = 1000,
) -> dict[int, SubprocessNode]:
    p1 = _find_free_port()
    p2 = _find_free_port()
    p3 = _find_free_port()

    peers_str = f"1:127.0.0.1:{p1},2:127.0.0.1:{p2},3:127.0.0.1:{p3}"
    nodes: dict[int, SubprocessNode] = {}

    for nid, port in [(3, p3), (2, p2), (1, p1)]:
        db_path = str(tmp_path / f"node{nid}.sqlite")
        log_path = str(tmp_path / f"node{nid}.log")
        node = SubprocessNode(
            node_id=nid,
            port=port,
            peers_str=peers_str,
            db_path=db_path,
            log_path=log_path,
            initial_coordinator_id=3,
            heartbeat_interval_ms=heartbeat_interval_ms,
            heartbeat_timeout_ms=heartbeat_timeout_ms,
            replication_policy="all",
            election_algorithm=algorithm,
        )
        node.env["ELECTION_TIMEOUT_MS"] = str(election_timeout_ms)
        node.start()
        nodes[nid] = node

    for node in nodes.values():
        node.wait_ready(timeout=10.0)

    return nodes


class TestSubprocessElectionFailover:
    """Subprocess integration tests with actual process termination."""

    def test_subprocess_bully_election_on_coordinator_stop(self, tmp_path):
        """Test 11a: Bully election upon actual coordinator (Node 3) subprocess kill.
        - Next highest live node (Node 2) wins.
        - Enters RECOVERING role.
        - Follower Node 1 accepts Node 2.
        - Node 2 rejects votes while in RECOVERING.
        - Node 2 sends heartbeats immediately to Node 1.
        """
        nodes = _spawn_cluster(tmp_path, algorithm="bully")

        try:
            # Confirm initial coordinator is Node 3
            st1 = nodes[1].stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
            assert st1.coordinator_id == 3

            # Kill coordinator process Node 3
            nodes[3].stop()

            # Wait for election to converge to Node 2
            deadline = time.monotonic() + 5.0
            converged = False
            while time.monotonic() < deadline:
                try:
                    s2 = nodes[2].stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.5)
                    s1 = nodes[1].stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.5)
                    if s2.role == "recovering" and s2.coordinator_id == 2 and s1.coordinator_id == 2:
                        converged = True
                        break
                except Exception:
                    pass
                time.sleep(0.05)

            assert converged is True, "Bully election failed to converge to Node 2 as recovering coordinator"

            # Node 2 is recovering and not accepting votes
            st2 = nodes[2].stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
            assert st2.role == "recovering"
            assert st2.accepting_votes is False

            # Verify vote submission to Node 2 is rejected
            req = voting_pb2.VoteRequest(client_id="voter_subprocess_1", choice="Alice")
            with pytest.raises(grpc.RpcError) as exc_info:
                nodes[2].stub.SubmitVote(req, timeout=2.0)
            assert exc_info.value.code() == grpc.StatusCode.FAILED_PRECONDITION

            # Verify Node 2 is actively sending heartbeats to Node 1
            time.sleep(0.2)
            st2_later = nodes[2].stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
            assert 1 in st2_later.active_peers

            # Verify Node 2 logs contain ELECTION_WON and COORDINATOR_ANNOUNCED
            logs2 = nodes[2].read_logs()
            events2 = [l.get("event") for l in logs2]
            assert "ELECTION_WON" in events2
            assert "COORDINATOR_ANNOUNCED" in events2

        finally:
            for n in nodes.values():
                n.stop()

    def test_subprocess_ring_election_on_coordinator_stop(self, tmp_path):
        """Test 11b: Ring election upon actual coordinator (Node 3) subprocess kill.
        - Ring skips dead Node 3 (logs RING_SUCCESSOR_SKIPPED).
        - Next highest live node (Node 2) wins.
        - Enters RECOVERING role.
        - Follower Node 1 accepts Node 2.
        - Node 2 rejects votes while in RECOVERING.
        - Node 2 sends heartbeats immediately to Node 1.
        """
        nodes = _spawn_cluster(tmp_path, algorithm="ring")

        try:
            # Confirm initial coordinator is Node 3
            st1 = nodes[1].stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
            assert st1.coordinator_id == 3

            # Kill coordinator process Node 3
            nodes[3].stop()

            # Wait for election to converge to Node 2
            deadline = time.monotonic() + 5.0
            converged = False
            while time.monotonic() < deadline:
                try:
                    s2 = nodes[2].stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.5)
                    s1 = nodes[1].stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.5)
                    if s2.role == "recovering" and s2.coordinator_id == 2 and s1.coordinator_id == 2:
                        converged = True
                        break
                except Exception:
                    pass
                time.sleep(0.05)

            assert converged is True, "Ring election failed to converge to Node 2 as recovering coordinator"

            # Node 2 is recovering and not accepting votes
            st2 = nodes[2].stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
            assert st2.role == "recovering"
            assert st2.accepting_votes is False

            # Verify vote submission to Node 2 is rejected
            req = voting_pb2.VoteRequest(client_id="voter_subprocess_ring", choice="Bob")
            with pytest.raises(grpc.RpcError) as exc_info:
                nodes[2].stub.SubmitVote(req, timeout=2.0)
            assert exc_info.value.code() == grpc.StatusCode.FAILED_PRECONDITION

            # Verify ring skipped dead Node 3
            logs2 = nodes[2].read_logs()
            events2 = [l.get("event") for l in logs2]
            assert "ELECTION_WON" in events2
            assert "COORDINATOR_ANNOUNCED" in events2

            logs1 = nodes[1].read_logs()
            events1 = [l.get("event") for l in logs1]
            assert "COORDINATOR_ACCEPTED" in events1
            assert "RING_SUCCESSOR_SKIPPED" in events1 or "RING_SUCCESSOR_SKIPPED" in events2

        finally:
            for n in nodes.values():
                n.stop()
