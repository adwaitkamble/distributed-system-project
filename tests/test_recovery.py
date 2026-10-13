"""Tests for Phase 4: State Recovery and SyncLog.

Covers:
- Durable SyncLog storage, schema, and logging
- State-change logging during vote lifecycle (VOTE_INSERTED, VOTE_FINALIZED)
- Log replay on node restart
- Lamport clock restoration from durable state
- State synchronization (SyncLog RPC, missing vote detection, deduplication)
- Deterministic merge ordering by (lamport_ts, origin_node_id, vote_id)
- Recovering coordinator state transition (RECOVERING -> COORDINATOR)
- Full recovery pipeline: State Change -> SyncLog -> Persistence -> Crash/Restart -> Replay -> Restoration -> Sync -> Normal Operation
"""

import os
import time
import pytest
import grpc

from node.config import NodeConfig, PeerInfo
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.lamport import LamportClock
from node.models import InsertResult, NodeRole, RecoverySummary, SyncLogEntry, VoteRecord, VoteStatus
from node.peer_client import PeerClient
from node.recovery import RecoveryManager
from node.replication import ReplicationManager
from node.runtime import NodeRuntime
from node.generated import voting_pb2, voting_pb2_grpc
from tests.test_integration import SubprocessNode, _find_free_port


def _make_config(node_id: int = 1, port: int = 50060, policy: str = "all", auto_recover: bool = False, db_path: str = None) -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        grpc_port=port,
        election_algorithm="bully",
        peers={
            1: PeerInfo(1, "127.0.0.1", 50061),
            2: PeerInfo(2, "127.0.0.1", 50062),
            3: PeerInfo(3, "127.0.0.1", 50063),
        },
        heartbeat_interval_ms=100,
        heartbeat_timeout_ms=500,
        election_timeout_ms=1000,
        replication_policy=policy,
        initial_coordinator_id=3,
        db_host="localhost",
        db_port=3307,
        db_user="root",
        db_password="rootpassword",
        db_name="voting_system",
        use_sqlite=True,
        sqlite_path=db_path,
        log_level="DEBUG",
        candidates=["Alice", "Bob", "Charlie"],
        auto_recover=auto_recover,
    )


