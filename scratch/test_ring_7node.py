import socket
import time
from pathlib import Path
import tempfile
from node.config import NodeConfig, PeerInfo
from node.models import NodeRole
from node.runtime import NodeRuntime

def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        return s.getsockname()[1]

def test_ring_7node():
    tmp_path = Path(tempfile.mkdtemp())
    ports = {i: _find_free_port() for i in range(1, 8)}
    nodes = {}

    print("1. Creating 7 nodes configured with algorithm='ring'...")
    for nid in range(1, 8):
        db_path = str(tmp_path / f"node_{nid}.sqlite")
        peers = {pid: PeerInfo(pid, "127.0.0.1", port) for pid, port in ports.items()}
        config = NodeConfig(
            node_id=nid,
            grpc_port=ports[nid],
            election_algorithm="ring",
            peers=peers,
            heartbeat_interval_ms=50,
            heartbeat_timeout_ms=1500,
            election_timeout_ms=3000,
            replication_policy="all",
            initial_coordinator_id=7,
            db_host="localhost",
            db_port=3306,
            db_user="root",
            db_password="password",
            db_name="voting",
            use_sqlite=True,
            sqlite_path=db_path,
            log_level="WARNING",
            candidates=["Alice", "Bob", "Charlie"],
            auto_recover=False,
        )
        nodes[nid] = NodeRuntime(config)

    for n in nodes.values():
        n.start()

    time.sleep(1.0)
    try:
        print("2. Verifying initial coordinator is Node 7...")
        assert nodes[7].state.is_coordinator()

        print("3. Stopping coordinator Node 7...")
        nodes[7].stop()

        print("4. Initiating Ring election from Node 1...")
        # Node 1 starts election; token propagates 1->2->3->4->5->6, skips dead 7, returns to 1
        nodes[1].election_strategy.start_election(blocking=True)

        time.sleep(2.0)

        # Winning node must be highest live node: Node 6
        print(f"Node 6 role: {nodes[6].state.role}")
        assert nodes[6].state.acts_as_coordinator(), f"Expected Node 6 to be coordinator, got {nodes[6].state.role}"

        # All surviving nodes (1..5) must recognize Node 6 as coordinator
        for nid in range(1, 6):
            coord = nodes[nid].state.coordinator_id
            assert coord == 6, f"Node {nid} coordinator is {coord}, expected 6"
            assert nodes[nid].state.role == NodeRole.FOLLOWER

        print("All surviving nodes 1..5 converged on Node 6 as coordinator (0 split brain)!")
        print("Ring leader election on 7 nodes verified successfully!")
    finally:
        for n in nodes.values():
            try:
                n.stop()
            except Exception:
                pass

if __name__ == "__main__":
    test_ring_7node()
