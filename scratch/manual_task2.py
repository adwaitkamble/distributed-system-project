import json
import subprocess
import time
import urllib.request

print("=== Testing Task 2: Coordinator Change during AutoFollowerSync ===")

# 1. Check current coordinator (should be 5)
coord_resp = json.loads(urllib.request.urlopen("http://localhost:5005/api/node").read())
print(f"Current coordinator: Node {coord_resp['node_id']}")
assert coord_resp["node_id"] == 5

# 2. Stop Node 1
print("Stopping Node 1...")
subprocess.run(["docker", "stop", "voting-node1"], check=True)
time.sleep(4.5)

# 3. Cast Vote 1 on Node 5 while Node 1 is down
client_id_1 = f"coord_change_v1_{int(time.time())}"
payload1 = json.dumps({"client_id": client_id_1, "choice": "Alice"}).encode()
req1 = urllib.request.Request("http://localhost:5005/api/votes", data=payload1, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req1) as resp:
    print(f"Vote 1 cast on Node 5: {resp.status}")

# 4. Restart Node 1 and immediately stop Node 5
print("Restarting Node 1...")
subprocess.run(["docker", "start", "voting-node1"], check=True)
time.sleep(0.5)
print("Stopping Node 5 (coordinator crash during follower recovery)...")
subprocess.run(["docker", "stop", "voting-node5"], check=True)

# 5. Wait for Bully election to converge among nodes 1, 2, 3, 4
# Node 4 should become the new coordinator!
print("Waiting for Bully election to converge on Node 4...")
new_coord_id = None
deadline = time.monotonic() + 15.0
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen("http://localhost:5004/api/node", timeout=2.0) as resp:
            d = json.loads(resp.read().decode())
            if d.get("is_coordinator") and d.get("accepting_votes"):
                new_coord_id = d["node_id"]
                break
    except Exception:
        pass
    time.sleep(1.0)

print(f"New coordinator elected: Node {new_coord_id}")
assert new_coord_id == 4, f"Expected Node 4, got {new_coord_id}"

# 6. Check that Node 1 adopts Node 4 as coordinator and is not coordinator itself
time.sleep(3.0)
with urllib.request.urlopen("http://localhost:5001/api/node", timeout=2.0) as resp:
    n1_status = json.loads(resp.read().decode())
    print("Node 1 status:", n1_status["role"], "coord:", n1_status["coordinator_id"])
    assert n1_status["coordinator_id"] == 4
    assert n1_status["role"] == "follower"
    assert not n1_status["is_coordinator"]

# 7. Cast Vote 2 on the new coordinator (Node 4)
client_id_2 = f"coord_change_v2_{int(time.time())}"
payload2 = json.dumps({"client_id": client_id_2, "choice": "Bob"}).encode()
req2 = urllib.request.Request("http://localhost:5004/api/votes", data=payload2, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req2) as resp:
    print(f"Vote 2 cast on Node 4: {resp.status}")

# 8. Wait for Node 1 to catch up both votes from Node 4
print("Checking Node 1 database for both Vote 1 and Vote 2...")
deadline = time.monotonic() + 10.0
v1_synced = False
v2_synced = False
while time.monotonic() < deadline:
    cmd = [
        "docker", "exec", "voting-node1-db",
        "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
        "-e", f"SELECT client_id, status FROM votes WHERE client_id IN ('{client_id_1}', '{client_id_2}');"
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    out = p.stdout.strip()
    if client_id_1 in out and client_id_2 in out and "COMMITTED" in out:
        v1_synced = True
        v2_synced = True
        print("Node 1 DB contents:\n", out)
        break
    time.sleep(1.0)

assert v1_synced and v2_synced, "Node 1 failed to recover both votes from new coordinator Node 4!"
print("✓ Node 1 successfully recovered state from new coordinator Node 4!")

# 9. Restart Node 5 and wait for convergence
print("Restarting Node 5...")
subprocess.run(["docker", "start", "voting-node5"], check=True)
time.sleep(6.0)

# Check all DBs for consistency
for nid in (1, 2, 3, 4, 5):
    cmd = [
        "docker", "exec", f"voting-node{nid}-db",
        "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
        "-e", f"SELECT client_id, status FROM votes WHERE client_id IN ('{client_id_1}', '{client_id_2}');"
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    lines = [line.strip() for line in p.stdout.strip().split("\n") if line.strip()]
    print(f"Node {nid} DB rows ({len(lines)}): {lines}")
    assert len(lines) == 2, f"Node {nid} has wrong count of rows"

print("=== Task 2 Coordinator Change Test PASSED ===")