class TestSyncLogDatabase:
    """Unit tests for SyncLog schema, append, replay, and Lamport max queries."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "synclog_test.db")
        self.db = DatabaseManager(use_sqlite=True, sqlite_path=self.db_path)
        self.db.initialize()

    def test_sqlite_sync_log_append_and_query(self):
        """Append sync log entries and verify structured retrieval."""
        entry = SyncLogEntry(
            entry_id=0,
            entry_type="VOTE_INSERTED",
            vote_id="vote-100",
            client_id="voter-1",
            origin_node_id=1,
            lamport_ts=10,
            choice="Alice",
            status=VoteStatus.PENDING.value,
            details="Initial pending vote",
            created_at_ms=1000,
        )
        eid = self.db.append_sync_log(entry)
        assert eid > 0

        # Query all
        entries = self.db.get_sync_log()
        assert len(entries) == 1
        assert entries[0].entry_type == "VOTE_INSERTED"
        assert entries[0].vote_id == "vote-100"
        assert entries[0].client_id == "voter-1"
        assert entries[0].origin_node_id == 1
        assert entries[0].lamport_ts == 10
        assert entries[0].choice == "Alice"
        assert entries[0].status == VoteStatus.PENDING.value

        # Query by entry_type filter
        assert len(self.db.get_sync_log(entry_type="VOTE_INSERTED")) == 1
        assert len(self.db.get_sync_log(entry_type="VOTE_FINALIZED")) == 0

    def test_sqlite_sync_log_get_max_lamport_ts(self):
        """Verify get_max_lamport_ts queries across votes, sync_log, and election_log."""
        # Baseline empty DB
        assert self.db.get_max_lamport_ts() == 0

        # Insert a vote with lamport_ts = 15
        vr = VoteRecord(
            vote_id="v1",
            client_id="c1",
            origin_node_id=1,
            lamport_ts=15,
            choice="Alice",
            received_at_ms=1000,
            status=VoteStatus.COMMITTED.value,
        )
        self.db.insert_vote(vr)
        assert self.db.get_max_lamport_ts() >= 15

        # Append a sync_log entry with lamport_ts = 42
        entry = SyncLogEntry(
            entry_id=0,
            entry_type="STATE_RESTORED",
            vote_id=None,
            client_id=None,
            origin_node_id=1,
            lamport_ts=42,
            choice=None,
            status=None,
            details=None,
            created_at_ms=2000,
        )
        self.db.append_sync_log(entry)
        assert self.db.get_max_lamport_ts() == 42

    def test_sqlite_sync_log_replay(self):
        """Verify replay_sync_log returns committed votes and total count."""
        v1 = VoteRecord(
            vote_id="v1",
            client_id="c1",
            origin_node_id=1,
            lamport_ts=10,
            choice="Alice",
            received_at_ms=1000,
            status=VoteStatus.PENDING.value,
        )
        self.db.insert_vote(v1)
        self.db.finalize_vote("v1")

        v2 = VoteRecord(
            vote_id="v2",
            client_id="c2",
            origin_node_id=1,
            lamport_ts=20,
            choice="Bob",
            received_at_ms=1000,
            status=VoteStatus.PENDING.value,
        )
        self.db.insert_vote(v2)
        # v2 left as PENDING (not finalized)

        res = self.db.replay_sync_log()
        assert res["committed_votes"] == 1
        assert res["pending_votes"] == 1
        assert res["sync_log_entries"] >= 2

    def test_sqlite_insert_synced_vote_idempotency(self):
        """Verify insert_synced_vote idempotently inserts or upgrades pending votes."""
        v = VoteRecord(
            vote_id="v-sync-1",
            client_id="c-sync-1",
            origin_node_id=2,
            lamport_ts=35,
            choice="Charlie",
            received_at_ms=1000,
            status=VoteStatus.COMMITTED.value,
        )
        res1 = self.db.insert_synced_vote(v)
        assert res1 == InsertResult.INSERTED

        # Re-inserting the same committed vote returns IDEMPOTENT
        res2 = self.db.insert_synced_vote(v)
        assert res2 == InsertResult.IDEMPOTENT
        assert self.db.count_votes(status=VoteStatus.COMMITTED.value) == 1

        # Test upgrading pending to committed
        v_pending = VoteRecord(
            vote_id="v-sync-2",
            client_id="c-sync-2",
            origin_node_id=1,
            lamport_ts=40,
            choice="Alice",
            received_at_ms=1000,
            status=VoteStatus.PENDING.value,
        )
        self.db.insert_vote(v_pending)
        assert self.db.count_votes(status=VoteStatus.COMMITTED.value) == 1

        # Peer sends committed version
        v_committed = VoteRecord(
            vote_id="v-sync-2",
            client_id="c-sync-2",
            origin_node_id=1,
            lamport_ts=40,
            choice="Alice",
            received_at_ms=1000,
            status=VoteStatus.COMMITTED.value,
        )
        res_upgrade = self.db.insert_synced_vote(v_committed)
        assert res_upgrade == InsertResult.INSERTED
        assert self.db.count_votes(status=VoteStatus.COMMITTED.value) == 2

    def test_vote_lifecycle_sync_log_audit_trail(self):
        """Verify that insert_vote and finalize_vote automatically create sync_log entries."""
        v = VoteRecord(
            vote_id="v-audit-1",
            client_id="voter-audit",
            origin_node_id=1,
            lamport_ts=12,
            choice="Bob",
            received_at_ms=1000,
            status=VoteStatus.PENDING.value,
        )
        self.db.insert_vote(v)
        entries = self.db.get_sync_log()
        assert len(entries) >= 1
        assert any(e.entry_type == "VOTE_INSERTED" and e.vote_id == "v-audit-1" for e in entries)

        self.db.finalize_vote("v-audit-1")
        entries2 = self.db.get_sync_log()
        assert any(e.entry_type == "VOTE_FINALIZED" and e.vote_id == "v-audit-1" for e in entries2)

    def test_mysql_sync_log_live(self):
        """Verify MySQL sync_log table schema and operations on live MySQL if reachable."""
        mysql_host = os.environ.get("TEST_MYSQL_HOST", "localhost")
        mysql_port = int(os.environ.get("TEST_MYSQL_PORT", "3307"))
        mysql_user = os.environ.get("TEST_MYSQL_USER", "root")
        mysql_pass = os.environ.get("TEST_MYSQL_PASSWORD", "votingpass")
        mysql_db = os.environ.get("TEST_MYSQL_DB", "voting_smoke_test")

        if not DatabaseManager.mysql_health_check(mysql_host, mysql_port, mysql_user, mysql_pass, timeout=2):
            pytest.skip(f"Live MySQL not reachable at {mysql_host}:{mysql_port}")

        import mysql.connector
        init_conn = mysql.connector.connect(
            host=mysql_host, port=mysql_port,
            user=mysql_user, password=mysql_pass,
        )
        cur = init_conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS {mysql_db}")
        init_conn.commit()
        init_conn.close()

        db_mysql = DatabaseManager(
            use_sqlite=False,
            mysql_config={
                "host": mysql_host,
                "port": mysql_port,
                "user": mysql_user,
                "password": mysql_pass,
                "database": mysql_db,
            },
        )
        db_mysql.initialize()

        # Test sync_log operations on MySQL
        entry = SyncLogEntry(
            entry_id=0,
            entry_type="VOTE_INSERTED",
            vote_id="v-mysql-1",
            client_id="c-mysql-1",
            origin_node_id=1,
            lamport_ts=99,
            choice="Charlie",
            status=VoteStatus.PENDING.value,
            details="MySQL sync log test",
            created_at_ms=int(time.time() * 1000),
        )
        eid = db_mysql.append_sync_log(entry)
        assert eid > 0
        assert db_mysql.get_max_lamport_ts() >= 99

        entries = db_mysql.get_sync_log(vote_id="v-mysql-1")
        assert len(entries) >= 1
        assert entries[0].choice == "Charlie"
        db_mysql.close()


class TestRecoveryManagerUnit:
    """Unit tests for RecoveryManager logic."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "rec_unit.db")
        self.db = DatabaseManager(use_sqlite=True, sqlite_path=self.db_path)
        self.db.initialize()
        self.clock = LamportClock()
        self.config = _make_config(node_id=2, db_path=self.db_path)
        self.state = CoordinatorState(node_id=2, initial_coordinator_id=3)
        self.recovery_mgr = RecoveryManager(
            node_id=2,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=self.config,
            peer_clients={},
        )

    def test_recover_local_state_restores_clock(self):
        """recover_local_state restores the Lamport clock to the highest timestamp in durable storage."""
        # Populate DB with votes at ts=75
        v = VoteRecord(
            vote_id="v-prior",
            client_id="c-prior",
            origin_node_id=2,
            lamport_ts=75,
            choice="Alice",
            received_at_ms=1000,
            status=VoteStatus.COMMITTED.value,
        )
        self.db.insert_vote(v)

        # Fresh clock starting at 0
        fresh_clock = LamportClock(0)
        mgr = RecoveryManager(
            node_id=2,
            db=self.db,
            clock=fresh_clock,
            state=self.state,
            config=self.config,
            peer_clients={},
        )

        summary = mgr.recover_local_state()
        assert summary.success is True
        assert summary.committed_votes_count == 1
        assert summary.max_lamport_ts >= 75
        assert fresh_clock.value >= 75

        # Check sync_log has LOCAL_STATE_RESTORED entry
        log_entries = self.db.get_sync_log(entry_type="LOCAL_STATE_RESTORED")
        assert len(log_entries) == 1

    def test_handle_sync_request_proto(self):
        """handle_sync_request returns serialized SyncResponse containing committed votes."""
        v = VoteRecord(
            vote_id="v-proto-1",
            client_id="c-proto-1",
            origin_node_id=2,
            lamport_ts=88,
            choice="Bob",
            received_at_ms=1000,
            status=VoteStatus.COMMITTED.value,
        )
        self.db.insert_vote(v)
        self.recovery_mgr.recover_local_state()

        req = voting_pb2.SyncRequest(
            requester_id=1,
            lamport_ts=10,
            election_term=1,
            initiator_id=2,
        )
        resp = self.recovery_mgr.handle_sync_request(req)
        assert resp.node_id == 2
        assert resp.lamport_ts >= 88
        assert len(resp.votes) == 1
        assert resp.votes[0].vote_id == "v-proto-1"
        assert resp.votes[0].choice == "Bob"
        assert resp.votes[0].status == VoteStatus.COMMITTED.value

    def test_deterministic_merge_ordering(self):
        """Verify sorting order by (lamport_ts, origin_node_id, vote_id)."""
        v1 = VoteRecord("v-c", "c1", 2, 10, "Alice", 1000, VoteStatus.COMMITTED.value)
        v2 = VoteRecord("v-a", "c2", 1, 10, "Bob", 1000, VoteStatus.COMMITTED.value)
        v3 = VoteRecord("v-b", "c3", 1, 5, "Charlie", 1000, VoteStatus.COMMITTED.value)
        v4 = VoteRecord("v-d", "c4", 1, 10, "Alice", 1000, VoteStatus.COMMITTED.value)

        votes = [v1, v2, v3, v4]
        sorted_votes = sorted(votes, key=lambda v: v.merge_key)

        expected_order = ["v-b", "v-a", "v-d", "v-c"]
        assert [v.vote_id for v in sorted_votes] == expected_order


