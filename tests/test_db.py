"""Unit tests for node.db.DatabaseManager (SQLite).

Invariant INV-1: single-vote per client_id.
Invariant INV-2: unique vote_id.
Invariant INV-6: idempotent replication (same vote_id + content → no-op).
Amendment 4: conflicting duplicates are rejected (not silently ignored).
Amendment 5: uses isolated temporary SQLite file per test.
"""

import time

import pytest

from node.db import DatabaseManager
from node.models import InsertResult, VoteRecord


# ── Helpers ──────────────────────────────────────────────────────

def _make_vote(
    client_id: str = "voter1",
    node_id: int = 1,
    lamport_ts: int = 10,
    choice: str = "Alice",
    status: str = "COMMITTED",
) -> VoteRecord:
    vote_id = VoteRecord.make_vote_id(client_id, node_id, lamport_ts)
    return VoteRecord(
        vote_id=vote_id,
        client_id=client_id,
        origin_node_id=node_id,
        lamport_ts=lamport_ts,
        choice=choice,
        received_at_ms=int(time.time() * 1000),
        status=status,
    )


# ── Tests ────────────────────────────────────────────────────────

class TestInsertVote:
    """Basic insert and retrieval."""

    def test_insert_returns_inserted(self, db_manager):
        vote = _make_vote()
        result = db_manager.insert_vote(vote)
        assert result == InsertResult.INSERTED

    def test_inserted_vote_is_retrievable_by_id(self, db_manager):
        vote = _make_vote()
        db_manager.insert_vote(vote)
        stored = db_manager.get_vote_by_id(vote.vote_id)
        assert stored is not None
        assert stored.vote_id == vote.vote_id
        assert stored.client_id == vote.client_id
        assert stored.choice == vote.choice

    def test_inserted_vote_is_retrievable_by_client_id(self, db_manager):
        vote = _make_vote()
        db_manager.insert_vote(vote)
        stored = db_manager.get_vote_by_client_id(vote.client_id)
        assert stored is not None
        assert stored.vote_id == vote.vote_id

    def test_get_nonexistent_returns_none(self, db_manager):
        assert db_manager.get_vote_by_id("nonexistent") is None
        assert db_manager.get_vote_by_client_id("nonexistent") is None


class TestDuplicateVoteId:
    """INV-2 + INV-6: same vote_id handling."""

    def test_same_vote_id_same_content_is_idempotent(self, db_manager):
        """Amendment 4: idempotent only when content is identical."""
        vote = _make_vote()
        db_manager.insert_vote(vote)

        # Replay with identical content (different received_at_ms is OK)
        replay = VoteRecord(
            vote_id=vote.vote_id,
            client_id=vote.client_id,
            origin_node_id=vote.origin_node_id,
            lamport_ts=vote.lamport_ts,
            choice=vote.choice,
            received_at_ms=int(time.time() * 1000) + 999,
        )
        result = db_manager.insert_vote(replay)
        assert result == InsertResult.IDEMPOTENT

    def test_same_vote_id_different_content_is_conflict(self, db_manager):
        """Amendment 4: different content → VOTE_ID_CONFLICT, not silent ignore."""
        vote = _make_vote(choice="Alice")
        db_manager.insert_vote(vote)

        conflicting = VoteRecord(
            vote_id=vote.vote_id,
            client_id=vote.client_id,
            origin_node_id=vote.origin_node_id,
            lamport_ts=vote.lamport_ts,
            choice="Bob",  # different!
            received_at_ms=int(time.time() * 1000),
        )
        result = db_manager.insert_vote(conflicting)
        assert result == InsertResult.VOTE_ID_CONFLICT

    def test_idempotent_insert_does_not_create_second_record(self, db_manager):
        vote = _make_vote()
        db_manager.insert_vote(vote)
        db_manager.insert_vote(vote)  # replay
        assert db_manager.count_votes() == 1


class TestDuplicateClientId:
    """INV-1: one vote per client_id."""

    def test_second_vote_from_same_client_is_rejected(self, db_manager):
        """Amendment 4: same client_id but different vote → CLIENT_ALREADY_VOTED."""
        vote1 = _make_vote(client_id="voter42", lamport_ts=10)
        result1 = db_manager.insert_vote(vote1)
        assert result1 == InsertResult.INSERTED

        vote2 = _make_vote(client_id="voter42", lamport_ts=20)
        result2 = db_manager.insert_vote(vote2)
        assert result2 == InsertResult.CLIENT_ALREADY_VOTED

    def test_rejected_duplicate_does_not_overwrite(self, db_manager):
        vote1 = _make_vote(client_id="voter42", choice="Alice", lamport_ts=10)
        db_manager.insert_vote(vote1)

        vote2 = _make_vote(client_id="voter42", choice="Bob", lamport_ts=20)
        db_manager.insert_vote(vote2)

        stored = db_manager.get_vote_by_client_id("voter42")
        assert stored.choice == "Alice"  # original preserved
        assert db_manager.count_votes() == 1


class TestTally:
    def test_empty_tally(self, db_manager):
        tally = db_manager.get_tally()
        assert tally == {}

    def test_tally_counts_choices(self, db_manager):
        db_manager.insert_vote(_make_vote(client_id="v1", choice="Alice", lamport_ts=1))
        db_manager.insert_vote(_make_vote(client_id="v2", choice="Bob", lamport_ts=2))
        db_manager.insert_vote(_make_vote(client_id="v3", choice="Alice", lamport_ts=3))
        tally = db_manager.get_tally()
        assert tally == {"Alice": 2, "Bob": 1}

    def test_count_votes(self, db_manager):
        for i in range(5):
            db_manager.insert_vote(_make_vote(client_id=f"v{i}", lamport_ts=i))
        assert db_manager.count_votes() == 5


