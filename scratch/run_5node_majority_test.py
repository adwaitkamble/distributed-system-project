"""Test Majority Replication Policy in 5-Node Cluster."""

import json
import time
import urllib.request
import subprocess

def test_majority_replication():
    print("=== Testing Majority Replication Policy in 5-Node Cluster ===")

    # 1. Verify policy is majority on coordinator
    with urllib.request.urlopen("http://localhost:5005/api/node", timeout=3.0) as resp:
        d = json.loads(resp.read().decode())
        assert d["replication_policy"] == "majority", f"Expected majority, got {d['replication_policy']}"
        coord_id = d["coordinator_id"]

    print(f"Coordinator is Node {coord_id} under majority policy")

    # 2. Stop 2 follower nodes (e.g., node1 and node2)
    print("Stopping follower containers voting-node1 and voting-node2 (leaving 3 alive out of 5)...")
    subprocess.run(["docker", "stop", "voting-node1", "voting-node2"], check=True)

    # 3. Submit a vote to the coordinator
    coord_port = 5000 + coord_id
    client_id = f"voter_5node_majority_{int(time.time())}"
    payload = json.dumps({"client_id": client_id, "choice": "Charlie"}).encode()
    req = urllib.request.Request(
        f"http://localhost:{coord_port}/api/votes",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        res = json.loads(resp.read().decode())
        print(f"Vote submitted under majority policy: {res}")
        assert res["success"] is True

    # 4. Verify vote committed in the 3 surviving database containers
    surviving_dbs = [f"voting-node{nid}-db" for nid in (3, 4, 5)]
    for db in surviving_dbs:
        cmd = [
            "docker", "exec", db,
            "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
            "-e", f"SELECT status, choice FROM votes WHERE client_id='{client_id}';"
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = p.stdout.strip()
        print(f"  {db} row for {client_id}: {out}")
        assert "COMMITTED" in out and "Charlie" in out

    print("✓ Majority replication succeeded with 2 nodes down (quorum 3/5 achieved)!")

    # 5. Restart the 2 stopped followers
    print("Restarting voting-node1 and voting-node2...")
    subprocess.run(["docker", "start", "voting-node1", "voting-node2"], check=True)
    print("Waiting for node restart and auto-catchup (up to 10s)...")
    for db in ("voting-node1-db", "voting-node2-db"):
        deadline = time.monotonic() + 10.0
        synced = False
        while time.monotonic() < deadline:
            cmd = [
                "docker", "exec", db,
                "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                "-e", f"SELECT status, choice FROM votes WHERE client_id='{client_id}';"
            ]
            p = subprocess.run(cmd, capture_output=True, text=True, check=True)
            out = p.stdout.strip()
            if "COMMITTED" in out and "Charlie" in out:
                synced = True
                print(f"  Rejoined {db} row for {client_id}: {out}")
                break
            time.sleep(1.0)
        assert synced, f"Node DB {db} failed to catch up missing state within deadline!"

    print("✓ Rejoined nodes successfully caught up missing state from coordinator!")
    print("=== Majority Replication Policy Test PASSED ===\n")

if __name__ == "__main__":
    test_majority_replication()
