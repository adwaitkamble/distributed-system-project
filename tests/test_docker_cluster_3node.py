"""Phase 6.2 / 6.3 — Live Docker 3-node cluster automated verification tests.

Validates that the 3-node cluster (node1, node2, node3) behaves correctly in Docker:
1. All three nodes are healthy and discover each other over voting-net.
2. One unified coordinator is elected and acknowledged across all nodes.
3. Votes submitted to coordinator replicate and commit across all 3 isolated MySQL databases.
4. Follower nodes reject votes with 409 and redirect hints.
5. Duplicate client votes are rejected with 409.
"""

import json
import urllib.error
import urllib.request
import pytest
import subprocess


def _is_3node_cluster_running() -> bool:
    try:
        for port in (5001, 5002, 5003):
            with urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=1.0) as resp:
                if resp.status != 200:
                    return False
        with urllib.request.urlopen("http://localhost:5001/api/nodes", timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("total_nodes") != 3:
                return False
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_3node_cluster_running(),
    reason="Docker 3-node cluster is not running on localhost:5001-5003",
)


class TestDockerCluster3Node:
    """Verifies live 3-node Docker cluster operation."""

    NODES = [(1, 5001), (2, 5002), (3, 5003)]

    def test_all_nodes_healthy_and_topologically_consistent(self):
        coordinators = []
        for nid, port in self.NODES:
            url = f"http://localhost:{port}/api/node"
            with urllib.request.urlopen(url, timeout=3.0) as resp:
                assert resp.status == 200
                d = json.loads(resp.read().decode("utf-8"))
                assert d["node_id"] == nid
                if d["is_coordinator"]:
                    coordinators.append(nid)

            # Check cluster topology view
            url_nodes = f"http://localhost:{port}/api/nodes"
            with urllib.request.urlopen(url_nodes, timeout=3.0) as resp:
                assert resp.status == 200
                topo = json.loads(resp.read().decode("utf-8"))
                assert topo["total_nodes"] == 3

        # Exactly one node must be coordinator
        assert len(coordinators) == 1, f"Expected 1 coordinator, got {coordinators}"

    def test_election_consensus_across_cluster(self):
        terms = set()
        coord_ids = set()
        for nid, port in self.NODES:
            url = f"http://localhost:{port}/api/election/status"
            with urllib.request.urlopen(url, timeout=3.0) as resp:
                assert resp.status == 200
                d = json.loads(resp.read().decode("utf-8"))
                coord_ids.add(d["current_coordinator"])
                terms.add(d["election_term"])

        # All nodes must agree on coordinator ID
        assert len(coord_ids) == 1

    def test_vote_submission_and_cluster_replication(self):
        # Identify coordinator port
        coord_port = None
        for nid, port in self.NODES:
            with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=3.0) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d["is_coordinator"]:
                    coord_port = port
                    break

        assert coord_port is not None, "No coordinator found in cluster"

        client_id = f"docker_clustertest_{id(self)}"
        payload = json.dumps({"client_id": client_id, "choice": "Alice"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://localhost:{coord_port}/api/votes",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            assert resp.status == 201
            res = json.loads(resp.read().decode("utf-8"))
            assert res["success"] is True
            assert res["client_id"] == client_id

        # Verify committed in coordinator tally
        with urllib.request.urlopen(f"http://localhost:{coord_port}/api/votes/tally", timeout=3.0) as resp:
            tally_data = json.loads(resp.read().decode("utf-8"))
            assert tally_data["success"] is True
            assert tally_data["tally"].get("Alice", 0) >= 1

        # Check replication across isolated MySQL databases
        for db_container in ("voting-node1-db", "voting-node2-db", "voting-node3-db"):
            cmd = [
                "docker", "exec", db_container,
                "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                "-e", f"SELECT status FROM votes WHERE client_id='{client_id}';"
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            assert proc.returncode == 0
            assert "COMMITTED" in proc.stdout

    def test_duplicate_vote_rejected(self):
        coord_port = None
        for nid, port in self.NODES:
            with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=3.0) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d["is_coordinator"]:
                    coord_port = port
                    break

        client_id = f"docker_dup_{id(self)}"
        payload1 = json.dumps({"client_id": client_id, "choice": "Alice"}).encode("utf-8")
        req1 = urllib.request.Request(
            f"http://localhost:{coord_port}/api/votes",
            data=payload1,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req1, timeout=3.0) as resp1:
            assert resp1.status == 201

        # Attempt second vote with same client_id but conflicting choice
        payload2 = json.dumps({"client_id": client_id, "choice": "Bob"}).encode("utf-8")
        req2 = urllib.request.Request(
            f"http://localhost:{coord_port}/api/votes",
            data=payload2,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req2, timeout=3.0)

        assert exc_info.value.code == 409
        err_data = json.loads(exc_info.value.read().decode("utf-8"))
        assert err_data["error"] == "duplicate_client"

    def test_follower_rejects_vote_with_hint(self):
        follower_port = None
        coord_id = None
        for nid, port in self.NODES:
            with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=3.0) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if not d["is_coordinator"]:
                    follower_port = port
                    coord_id = d["coordinator_id"]
                    break

        assert follower_port is not None

        payload = json.dumps({"client_id": f"follower_voter_{id(self)}", "choice": "Bob"}).encode("utf-8")
        req = urllib.request.Request(
            f"http://localhost:{follower_port}/api/votes",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req, timeout=3.0)

        assert exc_info.value.code == 409
        err_data = json.loads(exc_info.value.read().decode("utf-8"))
        assert err_data["error"] == "not_coordinator"
        assert err_data["coordinator_id"] == coord_id
