import subprocess

# 1. Insert dummy marker row into node1-db only
marker_id = 'isolation_probe_999'
insert_sql = f"INSERT INTO votes (vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status) VALUES ('{marker_id}', '{marker_id}', 1, 9999, 'Probe', 0, 'COMMITTED');"
insert_cmd = [
    'docker', 'exec', 'voting-node1-db',
    'mysql', '-uroot', '-pvotingpass', 'voting_node',
    '-e', insert_sql
]
subprocess.run(insert_cmd, check=True)

# 2. Check each DB container
results = {}
for db in ['voting-node1-db', 'voting-node2-db', 'voting-node3-db']:
    query_sql = f"SELECT count(*) FROM votes WHERE vote_id='{marker_id}';"
    query_cmd = [
        'docker', 'exec', db,
        'mysql', '-uroot', '-pvotingpass', 'voting_node', '-sN',
        '-e', query_sql
    ]
    p = subprocess.run(query_cmd, capture_output=True, text=True, check=True)
    results[db] = int(p.stdout.strip())

print('Database isolation probe results:', results)
assert results['voting-node1-db'] == 1, 'Marker should exist in node1-db'
assert results['voting-node2-db'] == 0, 'Marker must NOT exist in node2-db'
assert results['voting-node3-db'] == 0, 'Marker must NOT exist in node3-db'
print('PHYSICAL DATABASE ISOLATION VERIFIED: Databases are completely independent.')

# 3. Clean up marker row
cleanup_sql = f"DELETE FROM votes WHERE vote_id='{marker_id}';"
cleanup_cmd = [
    'docker', 'exec', 'voting-node1-db',
    'mysql', '-uroot', '-pvotingpass', 'voting_node',
    '-e', cleanup_sql
]
subprocess.run(cleanup_cmd, check=True)
print('Marker row cleaned up successfully.')
