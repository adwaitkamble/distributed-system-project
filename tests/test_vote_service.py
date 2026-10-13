"""Tests for VoteService (unit) and VotingServicer (gRPC integration).

Invariant INV-1: single-vote per client.
Invariant INV-2: unique vote_id with receipt format client:node:lamport.
Invariant INV-3: follower rejects votes with redirect hint.
Invariant INV-5: no phantom acks — unacknowledged votes are not counted.
"""

import pytest


# ═══════════════════════════════════════════════════════════════════
# UNIT TESTS — VoteService.submit_vote() called directly
# ═══════════════════════════════════════════════════════════════════

class TestVoteServiceUnit:
    """Direct method calls, no gRPC."""

    @pytest.fixture(autouse=True)
    def setup(self, tmp_path, node_config):
        from node.coordinator import CoordinatorState
        from node.db import DatabaseManager
        from node.lamport import LamportClock
        from node.vote_service import VoteService

        db_path = str(tmp_path / "unit_test_node.db")
        node_config.sqlite_path = db_path

        self.clock = LamportClock()
        self.db = DatabaseManager(use_sqlite=True, sqlite_path=db_path)
        self.db.initialize()
        self.state = CoordinatorState(
            node_config.node_id,
            node_config.default_coordinator_id,
        )
        self.svc = VoteService(self.db, self.clock, self.state, node_config)
        yield
        self.db.close()

    def test_submit_vote_success(self):
        result = self.svc.submit_vote("voter1", "Alice")
        assert result["success"] is True
        assert result["vote_id"] != ""
        assert result["error"] == ""
        assert result["lamport_ts"] > 0

    def test_receipt_format(self):
        """Amendment 5 (receipt): client_id:origin_node_id:lamport_ts."""
        result = self.svc.submit_vote("voter1", "Alice")
        parts = result["vote_id"].split(":")
        assert len(parts) == 3
        assert parts[0] == "voter1"        # client_id
        assert parts[1] == "1"             # origin_node_id
        assert int(parts[2]) > 0           # lamport_ts

        # Preserve receipt format: client IDs containing ':' must be rejected
        colon_res = self.svc.submit_vote("voter:1", "Alice")
        assert colon_res["success"] is False
        assert ":" in colon_res["error"]

    def test_duplicate_client_rejected(self):
        """INV-1: same client_id voting twice."""
        r1 = self.svc.submit_vote("voter1", "Alice")
        assert r1["success"] is True
        r2 = self.svc.submit_vote("voter1", "Bob")
        assert r2["success"] is False
        assert "already voted" in r2["error"]

    def test_empty_client_id_rejected(self):
        result = self.svc.submit_vote("", "Alice")
        assert result["success"] is False
        assert "non-empty" in result["error"]

    def test_whitespace_client_id_rejected(self):
        result = self.svc.submit_vote("   ", "Alice")
        assert result["success"] is False

    def test_whitespace_normalization_prevents_duplicate_voter(self):
        """Task 1: ' voter1 ' and 'voter1' normalize to the same ID and reject double voting."""
        r1 = self.svc.submit_vote(" voter1 ", "Alice")
        assert r1["success"] is True
        assert r1["vote_id"].startswith("voter1:1:")

        # Attempt with unpadded voter1
        r2 = self.svc.submit_vote("voter1", "Bob")
        assert r2["success"] is False
        assert "already voted" in r2["error"]

    def test_invalid_choice_rejected(self):
        result = self.svc.submit_vote("voter1", "InvalidCandidate")
        assert result["success"] is False
        assert "invalid choice" in result["error"]

    def test_vote_persisted_in_db(self):
        r = self.svc.submit_vote("voter1", "Alice")
        stored = self.db.get_vote_by_id(r["vote_id"])
        assert stored is not None
        assert stored.client_id == "voter1"
        assert stored.choice == "Alice"

    def test_successive_votes_have_increasing_timestamps(self):
        r1 = self.svc.submit_vote("v1", "Alice")
        r2 = self.svc.submit_vote("v2", "Bob")
        assert r2["lamport_ts"] > r1["lamport_ts"]

    def test_follower_rejects_vote(self, tmp_path, follower_config):
        """INV-3: non-coordinator node rejects with redirect hint."""
        from node.coordinator import CoordinatorState
        from node.db import DatabaseManager
        from node.lamport import LamportClock
        from node.vote_service import VoteService

        db_path = str(tmp_path / "follower_test.db")
        follower_config.sqlite_path = db_path
        db = DatabaseManager(use_sqlite=True, sqlite_path=db_path)
        db.initialize()

        state = CoordinatorState(
            follower_config.node_id,
            follower_config.default_coordinator_id,  # = 2, so node 1 is follower
        )
        svc = VoteService(db, LamportClock(), state, follower_config)
        result = svc.submit_vote("voter1", "Alice")

        assert result["success"] is False
        assert "not_coordinator" in result["error"]
        assert "2" in result["error"]  # redirect to node 2

        db.close()


