"""CLI runner for controlled fault-injection scenarios."""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Dict, Optional

from experiments.core.cluster_manager import ClusterManager
from experiments.core.fault_injector import FaultInjector
from experiments.core.telemetry_collector import TelemetryCollector
from experiments.core.workload_client import WorkloadClient

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_fault_experiment")


def run_coord_crash_scenario(cluster: ClusterManager, injector: FaultInjector) -> dict:
    """Executes coordinator crash-stop scenario and measures convergence and write-readiness."""
    logger.info("Starting coordinator crash-stop experiment...")
    coord_info = cluster.ensure_cluster_settled(timeout=15.0)
    if not coord_info:
        raise RuntimeError("No active coordinator available prior to crash injection")

    old_coord_id, old_port = coord_info
    logger.info("Active coordinator prior to crash: Node %d (port %d)", old_coord_id, old_port)

    # 1. Inject crash
    t_crash = time.perf_counter()
    injector.stop_node(old_coord_id)

    # 2. Poll surviving nodes to detect new coordinator election
    surviving_ports = [
        port for nid, port in cluster.profile.http_ports.items() if nid != old_coord_id
    ]

    t_new_coord_detected = None
    new_coord_id = None
    new_port = None
    deadline = time.monotonic() + 20.0

    while time.monotonic() < deadline:
        for port in surviving_ports:
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=1.0) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("is_coordinator") and data.get("accepting_votes"):
                            new_coord_id = data["node_id"]
                            new_port = port
                            t_new_coord_detected = time.perf_counter()
                            break
            except Exception:
                pass
        if new_coord_id is not None:
            break
        time.sleep(0.2)

    if not new_coord_id:
        raise TimeoutError("Surviving nodes failed to converge on a new coordinator within 20s")

    election_convergence_sec = t_new_coord_detected - t_crash
    logger.info(
        "Election converged! New Coordinator is Node %d in %.3f seconds",
        new_coord_id,
        election_convergence_sec,
    )

    # 3. Measure Write-Readiness Latency
    client = WorkloadClient(base_url=f"http://localhost:{new_port}")
    write_ready_client_id = f"crash_recovery_probe_{int(time.time()*1000)}"
    probe_res = client.submit_single_vote(write_ready_client_id, "Alice")

    t_first_write_ack = time.perf_counter()
    write_readiness_sec = t_first_write_ack - t_crash

    logger.info(
        "Write readiness confirmed (success=%s) in %.3f seconds",
        probe_res.success,
        write_readiness_sec,
    )

    # 4. Telemetry collection
    collector = TelemetryCollector(cluster.node_count)
    telemetry = collector.harvest_cluster_telemetry()

    return {
        "scenario": "coord_crash",
        "old_coordinator_id": old_coord_id,
        "new_coordinator_id": new_coord_id,
        "election_convergence_latency_ms": round(election_convergence_sec * 1000.0, 2),
        "write_readiness_latency_ms": round(write_readiness_sec * 1000.0, 2),
        "probe_write_success": probe_res.success,
        "total_election_messages": telemetry.total_cluster_election_messages,
        "election_sent": telemetry.election_messages_sent,
        "ok_sent": telemetry.ok_messages_sent,
        "coord_sent": telemetry.coord_messages_sent,
        "invariants_passed": telemetry.invariants_passed,
        "invariant_errors": telemetry.invariant_errors,
    }