class TestRecoveryIntegrationInProcess:
    """In-process integration tests with real gRPC servers and sockets."""

    def test_node_restart_restores_lamport_clock_and_votes(self, tmp_path):
        """State Change -> SyncLog -> Persistence -> Node Crash/Restart -> Log Replay -> State Restoration -> Normal Operation"""
        port = _find_free_port()
        db_path = str(tmp_path / "restart_test.db")
        cfg1 = _make_config(node_id=1, port=port, db_path=db_path)
        cfg1.peers = {1: PeerInfo(1, "127.0.0.1", port)}
        cfg1.initial_coordinator_id = 1

        # Run 1: Start node, cast vote, verify persistence
        rt1 = NodeRuntime(cfg1)
        rt1.start()
        try:
            channel = grpc.insecure_channel(f"127.0.0.1:{port}")
            stub = voting_pb2_grpc.NodeServiceStub(channel)

            resp1 = stub.SubmitVote(
                voting_pb2.VoteRequest(
                    client_id="voter-restart-1",
                    choice="Alice",
                ),
                timeout=2.0,
            )
            assert resp1.success is True
            pre_crash_clock = rt1.clock.value
            assert pre_crash_clock > 0

            status1 = stub.GetResults(voting_pb2.Empty(), timeout=2.0)
            assert status1.total_votes == 1
            assert status1.tally["Alice"] == 1
        finally:
            channel.close()
            rt1.stop()

        # Simulate Crash: rt1 is completely stopped and dereferenced.
        # Run 2: Start new NodeRuntime using the SAME database file
        cfg2 = _make_config(node_id=1, port=port, db_path=db_path)
        cfg2.peers = {1: PeerInfo(1, "127.0.0.1", port)}
        cfg2.initial_coordinator_id = 1
        rt2 = NodeRuntime(cfg2)
        rt2.start()  # executes recover_local_state()

        try:
            # Check clock was restored
            assert rt2.clock.value >= pre_crash_clock

            channel2 = grpc.insecure_channel(f"127.0.0.1:{port}")
            stub2 = voting_pb2_grpc.NodeServiceStub(channel2)

            # Check existing votes restored
            status2 = stub2.GetResults(voting_pb2.Empty(), timeout=2.0)
            assert status2.total_votes == 1
            assert status2.tally["Alice"] == 1

            # Normal Operation: Cast second vote
            resp2 = stub2.SubmitVote(
                voting_pb2.VoteRequest(
                    client_id="voter-restart-2",
                    choice="Bob",
                ),
                timeout=2.0,
            )
            assert resp2.success is True
            assert rt2.clock.value > pre_crash_clock

            status3 = stub2.GetResults(voting_pb2.Empty(), timeout=2.0)
            assert status3.total_votes == 2
            assert status3.tally["Alice"] == 1
            assert status3.tally["Bob"] == 1
        finally:
            channel2.close()
            rt2.stop()

    def test_recovering_coordinator_sync_and_promotion_flow(self, tmp_path):
        """Verify coordinator recovery pulls state from live peer, promotes to COORDINATOR, and resumes voting."""
        p1 = _find_free_port()
        p2 = _find_free_port()
        p3 = _find_free_port()

        db1 = str(tmp_path / "node1.db")
        db2 = str(tmp_path / "node2.db")
        db3 = str(tmp_path / "node3.db")

        peers = {
            1: PeerInfo(1, "127.0.0.1", p1),
            2: PeerInfo(2, "127.0.0.1", p2),
            3: PeerInfo(3, "127.0.0.1", p3),
        }

        cfg1 = _make_config(node_id=1, port=p1, db_path=db1)
        cfg1.peers = dict(peers)
        cfg1.initial_coordinator_id = 3

        cfg2 = _make_config(node_id=2, port=p2, db_path=db2)
        cfg2.peers = dict(peers)
        cfg2.initial_coordinator_id = 3

        cfg3 = _make_config(node_id=3, port=p3, db_path=db3)
        cfg3.peers = dict(peers)
        cfg3.initial_coordinator_id = 3

        rt1 = NodeRuntime(cfg1)
        rt2 = NodeRuntime(cfg2)
        rt3 = NodeRuntime(cfg3)

        rt1.start()
        rt2.start()
        rt3.start()

        ch1 = grpc.insecure_channel(f"127.0.0.1:{p1}")
        ch2 = grpc.insecure_channel(f"127.0.0.1:{p2}")
        ch3 = grpc.insecure_channel(f"127.0.0.1:{p3}")

        stub1 = voting_pb2_grpc.NodeServiceStub(ch1)
        stub2 = voting_pb2_grpc.NodeServiceStub(ch2)
        stub3 = voting_pb2_grpc.NodeServiceStub(ch3)

        try:
            # Cast vote to Node 3 (coordinator) - replicated to Node 1 and Node 2
            resp = stub3.SubmitVote(
                voting_pb2.VoteRequest(
                    client_id="v-peer-1",
                    choice="Alice",
                ),
                timeout=2.0,
            )
            assert resp.success is True

            # Stop coordinator Node 3 (crash)
            rt3.stop()
            rt2.state.mark_peer_inactive(3)
            rt1.state.mark_peer_inactive(3)

            # Node 2 enters election and wins
            rt2.state.win_election(election_term=10, initiator_id=2)
            assert rt2.state.role == NodeRole.RECOVERING

            # While RECOVERING, vote must be rejected with FAILED_PRECONDITION
            with pytest.raises(grpc.RpcError) as exc_info:
                stub2.SubmitVote(
                    voting_pb2.VoteRequest(
                        client_id="v-peer-2",
                        choice="Bob",
                    ),
                    timeout=2.0,
                )
            assert exc_info.value.code() == grpc.StatusCode.FAILED_PRECONDITION
            assert "not_coordinator" in exc_info.value.details()

            # Execute coordinator recovery on Node 2 with surviving peer Node 1
            summary = rt2.recover_coordinator(election_term=10, initiator_id=2, target_peer_ids=[1])
            assert summary.success is True
            assert rt2.state.role == NodeRole.COORDINATOR
            assert rt2.state.is_accepting_votes() is True

            # Now client casts vote to new coordinator Node 2 -> Normal Operation!
            ok_resp = stub2.SubmitVote(
                voting_pb2.VoteRequest(
                    client_id="v-peer-2",
                    choice="Bob",
                ),
                timeout=2.0,
            )
            assert ok_resp.success is True

            res2 = stub2.GetResults(voting_pb2.Empty(), timeout=2.0)
            assert res2.total_votes == 2
            assert res2.tally["Alice"] == 1
            assert res2.tally["Bob"] == 1

            res1 = stub1.GetResults(voting_pb2.Empty(), timeout=2.0)
            assert res1.total_votes == 2
            assert res1.tally["Alice"] == 1
            assert res1.tally["Bob"] == 1
        finally:
            ch1.close()
            ch2.close()
            ch3.close()
            rt1.stop()
            rt2.stop()


