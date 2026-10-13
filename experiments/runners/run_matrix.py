"""Master orchestrator for running the Phase 7 factorial experiment suite using ExperimentRunner."""

import argparse
import json
import logging
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.abspath("."))

from experiments.config.matrix_definitions import EXPERIMENT_CATALOG, ExperimentSpec, get_experiment_by_id
from experiments.core.experiment_runner import ExperimentConfig, ExperimentRunner, ExperimentRunResult

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("run_matrix")


BATCH_DEFINITIONS = {
    "1": ["EXP-01", "EXP-02", "EXP-03", "EXP-04"],
    "2": ["EXP-05", "EXP-06"],
    "3": ["EXP-07", "EXP-08", "EXP-09"],
}


def run_experiment_trial(
    spec: ExperimentSpec,
    node_count: int,
    algo: str,
    policy: str,
    trial_idx: int,
    requests: int,
    concurrency: int,
    warmup: int,
    output_dir: str,
    project_prefix: str = "matrix",
) -> ExperimentRunResult:
    """Run a single benchmark trial using the production ExperimentRunner."""
    cfg = ExperimentConfig(
        exp_id=spec.exp_id,
        name=spec.name,
        node_count=node_count,
        algorithm=algo,
        replication_policy=policy,
        fault_scenario=spec.fault_scenario,
        request_count=requests,
        concurrency=concurrency,
        warmup_count=warmup,
        trial_idx=trial_idx,
        output_dir=output_dir,
        project_name=f"{project_prefix}_{spec.exp_id.lower().replace('-', '_')}",
        manage_cluster=True,
        telemetry_interval_sec=1.0,
        timeout_sec=180.0,
    )
    runner = ExperimentRunner(cfg)
    return runner.run()


def main():
    parser = argparse.ArgumentParser(description="Master orchestrator for Phase 7 experimental matrix")
    parser.add_argument("--exp", type=str, default="", help="Specific Experiment ID to run (e.g. EXP-01)")
    parser.add_argument("--batch", type=str, default="", choices=["1", "2", "3"], help="Run a specific batch (1=Baselines, 2=Crashes, 3=Advanced Faults)")
    parser.add_argument("--all", action="store_true", help="Run all catalog experiments")
    parser.add_argument("--trials", type=int, default=3, help="Number of repeated trials per configuration (default: 3)")
    parser.add_argument("--requests", type=int, default=30, help="Requests per measured trial")
    parser.add_argument("--concurrency", type=int, default=3, help="Worker concurrency")
    parser.add_argument("--output-dir", type=str, default="data/experiments/matrix", help="Output directory for manifests & raw traces")
    parser.add_argument("--project-prefix", type=str, default="matrix", help="Docker compose project name prefix")
    parser.add_argument("--dry-run", action="store_true", help="Print execution plan without executing trials")
    args = parser.parse_args()

    targets: List[ExperimentSpec] = []
    if args.exp:
        spec = get_experiment_by_id(args.exp)
        if not spec:
            logger.error("Unknown experiment ID: %s", args.exp)
            sys.exit(1)
        targets.append(spec)
    elif args.batch:
        exp_ids = BATCH_DEFINITIONS[args.batch]
        for eid in exp_ids:
            spec = get_experiment_by_id(eid)
            if spec:
                targets.append(spec)
    elif args.all:
        targets = EXPERIMENT_CATALOG
    else:
        # Default to EXP-01
        targets = [EXPERIMENT_CATALOG[0]]

    # Print execution plan
    print("\n" + "=" * 80)
    print("PHASE 7 EXPERIMENTAL MATRIX EXECUTION PLAN")
    print("=" * 80)
    planned_runs = []
    for t in targets:
        for n in t.node_sizes:
            for algo in t.algorithms:
                for pol in t.policies:
                    for k in range(1, args.trials + 1):
                        planned_runs.append((t, n, algo, pol, k))
                        print(f"[{t.exp_id}] {t.name:<34s} | N={n} | Algo={algo:<5s} | Pol={pol:<8s} | Fault={t.fault_scenario:<16s} | Trial={k}/{args.trials}")

    print(f"\nTotal planned trial executions: {len(planned_runs)}")
    print("=" * 80 + "\n")

    if args.dry_run:
        logger.info("Dry-run requested. Exiting without execution.")
        return

    trial_results: List[ExperimentRunResult] = []
    t_start_all = time.time()

    for idx, (spec, n, algo, pol, k) in enumerate(planned_runs, 1):
        time.sleep(2.0)  # Brief buffer for host socket release (TIME_WAIT)
        print("\n" + "-" * 80)
        logger.info(
            "[%d/%d] Starting %s Trial %d/%d (N=%d, Algo=%s, Policy=%s, Fault=%s)...",
            idx,
            len(planned_runs),
            spec.exp_id,
            k,
            args.trials,
            n,
            algo,
            pol,
            spec.fault_scenario,
        )
        print("-" * 80)

        warmup_reqs = 3 if spec.fault_scenario == "none" else 2
        # Adjust requests/concurrency for fault scenarios if needed
        reqs = args.requests
        conc = args.concurrency
        if spec.fault_scenario in ("cascading_crash", "follower_rejoin"):
            reqs = max(20, reqs)
            conc = min(2, conc)

        res = run_experiment_trial(
            spec=spec,
            node_count=n,
            algo=algo,
            policy=pol,
            trial_idx=k,
            requests=reqs,
            concurrency=conc,
            warmup=warmup_reqs,
            output_dir=args.output_dir,
            project_prefix=args.project_prefix,
        )
        trial_results.append(res)

        logger.info(
            "[%d/%d] Finished %s Trial %d: Status=%s, Success=%s, Duration=%.2fs",
            idx,
            len(planned_runs),
            spec.exp_id,
            k,
            res.status,
            res.success,
            res.duration_sec,
        )

        # Check invariant safety gate: halt on invariant violation
        inv = res.invariant_summary or {}
        if not inv.get("invariants_passed", True):
            logger.error("CRITICAL SAFETY VIOLATION detected in %s Trial %d: %s", spec.exp_id, k, inv.get("invariant_errors"))
            logger.error("HALTING CAMPAIGN TO PRESERVE ARTIFACTS AND INVESTIGATE!")
            sys.exit(2)

    total_duration = time.time() - t_start_all
    passed_count = sum(1 for r in trial_results if r.success)
    failed_count = sum(1 for r in trial_results if not r.success)

    print("\n" + "=" * 80)
    print(f"BATCH CAMPAIGN SUMMARY ({len(trial_results)} trials executed in {total_duration:.1f}s)")
    print(f"PASSED: {passed_count} | FAILED: {failed_count}")
    print("=" * 80)
    for r in trial_results:
        print(f"[{r.exp_id}] RunID={r.run_id:<55s} | Status={r.status:<6s} | Duration={r.duration_sec:6.2f}s | Errors={len(r.errors)}")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
