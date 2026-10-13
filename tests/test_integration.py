"""Subprocess-based multi-process integration tests for Phase 2.

Launches 3 independent OS processes running node.main with:
- real gRPC channels over loopback ports
- isolated SQLite database files per process (node1.sqlite, node2.sqlite, node3.sqlite)
- heartbeat broadcaster and failure detection
- replication-before-ack (INV-4)
- rollback uncommitted vote on replication failure under 'all' policy (INV-5)
- idempotent replication replay (INV-6)
- follower redirection (INV-3)
"""

import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from typing import Generator
import pytest
import grpc

from node.config import PeerInfo
from node.generated import voting_pb2
from node.generated import voting_pb2_grpc

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_node_ready(port: int, timeout: float = 8.0) -> tuple[voting_pb2_grpc.NodeServiceStub, grpc.Channel]:
    """Poll NodeService.GetClusterStatus until node responds or timeout expires."""
    channel = grpc.insecure_channel(f"127.0.0.1:{port}")
    stub = voting_pb2_grpc.NodeServiceStub(channel)
    deadline = time.monotonic() + timeout
    last_err = None
    while time.monotonic() < deadline:
        try:
            status = stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.4)
            if status.this_node_id > 0:
                return stub, channel
        except Exception as e:
            last_err = e
            time.sleep(0.05)
    channel.close()
    raise TimeoutError(f"Node on 127.0.0.1:{port} failed to become ready within {timeout}s: {last_err}")


class SubprocessNode:
    """Manages an independent OS process running node.main with dedicated SQLite DB and port."""

    def __init__(
        self,
        node_id: int,
        port: int,
        peers_str: str,
        db_path: str,
        log_path: str,
        initial_coordinator_id: int = 3,
        heartbeat_interval_ms: int = 50,
        heartbeat_timeout_ms: int = 250,
        replication_policy: str = "all",
        election_algorithm: str = "bully",
    ) -> None:
        self.node_id = node_id
        self.port = port
        self.db_path = db_path
        self.log_path = log_path
        self.initial_coordinator_id = initial_coordinator_id

        # Isolated environment for this process
        env = os.environ.copy()
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["PYTHONUNBUFFERED"] = "1"
        env["NODE_ID"] = str(node_id)
        env["GRPC_PORT"] = str(port)
        env["PEERS"] = peers_str
        env["INITIAL_COORDINATOR_ID"] = str(initial_coordinator_id)
        env["USE_SQLITE"] = "true"
        env["SQLITE_PATH"] = str(db_path)
        env["HEARTBEAT_INTERVAL_MS"] = str(heartbeat_interval_ms)
        env["HEARTBEAT_TIMEOUT_MS"] = str(heartbeat_timeout_ms)
        env["ELECTION_TIMEOUT_MS"] = "1000"
        env["REPLICATION_POLICY"] = replication_policy
        env["ELECTION_ALGORITHM"] = election_algorithm
        env["LOG_LEVEL"] = "DEBUG"
        self.env = env

        self.process: subprocess.Popen | None = None
        self.log_file = None
        self.channel: grpc.Channel | None = None
        self.stub: voting_pb2_grpc.NodeServiceStub | None = None

    def start(self) -> None:
        """Launch the node subprocess redirecting stdout/stderr to dedicated log file."""
        self.log_file = open(self.log_path, "w", encoding="utf-8")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "node.main"],
            cwd=str(PROJECT_ROOT),
            env=self.env,
            stdout=self.log_file,
            stderr=subprocess.STDOUT,
        )

    def wait_ready(self, timeout: float = 8.0) -> None:
        """Wait until gRPC service responds."""
        self.stub, self.channel = _wait_for_node_ready(self.port, timeout=timeout)

    def stop(self, timeout: float = 3.0) -> None:
        """Gracefully terminate subprocess and release gRPC channels & log files."""
        if self.channel:
            try:
                self.channel.close()
            except Exception:
                pass
            self.channel = None
            self.stub = None

        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=2.0)
            self.process = None

        if self.log_file:
            try:
                self.log_file.close()
            except Exception:
                pass
            self.log_file = None

    def read_logs(self) -> list[dict]:
        """Read and parse structured JSON log lines from the node log file."""
        lines = []
        if os.path.exists(self.log_path):
            with open(self.log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("{") and line.endswith("}"):
                        try:
                            lines.append(json.loads(line))
                        except Exception:
                            pass
        return lines

    def query_votes_sqlite(self) -> list[dict]:
        """Directly query the isolated SQLite database file for this node."""
        if not os.path.exists(self.db_path):
            return []
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT vote_id, client_id, origin_node_id, lamport_ts, choice, status FROM votes")
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
        return rows


@pytest.fixture
def cluster_3nodes(tmp_path) -> Generator[dict[int, SubprocessNode], None, None]:
    """Fixture providing a live 3-node multi-process cluster.

    Processes:
    - Node 1: Follower, listening on port p1, isolated DB node1.sqlite
    - Node 2: Follower, listening on port p2, isolated DB node2.sqlite
    - Node 3: Coordinator (initial_coordinator_id=3), listening on port p3, isolated DB node3.sqlite
    """
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
            heartbeat_interval_ms=50,
            heartbeat_timeout_ms=250,
            replication_policy="all",
        )
        node.start()
        nodes[nid] = node

    # Await all nodes in parallel
    for node in nodes.values():
        node.wait_ready(timeout=10.0)

    yield nodes

    # Teardown: terminate all subprocesses
    for node in nodes.values():
        node.stop()


