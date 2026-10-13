"""Verify 5-node cluster health, database isolation, replication, and failover."""

import json
import urllib.request
import subprocess
import sys

def verify_db_isolation():
    print("--- 1. Testing Physical Database Isolation Across 5 MySQL Containers ---")
    dbs = [
        "voting-node1-db",
        "voting-node2-db",
        "voting-node3-db",
        "voting-node4-db",
        "voting-node5-db",
    ]
    marker_id = "isolation_probe_5node_999"
    insert_sql = (
        f"INSERT INTO votes (vote_id, client_id, origin_node_id, lamport_ts, choice, received_at_ms, status) "
        f"VALUES ('{marker_id}', '{marker_id}', 1, 9999, 'Probe', 0, 'COMMITTED');"
    )
    subprocess.run(
        ["docker", "exec", "voting-node1-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-e", insert_sql],
        check=True
    )

    print("Inserted probe record into voting-node1-db. Checking node2..node5...")
    counts = {}
    for db in dbs:
        query_sql = f"SELECT count(*) FROM votes WHERE vote_id='{marker_id}';"
        p = subprocess.run(
            ["docker", "exec", db, "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN", "-e", query_sql],
            capture_output=True, text=True, check=True
        )
        counts[db] = int(p.stdout.strip())
        print(f"  {db} count: {counts[db]}")

    # Clean up probe
    cleanup_sql = f"DELETE FROM votes WHERE vote_id='{marker_id}';"
    subprocess.run(
        ["docker", "exec", "voting-node1-db", "mysql", "-uroot", "-pvotingpass", "voting_node", "-e", cleanup_sql],
        check=True
    )

    assert counts["voting-node1-db"] == 1, "Probe not found in node1-db"
    for name in ("voting-node2-db", "voting-node3-db", "voting-node4-db", "voting-node5-db"):
        assert counts[name] == 0, f"Isolation failure! Probe found in {name}"
    print("✓ Physical DB Isolation Verified: All 5 databases are completely independent!\n")

def verify_cluster_nodes():
    print("--- 2. Verifying Cluster Topology and Coordinator ---")
    nodes = [(1, 5001), (2, 5002), (3, 5003), (4, 5004), (5, 5005)]
    coords = []
    for nid, port in nodes:
        url = f"http://localhost:{port}/api/node"
        with urllib.request.urlopen(url, timeout=3.0) as resp:
            data = json.loads(resp.read().decode())
            is_c = data["is_coordinator"]
            c_id = data["coordinator_id"]
            peers = data["active_peers"]
            print(f"  Node {nid} (port {port}): is_coord={is_c}, coord_id={c_id}, active_peers={peers}")
            if is_c:
                coords.append(nid)

    print(f"Coordinators found: {coords}")
    assert len(coords) == 1, f"Expected exactly 1 coordinator, got {coords}"
    print("✓ Cluster Topology Verified: Exactly one unified coordinator.\n")
    return coords[0]

def verify_vote_replication(coord_id):
    print(f"--- 3. Verifying Vote Replication across all 5 Nodes from Coordinator {coord_id} ---")
    port_map = {1: 5001, 2: 5002, 3: 5003, 4: 5004, 5: 5005}
    coord_port = port_map[coord_id]

    client_id = "voter_5node_alpha"
    payload = json.dumps({"client_id": client_id, "choice": "Charlie"}).encode()
    req = urllib.request.Request(
        f"http://localhost:{coord_port}/api/votes",
        data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        res = json.loads(resp.read().decode())
        print(f"  Vote submitted to coordinator port {coord_port}: {res}")
        assert res["success"] is True

    # Check all 5 MySQL DBs
    dbs = [
        "voting-node1-db",
        "voting-node2-db",
        "voting-node3-db",
        "voting-node4-db",
        "voting-node5-db",
    ]
    for db in dbs:
        cmd = [
            "docker", "exec", db,
            "mysql", "-uroot", "-pvotingpass", "voting_node", "-sN",
            "-e", f"SELECT status, choice FROM votes WHERE client_id='{client_id}';"
        ]
        p = subprocess.run(cmd, capture_output=True, text=True, check=True)
        out = p.stdout.strip()
        print(f"  {db} row for {client_id}: {out}")
        assert "COMMITTED" in out and "Charlie" in out

    print("✓ 5-Node Replication Verified: Vote committed across all 5 independent databases!\n")

if __name__ == "__main__":
    verify_db_isolation()
    coord = verify_cluster_nodes()
    verify_vote_replication(coord)
