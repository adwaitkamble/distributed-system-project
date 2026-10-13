import urllib.request
import urllib.error
import json
import subprocess
import time

# 1. Submit valid vote to Coordinator (Node 7)
cid = f"voter_7node_{int(time.time())}"
payload = json.dumps({"client_id": cid, "choice": "Alice"}).encode("utf-8")
req = urllib.request.Request("http://localhost:5007/api/votes", data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=5.0) as resp:
    assert resp.status == 201
    d = json.loads(resp.read().decode("utf-8"))
    assert d["success"] is True
    assert d["client_id"] == cid
    print(f"Vote submitted successfully: vote_id={d['vote_id']}")

# 2. Check tally on Coordinator
with urllib.request.urlopen("http://localhost:5007/api/votes/tally", timeout=2.0) as resp:
    tally_data = json.loads(resp.read().decode("utf-8"))
    assert tally_data["tally"]["Alice"] >= 1
    print(f"Coordinator tally: {tally_data['tally']}")

# 3. Check replication across all 7 MySQL databases
for nid in range(1, 8):
    container = f"voting-node{nid}-db"
    cmd = [
        "docker", "exec", container,
        "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
        "-e", f"SELECT status FROM votes WHERE client_id='{cid}';"
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    status = proc.stdout.strip()
    assert "COMMITTED" in status, f"Node {nid} DB missing or not COMMITTED: got '{status}'"
    print(f"Node {nid} DB: COMMITTED")

# 4. Check Follower node rejects write with redirect hint
req_f = urllib.request.Request("http://localhost:5001/api/votes", data=payload, headers={"Content-Type": "application/json"})
try:
    urllib.request.urlopen(req_f, timeout=2.0)
    assert False, "Follower should have rejected vote!"
except urllib.error.HTTPError as err:
    assert err.code == 409
    body = json.loads(err.read().decode("utf-8"))
    assert body["error"] == "not_coordinator"
    assert body["coordinator_id"] == 7
    print("Follower node 1 correctly rejected write with 409 and coordinator_id=7")

# 5. Check duplicate client vote is rejected
try:
    urllib.request.urlopen(req, timeout=2.0)
    assert False, "Duplicate voter should have been rejected!"
except urllib.error.HTTPError as err:
    assert err.code == 409
    body = json.loads(err.read().decode("utf-8"))
    assert body["error"] == "duplicate_client"
    print("Duplicate voter correctly rejected with 409")

print("Seven-node voting and replication verified successfully!")