class TestSubprocessCluster:
    """Subprocess-based multi-process integration tests with real gRPC and SQLite."""

    def test_normal_three_node_replication(self, cluster_3nodes):
        """Scenario 1: Submit vote to coordinator; verify it exists once in all 3 SQLite DBs."""
        node3 = cluster_3nodes[3]
        stub3 = node3.stub

        req = voting_pb2.VoteRequest(client_id="voter_alice", choice="Alice")
        resp = stub3.SubmitVote(req, timeout=4.0)

        assert resp.success is True
        assert resp.vote_id.startswith("voter_alice:3:")
        assert resp.error == ""

        # Verify the vote exists exactly once in each node's separate SQLite database file
        for nid in [1, 2, 3]:
            node = cluster_3nodes[nid]
            votes = node.query_votes_sqlite()
            assert len(votes) == 1, f"Node {nid} database {node.db_path} has {len(votes)} votes, expected 1"
            assert votes[0]["vote_id"] == resp.vote_id
            assert votes[0]["client_id"] == "voter_alice"
            assert votes[0]["choice"] == "Alice"

            # Check GetResults RPC on each node reflects tally
            res = node.stub.GetResults(voting_pb2.Empty(), timeout=2.0)
            assert res.total_votes == 1
            assert res.tally["Alice"] == 1

        # Verify structured logs in Coordinator Node 3
        logs = node3.read_logs()
        events = [l.get("event") for l in logs]
        assert "REPLICATION_STARTED" in events
        assert "REPLICATION_SUCCEEDED" in events
        assert "VOTE_ACCEPTED" in events

    def test_idempotent_replay(self, cluster_3nodes):
        """Scenario 2: Send the same vote multiple times; verify no duplicate record is created."""
        node3 = cluster_3nodes[3]
        node1 = cluster_3nodes[1]

        # First: submit vote normally
        resp = node3.stub.SubmitVote(
            voting_pb2.VoteRequest(client_id="voter_repeat", choice="Bob"),
            timeout=4.0,
        )
        assert resp.success is True

        # Now: send identical ReplicateVote RPC directly to Node 1 multiple times
        replay_req = voting_pb2.VoteRecord(
            vote_id=resp.vote_id,
            client_id="voter_repeat",
            origin_node_id=3,
            lamport_ts=resp.lamport_ts,
            choice="Bob",
            received_at_ms=1700000000000,
        )

        for _ in range(3):
            ack = node1.stub.ReplicateVote(replay_req, timeout=2.0)
            assert ack.success is True
            assert ack.error == ""

        # Verify Node 1 SQLite DB still has exactly 1 record
        node1_votes = node1.query_votes_sqlite()
        assert len(node1_votes) == 1
        assert node1_votes[0]["client_id"] == "voter_repeat"

        # Verify tally on all nodes is still exactly 1
        for nid in [1, 2, 3]:
            res = cluster_3nodes[nid].stub.GetResults(voting_pb2.Empty(), timeout=2.0)
            assert res.total_votes == 1
            assert res.tally["Bob"] == 1

        # Verify IDEMPOTENT_REPLAY log event in Node 1
        node1_logs = node1.read_logs()
        events = [l.get("event") for l in node1_logs]
        assert "IDEMPOTENT_REPLAY" in events

    def test_failed_replica_under_all_policy(self, cluster_3nodes):
        """Scenario 3: One replica unavailable; under 'all' policy, vote fails and stays PENDING.
        No tally includes it. Different choice is rejected. Retry with same choice succeeds."""
        node3 = cluster_3nodes[3]
        node2 = cluster_3nodes[2]
        node1 = cluster_3nodes[1]

        # Stop replica Node 1
        node1.stop()

        # Submit vote to Coordinator Node 3
        req = voting_pb2.VoteRequest(client_id="voter_unreachable", choice="Charlie")
        resp = node3.stub.SubmitVote(req, timeout=5.0)

        # Under 'all' policy, replication must fail
        assert resp.success is False
        assert "replication failed" in resp.error

        # CRITICAL: Coordinator and reachable replica retain the vote as PENDING (NOT deleted)
        node3_votes = node3.query_votes_sqlite()
        assert len(node3_votes) == 1
        assert node3_votes[0]["status"] == "PENDING"
        assert node3_votes[0]["choice"] == "Charlie"

        node2_votes = node2.query_votes_sqlite()
        assert len(node2_votes) == 1
        assert node2_votes[0]["status"] == "PENDING"

        # Neither coordinator nor replica counts the pending vote in results
        res3 = node3.stub.GetResults(voting_pb2.Empty(), timeout=2.0)
        assert res3.total_votes == 0
        assert res3.tally == {}

        res2 = node2.stub.GetResults(voting_pb2.Empty(), timeout=2.0)
        assert res2.total_votes == 0
        assert res2.tally == {}

        # Submitting different choice while pending is rejected
        conflict_req = voting_pb2.VoteRequest(client_id="voter_unreachable", choice="Alice")
        conflict_resp = node3.stub.SubmitVote(conflict_req, timeout=5.0)
        assert conflict_resp.success is False
        assert "different choice" in conflict_resp.error

        # Coordinator marked unavailable peer 1 as inactive
        status = node3.stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
        assert 1 not in status.active_peers
        assert 2 in status.active_peers

        # Client retries with SAME choice: now active peers is only {2}, so 'all' policy succeeds
        retry_resp = node3.stub.SubmitVote(req, timeout=5.0)
        assert retry_resp.success is True
        assert retry_resp.vote_id == resp.vote_id

        # Vote is now COMMITTED in both node 3 and node 2
        node3_votes_committed = node3.query_votes_sqlite()
        assert len(node3_votes_committed) == 1
        assert node3_votes_committed[0]["status"] == "COMMITTED"

        node2_votes_committed = node2.query_votes_sqlite()
        assert len(node2_votes_committed) == 1
        assert node2_votes_committed[0]["status"] == "COMMITTED"

        # Tally now reflects the vote
        res3_final = node3.stub.GetResults(voting_pb2.Empty(), timeout=2.0)
        assert res3_final.total_votes == 1
        assert res3_final.tally["Charlie"] == 1

        res2_final = node2.stub.GetResults(voting_pb2.Empty(), timeout=2.0)
        assert res2_final.total_votes == 1
        assert res2_final.tally["Charlie"] == 1

        # Verify structured log in Node 3 indicates REPLICATION_FAILED and PEER_UNAVAILABLE
        logs = node3.read_logs()
        events = [l.get("event") for l in logs]
        assert "REPLICATION_FAILED" in events
        assert "PEER_UNAVAILABLE" in events

    def test_heartbeat_receipt(self, cluster_3nodes):
        """Scenario 4: Verify heartbeat messages are sent and acknowledged over real gRPC."""
        node3 = cluster_3nodes[3]

        # Allow time for multiple heartbeat rounds (interval=50ms)
        time.sleep(0.25)

        # Check Coordinator's view of active peers
        status = node3.stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
        assert status.coordinator_id == 3
        assert sorted(status.active_peers) == [1, 2]

        # Check logs for HEARTBEAT_SENT and HEARTBEAT_ACKNOWLEDGED
        logs = node3.read_logs()
        events = [l.get("event") for l in logs]
        assert "HEARTBEAT_SENT" in events
        assert "HEARTBEAT_ACKNOWLEDGED" in events

    def test_heartbeat_timeout(self, cluster_3nodes):
        """Scenario 5: Stop one follower; verify coordinator detects timeout and updates liveness."""
        node3 = cluster_3nodes[3]
        node1 = cluster_3nodes[1]

        # Confirm both peers initially healthy
        status1 = node3.stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
        assert sorted(status1.active_peers) == [1, 2]

        # Stop follower Node 1
        node1.stop()

        # Wait beyond the 250ms timeout threshold (poll with deadline)
        deadline = time.monotonic() + 2.0
        updated = False
        while time.monotonic() < deadline:
            st = node3.stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.5)
            if 1 not in st.active_peers and 2 in st.active_peers:
                updated = True
                break
            time.sleep(0.05)

        assert updated is True, "Coordinator did not mark Node 1 inactive after heartbeat timeout"

        # Check Coordinator logs for HEARTBEAT_TIMEOUT or PEER_UNAVAILABLE
        logs = node3.read_logs()
        peer1_failures = [
            l for l in logs
            if l.get("event") in ("HEARTBEAT_TIMEOUT", "PEER_UNAVAILABLE")
            and l.get("data", {}).get("peer_id") == 1
        ]
        assert len(peer1_failures) > 0, "No HEARTBEAT_TIMEOUT/PEER_UNAVAILABLE event logged for peer 1"

    def test_follower_rejects_vote_with_redirect_hint(self, cluster_3nodes):
        """Follower rejects direct vote submission with FAILED_PRECONDITION: not_coordinator:3."""
        node1 = cluster_3nodes[1]
        req = voting_pb2.VoteRequest(client_id="voter_direct", choice="Alice")
        with pytest.raises(grpc.RpcError) as exc_info:
            node1.stub.SubmitVote(req, timeout=2.0)

        assert exc_info.value.code() == grpc.StatusCode.FAILED_PRECONDITION
        assert "not_coordinator:3" in exc_info.value.details()

    def test_coordinator_death_triggers_timeout_latch_once(self, cluster_3nodes):
        """Scenario 6: Genuine subprocess coordinator crash detection.
        - Stop the actual coordinator process.
        - Followers detect loss through monotonic heartbeat timeout.
        - The timeout latch causes only ONE failure trigger per incident.
        - No repeated triggers occur while the coordinator remains unavailable.
        """
        node3 = cluster_3nodes[3]
        node1 = cluster_3nodes[1]
        node2 = cluster_3nodes[2]

        # Allow initial heartbeats to flow and establish liveness
        time.sleep(0.25)

        # Confirm followers see Node 3 as coordinator
        st1 = node1.stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
        assert st1.coordinator_id == 3
        st2 = node2.stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
        assert st2.coordinator_id == 3

        # ── Kill the actual coordinator process ───────────────────────
        node3.stop()

        # Wait past the heartbeat timeout threshold (250ms timeout)
        time.sleep(0.6)

        # Verify follower Node 1 detected coordinator loss
        logs1 = node1.read_logs()
        events1 = [l.get("event") for l in logs1]
        timeout_events1 = [l for l in logs1 if l.get("event") == "HEARTBEAT_TIMEOUT" and "coordinator_id" in l.get("data", {})]
        trigger_events1 = [e for e in events1 if e == "COORDINATOR_TIMEOUT_TRIGGERED"]
        assert len(timeout_events1) == 1, f"Expected 1 monitor HEARTBEAT_TIMEOUT in node 1, got {len(timeout_events1)}"
        assert len(trigger_events1) == 1, f"Expected 1 COORDINATOR_TIMEOUT_TRIGGERED in node 1, got {len(trigger_events1)}"

        # Verify follower Node 2 detected coordinator loss
        logs2 = node2.read_logs()
        events2 = [l.get("event") for l in logs2]
        timeout_events2 = [l for l in logs2 if l.get("event") == "HEARTBEAT_TIMEOUT" and "coordinator_id" in l.get("data", {})]
        trigger_events2 = [e for e in events2 if e == "COORDINATOR_TIMEOUT_TRIGGERED"]
        assert len(timeout_events2) == 1, f"Expected 1 monitor HEARTBEAT_TIMEOUT in node 2, got {len(timeout_events2)}"
        assert len(trigger_events2) == 1, f"Expected 1 COORDINATOR_TIMEOUT_TRIGGERED in node 2, got {len(trigger_events2)}"

        # Wait additional time (~600ms) with coordinator still dead
        time.sleep(0.6)

        # Confirm NO repeated triggers occurred while coordinator remained unavailable
        logs1_later = node1.read_logs()
        events1_later = [l.get("event") for l in logs1_later]
        monitor_timeouts1_later = [l for l in logs1_later if l.get("event") == "HEARTBEAT_TIMEOUT" and "coordinator_id" in l.get("data", {})]
        assert len(monitor_timeouts1_later) == 1
        assert events1_later.count("COORDINATOR_TIMEOUT_TRIGGERED") == 1

        logs2_later = node2.read_logs()
        events2_later = [l.get("event") for l in logs2_later]
        monitor_timeouts2_later = [l for l in logs2_later if l.get("event") == "HEARTBEAT_TIMEOUT" and "coordinator_id" in l.get("data", {})]
        assert len(monitor_timeouts2_later) == 1
        assert events2_later.count("COORDINATOR_TIMEOUT_TRIGGERED") == 1

