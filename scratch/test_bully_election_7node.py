import urllib.request
import urllib.error
import json
import subprocess
import time

print("1. Verifying initial coordinator is Node 7...")
with urllib.request.urlopen("http://localhost:5007/api/node", timeout=2.0) as resp:
    d = json.loads(resp.read().decode("utf-8"))
    assert d["is_coordinator"] is True
    assert d["node_id"] == 7
    term7 = d["election_term"]
    print(f"Node 7 is coordinator (term={term7})")

print("2. Stopping Node 7 (coordinator failure)...")
subprocess.run(["docker", "stop", "voting-node7"], check=True)

try:
    print("3. Waiting for Bully re-election among surviving nodes (1..6)...")
    deadline = time.monotonic() + 20.0
    new_coord_id = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:5006/api/node", timeout=2.0) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d.get("role") == "recovering":
                    try:
                        req = urllib.request.Request("http://localhost:5006/api/recovery/start", data=b"{}", headers={"Content-Type": "application/json"})
                        urllib.request.urlopen(req, timeout=2.0)
                    except Exception:
                        pass
                if d.get("is_coordinator") and d.get("accepting_votes"):
                    new_coord_id = d["node_id"]
                    break
        except Exception:
            pass
        time.sleep(1.0)

    assert new_coord_id == 6, f"Expected Node 6 as new coordinator, got {new_coord_id}"
    print(f"Node 6 successfully elected coordinator! (highest survivor among 1..6)")

    # 4. Verify all surviving nodes agree on Node 6 as coordinator (no split-brain)
    time.sleep(2.0)
    for nid in range(1, 7):
        port = 5000 + nid
        with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=2.0) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            assert d["coordinator_id"] == 6, f"Node {nid} has coord {d['coordinator_id']} instead of 6"
            if nid != 6:
                assert d["role"] == "follower"
                assert not d["is_coordinator"]
    print("All surviving nodes (1..5) unanimously acknowledge Node 6 as coordinator (0 split-brain)")

    # 5. Submit new vote to new coordinator (Node 6)
    cid_new = f"bully_failover_vote_{int(time.time())}"
    p = json.dumps({"client_id": cid_new, "choice": "Alice"}).encode("utf-8")
    req = urllib.request.Request("http://localhost:5006/api/votes", data=p, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        assert resp.status == 201
        print("New vote submitted and committed on new coordinator Node 6!")

    # Verify committed across surviving nodes DBs
    for nid in range(1, 7):
        cmd = ["docker", "exec", f"voting-node{nid}-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN", "-e", f"SELECT status FROM votes WHERE client_id='{cid_new}';"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert "COMMITTED" in res.stdout
    print("Vote replicated and COMMITTED in all surviving databases (1..6)")

finally:
    # 6. Restart Node 7
    print("Restarting Node 7...")
    subprocess.run(["docker", "start", "voting-node7"], check=True)
    time.sleep(5.0)

    # Ensure Node 7 takes over as highest ID node
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://localhost:5007/api/node", timeout=2.0) as resp:
                d = json.loads(resp.read().decode("utf-8"))
                if d.get("role") == "recovering":
                    try:
                        req = urllib.request.Request("http://localhost:5007/api/recovery/start", data=b"{}", headers={"Content-Type": "application/json"})
                        urllib.request.urlopen(req, timeout=2.0)
                    except Exception:
                        pass
                if d.get("is_coordinator") and d.get("accepting_votes"):
                    break
        except Exception:
            pass
        time.sleep(1.0)

    # Verify Node 7 DB caught up the vote cast while offline
    cmd = ["docker", "exec", "voting-node7-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN", "-e", f"SELECT status FROM votes WHERE client_id='{cid_new}';"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert "COMMITTED" in res.stdout, f"Node 7 DB failed to catch up vote: got '{res.stdout}'"
    print("Node 7 DB caught up vote cast during offline period: COMMITTED")

print("Bully election on 7 nodes verified successfully!")
