"""Launch NodeRuntime with Flask REST Bridge serving the React UI on http://127.0.0.1:5000."""

import json
import os
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from node.config import NodeConfig, PeerInfo
from node.runtime import NodeRuntime
from api import create_app

def main():
    db_path = os.path.abspath("scratch/demo_node.db")
    if os.path.exists(db_path):
        try:
            os.remove(db_path)
        except Exception:
            pass

    config = NodeConfig(
        node_id=1,
        grpc_port=50070,
        election_algorithm="bully",
        peers={
            1: PeerInfo(1, "localhost", 50070),
            2: PeerInfo(2, "localhost", 50071),
            3: PeerInfo(3, "localhost", 50072),
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

    print("Starting NodeRuntime for Node 1...")
    runtime = NodeRuntime(config=config)
    runtime.start()
    with runtime.state._lock:
        runtime.state._active_peers.clear()

    print("Serving on http://127.0.0.1:5000...")
    app = create_app(runtime=runtime)
    from werkzeug.serving import make_server
    server = make_server("127.0.0.1", 5000, app, threaded=True)
    server.serve_forever()

if __name__ == "__main__":
    main()
