"""Test Bully Election failover in 5-node cluster with polling deadline."""

import json
import time
import urllib.request
import subprocess

def test_bully_failover():
    print("=== Testing Bully Election Failover in 5-Node Cluster ===")

    # 1. Check current coordinator
    url = "http://localhost:5001/api/election/status"
    with urllib.request.urlopen(url, timeout=3.0) as resp:
        d = json.loads(resp.read().decode())
        curr_coord = d["current_coordinator"]
        curr_term = d["election_term"]
        print(f"Initial coordinator: Node {curr_coord}, Term {curr_term}")

    # 2. Stop the current coordinator
    target_container = f"voting-node{curr_coord}"
    print(f"Stopping coordinator container {target_container}...")
    subprocess.run(["docker", "stop", target_container], check=True)

    # 3. Wait for heartbeat timeout and Bully election convergence (poll up to 15s)
    surviving_ports = [p for nid, p in [(1, 5001), (2, 5002), (3, 5003), (4, 5004), (5, 5005)] if nid != curr_coord]
    surviving_nodes = [nid for nid, p in [(1, 5001), (2, 5002), (3, 5003), (4, 5004), (5, 5005)] if nid != curr_coord]
    highest_survivor = max(surviving_nodes)

    print(f"Surviving nodes: {surviving_nodes}. Highest surviving node: {highest_survivor}")
    print("Polling surviving nodes for new coordinator convergence (up to 15s)...")

    deadline = time.monotonic() + 15.0
    new_coord = None
    while time.monotonic() < deadline:
        coords = set()
        terms = set()
        for port in surviving_ports:
            try:
                url = f"http://localhost:{port}/api/election/status"
                with urllib.request.urlopen(url, timeout=2.0) as resp:
                    d = json.loads(resp.read().decode())
                    coords.add(d["current_coordinator"])
                    terms.add(d["election_term"])
            except Exception:
                pass

        if len(coords) == 1 and list(coords)[0] != curr_coord and list(coords)[0] in surviving_nodes:
            new_coord = list(coords)[0]
            print(f"  Converged on coordinator Node {new_coord}, Term {list(terms)[0]} after {round(15.0 - (deadline - time.monotonic()), 1)}s")
            break
        time.sleep(1.0)

    assert new_coord is not None, f"Failed to converge on a new coordinator! Coords seen: {coords}"
    assert new_coord == highest_survivor, f"Expected node {highest_survivor} to win bully election, got {new_coord}"

    # 5. Submit a new vote to the new coordinator
    coord_port = 5000 + new_coord
    client_id = f"voter_5node_failover_{int(time.time())}"
    payload = json.dumps({"client_id": client_id, "choice": "Bob"}).encode()
    req = urllib.request.Request(
        f"http://localhost:{coord_port}/api/votes",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        res = json.loads(resp.read().decode())
        print(f"Vote submitted to new coordinator port {coord_port}: {res}")
        assert res["success"] is True

    # Check commit across surviving databases
    for nid in surviving_nodes:
        db = f"voting-node{nid}-db"
        cmd = [
            "docker", "exec", db,
            "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
            "-e", f"SELECT status, choice FROM votes WHERE client_id='{client_id}';"
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = p.stdout.strip()
        print(f"  {db} row for {client_id}: {out}")
        assert "COMMITTED" in out and "Bob" in out

    print("✓ Vote committed across all surviving nodes!")

    # 6. Restart the old coordinator
    print(f"Restarting old coordinator {target_container}...")
    subprocess.run(["docker", "start", target_container], check=True)
    print("Waiting for node restart and auto-catchup (up to 10s)...")

    # Poll old coordinator DB for state sync
    old_db = f"voting-node{curr_coord}-db"
    sync_deadline = time.monotonic() + 10.0
    synced = False
    while time.monotonic() < sync_deadline:
        cmd = [
            "docker", "exec", old_db,
            "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
            "-e", f"SELECT status, choice FROM votes WHERE client_id='{client_id}';"
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = p.stdout.strip()
        if "COMMITTED" in out and "Bob" in out:
            synced = True
            print(f"  Old coordinator DB ({old_db}) row for {client_id}: {out}")
            break
        time.sleep(1.0)

    assert synced, f"Node {curr_coord} failed to synchronize state after restart!"
    print(f"✓ Rejoin verified: Node {curr_coord} synchronized missing state!")
    print("=== Bully Failover in 5-Node Cluster PASSED ===\n")

if __name__ == "__main__":
    test_bully_failover()
