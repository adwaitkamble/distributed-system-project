"""Executes and records the Phase 8.5 Live Demonstration sequence."""

import json
import subprocess
import time
import urllib.request
import urllib.error

evidence = {
    "demonstration_name": "Phase 8.5 Live 3-Node Cluster Failover & State Recovery Demonstration",
    "timestamp_start": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    "steps": []
}

def http_get(url):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=4.0) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status

def http_post(url, payload):
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        return json.loads(resp.read().decode("utf-8")), resp.status

print("\n" + "="*80)
print("PHASE 8.5: LIVE 3-NODE CLUSTER DEMONSTRATION")
print("="*80)

# Step 1: Initial Topology Verification
print("\n[Step 1] Initial Cluster Topology Verification...")
step1 = {"step": 1, "description": "Initial Topology Verification", "nodes": {}}
for port, nid in [(5001, 1), (5002, 2), (5003, 3)]:
    d, status = http_get(f"http://localhost:{port}/api/node")
    print(f"  Node {nid} (Port {port}): Role={d['role']}, IsCoord={d['is_coordinator']}, CoordID={d['coordinator_id']}, Term={d['election_term']}")
    step1["nodes"][str(nid)] = d
evidence["steps"].append(step1)

# Step 2: Cast Initial Ballot to Coordinator (Node 3)
print("\n[Step 2] Casting Initial Ballot for Alice via Coordinator (Node 3)...")
ballot1 = {"client_id": "voter_eval_alice_01", "choice": "Alice"}
resp1, code1 = http_post("http://localhost:5003/api/votes", ballot1)
print(f"  Response ({code1}):", resp1)
time.sleep(0.5)

tallies_pre = {}
for port, nid in [(5001, 1), (5002, 2), (5003, 3)]:
    t, _ = http_get(f"http://localhost:{port}/api/votes/tally")
    tallies_pre[str(nid)] = t.get("tally", {})
    print(f"  Tally Node {nid}:", tallies_pre[str(nid)])

evidence["steps"].append({
    "step": 2,
    "description": "Initial Ballot Submission",
    "ballot": ballot1,
    "response": resp1,
    "http_status": code1,
    "tallies": tallies_pre
})

# Step 3: Trigger Coordinator Failure
print("\n[Step 3] Simulating Coordinator Crash: Stopping container voting-node3...")
t_stop = time.time()
subprocess.run(["docker", "stop", "voting-node3"], check=True)
print(f"  Container voting-node3 stopped at {t_stop:.3f}")

evidence["steps"].append({
    "step": 3,
    "description": "Coordinator Crash Injection",
    "target_container": "voting-node3",
    "t_stop": t_stop
})

# Step 4: Detect Failover & Monitor Election
print("\n[Step 4] Monitoring Failover & Leader Election on Node 1 and Node 2...")
elected_coord = None
t_elected = None
n2_data = {}
for _ in range(50):
    time.sleep(0.2)
    try:
        n2_data, _ = http_get("http://localhost:5002/api/node")
        if n2_data.get("is_coordinator"):
            t_elected = time.time()
            elected_coord = 2
            print(f"  Node 2 elected Coordinator! Elapsed: {t_elected - t_stop:.3f}s. Term={n2_data['election_term']}")
            break
    except Exception:
        pass

failover_duration_sec = t_elected - t_stop if t_elected else None
evidence["steps"].append({
    "step": 4,
    "description": "Leader Election Convergence",
    "new_coordinator_id": elected_coord,
    "failover_duration_sec": failover_duration_sec,
    "node2_status": n2_data
})

# Step 5: Post-Failure Vote under Majority Quorum
print("\n[Step 5] Casting Second Ballot for Bob via New Coordinator (Node 2)...")
ballot2 = {"client_id": "voter_eval_bob_02", "choice": "Bob"}
resp2, code2 = http_post("http://localhost:5002/api/votes", ballot2)
print(f"  Response ({code2}):", resp2)
time.sleep(0.5)

tallies_failover = {}
for port, nid in [(5001, 1), (5002, 2)]:
    t, _ = http_get(f"http://localhost:{port}/api/votes/tally")
    tallies_failover[str(nid)] = t.get("tally", {})
    print(f"  Tally Node {nid}:", tallies_failover[str(nid)])

evidence["steps"].append({
    "step": 5,
    "description": "Post-Failover Majority Quorum Vote",
    "ballot": ballot2,
    "response": resp2,
    "http_status": code2,
    "tallies": tallies_failover
})

# Step 6: Restart Node 3 & State Recovery
print("\n[Step 6] Restarting Crashed Node 3 (AutoFollowerSync Catch-up)...")
t_start = time.time()
subprocess.run(["docker", "start", "voting-node3"], check=True)
print(f"  Container voting-node3 started at {t_start:.3f}")

node3_synced = False
node3_data = None
for _ in range(50):
    time.sleep(0.3)
    try:
        node3_data, _ = http_get("http://localhost:5003/api/node")
        if node3_data.get("role") == "follower":
            # Verify tally has caught up
            t3, _ = http_get("http://localhost:5003/api/votes/tally")
            if t3.get("tally", {}).get("Bob") == 1:
                node3_synced = True
                print(f"  Node 3 rejoined, adopted Node 2, and synchronized tally in {time.time() - t_start:.3f}s!")
                break
    except Exception:
        pass

recovery_duration_sec = time.time() - t_start
evidence["steps"].append({
    "step": 6,
    "description": "Node Recovery & Catch-up Sync",
    "recovery_duration_sec": recovery_duration_sec,
    "node3_synced": node3_synced,
    "node3_status": node3_data
})

# Step 7: Final Consistency & WAL Parity Across All 3 Nodes
print("\n[Step 7] Final Committed Tally Across Cluster:")
final_tallies = {}
for port, nid in [(5001, 1), (5002, 2), (5003, 3)]:
    t, _ = http_get(f"http://localhost:{port}/api/votes/tally")
    final_tallies[str(nid)] = t.get("tally", {})
    print(f"  Node {nid} Tally:", final_tallies[str(nid)])

evidence["steps"].append({
    "step": 7,
    "description": "Final Committed Tally Parity",
    "final_tallies": final_tallies
})

evidence["timestamp_end"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
evidence["verdict"] = "PASS" if node3_synced and final_tallies["1"] == final_tallies["2"] == final_tallies["3"] else "FAIL"

output_path = "data/experiments/phase8_5/live_demo_log.json"
with open(output_path, "w", encoding="utf-8") as f:
    json.dump(evidence, f, indent=2)

print("\n" + "="*80)
print(f"DEMONSTRATION COMPLETE: Verdict = {evidence['verdict']}")
print(f"Failover Election Time: {failover_duration_sec:.3f}s")
print(f"State Recovery Time: {recovery_duration_sec:.3f}s")
print(f"Evidence log written to: {output_path}")
print("="*80)
