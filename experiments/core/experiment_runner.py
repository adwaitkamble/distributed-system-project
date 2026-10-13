"""Reusable master experiment runner orchestrating cluster lifecycle, telemetry, workloads, and faults."""

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import platform
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request
from uuid import uuid4

from experiments.config.benchmark_config import (
    CLUSTER_PROFILES,
    DEFAULT_BENCHMARK_REQUESTS,
    DEFAULT_CONCURRENCY,
    DEFAULT_WARMUP_REQUESTS,
)
from experiments.config.matrix_definitions import EXPERIMENT_CATALOG, ExperimentSpec, get_experiment_by_id
from experiments.core.cluster_manager import ClusterManager
from experiments.core.fault_injector import FaultInjector
from experiments.core.telemetry_collector import ContainerTelemetrySampler, TelemetryCollector
from experiments.core.workload_client import BenchmarkSummary, WorkloadClient

logger = logging.getLogger("experiments.experiment_runner")


def _compute_sha256(filepath: str) -> str:
    """Compute SHA-256 checksum of a file."""
    if not os.path.isfile(filepath):
        return ""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _count_lines(filepath: str) -> int:
    """Count non-empty lines in a file (for NDJSON record auditing)."""
    if not os.path.isfile(filepath):
        return 0
    count = 0
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


@dataclass
class ExperimentConfig:
    """Configuration specification for a single experiment trial run."""

    exp_id: str
    name: str = ""
    node_count: int = 3
    algorithm: str = "bully"
    replication_policy: str = "majority"
    fault_scenario: str = "none"
    request_count: int = DEFAULT_BENCHMARK_REQUESTS
    concurrency: int = DEFAULT_CONCURRENCY
    warmup_count: int = DEFAULT_WARMUP_REQUESTS
    trial_idx: int = 1
    output_dir: Optional[str] = None
    project_name: Optional[str] = None
    manage_cluster: bool = True
    telemetry_interval_sec: float = 1.0
    timeout_sec: float = 180.0

    def validate(self) -> None:
        """Validate configuration parameters strictly before execution."""
        if self.node_count not in CLUSTER_PROFILES:
            raise ValueError(
                f"Unsupported node count: {self.node_count}. Supported: {sorted(list(CLUSTER_PROFILES.keys()))}"
            )
        if self.algorithm.lower() not in ("bully", "ring"):
            raise ValueError(f"Unsupported algorithm: '{self.algorithm}'. Supported: ['bully', 'ring']")
        if self.replication_policy.lower() not in ("all", "majority"):
            raise ValueError(
                f"Unsupported replication policy: '{self.replication_policy}'. Supported: ['all', 'majority']"
            )
        valid_scenarios = {
            "none",
            "coord_crash",
            "follower_crash",
            "pause_node",
            "network_partition",
            "follower_rejoin",
            "cascading_crash",
        }
        if self.fault_scenario.lower() not in valid_scenarios:
            raise ValueError(
                f"Unsupported fault scenario: '{self.fault_scenario}'. Supported: {sorted(list(valid_scenarios))}"
            )
        if self.request_count <= 0:
            raise ValueError(f"request_count must be positive, got {self.request_count}")
        if self.concurrency <= 0:
            raise ValueError(f"concurrency must be positive, got {self.concurrency}")
        if self.warmup_count < 0:
            raise ValueError(f"warmup_count must be non-negative, got {self.warmup_count}")


@dataclass
class ExperimentRunResult:
    """Complete multi-dimensional output of an experiment execution."""

    run_id: str
    exp_id: str
    status: str  # "PASSED", "FAILED"
    success: bool
    duration_sec: float
    output_dir: str
    manifest_path: str
    summary_path: str
    raw_workload_path: Optional[str]
    raw_telemetry_path: Optional[str]
    workload_summary: Optional[Dict[str, Any]]
    telemetry_summary: Optional[Dict[str, Any]]
    invariant_summary: Optional[Dict[str, Any]]
    fault_metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


