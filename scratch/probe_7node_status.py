import urllib.request
import json

for port in range(5001, 5008):
    node_id = port - 5000
    try:
        with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"Node {node_id} (port {port}): role={data.get('role')}, coord_id={data.get('coordinator_id')}, is_coord={data.get('is_coordinator')}, term={data.get('election_term')}, peers={data.get('active_peers')}, accepting={data.get('accepting_votes')}")
    except Exception as exc:
        print(f"Node {node_id} (port {port}): ERROR {exc}")
