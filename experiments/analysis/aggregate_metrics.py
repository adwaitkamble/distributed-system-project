"""Statistical aggregation and summary table generator for benchmark trials."""

import argparse
import csv
import json
import math
import os
from pathlib import Path
import statistics
from typing import Any, Dict, List, Optional


def calculate_ci95(data: List[float]) -> float:
    """Calculate 95% confidence interval half-width: t * (std / sqrt(n)).
    Uses Student's t critical value for small sample sizes (n < 30).
    """
    n = len(data)
    if n < 2:
        return 0.0
    std = statistics.stdev(data)
    # Student's t critical values for 95% two-tailed confidence interval (alpha=0.05)
    t_table = {
        2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776,
        6: 2.571, 7: 2.447, 8: 2.365, 9: 2.306, 10: 2.262,
    }
    t_val = t_table.get(n, 1.96 if n >= 30 else 2.1)
    return round(t_val * (std / math.sqrt(n)), 3)


def get_order_percentile(sorted_data: List[float], p: float) -> float:
    """Compute non-parametric percentile with linear interpolation."""
    if not sorted_data:
        return 0.0
    idx = (len(sorted_data) - 1) * p
    lower = int(math.floor(idx))
    upper = int(math.ceil(idx))
    if lower == upper:
        return sorted_data[lower]
    weight = idx - lower
    return sorted_data[lower] * (1.0 - weight) + sorted_data[upper] * weight


