"""Tests for log replication: fan-out, replica ingestion, idempotency, and rollback.

Covers:
- INV-4: Replication-before-acknowledgment
- INV-5: Rollback uncommitted vote on quorum failure (no phantom ACKs)
- INV-6: Idempotent replication replay
- Policy enforcement: 'all' vs 'majority'
"""

from unittest.mock import MagicMock
import pytest

from node.config import NodeConfig, PeerInfo
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.lamport import LamportClock
from node.models import InsertResult, NodeRole, VoteRecord
from node.replication import ReplicationManager
from node.vote_service import VoteService
from node.generated import voting_pb2


def _make_config(node_id: int = 1, policy: str = "all") -> NodeConfig:
    return NodeConfig(
        node_id=node_id,
        grpc_port=50050 + node_id,
        election_algorithm="bully",
        peers={
            1: PeerInfo(1, "localhost", 50051),
            2: PeerInfo(2, "localhost", 50052),
            3: PeerInfo(3, "localhost", 50053),
        },
        heartbeat_interval_ms=1000,
        heartbeat_timeout_ms=3000,
        election_timeout_ms=5000,
        replication_policy=policy,
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


class TestReplicaIngestion:
    """Tests for replica-side ingestion via ReplicationManager.handle_replicate_vote."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "replica_test.db")
        self.db = DatabaseManager(use_sqlite=True, sqlite_path=self.db_path)
        self.db.initialize()
        self.clock = LamportClock()
        self.config = _make_config(node_id=2)
        self.state = CoordinatorState(node_id=2, initial_coordinator_id=1)
        self.repl_mgr = ReplicationManager(
            node_id=2,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=self.config,
            peer_clients={},
        )
        yield
        self.db.close()

    def test_normal_replica_ingestion(self):
        """Replica successfully ingests a replicated pending vote and updates Lamport clock."""
        req = voting_pb2.VoteRecord(
            vote_id="voter1:1:5",
            client_id="voter1",
            origin_node_id=1,
            lamport_ts=5,
            choice="Alice",
            received_at_ms=1700000000000,
        )

        success, err, out_ts = self.repl_mgr.handle_replicate_vote(req)
        assert success is True
        assert err == ""
        # Lamport receive rule: max(0, 5) + 1 = 6, then tick() for ack = 7
        assert out_ts >= 6

        # Verify persisted as PENDING in replica DB (not in tally yet)
        v = self.db.get_vote_by_id("voter1:1:5")
        assert v is not None
        assert v.client_id == "voter1"
        assert v.choice == "Alice"
        assert v.status == "PENDING"
        assert self.db.get_tally() == {}
        assert self.db.count_votes() == 0

        # Coordinator finalizes the vote
        fin_req = voting_pb2.FinalizeRequest(vote_id="voter1:1:5", lamport_ts=out_ts + 1)
        fin_ok, fin_err, fin_ts = self.repl_mgr.handle_finalize_vote(fin_req)
        assert fin_ok is True
        assert self.db.count_votes() == 1
        assert self.db.get_tally() == {"Alice": 1}
        assert self.db.get_vote_by_id("voter1:1:5").status == "COMMITTED"

    def test_idempotent_replica_replay_inv_6(self):
        """Replaying identical vote on replica succeeds without creating duplicate."""
        req = voting_pb2.VoteRecord(
            vote_id="voter1:1:5",
            client_id="voter1",
            origin_node_id=1,
            lamport_ts=5,
            choice="Alice",
            received_at_ms=1700000000000,
        )

        # First ingestion
        ok1, err1, _ = self.repl_mgr.handle_replicate_vote(req)
        assert ok1 is True

        # Replay
        ok2, err2, _ = self.repl_mgr.handle_replicate_vote(req)
        assert ok2 is True
        assert err2 == ""

        # Finalize
        fin_req = voting_pb2.FinalizeRequest(vote_id="voter1:1:5", lamport_ts=10)
        ok_fin, _, _ = self.repl_mgr.handle_finalize_vote(fin_req)
        assert ok_fin is True

        # Tally still exactly 1
        assert self.db.count_votes() == 1
        assert self.db.get_tally() == {"Alice": 1}

    def test_conflicting_client_rejected(self):
        """Replica rejects a second vote from the same client ID (INV-1)."""
        req1 = voting_pb2.VoteRecord(
            vote_id="voter1:1:5",
            client_id="voter1",
            origin_node_id=1,
            lamport_ts=5,
            choice="Alice",
            received_at_ms=1700000000000,
        )
        req2 = voting_pb2.VoteRecord(
            vote_id="voter1:1:8",
            client_id="voter1",
            origin_node_id=1,
            lamport_ts=8,
            choice="Bob",
            received_at_ms=1700000001000,
        )

        ok1, _, _ = self.repl_mgr.handle_replicate_vote(req1)
        assert ok1 is True

        ok2, err2, _ = self.repl_mgr.handle_replicate_vote(req2)
        assert ok2 is False
        assert "conflicting" in err2 or "different choice" in err2

        # Finalize req1
        self.repl_mgr.handle_finalize_vote(voting_pb2.FinalizeRequest(vote_id="voter1:1:5", lamport_ts=10))
        assert self.db.get_tally() == {"Alice": 1}

    def test_conflicting_vote_id_rejected(self):
        """Replica rejects a different vote payload sharing the same vote_id."""
        req1 = voting_pb2.VoteRecord(
            vote_id="same_id:1:5",
            client_id="voter1",
            origin_node_id=1,
            lamport_ts=5,
            choice="Alice",
            received_at_ms=1700000000000,
        )
        req2 = voting_pb2.VoteRecord(
            vote_id="same_id:1:5",
            client_id="voter2",
            origin_node_id=1,
            lamport_ts=5,
            choice="Bob",
            received_at_ms=1700000000000,
        )

        ok1, _, _ = self.repl_mgr.handle_replicate_vote(req1)
        assert ok1 is True

        ok2, err2, _ = self.repl_mgr.handle_replicate_vote(req2)
        assert ok2 is False
        assert "vote_id conflict" in err2


class TestCoordinatorFanOut:
    """Tests for coordinator replication fan-out with mock PeerClients."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "coord_test.db")
        self.db = DatabaseManager(use_sqlite=True, sqlite_path=self.db_path)
        self.db.initialize()
        self.clock = LamportClock()
        self.state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3])
        yield
        self.db.close()

    def test_fan_out_all_success(self):
        """All peers succeed under 'all' policy -> returns True and marks active."""
        config = _make_config(node_id=1, policy="all")

        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(
            success=True, node_id=2, lamport_ts=10
        )
        client3 = MagicMock()
        client3.replicate_vote.return_value = voting_pb2.ReplicationAck(
            success=True, node_id=3, lamport_ts=12
        )

        peer_clients = {2: client2, 3: client3}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v1:1:1", "v1", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        assert success is True
        assert sorted(acks) == [2, 3]
        assert self.state.active_peers == {2, 3}
        assert self.clock.value >= 12  # clock merged higher timestamp

    def test_fan_out_failed_replica_under_all_policy(self):
        """Under 'all' policy, 1 failed peer causes replication failure and inactive marking."""
        config = _make_config(node_id=1, policy="all")

        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(
            success=True, node_id=2, lamport_ts=10
        )
        client3 = MagicMock()
        client3.replicate_vote.return_value = None  # Failed RPC / unreachable

        peer_clients = {2: client2, 3: client3}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v1:1:1", "v1", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        assert success is False
        assert acks == [2]
        assert 2 in self.state.active_peers
        assert 3 not in self.state.active_peers

    def test_previously_inactive_peer_does_not_block_all_policy(self):
        """A peer that was previously declared inactive does not block 'all' policy replication."""
        config = _make_config(node_id=1, policy="all")
        # Pre-mark peer 3 as inactive
        self.state.mark_peer_inactive(3)
        assert self.state.active_peers == {2}

        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(
            success=True, node_id=2, lamport_ts=10
        )
        client3 = MagicMock()
        client3.replicate_vote.return_value = None  # Down

        peer_clients = {2: client2, 3: client3}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v1:1:1", "v1", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        # Active peer snapshot was only [2]. Peer 2 succeeded -> SUCCESS!
        assert success is True
        assert acks == [2]
        client3.replicate_vote.assert_not_called()

    def test_fan_out_majority_policy_with_one_peer_down(self):
        """Under 'majority' policy, 3-node cluster needs 2 nodes (local + 1 peer)."""
        config = _make_config(node_id=1, policy="majority")

        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(
            success=True, node_id=2, lamport_ts=10
        )
        client3 = MagicMock()
        client3.replicate_vote.return_value = None  # Peer 3 is down

        peer_clients = {2: client2, 3: client3}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v1:1:1", "v1", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        # 1 local + 1 peer = 2 >= quorum(2) -> SUCCESS
        assert success is True
        assert acks == [2]
        assert 3 not in self.state.active_peers

    def test_fan_out_majority_policy_5node_boundary_3_alive(self):
        """Under 'majority' policy in 5-node cluster, 3 nodes alive (local + 2 peers) meets quorum (3/5)."""
        peers = {i: PeerInfo(i, "localhost", 50050 + i) for i in range(1, 6)}
        config = NodeConfig(
            node_id=1,
            grpc_port=50051,
            election_algorithm="bully",
            peers=peers,
            heartbeat_interval_ms=1000,
            heartbeat_timeout_ms=3000,
            election_timeout_ms=5000,
            replication_policy="majority",
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
        state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3, 4, 5])

        # Peers 2 and 3 ACK, peers 4 and 5 are down
        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=2, lamport_ts=10)
        client3 = MagicMock()
        client3.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=3, lamport_ts=10)
        client4 = MagicMock()
        client4.replicate_vote.return_value = None
        client5 = MagicMock()
        client5.replicate_vote.return_value = None

        peer_clients = {2: client2, 3: client3, 4: client4, 5: client5}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v_maj3:1:1", "c_maj3", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        # 1 coordinator + 2 acks = 3 >= quorum(3) -> SUCCESS
        assert success is True
        assert sorted(acks) == [2, 3]

    def test_fan_out_majority_policy_5node_boundary_2_alive(self):
        """Under 'majority' policy in 5-node cluster, only 2 nodes alive (local + 1 peer) violates quorum (2 < 3)."""
        peers = {i: PeerInfo(i, "localhost", 50050 + i) for i in range(1, 6)}
        config = NodeConfig(
            node_id=1,
            grpc_port=50051,
            election_algorithm="bully",
            peers=peers,
            heartbeat_interval_ms=1000,
            heartbeat_timeout_ms=3000,
            election_timeout_ms=5000,
            replication_policy="majority",
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
        state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3, 4, 5])

        # Peer 2 ACKs, peers 3, 4, 5 are down
        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=2, lamport_ts=10)
        client3 = MagicMock()
        client3.replicate_vote.return_value = None
        client4 = MagicMock()
        client4.replicate_vote.return_value = None
        client5 = MagicMock()
        client5.replicate_vote.return_value = None

        peer_clients = {2: client2, 3: client3, 4: client4, 5: client5}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v_maj2:1:1", "c_maj2", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        # 1 coordinator + 1 ack = 2 < quorum(3) -> REJECTED
        assert success is False
        assert acks == [2]

    def test_fan_out_majority_policy_7node_boundary_4_alive(self):
        """Under 'majority' policy in 7-node cluster, 4 nodes alive (local + 3 peers) meets quorum (4/7)."""
        peers = {i: PeerInfo(i, "localhost", 50050 + i) for i in range(1, 8)}
        config = NodeConfig(
            node_id=1,
            grpc_port=50051,
            election_algorithm="bully",
            peers=peers,
            heartbeat_interval_ms=1000,
            heartbeat_timeout_ms=3000,
            election_timeout_ms=5000,
            replication_policy="majority",
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
        state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3, 4, 5, 6, 7])

        # Peers 2, 3, 4 ACK; peers 5, 6, 7 are down
        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=2, lamport_ts=10)
        client3 = MagicMock()
        client3.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=3, lamport_ts=10)
        client4 = MagicMock()
        client4.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=4, lamport_ts=10)
        client5 = MagicMock()
        client5.replicate_vote.return_value = None
        client6 = MagicMock()
        client6.replicate_vote.return_value = None
        client7 = MagicMock()
        client7.replicate_vote.return_value = None

        peer_clients = {2: client2, 3: client3, 4: client4, 5: client5, 6: client6, 7: client7}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v_maj4:1:1", "c_maj4", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        # 1 coordinator + 3 acks = 4 >= quorum(4) -> SUCCESS
        assert success is True
        assert sorted(acks) == [2, 3, 4]

    def test_fan_out_majority_policy_7node_boundary_3_alive(self):
        """Under 'majority' policy in 7-node cluster, only 3 nodes alive (local + 2 peers) violates quorum (3 < 4)."""
        peers = {i: PeerInfo(i, "localhost", 50050 + i) for i in range(1, 8)}
        config = NodeConfig(
            node_id=1,
            grpc_port=50051,
            election_algorithm="bully",
            peers=peers,
            heartbeat_interval_ms=1000,
            heartbeat_timeout_ms=3000,
            election_timeout_ms=5000,
            replication_policy="majority",
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
        state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3, 4, 5, 6, 7])

        # Peers 2 and 3 ACK; peers 4, 5, 6, 7 are down
        client2 = MagicMock()
        client2.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=2, lamport_ts=10)
        client3 = MagicMock()
        client3.replicate_vote.return_value = voting_pb2.ReplicationAck(success=True, node_id=3, lamport_ts=10)
        client4 = MagicMock()
        client4.replicate_vote.return_value = None
        client5 = MagicMock()
        client5.replicate_vote.return_value = None
        client6 = MagicMock()
        client6.replicate_vote.return_value = None
        client7 = MagicMock()
        client7.replicate_vote.return_value = None

        peer_clients = {2: client2, 3: client3, 4: client4, 5: client5, 6: client6, 7: client7}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=state,
            config=config,
            peer_clients=peer_clients,
        )

        vote = VoteRecord("v_maj3_7:1:1", "c_maj3_7", 1, 1, "Alice", 1000)
        success, acks = repl_mgr.replicate_vote(vote)

        # 1 coordinator + 2 acks = 3 < quorum(4) -> REJECTED
        assert success is False
        assert sorted(acks) == [2, 3]

    def test_finalize_vote_fan_out(self):
        """Coordinator fan-out sends FinalizeVote to all peers that acknowledged."""
        config = _make_config(node_id=1, policy="all")

        client2 = MagicMock()
        client2.finalize_vote.return_value = voting_pb2.FinalizeAck(
            success=True, node_id=2, lamport_ts=20
        )
        client3 = MagicMock()
        client3.finalize_vote.return_value = voting_pb2.FinalizeAck(
            success=True, node_id=3, lamport_ts=22
        )

        peer_clients = {2: client2, 3: client3}
        repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            peer_clients=peer_clients,
        )

        ok, acks = repl_mgr.finalize_vote("v1:1:1", [2, 3])
        assert ok is True
        assert sorted(acks) == [2, 3]
        assert self.clock.value >= 22


