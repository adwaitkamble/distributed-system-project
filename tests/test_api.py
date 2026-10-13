"""Comprehensive test suite for Phase 5 Flask REST API bridge.

Validates all 21 required test scenarios:
1. Health endpoint
2. Node status
3. Cluster/node listing
4. Valid vote submission
5. Invalid vote request
6. Duplicate client
7. Conflicting client vote
8. Pending vote behavior
9. Tally excludes PENDING votes
10. Vote lookup
11. Non-coordinator vote rejection
12. RECOVERING coordinator vote rejection
13. Election status
14. Election start
15. Recovery status
16. Recovery failure response
17. Recovery start
18. Unknown node
19. Unknown vote
20. Malformed JSON
21. Unexpected backend error mapping
"""

import json
import pytest

from api import create_app
from node.config import NodeConfig, PeerInfo
from node.models import NodeRole, VoteRecord, VoteStatus
from node.runtime import NodeRuntime


@pytest.fixture
def api_runtime(tmp_path):
    """Create a fully-initialized NodeRuntime using an isolated temporary SQLite database."""
    db_path = str(tmp_path / "api_test_node.db")
    config = NodeConfig(
        node_id=1,
        grpc_port=0,
        election_algorithm="bully",
        peers={
            1: PeerInfo(1, "localhost", 50051),
            2: PeerInfo(2, "localhost", 50052),
            3: PeerInfo(3, "localhost", 50053),
        },
        heartbeat_interval_ms=1000,
        heartbeat_timeout_ms=3000,
        election_timeout_ms=5000,
        replication_policy="all",
        initial_coordinator_id=1,
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="votingpass",
        db_name="voting_test",
        use_sqlite=True,
        sqlite_path=db_path,
        log_level="DEBUG",
        candidates=["Alice", "Bob", "Charlie"],
    )
    runtime = NodeRuntime(config=config)
    runtime.db.initialize()
    runtime.recovery_manager.recover_local_state()
    # In unit test fixture without running peer gRPC servers, clear active peers
    with runtime.state._lock:
        runtime.state._active_peers.clear()
    yield runtime
    runtime.db.close()


@pytest.fixture
def client(api_runtime):
    """Flask test client bound to api_runtime."""
    app = create_app(runtime=api_runtime, test_config={"TESTING": True})
    return app.test_client()


# ── 1. Health endpoint ──────────────────────────────────────────

def test_health_endpoint(client, api_runtime):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
    assert data["node_id"] == api_runtime.config.node_id


# ── 2. Node status ──────────────────────────────────────────────

def test_node_status(client, api_runtime):
    resp = client.get("/api/node")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["node_id"] == 1
    assert data["role"] == "coordinator"
    assert data["state"] == "COORDINATOR"
    assert data["is_coordinator"] is True
    assert data["accepting_votes"] is True
    assert data["coordinator_id"] == 1
    assert data["election_algorithm"] == "bully"
    assert "Alice" in data["candidates"]


# ── 3. Cluster / node listing ───────────────────────────────────

def test_cluster_node_listing(client):
    resp = client.get("/api/nodes")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["total_nodes"] == 3
    assert data["current_coordinator_id"] == 1

    node_ids = [n["node_id"] for n in data["nodes"]]
    assert node_ids == [1, 2, 3]

    self_node = next(n for n in data["nodes"] if n["node_id"] == 1)
    assert self_node["is_self"] is True
    assert self_node["is_coordinator"] is True


# ── 4. Valid vote submission ────────────────────────────────────

def test_valid_vote_submission(client):
    resp = client.post(
        "/api/votes",
        data=json.dumps({"client_id": "voter_101", "choice": "Alice"}),
        content_type="application/json",
    )
    assert resp.status_code == 201
    data = resp.get_json()
    assert data["success"] is True
    assert data["client_id"] == "voter_101"
    assert data["choice"] == "Alice"
    assert "voter_101:1:" in data["vote_id"]
    assert data["lamport_ts"] > 0


# ── 5. Invalid vote request ─────────────────────────────────────