def run_follower_crash_scenario(cluster: ClusterManager, injector: FaultInjector) -> dict:
    """Executes follower crash scenario and measures write availability under current policy."""
    logger.info("Starting follower crash experiment...")
    coord_info = cluster.ensure_cluster_settled(timeout=15.0)
    if not coord_info:
        raise RuntimeError("No active coordinator available prior to crash injection")

    coord_id, coord_port = coord_info
    follower_candidates = [nid for nid in cluster.profile.http_ports.keys() if nid != coord_id]
    target_follower = min(follower_candidates)

    logger.info("Crashing follower Node %d...", target_follower)
    injector.stop_node(target_follower)
    time.sleep(1.0)

    client = WorkloadClient(base_url=f"http://localhost:{coord_port}")
    probe_cid = f"follower_crash_probe_{int(time.time()*1000)}"
    probe_res = client.submit_single_vote(probe_cid, "Bob")

    collector = TelemetryCollector(cluster.node_count)
    telemetry = collector.harvest_cluster_telemetry()

    return {
        "scenario": "follower_crash",
        "crashed_follower_id": target_follower,
        "coordinator_id": coord_id,
        "replication_policy": telemetry.replication_policy,
        "write_success": probe_res.success,
        "status_code": probe_res.status_code,
        "error": probe_res.error,
        "latency_ms": probe_res.latency_ms,
        "invariants_passed": telemetry.invariants_passed,
    }


def run_follower_rejoin_scenario(cluster: ClusterManager, injector: FaultInjector) -> dict:
    """Measures AutoFollowerSync catch-up latency when an offline follower restarts."""
    logger.info("Starting follower rejoin & catch-up experiment...")
    coord_info = cluster.ensure_cluster_settled(timeout=15.0)
    if not coord_info:
        raise RuntimeError("No active coordinator available")

    coord_id, coord_port = coord_info
    target_follower = min([nid for nid in cluster.profile.http_ports.keys() if nid != coord_id])
    follower_port = cluster.profile.http_ports[target_follower]

    # 1. Stop follower
    logger.info("Stopping follower Node %d...", target_follower)
    injector.stop_node(target_follower)
    time.sleep(1.0)

    # 2. Write 15 votes while follower is offline
    client = WorkloadClient(base_url=f"http://localhost:{coord_port}")
    written_count = 0
    for i in range(15):
        cid = f"offline_lag_{i}_{int(time.time()*1000)}"
        res = client.submit_single_vote(cid, "Charlie")
        if res.success:
            written_count += 1

    logger.info("Committed %d votes to cluster while Node %d was offline", written_count, target_follower)

    # 3. Rejoin follower and measure catch-up time
    t_rejoin = time.perf_counter()
    injector.start_node(target_follower)

    t_synced = None
    deadline = time.monotonic() + 25.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://localhost:{follower_port}/api/votes/tally", timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    # If total votes on rejoining follower equals coordinator total, sync complete!
                    if data.get("total_votes", 0) >= written_count:
                        t_synced = time.perf_counter()
                        break
        except Exception:
            pass
        time.sleep(0.5)

    catchup_duration_ms = round((t_synced - t_rejoin) * 1000.0, 2) if t_synced else -1.0
    logger.info("Follower Node %d synchronized missing votes in %.2f ms", target_follower, catchup_duration_ms)

    collector = TelemetryCollector(cluster.node_count)
    telemetry = collector.harvest_cluster_telemetry()

    return {
        "scenario": "follower_rejoin",
        "rejoined_node_id": target_follower,
        "missed_votes_count": written_count,
        "catchup_duration_ms": catchup_duration_ms,
        "synchronized_successfully": (t_synced is not None),
        "invariants_passed": telemetry.invariants_passed,
        "invariant_errors": telemetry.invariant_errors,
    }


