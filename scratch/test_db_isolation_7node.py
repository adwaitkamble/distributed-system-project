import subprocess

probe_id = "probe_db_isolation_7node"
insert_sql = f"INSERT INTO votes (vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status) VALUES ('{probe_id}:1:1', '{probe_id}', 1, 1, 'Alice', 1000, 'COMMITTED');"
check_sql = f"SELECT count(*) FROM votes WHERE client_id='{probe_id}';"
delete_sql = f"DELETE FROM votes WHERE client_id='{probe_id}';"

# 1. Insert into node1-db only
cmd = ["docker", "exec", "voting-node1-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-e", insert_sql]
res = subprocess.run(cmd, capture_output=True, text=True)
assert res.returncode == 0, f"Insert failed: {res.stderr}"

# 2. Check node1-db has 1
cmd = ["docker", "exec", "voting-node1-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN", "-e", check_sql]
res = subprocess.run(cmd, capture_output=True, text=True)
count1 = int(res.stdout.strip())
assert count1 == 1, f"Expected 1 in node1-db, got {count1}"

# 3. Check node2-db through node7-db have 0
for nid in range(2, 8):
    container = f"voting-node{nid}-db"
    cmd = ["docker", "exec", container, "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN", "-e", check_sql]
    res = subprocess.run(cmd, capture_output=True, text=True)
    cnt = int(res.stdout.strip())
    assert cnt == 0, f"Violation: {container} contains record! count={cnt}"
    print(f"Verified {container}: {cnt} records (isolated)")

# 4. Clean up probe from node1-db
cmd = ["docker", "exec", "voting-node1-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-e", delete_sql]
subprocess.run(cmd, check=True)
print("Physical database isolation across all 7 databases verified successfully!")