# ═══════════════════════════════════════════════════════════════════
# gRPC INTEGRATION TESTS — full server round-trip
# ═══════════════════════════════════════════════════════════════════

class TestGrpcSubmitVote:
    """Tests that hit the real gRPC server via the fixture."""

    def test_submit_vote_via_grpc(self, grpc_server_and_stub):
        from node.generated import voting_pb2
        stub, server, db, clock, state = grpc_server_and_stub

        response = stub.SubmitVote(voting_pb2.VoteRequest(
            client_id="grpc_voter1",
            choice="Alice",
        ))
        assert response.success is True
        assert response.vote_id != ""
        assert response.lamport_ts > 0

    def test_duplicate_via_grpc(self, grpc_server_and_stub):
        from node.generated import voting_pb2
        stub = grpc_server_and_stub[0]

        stub.SubmitVote(voting_pb2.VoteRequest(client_id="dup_voter", choice="Alice"))
        r2 = stub.SubmitVote(voting_pb2.VoteRequest(client_id="dup_voter", choice="Bob"))
        assert r2.success is False
        assert "already voted" in r2.error

    def test_invalid_choice_via_grpc(self, grpc_server_and_stub):
        from node.generated import voting_pb2
        stub = grpc_server_and_stub[0]

        r = stub.SubmitVote(voting_pb2.VoteRequest(client_id="voter_x", choice="Nobody"))
        assert r.success is False
        assert "invalid choice" in r.error


class TestGrpcGetResults:
    def test_empty_tally(self, grpc_server_and_stub):
        from node.generated import voting_pb2
        stub = grpc_server_and_stub[0]

        r = stub.GetResults(voting_pb2.Empty())
        assert r.total_votes == 0
        assert dict(r.tally) == {}

    def test_tally_after_votes(self, grpc_server_and_stub):
        from node.generated import voting_pb2
        stub = grpc_server_and_stub[0]

        stub.SubmitVote(voting_pb2.VoteRequest(client_id="t1", choice="Alice"))
        stub.SubmitVote(voting_pb2.VoteRequest(client_id="t2", choice="Bob"))
        stub.SubmitVote(voting_pb2.VoteRequest(client_id="t3", choice="Alice"))

        r = stub.GetResults(voting_pb2.Empty())
        tally = dict(r.tally)
        assert tally == {"Alice": 2, "Bob": 1}
        assert r.total_votes == 3


class TestGrpcClusterStatus:
    def test_reports_coordinator_role(self, grpc_server_and_stub):
        from node.generated import voting_pb2
        stub = grpc_server_and_stub[0]

        r = stub.GetClusterStatus(voting_pb2.Empty())
        assert r.this_node_id == 1
        assert r.coordinator_id == 1
        assert r.role == "coordinator"
        assert r.accepting_votes is True
        assert r.election_algorithm == "bully"
