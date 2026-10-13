"""Audit React frontend and REST bridge endpoints across all 5 nodes in 5-node cluster."""

import json
import urllib.request
import sys

def audit_frontend_and_api():
    print("--- Auditing Frontend & REST Endpoints across 5-Node Cluster ---")

    # 1. SPA root
    with urllib.request.urlopen("http://localhost:5001/") as resp:
        assert resp.status == 200
        html = resp.read().decode("utf-8")
        assert '<div id="root">' in html
        assert "/assets/" in html
        print("  ✓ Node 1 root serves React Single Page Application (HTML/JS bundle)")

    # 2. REST endpoints on all 5 nodes
    endpoints = [
        "/api/health",
        "/api/node",
        "/api/nodes",
        "/api/votes/tally",
        "/api/election/status",
        "/api/recovery/status",
        "/api/events",
    ]

    for nid, port in [(1, 5001), (2, 5002), (3, 5003), (4, 5004), (5, 5005)]:
        print(f"\nNode {nid} (port {port}):")
        for ep in endpoints:
            url = f"http://localhost:{port}{ep}"
            with urllib.request.urlopen(url, timeout=3.0) as resp:
                assert resp.status == 200
                d = json.loads(resp.read().decode("utf-8"))
                if ep == "/api/nodes":
                    assert d["total_nodes"] == 5, f"Expected total_nodes == 5, got {d['total_nodes']}"
                    assert len(d["nodes"]) == 5
                print(f"  ✓ {ep:<22} -> HTTP 200 (keys: {sorted(list(d.keys()))[:4]})")

    print("\n✓ ALL 5-NODE FRONTEND & REST API CHECKS PASSED PERFECTLY!\n")

if __name__ == "__main__":
    audit_frontend_and_api()
