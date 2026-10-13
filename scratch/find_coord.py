import json
import urllib.request

for p in (5001, 5002, 5003, 5004, 5005):
    try:
        with urllib.request.urlopen(f"http://localhost:{p}/api/node", timeout=2) as resp:
            d = json.loads(resp.read().decode())
            print(f"Port {p}: node {d.get('node_id')}, is_coord={d.get('is_coordinator')}, coord_id={d.get('coordinator_id')}")
    except Exception as e:
        print(f"Port {p}: {e}")