class TestGetAllVotes:
    def test_returns_sorted_by_merge_key(self, db_manager):
        """Amendment 9: deterministic merge ordering."""
        db_manager.insert_vote(_make_vote(client_id="c", lamport_ts=30))
        db_manager.insert_vote(_make_vote(client_id="a", lamport_ts=10))
        db_manager.insert_vote(_make_vote(client_id="b", lamport_ts=20))
        votes = db_manager.get_all_votes()
        assert [v.client_id for v in votes] == ["a", "b", "c"]

    def test_defaults_to_committed_only_and_ignores_pending(self, db_manager):
        """Recovery-safe: get_all_votes() defaults to committed_only=True."""
        db_manager.insert_vote(_make_vote(client_id="v_comm", lamport_ts=10, status="COMMITTED"))
        db_manager.insert_vote(_make_vote(client_id="v_pend", lamport_ts=20, status="PENDING"))

        # Default query must NOT include the pending record
        committed = db_manager.get_all_votes()
        assert len(committed) == 1
        assert committed[0].client_id == "v_comm"

        # Diagnostic queries explicitly including pending records
        all_votes = db_manager.get_all_votes_including_pending()
        assert len(all_votes) == 2
        assert [v.client_id for v in all_votes] == ["v_comm", "v_pend"]

        all_votes_param = db_manager.get_all_votes(committed_only=False)
        assert len(all_votes_param) == 2


class TestElectionLog:
    def test_log_election_event(self, db_manager):
        db_manager.log_election_event(
            event_type="ELECTION_STARTED",
            node_id=1,
            lamport_ts=5,
            election_term=5,
            initiator_id=1,
            details={"reason": "heartbeat_timeout"},
        )
        # No assertion on content — just verify it doesn't crash.
        # Full verification via structured logs in Phase 7.


class TestIsolation:
    """Amendment 5: two separate db_managers on separate files don't share state."""

    def test_two_databases_are_independent(self, tmp_path):
        path_a = str(tmp_path / "node_a.db")
        path_b = str(tmp_path / "node_b.db")

        db_a = DatabaseManager(use_sqlite=True, sqlite_path=path_a)
        db_b = DatabaseManager(use_sqlite=True, sqlite_path=path_b)
        db_a.initialize()
        db_b.initialize()

        db_a.insert_vote(_make_vote(client_id="only_in_a", lamport_ts=1))
        assert db_a.count_votes() == 1
        assert db_b.count_votes() == 0

        db_a.close()
        db_b.close()


class TestLifecycleAndPendingRetry:
    """Tests for PENDING -> COMMITTED lifecycle and pending retry semantics."""

    def test_pending_vote_not_counted_in_tally(self, db_manager):
        vote = _make_vote(status="PENDING")
        res = db_manager.insert_vote(vote)
        assert res == InsertResult.INSERTED
        assert db_manager.count_votes() == 0
        assert db_manager.get_tally() == {}
        stored = db_manager.get_vote_by_id(vote.vote_id)
        assert stored is not None
        assert stored.status == "PENDING"

    def test_finalize_promotes_pending_to_committed(self, db_manager):
        vote = _make_vote(status="PENDING")
        db_manager.insert_vote(vote)
        assert db_manager.count_votes() == 0

        ok = db_manager.finalize_vote(vote.vote_id)
        assert ok is True
        assert db_manager.count_votes() == 1
        assert db_manager.get_tally() == {vote.choice: 1}
        stored = db_manager.get_vote_by_id(vote.vote_id)
        assert stored.status == "COMMITTED"

    def test_pending_retry_same_choice(self, db_manager):
        vote1 = _make_vote(client_id="v_retry", choice="Alice", lamport_ts=1, status="PENDING")
        res1 = db_manager.insert_vote(vote1)
        assert res1 == InsertResult.INSERTED

        vote2 = _make_vote(client_id="v_retry", choice="Alice", lamport_ts=2, status="PENDING")
        res2 = db_manager.insert_vote(vote2)
        assert res2 == InsertResult.PENDING_RETRY

    def test_pending_conflict_different_choice(self, db_manager):
        vote1 = _make_vote(client_id="v_conflict", choice="Alice", lamport_ts=1, status="PENDING")
        res1 = db_manager.insert_vote(vote1)
        assert res1 == InsertResult.INSERTED

        vote2 = _make_vote(client_id="v_conflict", choice="Bob", lamport_ts=2, status="PENDING")
        res2 = db_manager.insert_vote(vote2)
        assert res2 == InsertResult.PENDING_CONFLICT

    def test_finalize_is_idempotent(self, db_manager):
        """Repeated finalization of the same vote succeeds idempotently."""
        vote = _make_vote(status="PENDING")
        db_manager.insert_vote(vote)

        assert db_manager.finalize_vote(vote.vote_id) is True
        assert db_manager.count_votes() == 1

        # Second call on already COMMITTED vote must return True (idempotent success)
        assert db_manager.finalize_vote(vote.vote_id) is True
        assert db_manager.count_votes() == 1

        # Finalizing nonexistent vote returns False
        assert db_manager.finalize_vote("nonexistent:9:99") is False


