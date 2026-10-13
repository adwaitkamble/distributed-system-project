"""Bounded live smoke test of ExperimentRunner on a 1-node Docker cluster."""
import json
import logging
import os
import sys

sys.path.insert(0, os.path.abspath("."))

from experiments.core.experiment_runner import ExperimentConfig, ExperimentRunner

logging.basicConfig(level=logging.INFO)

cfg = ExperimentConfig(
    exp_id="SMOKE-72C",
    node_count=1,
    algorithm="bully",
    replication_policy="all",
    fault_scenario="none",
    request_count=5,
    concurrency=1,
    warmup_count=1,
    manage_cluster=True,
    output_dir="data/experiments/smoke_72c",
)

runner = ExperimentRunner(cfg)
res = runner.run()
print(f"Smoke test result: success={res.success}, status={res.status}")
print(f"Summary: {res.summary_path}")
print(f"Manifest: {res.manifest_path}")
if not res.success:
    print(f"Errors: {res.errors}")
    sys.exit(1)

with open(res.manifest_path, "r", encoding="utf-8") as f:
    manifest = json.load(f)
print("Manifest artifacts:", list(manifest["artifacts"].keys()))
