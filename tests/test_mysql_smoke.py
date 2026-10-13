"""MySQL smoke test (amendment 8).

Prerequisites:
  1. docker compose -f docker/docker-compose.test-mysql.yml up -d
  2. Wait until the health check passes (~30s).
  3. pytest tests/test_mysql_smoke.py -v -m mysql

Or set TEST_MYSQL_HOST / TEST_MYSQL_PORT env vars to point to an existing
MySQL instance.
"""

import os
import time

import pytest

from node.db import DatabaseManager
from node.models import InsertResult, VoteRecord


# ── Skip unless MySQL is reachable ───────────────────────────────

MYSQL_HOST = os.environ.get("TEST_MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.environ.get("TEST_MYSQL_PORT", "3307"))
MYSQL_USER = os.environ.get("TEST_MYSQL_USER", "root")
MYSQL_PASSWORD = os.environ.get("TEST_MYSQL_PASSWORD", "votingpass")
MYSQL_DB = "voting_smoke_test"


def _mysql_available() -> bool:
    return DatabaseManager.mysql_health_check(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD,
        timeout=3,
    )


pytestmark = pytest.mark.skipif(
    not _mysql_available(),
    reason=f"MySQL not reachable at {MYSQL_HOST}:{MYSQL_PORT}",
)


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture()
def mysql_db():
    """Create a fresh test database, yield a DatabaseManager, then drop it."""
    import mysql.connector

    # Create dedicated test database
    conn = mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {MYSQL_DB}")
    cur.execute(f"CREATE DATABASE {MYSQL_DB}")
    conn.commit()
    conn.close()

    # Initialise via DatabaseManager
    db = DatabaseManager(
        use_sqlite=False,
        mysql_config={
            "host": MYSQL_HOST,
            "port": MYSQL_PORT,
            "user": MYSQL_USER,
            "password": MYSQL_PASSWORD,
            "database": MYSQL_DB,
        },
    )
    db.initialize()
    yield db
    db.close()

    # Cleanup
    conn = mysql.connector.connect(
        host=MYSQL_HOST, port=MYSQL_PORT,
        user=MYSQL_USER, password=MYSQL_PASSWORD,
    )
    cur = conn.cursor()
    cur.execute(f"DROP DATABASE IF EXISTS {MYSQL_DB}")
    conn.commit()
    conn.close()


# ── Tests ────────────────────────────────────────────────────────

@pytest.mark.mysql
class TestMySQLSmoke:
    """Amendment 8: minimal real-MySQL smoke test."""

    def test_health_check_passes(self):
        assert _mysql_available()

    def test_insert_and_retrieve(self, mysql_db):
        vote = VoteRecord(
            vote_id="c1:1:10",
            client_id="c1",
            origin_node_id=1,
            lamport_ts=10,
            choice="Alice",
            received_at_ms=int(time.time() * 1000),
        )
        result = mysql_db.insert_vote(vote)
        assert result == InsertResult.INSERTED

        stored = mysql_db.get_vote_by_id("c1:1:10")
        assert stored is not None
        assert stored.client_id == "c1"
        assert stored.choice == "Alice"

    def test_duplicate_vote_id_idempotent(self, mysql_db):
        vote = VoteRecord(
            vote_id="c2:1:20", client_id="c2", origin_node_id=1,
            lamport_ts=20, choice="Bob",
            received_at_ms=int(time.time() * 1000),
            status="COMMITTED",
        )
        mysql_db.insert_vote(vote)
        result = mysql_db.insert_vote(vote)
        assert result == InsertResult.IDEMPOTENT
        assert mysql_db.count_votes() == 1

    def test_duplicate_client_id_rejected(self, mysql_db):
        v1 = VoteRecord(
            vote_id="c3:1:30", client_id="c3", origin_node_id=1,
            lamport_ts=30, choice="Alice",
            received_at_ms=int(time.time() * 1000),
            status="COMMITTED",
        )
        v2 = VoteRecord(
            vote_id="c3:1:40", client_id="c3", origin_node_id=1,
            lamport_ts=40, choice="Bob",
            received_at_ms=int(time.time() * 1000),
            status="COMMITTED",
        )
        mysql_db.insert_vote(v1)
        result = mysql_db.insert_vote(v2)
        assert result == InsertResult.CLIENT_ALREADY_VOTED

    def test_tally(self, mysql_db):
        for i, (cid, choice) in enumerate([("a", "Alice"), ("b", "Bob"), ("c", "Alice")]):
            mysql_db.insert_vote(VoteRecord(
                vote_id=f"{cid}:1:{i}",
                client_id=cid,
                origin_node_id=1,
                lamport_ts=i,
                choice=choice,
                received_at_ms=int(time.time() * 1000),
                status="COMMITTED",
            ))
        tally = mysql_db.get_tally()
        assert tally == {"Alice": 2, "Bob": 1}

    def test_mysql_pending_and_finalize_lifecycle(self, mysql_db):
        """Verify PENDING -> COMMITTED and retry semantics in MySQL."""
        v_pending = VoteRecord(
            vote_id="c_pen:1:50",
            client_id="c_pen",
            origin_node_id=1,
            lamport_ts=50,
            choice="Charlie",
            received_at_ms=int(time.time() * 1000),
            status="PENDING",
        )
        res1 = mysql_db.insert_vote(v_pending)
        assert res1 == InsertResult.INSERTED
        assert mysql_db.count_votes() == 0
        assert mysql_db.get_tally() == {}

        # Retry with same choice returns PENDING_RETRY
        v_retry = VoteRecord(
            vote_id="c_pen:1:51",
            client_id="c_pen",
            origin_node_id=1,
            lamport_ts=51,
            choice="Charlie",
            received_at_ms=int(time.time() * 1000),
            status="PENDING",
        )
        assert mysql_db.insert_vote(v_retry) == InsertResult.PENDING_RETRY

        # Retry with different choice returns PENDING_CONFLICT
        v_conflict = VoteRecord(
            vote_id="c_pen:1:52",
            client_id="c_pen",
            origin_node_id=1,
            lamport_ts=52,
            choice="Bob",
            received_at_ms=int(time.time() * 1000),
            status="PENDING",
        )
        assert mysql_db.insert_vote(v_conflict) == InsertResult.PENDING_CONFLICT

        # Finalize promotes to COMMITTED and tallies
        assert mysql_db.finalize_vote("c_pen:1:50") is True
        assert mysql_db.count_votes() == 1
        assert mysql_db.get_tally() == {"Charlie": 1}
        stored = mysql_db.get_vote_by_id("c_pen:1:50")
        assert stored.status == "COMMITTED"