class ExperimentRunner:
    """Orchestrates end-to-end experiment trials with guaranteed cleanup and artifact preservation."""

    def __init__(self, config: ExperimentConfig, project_root: Optional[str] = None):
        config.validate()
        self.config = config
        self.project_root = project_root or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

        # Generate collision-safe run ID
        ts_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        safe_exp = self.config.exp_id.lower().replace("-", "_")
        self.run_id = (
            f"{safe_exp}_{self.config.node_count}n_{self.config.algorithm.lower()}_"
            f"{self.config.replication_policy.lower()}_t{self.config.trial_idx}_{ts_str}_{uuid4().hex[:6]}"
        )

        # Establish collision-safe output paths
        base_results = os.path.join(self.project_root, "experiments", "results")
        self.output_dir = self.config.output_dir or os.path.join(base_results, self.run_id)
        os.makedirs(self.output_dir, exist_ok=True)

        self.raw_workload_path = os.path.join(self.output_dir, f"{self.run_id}_requests.ndjson")
        self.raw_telemetry_path = os.path.join(self.output_dir, f"{self.run_id}_telemetry.ndjson")
        self.summary_path = os.path.join(self.output_dir, f"{self.run_id}_summary.json")
        self.manifest_path = os.path.join(self.output_dir, f"{self.run_id}_manifest.json")

    def run(self) -> ExperimentRunResult:
        """Execute the entire ordered experiment trial lifecycle with strict fault isolation."""
        t_start = time.time()
        errors: List[str] = []
        workload_summary: Optional[Dict[str, Any]] = None
        telemetry_summary: Optional[Dict[str, Any]] = None
        invariant_summary: Optional[Dict[str, Any]] = None
        fault_metrics: Dict[str, Any] = {}

        cluster_mgr = ClusterManager(
            self.config.node_count,
            project_root=self.project_root,
            project_name=self.config.project_name,
        )
        sampler: Optional[ContainerTelemetrySampler] = None
        injector: Optional[FaultInjector] = None

        logger.info(
            "=== Starting Experiment [%s] RunID=%s (N=%d, Algo=%s, Policy=%s, Fault=%s) ===",
            self.config.exp_id,
            self.run_id,
            self.config.node_count,
            self.config.algorithm,
            self.config.replication_policy,
            self.config.fault_scenario,
        )

        try:
            # 1. Cluster Startup & Convergence
            if self.config.manage_cluster:
                logger.info("Spinning up %d-node cluster profile...", self.config.node_count)
                started = cluster_mgr.start_cluster(
                    algorithm=self.config.algorithm,
                    policy=self.config.replication_policy,
                    clean=True,
                    wait_for_settled=True,
                )
                if not started:
                    raise RuntimeError(f"Cluster failed to start: {cluster_mgr.last_error}")
            else:
                if not cluster_mgr.is_cluster_running():
                    raise RuntimeError("Unmanaged cluster mode specified, but cluster is not reachable.")

            coord_info = cluster_mgr.ensure_cluster_settled(timeout=20.0)
            if not coord_info:
                raise RuntimeError(
                    f"Cluster leader election failed to settle. Diagnostics: {cluster_mgr.get_diagnostic_summary()}"
                )
            coord_id, coord_port = coord_info
            logger.info("Cluster ready: Coordinator Node %d on port %d", coord_id, coord_port)

            # 2. Start Continuous Telemetry Sampling
            logger.info("Starting background container telemetry sampler...")
            sampler = ContainerTelemetrySampler(
                node_count=self.config.node_count,
                run_id=self.run_id,
                output_path=self.raw_telemetry_path,
                sampling_interval_sec=self.config.telemetry_interval_sec,
                cluster_manager=cluster_mgr,
            )
            sampler.start()

            # 3. Workload Client & Fault Injector Initialization
            client = WorkloadClient(base_url=f"http://localhost:{coord_port}")
            injector = FaultInjector(cluster_manager=cluster_mgr)

            # 4. Scenario-Specific Execution
            scenario = self.config.fault_scenario.lower()

            if scenario == "none":
                logger.info("Executing baseline benchmark (%d requests)...", self.config.request_count)
                bench_res = client.run_benchmark(
                    request_count=self.config.request_count,
                    concurrency=self.config.concurrency,
                    warmup_count=self.config.warmup_count,
                    raw_trace_path=self.raw_workload_path,
                    run_id=self.run_id,
                )
                workload_summary = bench_res.to_dict()

            elif scenario == "coord_crash":
                workload_summary, fault_metrics = self._execute_coord_crash_scenario(
                    cluster_mgr, injector, client, coord_id
                )

            elif scenario == "follower_crash":
                workload_summary, fault_metrics = self._execute_follower_crash_scenario(
                    cluster_mgr, injector, client, coord_id
                )

            elif scenario == "pause_node":
                workload_summary, fault_metrics = self._execute_pause_scenario(
                    cluster_mgr, injector, client, coord_id
                )

            elif scenario == "network_partition":
                workload_summary, fault_metrics = self._execute_partition_scenario(
                    cluster_mgr, injector, client, coord_id
                )

            elif scenario == "follower_rejoin":
                workload_summary, fault_metrics = self._execute_follower_rejoin_scenario(
                    cluster_mgr, injector, client, coord_id
                )

            elif scenario == "cascading_crash":
                workload_summary, fault_metrics = self._execute_cascading_crash_scenario(
                    cluster_mgr, injector, client, coord_id
                )

            else:
                raise NotImplementedError(f"Scenario '{scenario}' execution not yet defined.")

            # 5. Harvest Final Application-Level Invariants
            time.sleep(1.0)  # Brief buffer for background async sync
            collector = TelemetryCollector(self.config.node_count)
            inv_summary = collector.harvest_cluster_telemetry()
            invariant_summary = inv_summary.to_dict()

            if not inv_summary.invariants_passed:
                errors.extend(inv_summary.invariant_errors)
                logger.error("Safety invariants failed: %s", inv_summary.invariant_errors)

        except Exception as exc:
            errors.append(f"Execution exception: {str(exc)}")
            logger.error("Experiment run aborted with exception: %s", exc, exc_info=True)

        finally:
            # 6. Stop Telemetry Sampler Safely
            if sampler:
                try:
                    sampler.stop()
                    telemetry_summary = sampler.get_summary()
                except Exception as exc:
                    errors.append(f"Sampler shutdown error: {exc}")

            # 7. Guaranteed Fault State Reversion
            if injector:
                try:
                    revert_report = injector.revert_all_faults()
                    if revert_report.get("errors"):
                        errors.extend([f"Fault cleanup error: {e}" for e in revert_report["errors"]])
                except Exception as exc:
                    errors.append(f"Fault reversion exception: {exc}")

            # 8. Scoped Cluster Teardown
            if self.config.manage_cluster:
                try:
                    cluster_mgr.stop_cluster(purge_volumes=True)
                except Exception as exc:
                    errors.append(f"Cluster teardown error: {exc}")

        # 9. Evaluate Pass/Fail Gate
        duration_sec = round(time.time() - t_start, 3)
        passed = (
            len(errors) == 0
            and workload_summary is not None
            and invariant_summary is not None
            and invariant_summary.get("invariants_passed", False)
        )
        status = "PASSED" if passed else "FAILED"

        # 10. Write Machine-Readable Summary and Manifest
        self._write_summary(
            status=status,
            duration_sec=duration_sec,
            workload_summary=workload_summary,
            telemetry_summary=telemetry_summary,
            invariant_summary=invariant_summary,
            fault_metrics=fault_metrics,
            errors=errors,
        )

        self._write_manifest(
            status=status,
            duration_sec=duration_sec,
            errors=errors,
        )

        logger.info(
            "=== Experiment [%s] Finished with Status: %s in %.2fs (Errors: %d) ===",
            self.config.exp_id,
            status,
            duration_sec,
            len(errors),
        )

        return ExperimentRunResult(
            run_id=self.run_id,
            exp_id=self.config.exp_id,
            status=status,
            success=passed,
            duration_sec=duration_sec,
            output_dir=self.output_dir,
            manifest_path=self.manifest_path,
            summary_path=self.summary_path,
            raw_workload_path=self.raw_workload_path if os.path.exists(self.raw_workload_path) else None,
            raw_telemetry_path=self.raw_telemetry_path if os.path.exists(self.raw_telemetry_path) else None,
            workload_summary=workload_summary,
            telemetry_summary=telemetry_summary,
            invariant_summary=invariant_summary,
            fault_metrics=fault_metrics,
            errors=errors,
        )

    # ── Fault Scenario Implementations ────────────────────────────────

    def _execute_coord_crash_scenario(
        self,
        cluster: ClusterManager,
        injector: FaultInjector,
        client: WorkloadClient,
        old_coord_id: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Crash active coordinator, measure election failover and write-readiness."""
        # 1. Warm-up traffic
        initial_reqs = min(20, max(5, self.config.request_count // 5))
        client.run_benchmark(
            request_count=initial_reqs,
            concurrency=self.config.concurrency,
            warmup_count=2,
            client_prefix="pre_crash",
            run_id=self.run_id,
        )

        # 2. Inject Crash
        logger.info("Fault scenario: Crashing coordinator Node %d...", old_coord_id)
        t_crash = time.perf_counter()
        injector.stop_node(old_coord_id)

        # 3. Detect new coordinator election
        surviving_ports = [
            port for nid, port in cluster.profile.http_ports.items() if nid != old_coord_id
        ]
        t_new_coord = None
        new_coord_id = None
        new_port = None
        deadline = time.monotonic() + 25.0

        while time.monotonic() < deadline:
            for port in surviving_ports:
                try:
                    with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=1.0) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            if data.get("is_coordinator") and data.get("accepting_votes"):
                                new_coord_id = data["node_id"]
                                new_port = port
                                t_new_coord = time.perf_counter()
                                break
                except Exception:
                    pass
            if new_coord_id is not None:
                break
            time.sleep(0.2)

        if not new_coord_id or not t_new_coord:
            raise TimeoutError("Cluster failed to elect new coordinator following crash within 25s.")

        failover_ms = (t_new_coord - t_crash) * 1000.0

        # 4. Measure Write-Readiness
        new_client = WorkloadClient(base_url=f"http://localhost:{new_port}")
        probe_cid = WorkloadClient.generate_client_id("probe", self.run_id, 0)
        probe_res = new_client.submit_single_vote(probe_cid, "Alice", run_id=self.run_id)
        t_probe = time.perf_counter()
        write_readiness_ms = (t_probe - t_crash) * 1000.0

        # 5. Execute remaining workload against new coordinator
        remaining = max(10, self.config.request_count - initial_reqs)
        bench_res = new_client.run_benchmark(
            request_count=remaining,
            concurrency=self.config.concurrency,
            warmup_count=0,
            client_prefix="post_crash",
            raw_trace_path=self.raw_workload_path,
            run_id=self.run_id,
        )

        fault_metrics = {
            "scenario": "coord_crash",
            "crashed_coordinator_id": old_coord_id,
            "new_coordinator_id": new_coord_id,
            "election_failover_ms": round(failover_ms, 2),
            "write_readiness_ms": round(write_readiness_ms, 2),
            "probe_write_success": probe_res.success,
        }
        return bench_res.to_dict(), fault_metrics

    def _execute_follower_crash_scenario(
        self,
        cluster: ClusterManager,
        injector: FaultInjector,
        client: WorkloadClient,
        coord_id: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Crash a follower node and verify quorum policy sensitivity."""
        follower_id = 1 if coord_id != 1 else 2
        logger.info("Fault scenario: Crashing follower Node %d...", follower_id)
        injector.stop_node(follower_id)

        bench_res = client.run_benchmark(
            request_count=self.config.request_count,
            concurrency=self.config.concurrency,
            warmup_count=self.config.warmup_count,
            raw_trace_path=self.raw_workload_path,
            run_id=self.run_id,
        )

        fault_metrics = {
            "scenario": "follower_crash",
            "crashed_follower_id": follower_id,
            "policy": self.config.replication_policy,
        }
        return bench_res.to_dict(), fault_metrics

    def _execute_pause_scenario(
        self,
        cluster: ClusterManager,
        injector: FaultInjector,
        client: WorkloadClient,
        coord_id: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Pause follower process and unpause during benchmark."""
        follower_id = 1 if coord_id != 1 else 2
        logger.info("Fault scenario: Pausing follower Node %d...", follower_id)
        injector.pause_node(follower_id)

        bench_res = client.run_benchmark(
            request_count=self.config.request_count,
            concurrency=self.config.concurrency,
            warmup_count=self.config.warmup_count,
            raw_trace_path=self.raw_workload_path,
            run_id=self.run_id,
        )

        injector.unpause_node(follower_id)
        fault_metrics = {"scenario": "pause_node", "paused_node_id": follower_id}
        return bench_res.to_dict(), fault_metrics

    def _execute_partition_scenario(
        self,
        cluster: ClusterManager,
        injector: FaultInjector,
        client: WorkloadClient,
        coord_id: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Isolate minority partition from cluster bridge network and verify majority commits + minority rejects."""
        minority_size = max(1, (cluster.node_count - 1) // 2)
        candidates = [nid for nid in range(1, cluster.node_count + 1) if nid != coord_id]
        minority = candidates[-minority_size:] if len(candidates) >= minority_size else [1]
        logger.info("Fault scenario: Partitioning minority nodes %s (coordinator Node %d)...", minority, coord_id)
        injector.partition_nodes(minority)

        # 1. Probe minority node to confirm write rejection under majority policy
        minority_rejected = False
        if minority:
            min_node = minority[0]
            min_port = cluster.profile.http_ports[min_node]
            min_client = WorkloadClient(base_url=f"http://localhost:{min_port}")
            min_cid = WorkloadClient.generate_client_id("min_probe", self.run_id, 0)
            min_res = min_client.submit_single_vote(min_cid, "Alice", run_id=self.run_id)
            minority_rejected = not min_res.success

        # 2. Execute benchmark against majority coordinator
        bench_res = client.run_benchmark(
            request_count=self.config.request_count,
            concurrency=self.config.concurrency,
            warmup_count=self.config.warmup_count,
            raw_trace_path=self.raw_workload_path,
            run_id=self.run_id,
        )

        # 3. Heal partition
        injector.heal_partition(minority)
        time.sleep(1.0)  # Brief buffer for reconnection sync

        fault_metrics = {
            "scenario": "network_partition",
            "partitioned_nodes": minority,
            "minority_write_rejected": minority_rejected,
            "majority_coordinator_id": coord_id,
        }
        return bench_res.to_dict(), fault_metrics

    def _execute_cascading_crash_scenario(
        self,
        cluster: ClusterManager,
        injector: FaultInjector,
        client: WorkloadClient,
        first_coord_id: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Consecutive coordinator terminations and multi-term Lamport convergence (EXP-07)."""
        # 1. Warm-up traffic
        initial_reqs = min(15, max(5, self.config.request_count // 5))
        client.run_benchmark(
            request_count=initial_reqs,
            concurrency=self.config.concurrency,
            warmup_count=2,
            client_prefix="pre_cascade",
            run_id=self.run_id,
        )

        # 2. Crash first coordinator
        logger.info("Cascading Fault: Crashing first coordinator Node %d...", first_coord_id)
        t_crash1 = time.perf_counter()
        injector.stop_node(first_coord_id)

        # 3. Detect second coordinator election
        surviving_ports_1 = [
            port for nid, port in cluster.profile.http_ports.items() if nid != first_coord_id
        ]
        second_coord_id = None
        second_port = None
        deadline1 = time.monotonic() + 25.0

        while time.monotonic() < deadline1:
            for port in surviving_ports_1:
                try:
                    with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=1.0) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            if data.get("is_coordinator") and data.get("accepting_votes"):
                                second_coord_id = data["node_id"]
                                second_port = port
                                break
                except Exception:
                    pass
            if second_coord_id is not None:
                break
            time.sleep(0.2)

        if not second_coord_id:
            raise TimeoutError("Cluster failed to elect second coordinator in cascading scenario.")

        failover1_ms = (time.perf_counter() - t_crash1) * 1000.0

        # 4. Crash second coordinator immediately
        logger.info("Cascading Fault: Crashing second coordinator Node %d...", second_coord_id)
        t_crash2 = time.perf_counter()
        injector.stop_node(second_coord_id)

        # 5. Detect third coordinator election
        surviving_ports_2 = [
            port
            for nid, port in cluster.profile.http_ports.items()
            if nid not in (first_coord_id, second_coord_id)
        ]
        third_coord_id = None
        third_port = None
        deadline2 = time.monotonic() + 25.0

        while time.monotonic() < deadline2:
            for port in surviving_ports_2:
                try:
                    with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=1.0) as resp:
                        if resp.status == 200:
                            data = json.loads(resp.read().decode("utf-8"))
                            if data.get("is_coordinator") and data.get("accepting_votes"):
                                third_coord_id = data["node_id"]
                                third_port = port
                                break
                except Exception:
                    pass
            if third_coord_id is not None:
                break
            time.sleep(0.2)

        if not third_coord_id:
            raise TimeoutError("Cluster failed to elect third coordinator in cascading scenario.")

        failover2_ms = (time.perf_counter() - t_crash2) * 1000.0

        # 6. Measure Write-Readiness on third coordinator
        third_client = WorkloadClient(base_url=f"http://localhost:{third_port}")
        casc_cid = WorkloadClient.generate_client_id("probe_casc", self.run_id, 0)
        probe_res = third_client.submit_single_vote(casc_cid, "Alice", run_id=self.run_id)
        t_probe = time.perf_counter()
        write_readiness_ms = (t_probe - t_crash2) * 1000.0

        # 7. Execute remaining workload against third coordinator
        remaining = max(10, self.config.request_count - initial_reqs)
        bench_res = third_client.run_benchmark(
            request_count=remaining,
            concurrency=self.config.concurrency,
            warmup_count=0,
            client_prefix="post_cascade",
            raw_trace_path=self.raw_workload_path,
            run_id=self.run_id,
        )

        fault_metrics = {
            "scenario": "cascading_crash",
            "crashed_coordinators": [first_coord_id, second_coord_id],
            "surviving_coordinator_id": third_coord_id,
            "failover_1_ms": round(failover1_ms, 2),
            "failover_2_ms": round(failover2_ms, 2),
            "total_failover_ms": round(failover1_ms + failover2_ms, 2),
            "write_readiness_ms": round(write_readiness_ms, 2),
            "probe_write_success": probe_res.success,
        }
        return bench_res.to_dict(), fault_metrics

    def _execute_follower_rejoin_scenario(
        self,
        cluster: ClusterManager,
        injector: FaultInjector,
        client: WorkloadClient,
        coord_id: int,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Stop follower, commit batch of votes, restart follower, measure recovery."""
        follower_id = 1 if coord_id != 1 else 2
        logger.info("Fault scenario: Stopping follower Node %d for rejoin test...", follower_id)
        injector.stop_node(follower_id)

        # Commit initial votes
        batch_size = min(30, self.config.request_count)
        bench_res = client.run_benchmark(
            request_count=batch_size,
            concurrency=self.config.concurrency,
            warmup_count=0,
            client_prefix="rejoin",
            raw_trace_path=self.raw_workload_path,
            run_id=self.run_id,
        )

        # Restart follower
        t_restart = time.perf_counter()
        injector.start_node(follower_id)
        time.sleep(2.0)  # Wait for catchup
        rejoin_dur_ms = (time.perf_counter() - t_restart) * 1000.0

        fault_metrics = {
            "scenario": "follower_rejoin",
            "rejoined_follower_id": follower_id,
            "rejoin_settle_ms": round(rejoin_dur_ms, 2),
        }
        return bench_res.to_dict(), fault_metrics

    # ── Artifact Persistence ──────────────────────────────────────────

    def _write_summary(
        self,
        status: str,
        duration_sec: float,
        workload_summary: Optional[Dict[str, Any]],
        telemetry_summary: Optional[Dict[str, Any]],
        invariant_summary: Optional[Dict[str, Any]],
        fault_metrics: Dict[str, Any],
        errors: List[str],
    ) -> None:
        """Persist machine-readable experiment summary."""
        summary_payload = {
            "schema_version": "1.0",
            "run_id": self.run_id,
            "exp_id": self.config.exp_id,
            "status": status,
            "success": (status == "PASSED"),
            "duration_sec": duration_sec,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "config": asdict(self.config),
            "workload": workload_summary,
            "container_telemetry": telemetry_summary,
            "invariants": invariant_summary,
            "fault_metrics": fault_metrics,
            "errors": errors,
        }
        with open(self.summary_path, "w", encoding="utf-8") as f:
            json.dump(summary_payload, f, indent=2)

    def _write_manifest(
        self,
        status: str,
        duration_sec: float,
        errors: List[str],
    ) -> None:
        """Persist machine-readable artifact manifest with cryptographic checksums."""
        artifacts: Dict[str, Any] = {}

        file_mappings = [
            ("raw_workload_ndjson", self.raw_workload_path),
            ("raw_telemetry_ndjson", self.raw_telemetry_path),
            ("summary_json", self.summary_path),
        ]

        for key, fpath in file_mappings:
            if os.path.exists(fpath):
                artifacts[key] = {
                    "filename": os.path.basename(fpath),
                    "path": os.path.abspath(fpath),
                    "size_bytes": os.path.getsize(fpath),
                    "sha256": _compute_sha256(fpath),
                    "record_count": _count_lines(fpath) if fpath.endswith(".ndjson") else None,
                }

        manifest_payload = {
            "manifest_version": "1.0",
            "run_id": self.run_id,
            "exp_id": self.config.exp_id,
            "status": status,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "duration_sec": duration_sec,
            "config": asdict(self.config),
            "environment": {
                "python_version": sys.version.split()[0],
                "platform": platform.platform(),
                "os": platform.system(),
            },
            "artifacts": artifacts,
            "error_count": len(errors),
        }

        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest_payload, f, indent=2)
