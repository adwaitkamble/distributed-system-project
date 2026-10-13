import json
import subprocess
import time
import urllib.error
import urllib.request

def run_tests():
    print("=== Testing Tasks 5, 6, 7 under REPLICATION_POLICY=majority ===")

    # Dynamically find current coordinator
    coord_id = None
    coord_port = None
    for p in (5001, 5002, 5003, 5004, 5005):
        try:
            with urllib.request.urlopen(f"http://localhost:{p}/api/node", timeout=2.0) as resp:
                d = json.loads(resp.read().decode())
                if d.get("is_coordinator") and d.get("accepting_votes"):
                    coord_id = d["node_id"]
                    coord_port = p
                    break
        except Exception:
            pass
    assert coord_id is not None, "No active coordinator found"
    print(f"Current active coordinator: Node {coord_id} on port {coord_port}")

    # ─────────────────────────────────────────────────────────────────
    # TASK 5 CASE A: Exactly 3 nodes alive (stop 2 followers: 1 and 2)
    # ─────────────────────────────────────────────────────────────────
    print("\n--- Task 5 Case A: Exactly 3 nodes alive (quorum 3/5) ---")
    subprocess.run(["docker", "stop", "voting-node1", "voting-node2"], check=True)
    time.sleep(1.0)

    cid_q3 = f"voter_q3_{int(time.time())}"
    payload_q3 = json.dumps({"client_id": cid_q3, "choice": "Alice"}).encode()
    req = urllib.request.Request(f"http://localhost:{coord_port}/api/votes", data=payload_q3, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        res = json.loads(resp.read().decode())
        print(f"Vote with 3 alive submitted: {res}")
        assert res["success"] is True

    # Verify committed on active nodes 3, 4, 5
    for nid in (3, 4, 5):
        cmd = [
            "docker", "exec", f"voting-node{nid}-db",
            "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
            "-e", f"SELECT status, choice FROM votes WHERE client_id='{cid_q3}';"
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, check=True)
        assert "COMMITTED" in p.stdout and "Alice" in p.stdout
    print("Task 5 Case A PASSED: 3 alive (3 >= 3) committed vote.")

    # ─────────────────────────────────────────────────────────────────
    # TASK 5 CASE B: Only 2 nodes alive (stop node 3, leaving 4 and 5)
    # ─────────────────────────────────────────────────────────────────
    print("\n--- Task 5 Case B: Only 2 nodes alive (quorum lost: 2 < 3) ---")
    subprocess.run(["docker", "stop", "voting-node3"], check=True)
    time.sleep(1.0)

    cid_q2 = f"voter_q2_{int(time.time())}"
    payload_q2 = json.dumps({"client_id": cid_q2, "choice": "Bob"}).encode()
    req = urllib.request.Request(f"http://localhost:{coord_port}/api/votes", data=payload_q2, headers={"Content-Type": "application/json"})

    rejected = False
    try:
        urllib.request.urlopen(req, timeout=5.0)
    except urllib.error.HTTPError as e:
        print(f"Expected HTTP failure received: HTTP {e.code} - {e.read().decode()}")
        assert e.code in (503, 409)
        rejected = True

    assert rejected, "Vote with 2 alive should have been rejected due to quorum loss!"

    # Verify vote did NOT become COMMITTED on coordinator DB
    cmd = [
        "docker", "exec", f"voting-node{coord_id}-db",
        "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
        "-e", f"SELECT status FROM votes WHERE client_id='{cid_q2}';"
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = p.stdout.strip()
    print(f"Coordinator DB status for rejected vote {cid_q2}: {out}")
    assert "COMMITTED" not in out
    print("Task 5 Case B PASSED: 2 alive (< 3) rejected vote; no phantom commit.")

    # ─────────────────────────────────────────────────────────────────
    # TASK 7: REJOIN AFTER QUORUM LOSS
    # ─────────────────────────────────────────────────────────────────
    print("\n--- Task 7: Rejoin after Quorum Loss ---")
    # Currently 2 alive (4, 5). Rejoin node 3 -> 3 alive (3, 4, 5)
    print("Restarting node 3 to restore quorum...")
    subprocess.run(["docker", "start", "voting-node3"], check=True)
    time.sleep(4.0)

    cid_q_restored = f"voter_q_restored_{int(time.time())}"
    payload_q_res = json.dumps({"client_id": cid_q_restored, "choice": "Charlie"}).encode()
    req = urllib.request.Request(f"http://localhost:{coord_port}/api/votes", data=payload_q_res, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        res = json.loads(resp.read().decode())
        print(f"Vote after quorum restoration submitted: {res}")
        assert res["success"] is True

    # Restart remaining followers 1 and 2
    print("Restarting nodes 1 and 2 to restore full 5-node cluster...")
    subprocess.run(["docker", "start", "voting-node1", "voting-node2"], check=True)
    time.sleep(6.0)

    # Check complete convergence on all 5 databases for cid_q3 and cid_q_restored
    for cid in (cid_q3, cid_q_restored):
        for nid in (1, 2, 3, 4, 5):
            deadline = time.monotonic() + 12.0
            synced = False
            while time.monotonic() < deadline:
                cmd = [
                    "docker", "exec", f"voting-node{nid}-db",
                    "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
                    "-e", f"SELECT status FROM votes WHERE client_id='{cid}';"
                ]
                p = subprocess.run(cmd, capture_output=True, text=True)
                if "COMMITTED" in p.stdout:
                    synced = True
                    break
                time.sleep(1.0)
            assert synced, f"Node {nid} failed to synchronize {cid}"
    print("Task 7 PASSED: Quorum dynamically restored; full cluster converged.")

    # ─────────────────────────────────────────────────────────────────
    # TASK 6: SEQUENTIAL FAILURE SCENARIO
    # ─────────────────────────────────────────────────────────────────
    print("\n--- Task 6: Sequential Failure Scenario ---")
    # All 5 nodes alive.
    # 1. Coordinator failure: kill node 5
    print("Step 1: Coordinator failure (stopping Node 5)...")
    subprocess.run(["docker", "stop", "voting-node5"], check=True)

    # Wait for Bully election to elect Node 4
    deadline = time.monotonic() + 15.0
    new_coord = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:5004/api/node", timeout=2.0) as resp:
                d = json.loads(resp.read().decode())
                if d.get("is_coordinator") and d.get("accepting_votes"):
                    new_coord = d["node_id"]
                    break
        except Exception:
            pass
        time.sleep(1.0)
    assert new_coord == 4, f"Expected Node 4 as coordinator, got {new_coord}"
    print(f"New coordinator elected: Node {new_coord}")

    # 2. Submit vote on 4-node active cluster (nodes 1, 2, 3, 4)
    cid_seq1 = f"voter_seq1_{int(time.time())}"
    payload_s1 = json.dumps({"client_id": cid_seq1, "choice": "Alice"}).encode()
    req = urllib.request.Request("http://localhost:5004/api/votes", data=payload_s1, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        res = json.loads(resp.read().decode())
        assert res["success"] is True
    print(f"Step 2: Vote submitted on 4 nodes active: {res['success']}")

    # 3. Follower failure: kill node 1 (leaving 3 nodes: 2, 3, 4 -> quorum 3/5 met)
    print("Step 3: Follower failure (stopping Node 1)...")
    subprocess.run(["docker", "stop", "voting-node1"], check=True)
    time.sleep(1.0)

    cid_seq2 = f"voter_seq2_{int(time.time())}"
    payload_s2 = json.dumps({"client_id": cid_seq2, "choice": "Bob"}).encode()
    req = urllib.request.Request("http://localhost:5004/api/votes", data=payload_s2, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        res = json.loads(resp.read().decode())
        assert res["success"] is True
    print(f"Step 4: Vote submitted on 3 nodes active (boundary): {res['success']}")

    # 4. Additional failure: kill node 2 (leaving 2 nodes: 3, 4 -> quorum 2 < 3 LOST)
    print("Step 5: Additional failure (stopping Node 2, leaving 2 alive)...")
    subprocess.run(["docker", "stop", "voting-node2"], check=True)
    time.sleep(1.0)

    cid_seq3 = f"voter_seq3_{int(time.time())}"
    payload_s3 = json.dumps({"client_id": cid_seq3, "choice": "Charlie"}).encode()
    req = urllib.request.Request("http://localhost:5004/api/votes", data=payload_s3, headers={"Content-Type": "application/json"})
    rej = False
    try:
        urllib.request.urlopen(req, timeout=5.0)
    except urllib.error.HTTPError as e:
        assert e.code in (503, 409)
        rej = True
    assert rej, "Vote must be rejected when quorum boundary breached (2 < 3)!"
    print("Step 6: Vote successfully rejected when 2 nodes active (insufficient majority).")

    # Clean up: restart stopped nodes (1, 2, 5)
    print("\nRecovering cluster: restarting nodes 1, 2, 5...")
    subprocess.run(["docker", "start", "voting-node1", "voting-node2", "voting-node5"], check=True)
    time.sleep(6.0)

    # Let Bully election re-elect Node 5
    req = urllib.request.Request("http://localhost:5005/api/election/start", data=b"{}", headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=3.0)
    except Exception:
        pass
    time.sleep(3.0)

    print("Task 6 PASSED: Sequential failure sequence verified.")
    print("\n=== ALL TASKS 5, 6, 7 TESTS COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_tests()
