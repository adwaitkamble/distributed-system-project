import urllib.request
import json

BASE_URL = "http://localhost:5001"

print("1. Fetching SPA root '/'...")
with urllib.request.urlopen(f"{BASE_URL}/", timeout=3.0) as resp:
    assert resp.status == 200
    html = resp.read().decode("utf-8")
    assert '<div id="root"></div>' in html
    assert "Distributed Fault-Tolerant Voting System" in html
    print("   ✓ Root HTML properly served with React root div")

print("2. Verifying Dashboard API endpoints...")
for endpoint in ["/api/health", "/api/node", "/api/nodes", "/api/votes/tally", "/api/election/status", "/api/recovery/status", "/api/events"]:
    url = f"{BASE_URL}{endpoint}"
    with urllib.request.urlopen(url, timeout=3.0) as resp:
        assert resp.status == 200
        data = json.loads(resp.read().decode("utf-8"))
        print(f"   ✓ {endpoint:25} -> HTTP 200 (keys: {list(data.keys())[:4]})")

print("\nALL 6 VIEW APIS VERIFIED AGAINST LIVE CLUSTER CONTAINER.")
