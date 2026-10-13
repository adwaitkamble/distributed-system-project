import json
import subprocess
import time
import urllib.request

print("Testing Task 3 flow...")
coord_resp = json.loads(urllib.request.urlopen("http://localhost:5005/api/node").read())
print("Coord:", coord_resp["node_id"], coord_resp["role"], coord_resp["active_peers"])

print("Stopping node1 and node2...")
subprocess.run(["docker", "stop", "voting-node1", "voting-node2"], check=True)

print("Waiting 4.5s for coordinator heartbeat timeout...")
time.sleep(4.5)

coord_resp2 = json.loads(urllib.request.urlopen("http://localhost:5005/api/node").read())
print("Coord active peers after timeout:", coord_resp2["active_peers"])

client_id = f"test_task3_manual_{int(time.time())}"
payload = json.dumps({"client_id": client_id, "choice": "Alice"}).encode()
req = urllib.request.Request("http://localhost:5005/api/votes", data=payload, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    print("Vote resp:", resp.status, resp.read().decode())

print("Restarting node1 and node2 simultaneously...")
subprocess.run(["docker", "start", "voting-node1", "voting-node2"], check=True)

print("Waiting 6s for auto sync on node1 and node2...")
time.sleep(6.0)

for nid in (1, 2, 3, 4, 5):
    cmd = [
        "docker", "exec", f"voting-node{nid}-db",
        "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
        "-e", f"SELECT status, choice FROM votes WHERE client_id='{client_id}';"
    ]
    p = subprocess.run(cmd, capture_output=True, text=True)
    print(f"Node {nid} DB:", p.stdout.strip())
