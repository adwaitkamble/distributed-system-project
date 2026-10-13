"""Diagnostic script to isolate post-crash 500 error on Node 2."""
import json
import logging
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.abspath("."))

from experiments.core.cluster_manager import ClusterManager
from experiments.core.fault_injector import FaultInjector
from experiments.core.workload_client import WorkloadClient

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("diagnose")

def main():
    project = "diag_run"
    cluster = ClusterManager(
        node_count=3,
        project_name=project,
    )
    injector = FaultInjector(cluster_manager=cluster)

    try:
        logger.info("Starting cluster...")
        cluster.start_cluster(algorithm="bully", policy="majority", clean=True)
        # Cluster already verified healthy and settled by start_cluster

        coord_info = cluster.get_coordinator_info()
        assert coord_info is not None, "No coordinator found"
        coord_id, coord_port = coord_info
        logger.info("Initial coordinator: %s on port %s", coord_id, coord_port)

        # Submit 1 vote
        c1 = WorkloadClient(base_url=f"http://localhost:{cluster.profile.http_ports[coord_id]}")
        r1 = c1.submit_single_vote("diag_client_1", "Alice")
        logger.info("Pre-crash vote: success=%s, code=%s, err=%s", r1.success, r1.status_code, r1.error)

        # Crash coordinator
        logger.info("Stopping coordinator Node %d...", coord_id)
        injector.stop_node(coord_id)

        # Wait for new coordinator
        surviving = [p for nid, p in cluster.profile.http_ports.items() if nid != coord_id]
        new_coord = None
        new_port = None
        for _ in range(50):
            for p in surviving:
                try:
                    import urllib.request
                    with urllib.request.urlopen(f"http://localhost:{p}/api/node", timeout=1.0) as resp:
                        data = json.loads(resp.read().decode())
                        if data.get("is_coordinator") and data.get("accepting_votes"):
                            new_coord = data["node_id"]
                            new_port = p
                            break
                except Exception:
                    pass
            if new_coord:
                break
            time.sleep(0.5)

        logger.info("New coordinator detected: Node %s on port %s", new_coord, new_port)

        # Probe vote
        c2 = WorkloadClient(base_url=f"http://localhost:{new_port}")
        r2 = c2.submit_single_vote("diag_client_probe", "Bob")
        logger.info("Probe vote: success=%s, code=%s, err=%s", r2.success, r2.status_code, r2.error)

        # Rapid concurrent benchmark
        logger.info("Running small concurrent benchmark (concurrency=2, requests=4)...")
        res_bench = c2.run_workload(
            request_count=4,
            concurrency=2,
            warmup_count=0,
            client_prefix="diag_bench",
        )
        logger.info("Benchmark summary: attempted=%d, success=%d, failed=%d, rejected=%d",
                    res_bench.attempted_requests, res_bench.successful_requests,
                    res_bench.failed_requests, res_bench.rejected_requests)

    finally:
        logger.info("Dumping docker logs for voting-node2:")
        try:
            logs = subprocess.run(
                ["docker", "logs", "--tail", "50", "voting-node2"],
                capture_output=True,
                text=True,
                check=False,
            )
            print("=== voting-node2 LOGS ===")
            print(logs.stdout)
            print(logs.stderr)
            print("=========================")
        except Exception as e:
            logger.error("Failed to dump logs: %s", e)

        logger.info("Stopping cluster...")
        cluster.stop_cluster(purge_volumes=True)

if __name__ == "__main__":
    main()
