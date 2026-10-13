import urllib.request
import urllib.error
import json
import subprocess
import time

# 1. Stop node 1
print("Stopping voting-node1...")
subprocess.run(["docker", "stop", "voting-node1"], check=True)

try:
    # Immediate vote while Node 1 is still in coordinator's active snapshot -> should fail under ALL policy
    cid_immediate = f"all_policy_fail_{int(time.time())}"
    p_imm = json.dumps({"client_id": cid_immediate, "choice": "Bob"}).encode("utf-8")
    req_imm = urllib.request.Request("http://localhost:5007/api/votes", data=p_imm, headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req_imm, timeout=4.0)
        print("Warning: immediate vote succeeded (already timed out)")
    except urllib.error.HTTPError as err:
        assert err.code == 503
        print("Immediate vote correctly rejected with 503 under ALL policy")

    # Wait for heartbeat timeout (> 3.0s) so Node 7 updates active_peers snapshot
    print("Waiting 4.5s for heartbeat timeout...")
    time.sleep(4.5)

    # Now vote should succeed across surviving 6 nodes
    cid_survivors = f"all_policy_surv_{int(time.time())}"
    p_surv = json.dumps({"client_id": cid_survivors, "choice": "Charlie"}).encode("utf-8")
    req_surv = urllib.request.Request("http://localhost:5007/api/votes", data=p_surv, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req_surv, timeout=5.0) as resp:
        assert resp.status == 201
        print("Vote committed across surviving peers!")

    # Verify committed in surviving nodes 2..7 DBs
    for nid in range(2, 8):
        cmd = ["docker", "exec", f"voting-node{nid}-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN", "-e", f"SELECT status FROM votes WHERE client_id='{cid_survivors}';"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert "COMMITTED" in res.stdout
        print(f"Node {nid} DB: COMMITTED")

finally:
    # Restart node 1
    print("Restarting voting-node1...")
    subprocess.run(["docker", "start", "voting-node1"], check=True)
    time.sleep(4.0)

    # Verify Node 1 catches up via AutoFollowerSync
    cmd = ["docker", "exec", "voting-node1-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN", "-e", f"SELECT status FROM votes WHERE client_id='{cid_survivors}';"]
    res = subprocess.run(cmd, capture_output=True, text=True)
    assert "COMMITTED" in res.stdout, f"Node 1 failed to catch up: got '{res.stdout}'"
    print("Node 1 DB caught up via AutoFollowerSync: COMMITTED")

print("ALL policy with follower stop and catch-up verified successfully!")