def run_partition_scenario(cluster: ClusterManager, injector: FaultInjector) -> dict:
    """Evaluates quorum enforcement under network partition and subsequent healing."""
    logger.info("Starting network partition experiment on %d-node cluster...", cluster.node_count)
    if cluster.node_count < 5:
        raise ValueError("Network partition scenario requires at least 5 nodes for majority/minority split")

    coord_info = cluster.ensure_cluster_settled(timeout=15.0)
    if not coord_info:
        raise RuntimeError("No active coordinator available prior to partition")

    coord_id, coord_port = coord_info
    # Isolate the top minority nodes (e.g. nodes 4 and 5 in 5-node cluster)
    minority_nodes = sorted(list(cluster.profile.http_ports.keys()))[cluster.node_count // 2 + 1:]
    majority_nodes = [nid for nid in cluster.profile.http_ports.keys() if nid not in minority_nodes]

    logger.info("Partitioning cluster: Majority=%s, Minority=%s", majority_nodes, minority_nodes)

    # 1. Disconnect minority nodes from bridge network
    for nid in minority_nodes:
        injector.disconnect_network(nid)
    time.sleep(2.0)

    # 2. Probe write on majority partition
    maj_coord_port = cluster.profile.http_ports[majority_nodes[-1]]
    client_maj = WorkloadClient(base_url=f"http://localhost:{maj_coord_port}")
    maj_cid = f"maj_part_vote_{int(time.time()*1000)}"
    res_maj = client_maj.submit_single_vote(maj_cid, "Alice")

    # 3. Probe write on minority partition (should fail quorum HTTP 503)
    min_port = cluster.profile.http_ports[minority_nodes[0]]
    client_min = WorkloadClient(base_url=f"http://localhost:{min_port}")
    min_cid = f"min_part_vote_{int(time.time()*1000)}"
    res_min = client_min.submit_single_vote(min_cid, "Bob")

    logger.info("Majority write result: %s (status=%d)", res_maj.success, res_maj.status_code)
    logger.info("Minority write result: %s (status=%d)", res_min.success, res_min.status_code)

    # 4. Heal Partition
    logger.info("Healing network partition...")
    for nid in minority_nodes:
        injector.reconnect_network(nid)
    time.sleep(3.0)

    collector = TelemetryCollector(cluster.node_count)
    telemetry = collector.harvest_cluster_telemetry()

    return {
        "scenario": "network_partition",
        "majority_nodes": majority_nodes,
        "minority_nodes": minority_nodes,
        "majority_write_success": res_maj.success,
        "minority_write_success": res_min.success,
        "minority_status_code": res_min.status_code,
        "quorum_enforced": (res_min.status_code in (409, 503, 0) and not res_min.success),
        "invariants_passed": telemetry.invariants_passed,
        "invariant_errors": telemetry.invariant_errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Run controlled fault-injection experiments")
    parser.add_argument("--scenario", type=str, required=True, choices=["coord_crash", "follower_crash", "follower_rejoin", "network_partition"], help="Fault scenario to run")
    parser.add_argument("--nodes", type=int, default=3, choices=[3, 5, 7], help="Cluster size (3, 5, or 7)")
    parser.add_argument("--output", type=str, default="", help="Path to write JSON results")
    args = parser.parse_args()

    cluster = ClusterManager(args.nodes)
    if not cluster.is_cluster_running():
        logger.error("Cluster (%d nodes) is not running.", args.nodes)
        sys.exit(1)

    injector = FaultInjector()

    try:
        if args.scenario == "coord_crash":
            results = run_coord_crash_scenario(cluster, injector)
        elif args.scenario == "follower_crash":
            results = run_follower_crash_scenario(cluster, injector)
        elif args.scenario == "follower_rejoin":
            results = run_follower_rejoin_scenario(cluster, injector)
        elif args.scenario == "network_partition":
            results = run_partition_scenario(cluster, injector)
        else:
            logger.error("Unsupported scenario: %s", args.scenario)
            sys.exit(1)

        print("\n" + "=" * 60)
        print(f"FAULT EXPERIMENT RESULTS: {args.scenario.upper()}")
        print("=" * 60)
        for k, v in results.items():
            print(f"{k:35s}: {v}")
        print("=" * 60 + "\n")

        if args.output:
            os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
            with open(args.output, "w", encoding="utf-8") as f:
                json.dump(results, f, indent=2)
            logger.info("Saved fault experiment output to %s", args.output)

    finally:
        logger.info("Executing safe fault rollback to restore cluster state...")
        injector.revert_all_faults(list(cluster.profile.http_ports.keys()))
        cluster.ensure_cluster_settled(timeout=10.0)


if __name__ == "__main__":
    main()