class TestRecoverySafetyBlockers:
    """Rigorous regression tests for Blockers 1, 2, and 3."""

    def test_ghost_vote_partial_finalization_never_resurrected(self, tmp_path):
        """Blocker 1 regression test:
        1. Create exact Phase 2 partial-finalization state:
           - coordinator (Node 3): PENDING
           - replica A (Node 2): COMMITTED
           - replica B (Node 1): PENDING
           - client received failure (no successful receipt)
        2. Crash the original coordinator Node 3.
        3. Elect and recover new coordinator Node 2.
        4. Prove the failed client vote is NOT included in the recovered tally and
           does NOT become a successful receipt merely because replica 2 said COMMITTED.
        5. Then prove a genuinely fully accepted vote IS restored correctly after the same type of failover.
        """
        db1_path = str(tmp_path / "bv1.db")
        db2_path = str(tmp_path / "bv2.db")
        db3_path = str(tmp_path / "bv3.db")

        db1 = DatabaseManager(use_sqlite=True, sqlite_path=db1_path)
        db2 = DatabaseManager(use_sqlite=True, sqlite_path=db2_path)
        db3 = DatabaseManager(use_sqlite=True, sqlite_path=db3_path)
        db1.initialize()
        db2.initialize()
        db3.initialize()

        # ── 1. Create exact Phase 2 partial-finalization state ───────
        ghost_vote_id = "voter_ghost:3:10"
        # Node 3 (coordinator): PENDING
        db3.insert_vote(VoteRecord(ghost_vote_id, "voter_ghost", 3, 10, "Alice", 1000, VoteStatus.PENDING.value))
        # Replica A (Node 2): COMMITTED (received FinalizeVote before partial failure)
        db2.insert_vote(VoteRecord(ghost_vote_id, "voter_ghost", 3, 10, "Alice", 1000, VoteStatus.PENDING.value))
        db2.finalize_vote(ghost_vote_id)
        assert db2.get_vote_by_id(ghost_vote_id).status == VoteStatus.COMMITTED.value
        # Replica B (Node 1): PENDING (failed to receive FinalizeVote)
        db1.insert_vote(VoteRecord(ghost_vote_id, "voter_ghost", 3, 10, "Alice", 1000, VoteStatus.PENDING.value))
        assert db1.get_vote_by_id(ghost_vote_id).status == VoteStatus.PENDING.value

        # ── 2. Crash coordinator Node 3 ──────────────────────────────
        db3.close()  # Node 3 is dead

        # ── 3. Elect and recover new coordinator Node 2 ──────────────
        clock2 = LamportClock(10)
        state2 = CoordinatorState(node_id=2, initial_coordinator_id=3, all_peer_ids=[1, 2, 3])
        state2.win_election(election_term=15, initiator_id=2)
        assert state2.role == NodeRole.RECOVERING

        # Mock peer client from Node 2 to live replica Node 1
        from unittest.mock import MagicMock
        mock_client1 = MagicMock()

        # Node 1 returns all its votes via SyncLog (including ghost vote as PENDING)
        def _mock_sync_log(requester_id, election_term, initiator_id, lamport_ts, timeout=2.0):
            all_votes1 = db1.get_all_votes(committed_only=False)
            return voting_pb2.SyncResponse(
                votes=[
                    voting_pb2.VoteRecord(
                        vote_id=v.vote_id, client_id=v.client_id, origin_node_id=v.origin_node_id,
                        lamport_ts=v.lamport_ts, choice=v.choice, received_at_ms=v.received_at_ms,
                        status=v.status,
                    ) for v in all_votes1
                ],
                node_id=1,
                lamport_ts=lamport_ts + 1,
            )
        mock_client1.sync_log.side_effect = _mock_sync_log

        # Replication manager on Node 2 with peer 1
        cfg2 = _make_config(node_id=2, db_path=db2_path, policy="all")
        repl_mgr2 = ReplicationManager(
            node_id=2, db=db2, clock=clock2, state=state2, config=cfg2,
            peer_clients={1: mock_client1},
        )

        recovery_mgr2 = RecoveryManager(
            node_id=2, db=db2, clock=clock2, state=state2, config=cfg2,
            peer_clients={1: mock_client1}, replication_manager=repl_mgr2,
        )

        # ── 4. Execute recovery on Node 2 ────────────────────────────
        summary = recovery_mgr2.recover_coordinator(
            election_term=15, initiator_id=2, target_peer_ids=[1]
        )

        assert summary.success is True
        assert summary.rejected_partial_finalizations_count == 1
        assert summary.accepted_votes_count == 0

        # CRITICAL ASSERTION: The ghost vote is NOT in the recovered tally!
        assert db2.get_tally() == {}
        assert db2.count_votes(status=VoteStatus.COMMITTED.value) == 0

        # And replica Node 2 demoted the vote to PENDING
        rec2 = db2.get_vote_by_id(ghost_vote_id)
        assert rec2 is not None
        assert rec2.status == VoteStatus.PENDING.value

        # ── 5. Prove genuinely fully accepted vote IS restored ─────────
        # Add a genuinely accepted vote that was finalized on BOTH replicas
        genuine_vote_id = "voter_genuine:3:20"
        v_gen = VoteRecord(genuine_vote_id, "voter_genuine", 3, 20, "Bob", 1000, VoteStatus.COMMITTED.value)
        db1.insert_synced_vote(v_gen)
        db2.insert_synced_vote(v_gen)

        summary2 = recovery_mgr2.recover_coordinator(
            election_term=16, initiator_id=2, target_peer_ids=[1]
        )
        assert summary2.success is True
        assert summary2.accepted_votes_count == 1
        assert db2.get_tally() == {"Bob": 1}
        assert db2.count_votes(status=VoteStatus.COMMITTED.value) == 1

        db1.close()
        db2.close()

    def test_recovery_with_synclog_failure_remains_recovering(self, tmp_path):
        """Blocker 2: Recovery with one required peer SyncLog failure remains RECOVERING."""
        db_path = str(tmp_path / "rec_fail1.db")
        db = DatabaseManager(use_sqlite=True, sqlite_path=db_path)
        db.initialize()

        clock = LamportClock()
        state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2])
        state.win_election(election_term=5, initiator_id=1)
        assert state.role == NodeRole.RECOVERING

        from unittest.mock import MagicMock
        mock_client2 = MagicMock()
        # Peer 2 SyncLog RPC returns None (network error / peer dead)
        mock_client2.sync_log.return_value = None

        cfg = _make_config(node_id=1, db_path=db_path, policy="all")
        mgr = RecoveryManager(
            node_id=1, db=db, clock=clock, state=state, config=cfg,
            peer_clients={2: mock_client2},
        )

        summary = mgr.recover_coordinator(election_term=5, initiator_id=1, target_peer_ids=[2])
        assert summary.success is False
        assert "uncontacted or failed peers [2]" in summary.error
        # Must remain in RECOVERING role!
        assert state.role == NodeRole.RECOVERING
        assert state.is_accepting_votes() is False
        db.close()

    def test_recovery_with_repair_failure_remains_recovering(self, tmp_path):
        """Blocker 2: Recovery with one required repair failure remains RECOVERING."""
        db_path = str(tmp_path / "rec_fail2.db")
        db = DatabaseManager(use_sqlite=True, sqlite_path=db_path)
        db.initialize()

        # Add authoritative vote on node 1
        v = VoteRecord("v-auth-1", "v-auth", 1, 10, "Alice", 1000, VoteStatus.COMMITTED.value)
        db.insert_vote(v)
        db.finalize_vote("v-auth-1")

        clock = LamportClock()
        state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2])
        state.win_election(election_term=5, initiator_id=1)
        assert state.role == NodeRole.RECOVERING

        from unittest.mock import MagicMock
        mock_client2 = MagicMock()
        # SyncLog succeeds (empty peer log)
        mock_client2.sync_log.return_value = voting_pb2.SyncResponse(votes=[], node_id=2, lamport_ts=15)
        # But repair replicate_vote fails!
        mock_client2.replicate_vote.return_value = None

        cfg = _make_config(node_id=1, db_path=db_path, policy="all")
        repl_mgr = ReplicationManager(
            node_id=1, db=db, clock=clock, state=state, config=cfg,
            peer_clients={2: mock_client2},
        )
        mgr = RecoveryManager(
            node_id=1, db=db, clock=clock, state=state, config=cfg,
            peer_clients={2: mock_client2}, replication_manager=repl_mgr,
        )

        summary = mgr.recover_coordinator(election_term=5, initiator_id=1, target_peer_ids=[2])
        assert summary.success is False
        assert state.role == NodeRole.RECOVERING
        assert state.is_accepting_votes() is False
        db.close()

    def test_recovery_policy_all_vs_majority(self, tmp_path):
        """Blocker 2: Test both 'all' and 'majority' policy behavior explicitly.
        Cluster has 3 nodes (1, 2, 3). Node 2 is healthy, Node 3 is down.
        - Under 'all': fails, remains RECOVERING.
        - Under 'majority': succeeds (1 self + 1 peer = 2/3), promotes to COORDINATOR.
        """
        db_path = str(tmp_path / "rec_policy.db")
        db = DatabaseManager(use_sqlite=True, sqlite_path=db_path)
        db.initialize()

        clock = LamportClock()
        from unittest.mock import MagicMock
        mock_client2 = MagicMock()
        mock_client2.sync_log.return_value = voting_pb2.SyncResponse(votes=[], node_id=2, lamport_ts=20)

        mock_client3 = MagicMock()
        mock_client3.sync_log.return_value = None  # Node 3 is down

        peer_clients = {2: mock_client2, 3: mock_client3}

        # ── Test under 'all' policy ──────────────────────────────────
        state_all = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3])
        state_all.win_election(election_term=5, initiator_id=1)
        cfg_all = _make_config(node_id=1, db_path=db_path, policy="all")
        mgr_all = RecoveryManager(
            node_id=1, db=db, clock=clock, state=state_all, config=cfg_all,
            peer_clients=peer_clients,
        )
        res_all = mgr_all.recover_coordinator(election_term=5, initiator_id=1, target_peer_ids=[2, 3])
        assert res_all.success is False
        assert state_all.role == NodeRole.RECOVERING

        # ── Test under 'majority' policy ─────────────────────────────
        state_maj = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3])
        state_maj.win_election(election_term=5, initiator_id=1)
        cfg_maj = _make_config(node_id=1, db_path=db_path, policy="majority")
        mgr_maj = RecoveryManager(
            node_id=1, db=db, clock=clock, state=state_maj, config=cfg_maj,
            peer_clients=peer_clients,
        )
        res_maj = mgr_maj.recover_coordinator(election_term=5, initiator_id=1, target_peer_ids=[2, 3])
        assert res_maj.success is True
        assert state_maj.role == NodeRole.COORDINATOR
        assert state_maj.is_accepting_votes() is True

        db.close()

    def test_follower_catch_up_runtime_api_no_type_error(self, tmp_path):
        """Blocker 3: Confirm NodeRuntime.sync_with_cluster() catches up a lagging follower without raising TypeError."""
        p1 = _find_free_port()
        p2 = _find_free_port()

        db1 = str(tmp_path / "lag_node1.db")
        db2 = str(tmp_path / "lag_node2.db")

        cfg1 = _make_config(node_id=1, port=p1, db_path=db1)
        cfg1.peers = {1: PeerInfo(1, "127.0.0.1", p1), 2: PeerInfo(2, "127.0.0.1", p2)}
        cfg1.initial_coordinator_id = 2

        cfg2 = _make_config(node_id=2, port=p2, db_path=db2)
        cfg2.peers = {1: PeerInfo(1, "127.0.0.1", p1), 2: PeerInfo(2, "127.0.0.1", p2)}
        cfg2.initial_coordinator_id = 2

        rt1 = NodeRuntime(cfg1)
        rt2 = NodeRuntime(cfg2)
        rt1.start()
        rt2.start()

        ch2 = grpc.insecure_channel(f"127.0.0.1:{p2}")
        stub2 = voting_pb2_grpc.NodeServiceStub(ch2)

        try:
            # Commit a vote directly to coordinator 2 (without replicating to 1)
            v = VoteRecord("v-lag-1", "voter-lag", 2, 5, "Charlie", 1000, VoteStatus.COMMITTED.value)
            rt2.db.insert_synced_vote(v)
            assert rt2.db.count_votes(status=VoteStatus.COMMITTED.value) == 1
            assert rt1.db.count_votes(status=VoteStatus.COMMITTED.value) == 0

            # Follower 1 catches up using NodeRuntime.sync_with_cluster(coordinator_id=2)
            summary = rt1.sync_with_cluster(coordinator_id=2, timeout=2.0)
            assert summary.success is True
            assert summary.votes_synced_count == 1
            assert rt1.db.count_votes(status=VoteStatus.COMMITTED.value) == 1
            assert rt1.db.get_tally() == {"Charlie": 1}

            # Also test positional argument call: rt1.sync_with_cluster(2)
            summary_pos = rt1.sync_with_cluster(2)
            assert summary_pos.success is True
        finally:
            ch2.close()
            rt1.stop()
            rt2.stop()



