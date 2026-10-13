import json
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import time
import threading
import urllib.request
import urllib.error

from node.config import NodeConfig, PeerInfo
from node.runtime import NodeRuntime
from api import create_app

def http_get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))

def http_post(url, data):
    body = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST"
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))

def run_verification():
    db_path = os.path.abspath("scratch/runtime_verify_node.db")
    if os.path.exists(db_path):
        os.remove(db_path)

    config = NodeConfig(
        node_id=1,
        grpc_port=50065,
        election_algorithm="bully",
        peers={
            1: PeerInfo(1, "localhost", 50065),
            2: PeerInfo(2, "localhost", 50066),
            3: PeerInfo(3, "localhost", 50067),
        },
        heartbeat_interval_ms=1000,
        heartbeat_timeout_ms=3000,
        election_timeout_ms=5000,
        replication_policy="all",
        initial_coordinator_id=1,
        db_host="localhost",
        db_port=3306,
        db_user="root",
        db_password="votingpass",
        db_name="voting_test",
        use_sqlite=True,
        sqlite_path=db_path,
        log_level="INFO",
        candidates=["Alice", "Bob", "Charlie"],
    )

    print("1. Initializing and starting NodeRuntime...")
    runtime = NodeRuntime(config=config)
    runtime.start()
    with runtime.state._lock:
        runtime.state._active_peers.clear()

    print("2. Starting Flask bridge on http://127.0.0.1:5005...")
    app = create_app(runtime=runtime)
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 5005, app, threaded=True)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    time.sleep(0.5)

    base = "http://127.0.0.1:5005/api"

    try:
        # GET /api/health
        code, h = http_get(f"{base}/health")
        print(f"   [GET /api/health] -> {code}, {h}")
        assert code == 200 and h["status"] == "ok" and h["node_id"] == 1

        # GET /api/node
        code, n = http_get(f"{base}/node")
        print(f"   [GET /api/node] -> {code}, node_id={n['node_id']}, role={n['role']}, coord={n['coordinator_id']}")
        assert n["is_coordinator"] is True

        # GET /api/nodes
        code, ns = http_get(f"{base}/nodes")
        print(f"   [GET /api/nodes] -> {code}, total_nodes={ns['total_nodes']}")
        assert ns["total_nodes"] == 3

        # GET /api/election/status
        code, el = http_get(f"{base}/election/status")
        print(f"   [GET /api/election/status] -> {code}, algorithm={el['algorithm']}, term={el['election_term']}")
        assert el["algorithm"] == "bully"

        # GET /api/recovery/status
        code, rec = http_get(f"{base}/recovery/status")
        print(f"   [GET /api/recovery/status] -> {code}, role={rec['role']}, is_recovering={rec['is_recovering']}")
        assert rec["is_recovering"] is False

        # GET /api/events
        code, ev = http_get(f"{base}/events")
        print(f"   [GET /api/events] -> {code}, count={ev['count']}")
        assert "events" in ev

        # GET /api/votes/tally (initially 0)
        code, tally0 = http_get(f"{base}/votes/tally")
        print(f"   [GET /api/votes/tally] -> {code}, total_votes={tally0['total_votes']}")
        assert tally0["total_votes"] == 0

        # POST /api/votes: normal vote
        code, v_res = http_post(f"{base}/votes", {"client_id": "manual_test_001", "choice": "Alice"})
        print(f"   [POST /api/votes] -> status={code}, data={v_res}")
        assert code == 201
        vote_id = v_res["vote_id"]

        # GET /api/votes/tally (after vote: 1)
        code, tally1 = http_get(f"{base}/votes/tally")
        print(f"   [GET /api/votes/tally] -> total_votes={tally1['total_votes']}, tally={tally1['tally']}")
        assert tally1["total_votes"] == 1
        assert tally1["tally"]["Alice"] == 1

        # GET /api/votes/<vote_id>
        code, v_info = http_get(f"{base}/votes/{vote_id}")
        print(f"   [GET /api/votes/{vote_id}] -> status={v_info['vote']['status']}")
        assert v_info["vote"]["status"] == "COMMITTED"
        assert v_info["vote"]["client_id"] == "manual_test_001"

        # Duplicate vote: same voter ID
        code, dup_res = http_post(f"{base}/votes", {"client_id": "manual_test_001", "choice": "Alice"})
        print(f"   [Duplicate vote] -> status={code}, error={dup_res['error']}")
        assert code == 409
        assert dup_res["error"] == "duplicate_client"

        # Trigger election
        code, el_res = http_post(f"{base}/election/start", {"blocking": False})
        print(f"   [POST /api/election/start] -> status={code}, res={el_res}")
        assert code == 200

        # Trigger recovery
        code, rec_res = http_post(f"{base}/recovery/start", {"target_peer_ids": []})
        print(f"   [POST /api/recovery/start] -> status={code}, res={rec_res}")
        assert code == 200
        assert rec_res["committed_votes_count"] == 1

        # Check frontend serving index.html
        req = urllib.request.Request("http://127.0.0.1:5005/")
        with urllib.request.urlopen(req) as resp:
            content = resp.read().decode("utf-8")
            assert '<div id="root"></div>' in content
            print("   [GET / (SPA)] -> 200 OK (Served React dist/index.html)")

        print("\nALL RUNTIME API & SPA CHECKS PASSED LIVE ON REAL HTTP SOCKET!")
    finally:
        print("Shutting down Flask server and NodeRuntime...")
        server.shutdown()
        runtime.stop(grace=0.5)

if __name__ == "__main__":
    run_verification()
