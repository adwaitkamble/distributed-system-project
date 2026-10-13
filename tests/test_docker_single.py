"""Phase 6.1 — Docker single-node verification tests.

Validates that the single-node container deployment satisfies:
1. HTTP REST Bridge connectivity (/api/health, /api/node, /api/nodes, /api/election/status, /api/recovery/status, /api/votes/tally)
2. gRPC connectivity (Heartbeat, GetClusterStatus, GetResults)
3. React production build hosting at GET /
4. Real vote submission and COMMITTED finalization against isolated MySQL container
"""

import json
import urllib.error
import urllib.request
import pytest
import grpc

from node.generated import voting_pb2, voting_pb2_grpc


def _is_single_node_running() -> bool:
    try:
        with urllib.request.urlopen("http://localhost:5000/api/health", timeout=1.0) as resp:
            return resp.status == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_single_node_running(),
    reason="Docker single-node container (voting-node1) is not running on localhost:5000",
)


class TestDockerSingleNode:
    """Verifies that the live Docker container correctly executes NodeRuntime, gRPC, Flask, and DB."""

    BASE_URL = "http://localhost:5000"
    GRPC_TARGET = "localhost:50051"

    def test_http_health_endpoint(self):
        url = f"{self.BASE_URL}/api/health"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["status"] == "ok"
            assert data["node_id"] == 1

    def test_http_node_status(self):
        url = f"{self.BASE_URL}/api/node"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["node_id"] == 1
            assert data["is_coordinator"] is True
            assert data["role"] == "coordinator"
            assert data["accepting_votes"] is True

    def test_http_cluster_topology(self):
        url = f"{self.BASE_URL}/api/nodes"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["success"] is True
            assert data["total_nodes"] == 1
            assert data["current_coordinator_id"] == 1

    def test_http_election_status(self):
        url = f"{self.BASE_URL}/api/election/status"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["success"] is True
            assert data["current_coordinator"] == 1
            assert data["algorithm"] == "bully"

    def test_http_recovery_status(self):
        url = f"{self.BASE_URL}/api/recovery/status"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["success"] is True
            assert data["is_recovering"] is False

    def test_react_frontend_served(self):
        url = f"{self.BASE_URL}/"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "<!doctype html>" in content.lower()
            assert "html" in content

    def test_grpc_connectivity(self):
        channel = grpc.insecure_channel(self.GRPC_TARGET)
        stub = voting_pb2_grpc.NodeServiceStub(channel)

        ping = voting_pb2.HeartbeatPing(
            coordinator_id=1,
            lamport_ts=1,
            election_term=0,
            initiator_id=0,
        )
        pong = stub.Heartbeat(ping, timeout=3.0)
        assert pong.node_id == 1

        status = stub.GetClusterStatus(voting_pb2.Empty(), timeout=3.0)
        assert status.this_node_id == 1
        assert status.role == "coordinator"
        assert status.accepting_votes is True
        channel.close()

    def test_vote_submission_and_committed_tally(self):
        client_id = f"test_voter_automated_{id(self)}"
        vote_payload = json.dumps({"client_id": client_id, "choice": "Charlie"}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.BASE_URL}/api/votes",
            data=vote_payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            assert resp.status == 201
            result = json.loads(resp.read().decode("utf-8"))
            assert result["success"] is True
            assert result["client_id"] == client_id
            assert result["choice"] == "Charlie"
            assert result["vote_id"].startswith(f"{client_id}:1:")

        # Verify tally reflects the vote
        with urllib.request.urlopen(f"{self.BASE_URL}/api/votes/tally", timeout=3.0) as resp:
            assert resp.status == 200
            tally_data = json.loads(resp.read().decode("utf-8"))
            assert tally_data["success"] is True
            assert tally_data["tally"].get("Charlie", 0) >= 1