class TestRecoverySubprocess:
    """Subprocess integration tests with actual process termination and recovery."""

    def test_subprocess_coordinator_failover_recovery_and_normal_operation(self, tmp_path):
        """Full end-to-end failover with AUTO_RECOVER=true:
        1. 3 subprocess nodes start with Node 3 as coordinator.
        2. Client casts vote to Node 3; replicated to 1 and 2.
        3. Node 3 is terminated (simulating crash).
        4. Heartbeat timeout triggers election; Node 2 wins.
        5. Node 2 auto-recovers (SyncLog from Node 1, promotes to COORDINATOR).
        6. Client casts new vote to Node 2 -> Vote accepted!
        7. Normal operation confirmed on both live nodes.
        """
        p1 = _find_free_port()
        p2 = _find_free_port()
        p3 = _find_free_port()

        peers_str = f"1:127.0.0.1:{p1},2:127.0.0.1:{p2},3:127.0.0.1:{p3}"
        nodes: dict[int, SubprocessNode] = {}

        for nid, port in [(3, p3), (2, p2), (1, p1)]:
            db_path = str(tmp_path / f"sub_node{nid}.sqlite")
            log_path = str(tmp_path / f"sub_node{nid}.log")
            node = SubprocessNode(
                node_id=nid,
                port=port,
                peers_str=peers_str,
                db_path=db_path,
                log_path=log_path,
                initial_coordinator_id=3,
                heartbeat_interval_ms=50,
                heartbeat_timeout_ms=800,
                replication_policy="all",
                election_algorithm="bully",
            )
            node.env["ELECTION_TIMEOUT_MS"] = "1000"
            node.env["AUTO_RECOVER"] = "true"
            node.start()
            nodes[nid] = node

        try:
            for node in nodes.values():
                node.wait_ready(timeout=10.0)

            # Confirm initial coordinator is Node 3
            st1 = nodes[1].stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
            assert st1.coordinator_id == 3
            st3 = nodes[3].stub.GetClusterStatus(voting_pb2.Empty(), timeout=2.0)
            assert st3.coordinator_id == 3 and st3.role.lower() == "coordinator"

            # Cast first vote to Node 3
            v1_resp = nodes[3].stub.SubmitVote(
                voting_pb2.VoteRequest(
                    client_id="voter-failover-1",
                    choice="Alice",
                ),
                timeout=3.0,
            )
            assert v1_resp.success is True

            # Kill coordinator process Node 3
            nodes[3].stop()

            # Wait for Node 2 to win election, auto-recover, and become COORDINATOR
            deadline = time.monotonic() + 8.0
            recovered_coordinator = False
            while time.monotonic() < deadline:
                try:
                    st2 = nodes[2].stub.GetClusterStatus(voting_pb2.Empty(), timeout=0.5)
                    if st2.coordinator_id == 2 and st2.role.lower() == "coordinator" and st2.accepting_votes:
                        recovered_coordinator = True
                        break
                except Exception:
                    pass
                time.sleep(0.1)

            assert recovered_coordinator, "Node 2 failed to auto-recover to coordinator within deadline"

            # Cast second vote directly to Node 2 (Normal Operation)
            v2_resp = nodes[2].stub.SubmitVote(
                voting_pb2.VoteRequest(
                    client_id="voter-failover-2",
                    choice="Bob",
                ),
                timeout=3.0,
            )
            assert v2_resp.success is True
            assert v2_resp.error == ""

            # Verify final tallies on both live nodes
            res2 = nodes[2].stub.GetResults(voting_pb2.Empty(), timeout=2.0)
            res1 = nodes[1].stub.GetResults(voting_pb2.Empty(), timeout=2.0)

            assert res2.total_votes == 2
            assert res2.tally["Alice"] == 1
            assert res2.tally["Bob"] == 1

            assert res1.total_votes == 2
            assert res1.tally["Alice"] == 1
            assert res1.tally["Bob"] == 1
        finally:
            for node in nodes.values():
                node.stop()