def aggregate_raw_trials(trial_files: List[str]) -> dict:
    """Aggregate a set of repeated raw trial JSON runs with statistical rigor."""
    passed_throughputs = []
    passed_p50s = []
    passed_p90s = []
    passed_p95s = []
    passed_p99s = []
    passed_means = []
    passed_successes = []
    passed_attempts = []
    total_msgs = []
    failover_times = []
    total_readiness_times = []
    post_election_readiness_times = []
    pooled_latencies: List[float] = []
    
    invariants_passed = True
    invariant_errors = []
    failed_trials_count = 0
    passed_trials_count = 0

    exp_id = ""
    node_count = 0
    algorithm = "unknown"
    policy = "unknown"
    fault_scenario = "none"

    for fpath in trial_files:
        with open(fpath, "r", encoding="utf-8") as f:
            d = json.load(f)
            status = d.get("status", "UNKNOWN")
            cfg = d.get("config", {})
            workload = d.get("workload") or d.get("benchmark") or {}
            telemetry = d.get("invariants") or d.get("telemetry") or {}
            fault = d.get("fault_metrics", {})

            exp_id = d.get("exp_id") or cfg.get("exp_id", exp_id)
            node_count = cfg.get("node_count") or workload.get("node_count", node_count)
            algorithm = cfg.get("algorithm") or telemetry.get("algorithm", algorithm)
            policy = cfg.get("replication_policy") or telemetry.get("replication_policy", policy)
            fault_scenario = cfg.get("fault_scenario", fault_scenario)

            if status != "PASSED":
                failed_trials_count += 1
                continue

            passed_trials_count += 1

            lat_stats = workload.get("latency_stats_ms", {})
            p50 = lat_stats.get("p50", workload.get("p50_ms", 0.0))
            p90 = lat_stats.get("p90", workload.get("p90_ms", 0.0))
            p95 = lat_stats.get("p95", workload.get("p95_ms", 0.0))
            p99 = lat_stats.get("p99", workload.get("p99_ms", 0.0))
            mean = lat_stats.get("mean", workload.get("mean_ms", 0.0))
            tp = workload.get("successful_throughput_ops_sec") or workload.get("throughput_ops_sec", 0.0)

            passed_throughputs.append(tp)
            passed_p50s.append(p50)
            passed_p90s.append(p90)
            passed_p95s.append(p95)
            passed_p99s.append(p99)
            passed_means.append(mean)
            passed_successes.append(workload.get("successful_requests", 0))
            passed_attempts.append(workload.get("attempted_requests", 0))
            total_msgs.append(telemetry.get("total_cluster_election_messages", 0))

            f_ms = None
            if "election_failover_ms" in fault:
                f_ms = fault["election_failover_ms"]
                failover_times.append(f_ms)
            elif "total_failover_ms" in fault:
                f_ms = fault["total_failover_ms"]
                failover_times.append(f_ms)

            if "write_readiness_ms" in fault:
                w_ms = fault["write_readiness_ms"]
                total_readiness_times.append(w_ms)
                if f_ms is not None:
                    post_election_readiness_times.append(w_ms - f_ms)
            elif "rejoin_settle_ms" in fault:
                total_readiness_times.append(fault["rejoin_settle_ms"])

            if not telemetry.get("invariants_passed", True):
                invariants_passed = False
                invariant_errors.extend(telemetry.get("invariant_errors", []))

            # Pool non-warmup request latencies from raw NDJSON
            run_id = d.get("run_id")
            if run_id:
                ndjson_path = Path(fpath).parent / f"{run_id}_requests.ndjson"
                if ndjson_path.exists():
                    try:
                        with open(ndjson_path, "r", encoding="utf-8") as rf:
                            for line in rf:
                                if not line.strip():
                                    continue
                                r = json.loads(line)
                                if not r.get("is_warmup", False) and r.get("success", False):
                                    pooled_latencies.append(float(r["latency_ms"]))
                    except Exception:
                        pass

    trials_count = len(trial_files)
    if trials_count == 0:
        return {}

    pooled_latencies.sort()
    pooled_p50 = round(get_order_percentile(pooled_latencies, 0.50), 2)
    pooled_p90 = round(get_order_percentile(pooled_latencies, 0.90), 2)
    pooled_p95 = round(get_order_percentile(pooled_latencies, 0.95), 2)
    pooled_p99 = round(get_order_percentile(pooled_latencies, 0.99), 2)

    tp_mean = round(statistics.mean(passed_throughputs), 2) if passed_throughputs else 0.0
    tp_ci = calculate_ci95(passed_throughputs) if len(passed_throughputs) >= 2 else 0.0
    tp_lower = round(max(0.0, tp_mean - tp_ci), 2)
    tp_upper = round(tp_mean + tp_ci, 2)

    p50_mean = round(statistics.mean(passed_p50s), 2) if passed_p50s else 0.0
    p50_ci = calculate_ci95(passed_p50s) if len(passed_p50s) >= 2 else 0.0

    p90_mean = round(statistics.mean(passed_p90s), 2) if passed_p90s else 0.0
    p90_ci = calculate_ci95(passed_p90s) if len(passed_p90s) >= 2 else 0.0

    p95_mean = round(statistics.mean(passed_p95s), 2) if passed_p95s else 0.0
    p95_ci = calculate_ci95(passed_p95s) if len(passed_p95s) >= 2 else 0.0

    p99_mean = round(statistics.mean(passed_p99s), 2) if passed_p99s else 0.0
    p99_ci = calculate_ci95(passed_p99s) if len(passed_p99s) >= 2 else 0.0

    mean_lat = round(statistics.mean(passed_means), 2) if passed_means else 0.0

    agg = {
        "exp_id": exp_id,
        "node_count": node_count,
        "algorithm": algorithm,
        "policy": policy,
        "fault_scenario": fault_scenario,
        "trials_count": trials_count,
        "trials_passed": passed_trials_count,
        "trials_failed": failed_trials_count,
        "pooled_requests_count": len(pooled_latencies),
        "attempted_mean": round(statistics.mean(passed_attempts), 1) if passed_attempts else 0,
        "successful_mean": round(statistics.mean(passed_successes), 1) if passed_successes else 0,
        "throughput_mean": tp_mean,
        "throughput_ci95": tp_ci,
        "throughput_ci95_lower": tp_lower,
        "throughput_ci95_upper": tp_upper,
        "pooled_p50_ms": pooled_p50,
        "pooled_p90_ms": pooled_p90,
        "pooled_p95_ms": pooled_p95,
        "pooled_p99_ms": pooled_p99,
        "p50_mean": p50_mean,
        "p50_ci95": p50_ci,
        "p90_mean": p90_mean,
        "p90_ci95": p90_ci,
        "p95_mean": p95_mean,
        "p95_ci95": p95_ci,
        "p99_mean": p99_mean,
        "p99_ci95": p99_ci,
        "mean_latency_ms": mean_lat,
        "total_messages_mean": round(statistics.mean(total_msgs), 1) if total_msgs else 0,
        "invariants_passed_all_trials": invariants_passed,
        "invariant_error_count": len(invariant_errors),
    }

    if failover_times:
        agg["failover_time_mean_ms"] = round(statistics.mean(failover_times), 2)
        agg["failover_time_ci95_ms"] = calculate_ci95(failover_times)
    else:
        agg["failover_time_mean_ms"] = 0.0
        agg["failover_time_ci95_ms"] = 0.0

    if total_readiness_times:
        agg["write_readiness_mean_ms"] = round(statistics.mean(total_readiness_times), 2)
        agg["write_readiness_ci95_ms"] = calculate_ci95(total_readiness_times)
    else:
        agg["write_readiness_mean_ms"] = 0.0
        agg["write_readiness_ci95_ms"] = 0.0

    if post_election_readiness_times:
        agg["post_election_readiness_mean_ms"] = round(statistics.mean(post_election_readiness_times), 2)
        agg["post_election_readiness_ci95_ms"] = calculate_ci95(post_election_readiness_times)
    else:
        agg["post_election_readiness_mean_ms"] = 0.0
        agg["post_election_readiness_ci95_ms"] = 0.0

    return agg