class TestVoteServiceReplicationIntegration:
    """Tests for VoteService integrating ReplicationManager (INV-4 & two-phase commit)."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path):
        self.db_path = str(tmp_path / "votesvc_repl.db")
        self.db = DatabaseManager(use_sqlite=True, sqlite_path=self.db_path)
        self.db.initialize()
        self.clock = LamportClock()
        self.config = _make_config(node_id=1, policy="all")
        self.state = CoordinatorState(node_id=1, initial_coordinator_id=1, all_peer_ids=[1, 2, 3])
        yield
        self.db.close()

    def test_vote_acknowledged_only_after_replication_inv_4(self):
        """Vote is acknowledged to client only when replication and finalization succeed."""
        mock_repl = MagicMock()
        mock_repl.replicate_vote.return_value = (True, [2, 3])
        mock_repl.finalize_vote.return_value = (True, [2, 3])

        svc = VoteService(
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=self.config,
            replication_manager=mock_repl,
        )

        res = svc.submit_vote("voter1", "Alice")
        assert res["success"] is True
        assert res["vote_id"] == "voter1:1:1"
        assert res["error"] == ""

        # Vote persisted and committed locally
        assert self.db.count_votes() == 1
        assert self.db.get_tally() == {"Alice": 1}
        assert self.db.get_vote_by_id("voter1:1:1").status == "COMMITTED"
        mock_repl.replicate_vote.assert_called_once()
        mock_repl.finalize_vote.assert_called_once()

    def test_partial_replication_failure_leaves_vote_pending_inv_5(self):
        """If replication fails, local vote remains PENDING (not deleted); no tally includes it."""
        mock_repl = MagicMock()
        # Replication fails (only 1 of 2 peers acked under 'all' policy)
        mock_repl.replicate_vote.return_value = (False, [2])

        svc = VoteService(
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=self.config,
            replication_manager=mock_repl,
        )

        res = svc.submit_vote("voter1", "Alice")
        assert res["success"] is False
        assert "replication failed" in res["error"]

        # Crucial: vote remains in local DB as PENDING (NOT deleted / rolled back)
        stored = self.db.get_vote_by_id("voter1:1:1")
        assert stored is not None
        assert stored.status == "PENDING"

        # Tally and count_votes do NOT include the pending vote
        assert self.db.count_votes() == 0
        assert self.db.get_tally() == {}

        # Client can retry with same choice: safely resumes and finalizes
        mock_repl.replicate_vote.return_value = (True, [2, 3])
        mock_repl.finalize_vote.return_value = (True, [2, 3])
        retry_res = svc.submit_vote("voter1", "Alice")
        assert retry_res["success"] is True
        assert self.db.count_votes() == 1
        assert self.db.get_tally() == {"Alice": 1}
        assert self.db.get_vote_by_id("voter1:1:1").status == "COMMITTED"

    def test_different_choice_while_pending_is_rejected(self):
        """Submitting a different choice while vote is pending must be clearly rejected."""
        mock_repl = MagicMock()
        mock_repl.replicate_vote.return_value = (False, [2])

        svc = VoteService(
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=self.config,
            replication_manager=mock_repl,
        )

        # Initial vote fails replication and remains pending
        res1 = svc.submit_vote("voter1", "Alice")
        assert res1["success"] is False

        # Attempt to change choice to Bob while vote is pending
        res2 = svc.submit_vote("voter1", "Bob")
        assert res2["success"] is False
        assert "different choice" in res2["error"]

        # Original pending vote remains unchanged
        stored = self.db.get_vote_by_client_id("voter1")
        assert stored is not None
        assert stored.choice == "Alice"
        assert stored.status == "PENDING"

    def test_partial_replication_one_replica_fails_no_tally_includes_vote(self):
        """Integration: coordinator + 2 replicas under 'all' policy with 1 replica failing.
        Verify that replica 1 has PENDING vote, but neither coordinator nor replica 1 counts it in tally.
        """
        # Node 1 is coordinator
        # Node 2 is healthy replica
        # Node 3 is failing replica
        db2_path = str(self.db_path + ".node2.db")
        db2 = DatabaseManager(use_sqlite=True, sqlite_path=db2_path)
        db2.initialize()

        repl_mgr2 = ReplicationManager(
            node_id=2,
            db=db2,
            clock=LamportClock(),
            state=CoordinatorState(node_id=2, initial_coordinator_id=1),
            config=_make_config(node_id=2),
            peer_clients={},
        )

        # Client 2 connects to replica 2
        mock_client2 = MagicMock()
        def _mock_repl2(vote_rec, timeout=2.0):
            pb = voting_pb2.VoteRecord(
                vote_id=vote_rec.vote_id,
                client_id=vote_rec.client_id,
                origin_node_id=vote_rec.origin_node_id,
                lamport_ts=vote_rec.lamport_ts,
                choice=vote_rec.choice,
                received_at_ms=vote_rec.received_at_ms,
            )
            ok, err, ts = repl_mgr2.handle_replicate_vote(pb)
            return voting_pb2.ReplicationAck(success=ok, node_id=2, lamport_ts=ts, error=err)
        mock_client2.replicate_vote.side_effect = _mock_repl2

        # Client 3 fails (unreachable)
        mock_client3 = MagicMock()
        mock_client3.replicate_vote.return_value = None

        real_repl_mgr = ReplicationManager(
            node_id=1,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=self.config,
            peer_clients={2: mock_client2, 3: mock_client3},
        )

        svc = VoteService(
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=self.config,
            replication_manager=real_repl_mgr,
        )

        res = svc.submit_vote("voter_part", "Charlie")
        assert res["success"] is False

        # Replica 2 has the vote as PENDING
        v2 = db2.get_vote_by_client_id("voter_part")
        assert v2 is not None
        assert v2.status == "PENDING"
        # Neither coordinator nor replica counts the vote in tally
        assert self.db.get_tally() == {}
        assert db2.get_tally() == {}
        assert self.db.count_votes() == 0
        assert db2.count_votes() == 0

        db2.close()

    def test_deterministic_partial_finalization_safe_retry(self):
        """Deterministic partial-finalization test:
        1. Preparation (replication) succeeds on both replicas.
        2. One replica acknowledges FinalizeVote; another replica fails FinalizeVote.
        3. Coordinator record remains PENDING.
        4. Coordinator tally remains unchanged (0).
        5. No successful client receipt returned.
        6. A later same-vote retry completes successfully (replica 2 idempotent finalize).
        7. Final tally is exactly one and no duplicate exists.
        """
        # Node 1 = Coordinator, Node 2 & 3 = Replicas
        db2 = DatabaseManager(use_sqlite=True, sqlite_path=str(self.db_path + ".pfin2.db"))
        db2.initialize()
        db3 = DatabaseManager(use_sqlite=True, sqlite_path=str(self.db_path + ".pfin3.db"))
        db3.initialize()

        repl_mgr2 = ReplicationManager(
            node_id=2, db=db2, clock=LamportClock(),
            state=CoordinatorState(node_id=2, initial_coordinator_id=1),
            config=_make_config(node_id=2), peer_clients={},
        )
        repl_mgr3 = ReplicationManager(
            node_id=3, db=db3, clock=LamportClock(),
            state=CoordinatorState(node_id=3, initial_coordinator_id=1),
            config=_make_config(node_id=3), peer_clients={},
        )

        mock_client2 = MagicMock()
        def _mock_replicate2(vote_rec, timeout=2.0):
            pb = voting_pb2.VoteRecord(
                vote_id=vote_rec.vote_id, client_id=vote_rec.client_id,
                origin_node_id=vote_rec.origin_node_id, lamport_ts=vote_rec.lamport_ts,
                choice=vote_rec.choice, received_at_ms=vote_rec.received_at_ms,
            )
            ok, err, ts = repl_mgr2.handle_replicate_vote(pb)
            return voting_pb2.ReplicationAck(success=ok, node_id=2, lamport_ts=ts, error=err)
        mock_client2.replicate_vote.side_effect = _mock_replicate2

        mock_client3 = MagicMock()
        def _mock_replicate3(vote_rec, timeout=2.0):
            pb = voting_pb2.VoteRecord(
                vote_id=vote_rec.vote_id, client_id=vote_rec.client_id,
                origin_node_id=vote_rec.origin_node_id, lamport_ts=vote_rec.lamport_ts,
                choice=vote_rec.choice, received_at_ms=vote_rec.received_at_ms,
            )
            ok, err, ts = repl_mgr3.handle_replicate_vote(pb)
            return voting_pb2.ReplicationAck(success=ok, node_id=3, lamport_ts=ts, error=err)
        mock_client3.replicate_vote.side_effect = _mock_replicate3

        # Finalize mocking: Node 2 succeeds, Node 3 fails on attempt 1
        def _mock_finalize2(vote_id, lamport_ts=0, timeout=2.0):
            ok, err, ts = repl_mgr2.handle_finalize_vote(voting_pb2.FinalizeRequest(vote_id=vote_id, lamport_ts=lamport_ts))
            return voting_pb2.FinalizeAck(success=ok, node_id=2, error=err, lamport_ts=ts)
        mock_client2.finalize_vote.side_effect = _mock_finalize2

        node3_finalize_should_fail = True
        def _mock_finalize3(vote_id, lamport_ts=0, timeout=2.0):
            if node3_finalize_should_fail:
                # Replica 3 fails to finalize (e.g. network partition or timeout)
                return None
            ok, err, ts = repl_mgr3.handle_finalize_vote(voting_pb2.FinalizeRequest(vote_id=vote_id, lamport_ts=lamport_ts))
            return voting_pb2.FinalizeAck(success=ok, node_id=3, error=err, lamport_ts=ts)
        mock_client3.finalize_vote.side_effect = _mock_finalize3

        real_repl_mgr = ReplicationManager(
            node_id=1, db=self.db, clock=self.clock,
            state=self.state, config=self.config,
            peer_clients={2: mock_client2, 3: mock_client3},
        )

        svc = VoteService(
            db=self.db, clock=self.clock, state=self.state,
            config=self.config, replication_manager=real_repl_mgr,
        )

        # ── First Attempt: Partial Finalization Failure ────────────────
        res = svc.submit_vote("voter_partial_fin", "Alice")

        # 1. Preparation succeeded (both replicas received pending vote)
        v2_pen = db2.get_vote_by_client_id("voter_partial_fin")
        assert v2_pen is not None
        v3_pen = db3.get_vote_by_client_id("voter_partial_fin")
        assert v3_pen is not None

        # 2. Replica 2 finalized, Replica 3 failed
        assert db2.get_vote_by_client_id("voter_partial_fin").status == "COMMITTED"
        assert db3.get_vote_by_client_id("voter_partial_fin").status == "PENDING"

        # 3. Coordinator record remains PENDING
        coord_vote = self.db.get_vote_by_client_id("voter_partial_fin")
        assert coord_vote is not None
        assert coord_vote.status == "PENDING"

        # 4. Coordinator tally remains unchanged (0)
        assert self.db.count_votes() == 0
        assert self.db.get_tally() == {}

        # 5. No successful client receipt returned
        assert res["success"] is False
        assert "finalization failed" in res["error"]

        # ── Second Attempt: Same Client and Choice Retries ─────────────
        # Now replica 3 network recovers
        node3_finalize_should_fail = False

        retry_res = svc.submit_vote("voter_partial_fin", "Alice")

        # 6. Retry completes successfully with the same vote_id
        assert retry_res["success"] is True
        assert retry_res["vote_id"] == coord_vote.vote_id

        # 7. Coordinator record is now COMMITTED
        assert self.db.get_vote_by_id(coord_vote.vote_id).status == "COMMITTED"
        assert db2.get_vote_by_id(coord_vote.vote_id).status == "COMMITTED"
        assert db3.get_vote_by_id(coord_vote.vote_id).status == "COMMITTED"

        # 8. Final tally is exactly one and no duplicate exists
        assert self.db.count_votes() == 1
        assert self.db.get_tally() == {"Alice": 1}
        assert db2.count_votes() == 1
        assert db3.count_votes() == 1

        db2.close()
        db3.close()