def test_invalid_vote_request(client):
    # Missing fields
    resp = client.post("/api/votes", json={"client_id": "v1"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "missing_fields"

    # Empty client_id
    resp = client.post("/api/votes", json={"client_id": "   ", "choice": "Alice"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_client_id"

    # Colon in client_id
    resp = client.post("/api/votes", json={"client_id": "voter:1", "choice": "Alice"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_client_id"

    # Invalid candidate choice
    resp = client.post("/api/votes", json={"client_id": "v1", "choice": "Mallory"})
    assert resp.status_code == 400
    assert resp.get_json()["error"] == "invalid_choice"


# ── 6. Duplicate client ─────────────────────────────────────────

def test_duplicate_client(client):
    resp1 = client.post("/api/votes", json={"client_id": "dup_voter", "choice": "Alice"})
    assert resp1.status_code == 201

    resp2 = client.post("/api/votes", json={"client_id": "dup_voter", "choice": "Alice"})
    assert resp2.status_code == 409
    data = resp2.get_json()
    assert data["success"] is False
    assert data["error"] == "duplicate_client"


# ── 7. Conflicting client vote ──────────────────────────────────

def test_conflicting_client_vote(client, api_runtime):
    # Insert a pending vote directly in DB
    pending_vote = VoteRecord(
        vote_id="conf_voter:1:10",
        client_id="conf_voter",
        origin_node_id=1,
        lamport_ts=10,
        choice="Alice",
        received_at_ms=1000,
        status=VoteStatus.PENDING.value,
    )
    api_runtime.db.insert_vote(pending_vote)

    # Attempt to vote with different choice
    resp = client.post("/api/votes", json={"client_id": "conf_voter", "choice": "Bob"})
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "pending_conflict"


# ── 8. Pending vote behavior ────────────────────────────────────

def test_pending_vote_retry_behavior(client, api_runtime):
    # Insert a pending vote directly in DB
    pending_vote = VoteRecord(
        vote_id="retry_voter:1:20",
        client_id="retry_voter",
        origin_node_id=1,
        lamport_ts=20,
        choice="Bob",
        received_at_ms=1000,
        status=VoteStatus.PENDING.value,
    )
    api_runtime.db.insert_vote(pending_vote)

    # Retry same choice while pending: succeeds and finalizes
    resp = client.post("/api/votes", json={"client_id": "retry_voter", "choice": "Bob"})
    assert resp.status_code == 201
    assert resp.get_json()["success"] is True

    # Check vote is now COMMITTED
    v = api_runtime.db.get_vote_by_id("retry_voter:1:20")
    assert v is not None
    assert v.status == VoteStatus.COMMITTED.value


# ── 9. Tally excludes PENDING votes ─────────────────────────────

def test_tally_excludes_pending_votes(client, api_runtime):
    # 1 committed vote
    resp = client.post("/api/votes", json={"client_id": "comm_voter", "choice": "Charlie"})
    assert resp.status_code == 201

    # 1 pending vote
    pending_vote = VoteRecord(
        vote_id="pend_voter:1:30",
        client_id="pend_voter",
        origin_node_id=1,
        lamport_ts=30,
        choice="Alice",
        received_at_ms=1000,
        status=VoteStatus.PENDING.value,
    )
    api_runtime.db.insert_vote(pending_vote)

    tally_resp = client.get("/api/votes/tally")
    assert tally_resp.status_code == 200
    tally_data = tally_resp.get_json()
    assert tally_data["success"] is True
    assert tally_data["total_votes"] == 1
    assert tally_data["tally"].get("Charlie") == 1
    assert "Alice" not in tally_data["tally"]  # Pending vote MUST NOT appear in tally


# ── 10. Vote lookup ─────────────────────────────────────────────

def test_vote_lookup(client):
    resp = client.post("/api/votes", json={"client_id": "lookup_voter", "choice": "Alice"})
    vote_id = resp.get_json()["vote_id"]

    get_resp = client.get(f"/api/votes/{vote_id}")
    assert get_resp.status_code == 200
    data = get_resp.get_json()
    assert data["success"] is True
    assert data["vote"]["vote_id"] == vote_id
    assert data["vote"]["client_id"] == "lookup_voter"
    assert data["vote"]["choice"] == "Alice"
    assert data["vote"]["status"] == "COMMITTED"


# ── 11. Non-coordinator vote rejection ──────────────────────────

def test_non_coordinator_vote_rejection(client, api_runtime):
    # Force follower role
    api_runtime.state.become_follower(coordinator_id=2, election_term=2, initiator_id=2)

    resp = client.post("/api/votes", json={"client_id": "voter_follower", "choice": "Alice"})
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "not_coordinator"
    assert data["coordinator_id"] == 2


# ── 12. RECOVERING coordinator vote rejection ───────────────────

def test_recovering_coordinator_vote_rejection(client, api_runtime):
    # Transition to RECOVERING
    with api_runtime.state._lock:
        api_runtime.state._role = NodeRole.RECOVERING

    resp = client.post("/api/votes", json={"client_id": "voter_recovering", "choice": "Alice"})
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "not_coordinator"
    assert data["role"] == "recovering"


# ── 13. Election status ─────────────────────────────────────────

def test_election_status(client):
    resp = client.get("/api/election/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["algorithm"] == "bully"
    assert data["is_coordinator"] is True
    assert "last_election_metrics" in data
    assert "message_counts" in data


# ── 14. Election start ──────────────────────────────────────────

def test_election_start(client, api_runtime):
    # Start election (non-blocking)
    resp = client.post("/api/election/start", json={"blocking": False})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["algorithm"] == "bully"


# ── 15. Recovery status ─────────────────────────────────────────

def test_recovery_status(client, api_runtime):
    resp = client.get("/api/recovery/status")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["node_id"] == 1
    assert data["role"] == "coordinator"
    assert data["replication_policy"] == "all"
    assert data["last_recovery"] is not None
    assert data["last_recovery"]["success"] is True


# ── 16. Recovery failure response ───────────────────────────────

def test_recovery_failure_response(client, api_runtime):
    # Configure recovery against an uncontactable peer under 'all' policy
    resp = client.post(
        "/api/recovery/start",
        json={"target_peer_ids": [2], "timeout": 0.05},
    )
    assert resp.status_code == 409
    data = resp.get_json()
    assert data["success"] is False
    assert "Recovery policy 'all' failed" in data["error"]
    assert data["role"] == "recovering"


# ── 17. Recovery start (success) ────────────────────────────────

def test_recovery_start_success(client, api_runtime):
    # Recover with empty target peers (local authoritative restoration)
    resp = client.post(
        "/api/recovery/start",
        json={"target_peer_ids": [], "timeout": 0.5},
    )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert data["role"] == "coordinator"
    assert data["is_coordinator"] is True


# ── 18. Unknown node ────────────────────────────────────────────

def test_unknown_node(client):
    resp = client.get("/api/nodes/999")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "node_not_found"


# ── 19. Unknown vote ────────────────────────────────────────────

def test_unknown_vote(client):
    resp = client.get("/api/votes/non_existent_vote_id")
    assert resp.status_code == 404
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "vote_not_found"


# ── 20. Malformed JSON ──────────────────────────────────────────

def test_malformed_json(client):
    # Non-JSON content type
    resp1 = client.post("/api/votes", data="not json", content_type="text/plain")
    assert resp1.status_code == 400
    assert resp1.get_json()["error"] == "invalid_json"

    # Malformed JSON syntax
    resp2 = client.post("/api/votes", data="{bad_json:", content_type="application/json")
    assert resp2.status_code == 400
    assert resp2.get_json()["error"] == "invalid_json"


# ── 21. Unexpected backend error mapping ────────────────────────

def test_unexpected_backend_error_mapping(client, monkeypatch, api_runtime):
    def _exploding_submit(*args, **kwargs):
        raise RuntimeError("Disk crashed unexpectedly")

    monkeypatch.setattr(api_runtime.vote_service, "submit_vote", _exploding_submit)

    resp = client.post("/api/votes", json={"client_id": "v1", "choice": "Alice"})
    assert resp.status_code == 500
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "internal_error"
    # Ensure raw Python traceback is NOT exposed
    assert "Traceback" not in resp.get_data(as_text=True)
    assert "Disk crashed" not in data["message"]


# ── 22. Replication failure mapping (503) ───────────────────────

def test_replication_failure_response(client, api_runtime):
    # Mark peer 2 as active so replication attempts fan-out to it and fails
    api_runtime.state.mark_peer_active(2)
    resp = client.post("/api/votes", json={"client_id": "voter_rep_fail", "choice": "Alice"})
    assert resp.status_code == 503
    data = resp.get_json()
    assert data["success"] is False
    assert data["error"] == "replication_failed"


# ── Observability Events ────────────────────────────────────────

def test_events_observability(client, api_runtime):
    # Submit vote to generate sync log entry
    client.post("/api/votes", json={"client_id": "event_voter", "choice": "Bob"})

    # Log an election event
    api_runtime.db.log_election_event("ELECTION_STARTED", 1, 10, election_term=1, initiator_id=1)

    resp = client.get("/api/events")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["success"] is True
    assert len(data["events"]) > 0

    # Filter by source=election
    el_resp = client.get("/api/events?source=election")
    assert el_resp.status_code == 200
    el_data = el_resp.get_json()
    assert all(e["source"] == "election" for e in el_data["events"])