def export_summary_csv(aggregated_rows: List[dict], output_csv_path: str) -> None:
    """Export aggregated rows to a clean CSV file."""
    if not aggregated_rows:
        return

    os.makedirs(os.path.dirname(os.path.abspath(output_csv_path)), exist_ok=True)
    fieldnames = list(aggregated_rows[0].keys())

    with open(output_csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(aggregated_rows)


def main():
    parser = argparse.ArgumentParser(description="Aggregate raw benchmark trials into statistical summaries")
    parser.add_argument("--raw-dir", type=str, default="data/experiments/matrix", help="Directory containing summary JSON files")
    parser.add_argument("--output-csv", type=str, default="data/experiments/matrix/summary/benchmark_summary.csv", help="Output summary CSV")
    args = parser.parse_args()

    raw_dir = Path(args.raw_dir)
    if not raw_dir.exists():
        print(f"Directory {raw_dir} does not exist.")
        return

    # Group trials by config group
    groups: Dict[str, List[str]] = {}
    for p in raw_dir.glob("*_summary.json"):
        try:
            with open(p, "r", encoding="utf-8") as f:
                d = json.load(f)
                cfg = d.get("config", {})
                exp_id = d.get("exp_id") or cfg.get("exp_id", "EXP")
                n = cfg.get("node_count", 0)
                algo = cfg.get("algorithm", "algo")
                pol = cfg.get("replication_policy", "pol")
                group_key = f"{exp_id}_{n}n_{algo}_{pol}"
                groups.setdefault(group_key, []).append(str(p))
        except Exception:
            pass

    aggregated_rows = []
    print("\n" + "=" * 100)
    print("STATISTICAL BENCHMARK SUMMARY (Mean ± 95% CI across trials)")
    print("=" * 100)
    print(f"{'Group / Config':<28s} | {'Throughput (ops/s)':<18s} | {'Latency p50 (ms)':<16s} | {'Latency p95 (ms)':<16s} | {'Invariants':<10s}")
    print("-" * 100)

    for group_name, files in sorted(groups.items()):
        agg = aggregate_raw_trials(files)
        if agg:
            agg["config_group"] = group_name
            aggregated_rows.append(agg)
            t_str = f"{agg['throughput_mean']} ± {agg['throughput_ci95']}"
            p50_str = f"{agg['p50_mean']} ± {agg['p50_ci95']}"
            p95_str = f"{agg['p95_mean']} ± {agg['p95_ci95']}"
            inv_str = "PASS" if agg["invariants_passed_all_trials"] else "FAIL"
            print(f"{group_name:<28s} | {t_str:<18s} | {p50_str:<16s} | {p95_str:<16s} | {inv_str:<10s}")

    print("=" * 100 + "\n")

    if aggregated_rows:
        export_summary_csv(aggregated_rows, args.output_csv)
        print(f"Saved summary CSV to {args.output_csv}")


if __name__ == "__main__":
    main()
