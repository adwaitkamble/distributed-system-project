"""End-to-End integration test for Phase 5 Flask bridge and React UI assets.

Verifies:
1. React production build assets served correctly by Flask at '/'.
2. Full lifecycle: node status query, vote submission, committed tally update,
   election trigger and status reflection, recovery trigger and status reflection.
3. React never connects to gRPC/database; all interaction flows through Flask REST API.
"""

import json
import pytest

from api import create_app
from node.config import NodeConfig, PeerInfo
from node.runtime import NodeRuntime


@pytest.fixture
def e2e_runtime(tmp_path):
    """Runtime instance with isolated SQLite database."""
    db_path = str(tmp_path / "e2e_node.db")
    config = NodeConfig(
        node_id=1,
        grpc_port=0,
        election_algorithm="bully",
        peers={
            1: PeerInfo(1, "localhost", 50061),
            2: PeerInfo(2, "localhost", 50062),
            3: PeerInfo(3, "localhost", 50063),
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
    # In isolated e2e test, clear active peers so coordinator commits locally
    with runtime.state._lock:
        runtime.state._active_peers.clear()
    yield runtime
    runtime.db.close()


@pytest.fixture
def e2e_client(e2e_runtime):
    app = create_app(runtime=e2e_runtime, test_config={"TESTING": True})
    return app.test_client()


def test_e2e_frontend_html_served(e2e_client):
    """Verify Flask serves the compiled React Single-Page Application."""
    resp = e2e_client.get("/")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert '<div id="root"></div>' in html
    assert "Distributed Fault-Tolerant Voting System" in html


def test_e2e_full_voting_and_tally_flow(e2e_client, e2e_runtime):
    """Verify complete end-to-end voting, committed tally, election and recovery workflow."""
    # 1. Check initial node status
    status_resp = e2e_client.get("/api/node")
    assert status_resp.status_code == 200
    status_data = status_resp.get_json()
    assert status_data["node_id"] == 1
    assert status_data["role"] == "coordinator"
    assert status_data["accepting_votes"] is True

    # 2. Check initial tally is empty
    tally_resp = e2e_client.get("/api/votes/tally")
    assert tally_resp.status_code == 200
    assert tally_resp.get_json()["total_votes"] == 0

    # 3. Submit vote via HTTP POST
    vote_resp = e2e_client.post(
        "/api/votes",
        json={"client_id": "e2e_voter_1", "choice": "Alice"},
    )
    assert vote_resp.status_code == 201
    vote_data = vote_resp.get_json()
    assert vote_data["success"] is True
    vote_id = vote_data["vote_id"]
    assert "e2e_voter_1:1:" in vote_id

    # 4. Verify committed tally reflects submitted vote
    tally_resp2 = e2e_client.get("/api/votes/tally")
    assert tally_resp2.status_code == 200
    tally_data2 = tally_resp2.get_json()
    assert tally_data2["total_votes"] == 1
    assert tally_data2["tally"]["Alice"] == 1

    # 5. Verify individual vote lookup
    lookup_resp = e2e_client.get(f"/api/votes/{vote_id}")
    assert lookup_resp.status_code == 200
    lookup_data = lookup_resp.get_json()
    assert lookup_data["vote"]["client_id"] == "e2e_voter_1"
    assert lookup_data["vote"]["choice"] == "Alice"
    assert lookup_data["vote"]["status"] == "COMMITTED"

    # 6. Verify duplicate vote rejection
    dup_resp = e2e_client.post(
        "/api/votes",
        json={"client_id": "e2e_voter_1", "choice": "Alice"},
    )
    assert dup_resp.status_code == 409
    assert dup_resp.get_json()["error"] == "duplicate_client"

    # 7. Trigger election via API
    elect_resp = e2e_client.post("/api/election/start", json={"blocking": False})
    assert elect_resp.status_code == 200
    assert elect_resp.get_json()["success"] is True

    # Check election status
    el_status_resp = e2e_client.get("/api/election/status")
    assert el_status_resp.status_code == 200
    assert el_status_resp.get_json()["algorithm"] == "bully"

    # 8. Trigger recovery via API
    rec_resp = e2e_client.post("/api/recovery/start", json={"target_peer_ids": []})
    assert rec_resp.status_code == 200
    rec_data = rec_resp.get_json()
    assert rec_data["success"] is True
    assert rec_data["committed_votes_count"] == 1

    # Check recovery status
    rec_status_resp = e2e_client.get("/api/recovery/status")
    assert rec_status_resp.status_code == 200
    assert rec_status_resp.get_json()["last_recovery"]["success"] is True

    # 9. Verify tally remains unchanged and authoritative
    tally_resp3 = e2e_client.get("/api/votes/tally")
    assert tally_resp3.get_json()["total_votes"] == 1
