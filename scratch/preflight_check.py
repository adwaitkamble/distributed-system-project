"""Preflight verification for Phase 7.3: executes 1 baseline and 1 fault trial on a 3-node cluster."""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from experiments.core.experiment_runner import ExperimentConfig, ExperimentRunner

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s: %(message)s")
logger = logging.getLogger("preflight")

def run_preflight():
    print("=== STARTING PREFLIGHT: Baseline 3-Node Trial ===")
    cfg_base = ExperimentConfig(
        exp_id="PREFLIGHT-01",
        node_count=3,
        algorithm="bully",
        replication_policy="all",
        fault_scenario="none",
        request_count=10,
        concurrency=2,
        warmup_count=2,
        manage_cluster=True,
        output_dir="data/experiments/preflight",
        project_name="preflight_run",
    )
    runner_base = ExperimentRunner(cfg_base)
    res_base = runner_base.run()
    print(f"Baseline Result: success={res_base.success}, status={res_base.status}")
    if not res_base.success:
        print(f"Baseline failed with errors: {res_base.errors}")
        sys.exit(1)

    print("\n=== STARTING PREFLIGHT: Controlled Fault 3-Node Trial (coord_crash) ===")
    cfg_fault = ExperimentConfig(
        exp_id="PREFLIGHT-02",
        node_count=3,
        algorithm="bully",
        replication_policy="majority",
        fault_scenario="coord_crash",
        request_count=15,
        concurrency=2,
        warmup_count=2,
        manage_cluster=True,
        output_dir="data/experiments/preflight",
        project_name="preflight_run",
    )
    runner_fault = ExperimentRunner(cfg_fault)
    res_fault = runner_fault.run()
    print(f"Fault Result: success={res_fault.success}, status={res_fault.status}")
    if not res_fault.success:
        print(f"Fault trial failed with errors: {res_fault.errors}")
        sys.exit(1)

    print("\n=== PREFLIGHT VERIFICATION PASSED SUCCESSFULLY ===")
    print(f"Baseline manifest: {res_base.manifest_path}")
    print(f"Fault manifest:    {res_fault.manifest_path}")

if __name__ == "__main__":
    run_preflight()
