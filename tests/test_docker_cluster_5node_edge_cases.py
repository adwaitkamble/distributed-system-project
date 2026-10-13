"""Phase 6.7 — Live Docker 5-node cluster edge-case hardening and verification tests.

Verifies:
- Task 2: Coordinator change during AutoFollowerSync (failover & recovery race).
- Task 3: Two followers rejoin simultaneously and synchronize state.
- Task 4: 5-node ALL replication policy and active-peer snapshot handling.
- Tasks 5, 6, 7: Quorum boundary (active peer snapshot vs failure rejection, rejoin restores consensus).
"""

import json
import subprocess
import time
import urllib.error
import urllib.request
import pytest


def _is_5node_cluster_running() -> bool:
    try:
        for port in (5001, 5002, 5003, 5004, 5005):
            with urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=1.0) as resp:
                if resp.status != 200:
                    return False
        with urllib.request.urlopen("http://localhost:5001/api/nodes", timeout=1.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("total_nodes") != 5:
                return False
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _is_5node_cluster_running(),
    reason="Docker 5-node cluster is not running on localhost:5001-5005",
)


class TestDocker5NodeEdgeCases:
    """Verifies live distributed edge cases in the 5-node Docker cluster."""

    def _ensure_cluster_healthy(self):
        """Ensure all 5 node containers are running, healthy, and coordinator is promoted."""
        subprocess.run(["docker", "start", "voting-node1", "voting-node2", "voting-node3", "voting-node4", "voting-node5"])
        deadline = time.monotonic() + 15.0
        while time.monotonic() < deadline:
            try:
                all_up = True
                for p in (5001, 5002, 5003, 5004, 5005):
                    with urllib.request.urlopen(f"http://localhost:{p}/api/health", timeout=1.0) as resp:
                        if resp.status != 200:
                            all_up = False
                            break
                if all_up:
                    break
            except Exception:
                pass
            time.sleep(1.0)

        # Ensure Node 5 is promoted and actively accepting votes
        coord_deadline = time.monotonic() + 15.0
        while time.monotonic() < coord_deadline:
            try:
                with urllib.request.urlopen("http://localhost:5005/api/node", timeout=2.0) as resp:
                    d = json.loads(resp.read().decode("utf-8"))
                    if d.get("role") == "recovering":
                        try:
                            req = urllib.request.Request("http://localhost:5005/api/recovery/start", data=b"{}", headers={"Content-Type": "application/json"})
                            urllib.request.urlopen(req, timeout=2.0)
                        except Exception:
                            pass
                    if d.get("is_coordinator") and d.get("accepting_votes"):
                        break
            except Exception:
                pass
            time.sleep(0.5)
        time.sleep(1.0)

    def _get_coordinator_info(self, timeout: float = 10.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for port in (5005, 5004, 5003, 5002, 5001):
                try:
                    with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=2.0) as resp:
                        d = json.loads(resp.read().decode("utf-8"))
                        if d.get("role") == "recovering":
                            try:
                                req = urllib.request.Request(f"http://localhost:{port}/api/recovery/start", data=b"{}", headers={"Content-Type": "application/json"})
                                urllib.request.urlopen(req, timeout=2.0)
                            except Exception:
                                pass
                            # Do not fall through to lower nodes if this higher node is recovering
                            break
                        if d.get("is_coordinator") and d.get("accepting_votes"):
                            return d["node_id"], port
                except Exception:
                    pass
            time.sleep(0.5)
        return None, None

    def test_task2_coordinator_change_during_autofollowersync(self):
        """Task 2: Coordinator fails during follower recovery; follower adopts new coordinator and syncs."""
        self._ensure_cluster_healthy()
        coord_id, coord_port = self._get_coordinator_info()
        assert coord_id == 5

        # 1. Stop Node 1
        subprocess.run(["docker", "stop", "voting-node1"], check=True)
        time.sleep(4.5)

        try:
            # 2. Cast Vote 1 on Node 5 while Node 1 is offline
            cid1 = f"t2_coord_change_v1_{int(time.time())}"
            p1 = json.dumps({"client_id": cid1, "choice": "Alice"}).encode("utf-8")
            req1 = urllib.request.Request(f"http://localhost:5005/api/votes", data=p1, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req1, timeout=5.0) as resp:
                assert resp.status == 201

            # 3. Restart Node 1 and immediately crash Node 5 (coordinator crash during follower sync)
            subprocess.run(["docker", "start", "voting-node1"], check=True)
            time.sleep(0.5)
            subprocess.run(["docker", "stop", "voting-node5"], check=True)

            # 4. Wait for election convergence among surviving nodes (1, 2, 3, 4) -> Node 4 must win
            deadline = time.monotonic() + 15.0
            new_coord_id = None
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen("http://localhost:5004/api/node", timeout=2.0) as resp:
                        d = json.loads(resp.read().decode("utf-8"))
                        if d.get("role") == "recovering":
                            try:
                                req = urllib.request.Request("http://localhost:5004/api/recovery/start", data=b"{}", headers={"Content-Type": "application/json"})
                                urllib.request.urlopen(req, timeout=2.0)
                            except Exception:
                                pass
                        if d.get("is_coordinator") and d.get("accepting_votes"):
                            new_coord_id = d["node_id"]
                            break
                except Exception:
                    pass
                time.sleep(1.0)
            assert new_coord_id == 4, f"Expected Node 4 as new coordinator, got {new_coord_id}"

            # 5. Verify Node 1 adopts Node 4 as coordinator and does not claim coordinator
            deadline = time.monotonic() + 15.0
            n1_adopted = False
            n1_data = {}
            while time.monotonic() < deadline:
                try:
                    with urllib.request.urlopen("http://localhost:5001/api/node", timeout=2.0) as resp:
                        n1_data = json.loads(resp.read().decode("utf-8"))
                        if n1_data.get("coordinator_id") == 4 and n1_data.get("role") == "follower":
                            n1_adopted = True
                            break
                except Exception:
                    pass
                time.sleep(1.0)
            assert n1_adopted, f"Node 1 did not adopt Node 4 as coordinator: {n1_data}"
            assert not n1_data.get("is_coordinator")

            # 6. Cast Vote 2 on new coordinator Node 4
            cid2 = f"t2_coord_change_v2_{int(time.time())}"
            p2 = json.dumps({"client_id": cid2, "choice": "Bob"}).encode("utf-8")
            req2 = urllib.request.Request(f"http://localhost:5004/api/votes", data=p2, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req2, timeout=5.0) as resp:
                assert resp.status == 201

            # 7. Verify Node 1 database synchronizes both Vote 1 and Vote 2 from Node 4
            deadline = time.monotonic() + 12.0
            n1_synced = False
            while time.monotonic() < deadline:
                cmd = [
                    "docker", "exec", "voting-node1-db",
                    "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                    "-e", f"SELECT client_id FROM votes WHERE client_id IN ('{cid1}', '{cid2}') AND status='COMMITTED';"
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                lines = [line.strip() for line in proc.stdout.strip().split("\n") if line.strip()]
                if len(lines) == 2:
                    n1_synced = True
                    break
                time.sleep(1.0)
            assert n1_synced, "Node 1 failed to catch up both votes from new coordinator Node 4"

        finally:
            self._ensure_cluster_healthy()

    def test_task3_two_followers_simultaneous_rejoin(self):
        """Task 3: Stop two followers, submit committed vote, restart both simultaneously, verify sync."""
        self._ensure_cluster_healthy()
        coord_id, coord_port = self._get_coordinator_info()
        assert coord_id is not None, "No active coordinator found"

        followers_to_stop = [nid for nid in (1, 2) if nid != coord_id][:2]
        containers_to_stop = [f"voting-node{nid}" for nid in followers_to_stop]

        # Stop both followers
        subprocess.run(["docker", "stop"] + containers_to_stop, check=True)
        time.sleep(4.5)  # Wait for coordinator heartbeat timeout to snapshot active peers

        try:
            # Cast vote to coordinator while both followers are down
            client_id = f"simul_rejoin_{int(time.time())}"
            payload = json.dumps({"client_id": client_id, "choice": "Alice"}).encode("utf-8")
            req = urllib.request.Request(
                f"http://localhost:{coord_port}/api/votes",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                assert resp.status == 201

            # Restart both followers simultaneously
            subprocess.run(["docker", "start"] + containers_to_stop, check=True)

            # Poll both rejoined databases for automatic synchronization
            for nid in followers_to_stop:
                db_container = f"voting-node{nid}-db"
                deadline = time.monotonic() + 12.0
                synced = False
                while time.monotonic() < deadline:
                    cmd = [
                        "docker", "exec", db_container,
                        "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                        "-e", f"SELECT status, choice FROM votes WHERE client_id='{client_id}';"
                    ]
                    proc = subprocess.run(cmd, capture_output=True, text=True)
                    if proc.returncode == 0 and "COMMITTED" in proc.stdout and "Alice" in proc.stdout:
                        synced = True
                        break
                    time.sleep(1.0)
                assert synced, f"Node {nid} failed to synchronize state after simultaneous rejoin"

            # Check that tallies on all 5 nodes agree
            tallies = set()
            for port in (5001, 5002, 5003, 5004, 5005):
                with urllib.request.urlopen(f"http://localhost:{port}/api/votes/tally", timeout=2.0) as resp:
                    t_data = json.loads(resp.read().decode("utf-8"))
                    tallies.add(t_data["total_votes"])
            assert len(tallies) == 1, f"Tally divergence across nodes: {tallies}"
        finally:
            self._ensure_cluster_healthy()

    def test_task4_all_replication_policy_and_peer_failure(self):
        """Task 4: Normal vote across all 5 nodes, then verify failure of one follower."""
        self._ensure_cluster_healthy()
        coord_id, coord_port = self._get_coordinator_info()
        assert coord_id is not None

        # 1. Normal vote across 5 healthy nodes
        client_id1 = f"all_policy_5node_{int(time.time())}"
        payload1 = json.dumps({"client_id": client_id1, "choice": "Bob"}).encode("utf-8")
        req1 = urllib.request.Request(
            f"http://localhost:{coord_port}/api/votes",
            data=payload1,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req1, timeout=5.0) as resp:
            assert resp.status == 201

        for nid in (1, 2, 3, 4, 5):
            cmd = [
                "docker", "exec", f"voting-node{nid}-db",
                "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                "-e", f"SELECT status FROM votes WHERE client_id='{client_id1}';"
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            assert "COMMITTED" in proc.stdout

        # 2. Stop 1 follower
        follower_id = 1 if coord_id != 1 else 2
        subprocess.run(["docker", "stop", f"voting-node{follower_id}"], check=True)

        try:
            # Immediate vote attempt before heartbeat timeout fails replication under ALL policy
            client_id_fail = f"all_fail_immediate_{int(time.time())}"
            payload_fail = json.dumps({"client_id": client_id_fail, "choice": "Alice"}).encode("utf-8")
            req_fail = urllib.request.Request(
                f"http://localhost:{coord_port}/api/votes",
                data=payload_fail,
                headers={"Content-Type": "application/json"},
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req_fail, timeout=4.0)
            assert exc_info.value.code in (409, 503)

            # Wait for coordinator to detect follower timeout (~4s) and take active snapshot
            time.sleep(4.5)

            # Subsequent vote succeeds across surviving active nodes
            client_id2 = f"all_policy_survivors_{int(time.time())}"
            payload2 = json.dumps({"client_id": client_id2, "choice": "Charlie"}).encode("utf-8")
            req2 = urllib.request.Request(
                f"http://localhost:{coord_port}/api/votes",
                data=payload2,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req2, timeout=5.0) as resp:
                assert resp.status == 201

            # Check that surviving databases committed the vote
            surviving_nids = [n for n in (1, 2, 3, 4, 5) if n != follower_id]
            for nid in surviving_nids:
                cmd = [
                    "docker", "exec", f"voting-node{nid}-db",
                    "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                    "-e", f"SELECT status FROM votes WHERE client_id='{client_id2}';"
                ]
                proc = subprocess.run(cmd, capture_output=True, text=True)
                assert "COMMITTED" in proc.stdout
        finally:
            self._ensure_cluster_healthy()

    def test_task5_6_7_quorum_boundary_and_rejoin(self):
        """Tasks 5, 6, 7: Quorum boundary (active peer snapshot vs failure rejection, rejoin restores consensus)."""
        self._ensure_cluster_healthy()
        coord_id, coord_port = self._get_coordinator_info()
        assert coord_id is not None

        non_coords = [nid for nid in (1, 2, 3, 4, 5) if nid != coord_id]
        f1, f2, f3 = non_coords[0], non_coords[1], non_coords[2]

        try:
            # Case A: Stop 2 followers, wait for active snapshot update -> 3 active nodes
            subprocess.run(["docker", "stop", f"voting-node{f1}", f"voting-node{f2}"], check=True)
            time.sleep(4.5)

            client_id_q3 = f"quorum_3alive_{int(time.time())}"
            payload_q3 = json.dumps({"client_id": client_id_q3, "choice": "Alice"}).encode("utf-8")
            req_q3 = urllib.request.Request(
                f"http://localhost:{coord_port}/api/votes",
                data=payload_q3,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req_q3, timeout=5.0) as resp:
                assert resp.status == 201

            # Case B: Stop f3 and IMMEDIATELY attempt vote (snapshot still expects f3, but f3 is down)
            subprocess.run(["docker", "stop", f"voting-node{f3}"], check=True)

            client_id_q2 = f"quorum_2alive_{int(time.time())}"
            payload_q2 = json.dumps({"client_id": client_id_q2, "choice": "Bob"}).encode("utf-8")
            req_q2 = urllib.request.Request(
                f"http://localhost:{coord_port}/api/votes",
                data=payload_q2,
                headers={"Content-Type": "application/json"},
            )
            # Replication cannot succeed when a snapshot peer fails to ACK!
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req_q2, timeout=4.0)

            assert exc_info.value.code in (409, 503)

            # Confirm that uncommitted vote does NOT exist with COMMITTED status on coordinator
            cmd = [
                "docker", "exec", f"voting-node{coord_id}-db",
                "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                "-e", f"SELECT status FROM votes WHERE client_id='{client_id_q2}';"
            ]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            assert "COMMITTED" not in proc.stdout

            # Task 7: Rejoin f3 -> restores nodes alive
            subprocess.run(["docker", "start", f"voting-node{f3}"], check=True)
            time.sleep(4.5)

            client_id_restored = f"quorum_restored_{int(time.time())}"
            payload_res = json.dumps({"client_id": client_id_restored, "choice": "Charlie"}).encode("utf-8")
            req_res = urllib.request.Request(
                f"http://localhost:{coord_port}/api/votes",
                data=payload_res,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req_res, timeout=5.0) as resp:
                assert resp.status == 201

        finally:
            self._ensure_cluster_healthy()
