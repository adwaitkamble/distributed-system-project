"""CLI runner for executing steady-state write benchmarks."""

import argparse
import json
import logging
import os
import sys
from typing import Optional

from experiments.config.benchmark_config import (
    DEFAULT_BENCHMARK_REQUESTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_WARMUP_REQUESTS,
)
from experiments.core.cluster_manager import ClusterManager
from experiments.core.telemetry_collector import TelemetryCollector
from experiments.core.workload_client import WorkloadClient

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_benchmark")


def main():
    parser = argparse.ArgumentParser(description="Run steady-state voting write benchmark")
    parser.add_argument("--nodes", type=int, default=3, choices=[3, 5, 7], help="Cluster size (3, 5, or 7)")
    parser.add_argument("--requests", type=int, default=DEFAULT_BENCHMARK_REQUESTS, help="Total measurement requests")
    parser.add_argument("--concurrency", type=int, default=DEFAULT_CONCURRENCY, help="Concurrent client workers")
    parser.add_argument("--warmup", type=int, default=DEFAULT_WARMUP_REQUESTS, help="Warm-up requests (discarded)")
    parser.add_argument("--output", type=str, default="", help="Path to write JSON results")
    parser.add_argument("--no-manage", action="store_true", help="Do not spin up/down Docker; assume cluster is already running")
    args = parser.parse_args()

    cluster = ClusterManager(args.nodes)

    if not args.no_manage:
        if not cluster.is_cluster_running():
            logger.error("Cluster (%d nodes) is not running. Please start the cluster first or omit --no-manage.", args.nodes)
            sys.exit(1)

    coord_info = cluster.ensure_cluster_settled(timeout=15.0)
    if not coord_info:
        logger.error("Could not find a stable coordinator accepting votes.")
        sys.exit(1)

    coord_id, coord_port = coord_info
    logger.info("Discovered active coordinator: Node %d on port %d", coord_id, coord_port)

    client = WorkloadClient(base_url=f"http://localhost:{coord_port}")
    bench_result = client.run_benchmark(
        request_count=args.requests,
        concurrency=args.concurrency,
        warmup_count=args.warmup,
        client_prefix="bench",
    )

    collector = TelemetryCollector(args.nodes)
    telemetry = collector.harvest_cluster_telemetry()

    output_data = {
        "benchmark": {
            "node_count": args.nodes,
            "coordinator_id": coord_id,
            "requests": args.requests,
            "concurrency": args.concurrency,
            "warmup": args.warmup,
            "total_requests": bench_result.total_requests,
            "successful_requests": bench_result.successful_requests,
            "rejected_requests": bench_result.rejected_requests,
            "failed_requests": bench_result.failed_requests,
            "duration_sec": bench_result.duration_sec,
            "throughput_ops_sec": bench_result.throughput_ops_sec,
            "p50_ms": bench_result.p50_ms,
            "p90_ms": bench_result.p90_ms,
            "p95_ms": bench_result.p95_ms,
            "p99_ms": bench_result.p99_ms,
            "mean_ms": bench_result.mean_ms,
            "stddev_ms": bench_result.stddev_ms,
            "min_ms": bench_result.min_ms,
            "max_ms": bench_result.max_ms,
        },
        "telemetry": {
            "election_term": telemetry.election_term,
            "algorithm": telemetry.algorithm,
            "replication_policy": telemetry.replication_policy,
            "total_cluster_election_messages": telemetry.total_cluster_election_messages,
            "total_committed_votes": telemetry.total_committed_votes,
            "tally": telemetry.tally,
            "invariants_passed": telemetry.invariants_passed,
            "invariant_errors": telemetry.invariant_errors,
        },
    }

    print("\n" + "=" * 60)
    print("BENCHMARK SUMMARY RESULTS")
    print("=" * 60)
    print(f"Cluster Size:       {args.nodes} nodes (Coordinator: Node {coord_id})")
    print(f"Algorithm / Policy: {telemetry.algorithm.upper()} / {telemetry.replication_policy.upper()}")
    print(f"Throughput:         {bench_result.throughput_ops_sec:.2f} votes/sec")
    print(f"Latency p50:        {bench_result.p50_ms:.2f} ms")
    print(f"Latency p95:        {bench_result.p95_ms:.2f} ms")
    print(f"Latency p99:        {bench_result.p99_ms:.2f} ms")
    print(f"Invariants Passed:  {telemetry.invariants_passed}")
    if telemetry.invariant_errors:
        print(f"Invariant Errors:   {telemetry.invariant_errors}")
    print("=" * 60 + "\n")

    if args.output:
        os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2)
        logger.info("Saved benchmark output to %s", args.output)


if __name__ == "__main__":
    main()
