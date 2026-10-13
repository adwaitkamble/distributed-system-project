"""Matrix definitions and experiment catalog for Phase 7 experimental study."""

from dataclasses import dataclass
from typing import List, Optional


@dataclass(frozen=True)
class ExperimentSpec:
    exp_id: str
    name: str
    node_sizes: List[int]
    algorithms: List[str]
    policies: List[str]
    fault_scenario: str
    description: str


EXPERIMENT_CATALOG: List[ExperimentSpec] = [
    ExperimentSpec(
        exp_id="EXP-01",
        name="Bully Baseline (ALL Policy)",
        node_sizes=[3, 5, 7],
        algorithms=["bully"],
        policies=["all"],
        fault_scenario="none",
        description="Steady-state throughput and commit latency (p50/p95/p99) under ALL replication policy.",
    ),
    ExperimentSpec(
        exp_id="EXP-02",
        name="Bully Baseline (MAJORITY Policy)",
        node_sizes=[3, 5, 7],
        algorithms=["bully"],
        policies=["majority"],
        fault_scenario="none",
        description="Steady-state throughput and latency under MAJORITY replication policy across scaling cluster sizes.",
    ),
    ExperimentSpec(
        exp_id="EXP-03",
        name="Ring Baseline (ALL Policy)",
        node_sizes=[3, 5, 7],
        algorithms=["ring"],
        policies=["all"],
        fault_scenario="none",
        description="Ring algorithm steady-state comparison with ALL replication policy.",
    ),
    ExperimentSpec(
        exp_id="EXP-04",
        name="Ring Baseline (MAJORITY Policy)",
        node_sizes=[3, 5, 7],
        algorithms=["ring"],
        policies=["majority"],
        fault_scenario="none",
        description="Ring algorithm steady-state comparison with MAJORITY replication policy.",
    ),
    ExperimentSpec(
        exp_id="EXP-05",
        name="Coordinator Crash Failover Comparison",
        node_sizes=[3, 5, 7],
        algorithms=["bully", "ring"],
        policies=["majority"],
        fault_scenario="coord_crash",
        description="Election convergence latency, message overhead, and write-readiness latency following coordinator crash.",
    ),
    ExperimentSpec(
        exp_id="EXP-06",
        name="Follower Crash Quorum Sensitivity",
        node_sizes=[3, 5, 7],
        algorithms=["bully"],
        policies=["all", "majority"],
        fault_scenario="follower_crash",
        description="Write availability comparison: ALL policy blocks (HTTP 503) vs MAJORITY policy continues committing.",
    ),
    ExperimentSpec(
        exp_id="EXP-07",
        name="Sequential Cascading Failover",
        node_sizes=[5, 7],
        algorithms=["bully", "ring"],
        policies=["majority"],
        fault_scenario="cascading_crash",
        description="Consecutive coordinator terminations and multi-term Lamport convergence.",
    ),
    ExperimentSpec(
        exp_id="EXP-08",
        name="Follower Rejoin & Catch-up Benchmark",
        node_sizes=[3, 5, 7],
        algorithms=["bully"],
        policies=["majority"],
        fault_scenario="follower_rejoin",
        description="Measures AutoFollowerSync catch-up latency, missing record ingestion, and database WAL parity.",
    ),
    ExperimentSpec(
        exp_id="EXP-09",
        name="Majority vs Minority Network Partition",
        node_sizes=[5, 7],
        algorithms=["bully"],
        policies=["majority"],
        fault_scenario="network_partition",
        description="Simulates network partition: majority continues committing, minority rejects with HTTP 503.",
    ),
]


def get_experiment_by_id(exp_id: str) -> Optional[ExperimentSpec]:
    for spec in EXPERIMENT_CATALOG:
        if spec.exp_id.upper() == exp_id.upper():
            return spec
    return None
