"""Unit tests for Phase 7.2C ExperimentRunner, configuration validation, lifecycle, and artifacts."""

import json
import os
from unittest.mock import MagicMock
import pytest

from experiments.core.experiment_runner import (
    ExperimentConfig,
    ExperimentRunner,
    _compute_sha256,
    _count_lines,
)
from experiments.core.workload_client import BenchmarkSummary


def test_experiment_config_validation():
    """Verify ExperimentConfig validates all parameters strictly."""
    # Valid config
    valid_cfg = ExperimentConfig(
        exp_id="EXP-01",
        node_count=3,
        algorithm="bully",
        replication_policy="majority",
        fault_scenario="none",
        request_count=100,
        concurrency=5,
    )
    valid_cfg.validate()

    # Invalid node count
    with pytest.raises(ValueError, match="Unsupported node count"):
        ExperimentConfig(exp_id="EXP-01", node_count=4).validate()

    # Invalid algorithm
    with pytest.raises(ValueError, match="Unsupported algorithm"):
        ExperimentConfig(exp_id="EXP-01", node_count=3, algorithm="raft").validate()

    # Invalid policy
    with pytest.raises(ValueError, match="Unsupported replication policy"):
        ExperimentConfig(exp_id="EXP-01", node_count=3, replication_policy="single").validate()

    # Invalid fault scenario
    with pytest.raises(ValueError, match="Unsupported fault scenario"):
        ExperimentConfig(exp_id="EXP-01", node_count=3, fault_scenario="byzantine").validate()

    # Invalid request count or concurrency
    with pytest.raises(ValueError, match="request_count must be positive"):
        ExperimentConfig(exp_id="EXP-01", node_count=3, request_count=0).validate()

    with pytest.raises(ValueError, match="concurrency must be positive"):
        ExperimentConfig(exp_id="EXP-01", node_count=3, concurrency=-1).validate()


def test_experiment_runner_run_id_and_collision_safe_paths(tmp_path):
    """Verify ExperimentRunner constructs collision-safe run IDs and output directories."""
    cfg = ExperimentConfig(
        exp_id="EXP-02",
        node_count=5,
        algorithm="bully",
        replication_policy="majority",
        trial_idx=3,
        output_dir=str(tmp_path / "custom_out"),
    )
    runner = ExperimentRunner(cfg)

    assert "exp_02" in runner.run_id
    assert "5n_bully_majority" in runner.run_id
    assert "_t3_" in runner.run_id
    assert runner.output_dir == str(tmp_path / "custom_out")
    assert os.path.exists(runner.output_dir)
    assert runner.raw_workload_path.endswith("_requests.ndjson")
    assert runner.raw_telemetry_path.endswith("_telemetry.ndjson")
    assert runner.summary_path.endswith("_summary.json")
    assert runner.manifest_path.endswith("_manifest.json")


def test_experiment_runner_lifecycle_ordering_mocked(tmp_path, monkeypatch):
    """Verify ExperimentRunner executes the exact lifecycle sequence in order."""
    cfg = ExperimentConfig(
        exp_id="EXP-01",
        node_count=3,
        algorithm="bully",
        replication_policy="all",
        fault_scenario="none",
        request_count=10,
        output_dir=str(tmp_path / "run_lifecycle"),
        manage_cluster=True,
    )
    runner = ExperimentRunner(cfg)

    lifecycle_events = []

    # Mock ClusterManager
    from experiments.core.cluster_manager import ClusterManager

    def mock_start(self, **kwargs):
        lifecycle_events.append("cluster_start")
        return True

    def mock_settled(self, **kwargs):
        lifecycle_events.append("cluster_settled")
        return (3, 5003)

    def mock_stop(self, **kwargs):
        lifecycle_events.append("cluster_stop")
        return True

    monkeypatch.setattr(ClusterManager, "start_cluster", mock_start)
    monkeypatch.setattr(ClusterManager, "ensure_cluster_settled", mock_settled)
    monkeypatch.setattr(ClusterManager, "stop_cluster", mock_stop)

    # Mock ContainerTelemetrySampler
    from experiments.core.telemetry_collector import ContainerTelemetrySampler

    def mock_sampler_start(self):
        lifecycle_events.append("sampler_start")

    def mock_sampler_stop(self):
        lifecycle_events.append("sampler_stop")

    def mock_sampler_summary(self):
        return {"total_samples": 5, "containers": {}}

    monkeypatch.setattr(ContainerTelemetrySampler, "start", mock_sampler_start)
    monkeypatch.setattr(ContainerTelemetrySampler, "stop", mock_sampler_stop)
    monkeypatch.setattr(ContainerTelemetrySampler, "get_summary", mock_sampler_summary)

    # Mock WorkloadClient
    from experiments.core.workload_client import WorkloadClient

    def mock_benchmark(self, **kwargs):
        lifecycle_events.append("workload_execute")
        # Write 2 lines to raw trace path for manifest testing
        trace_path = kwargs.get("raw_trace_path")
        if trace_path:
            with open(trace_path, "w", encoding="utf-8") as f:
                f.write('{"req_id": 1}\n{"req_id": 2}\n')
        return BenchmarkSummary(
            total_requests=10,
            successful_requests=10,
            rejected_requests=0,
            failed_requests=0,
            duration_sec=1.0,
            throughput_ops_sec=10.0,
            p50_ms=5.0,
            p90_ms=7.0,
            p95_ms=8.0,
            p99_ms=9.0,
            mean_ms=5.2,
            stddev_ms=1.1,
            min_ms=3.0,
            max_ms=9.0,
        )

    monkeypatch.setattr(WorkloadClient, "run_benchmark", mock_benchmark)

    # Mock FaultInjector
    from experiments.core.fault_injector import FaultInjector

    def mock_revert(self, **kwargs):
        lifecycle_events.append("fault_revert")
        return {"unpaused": [], "reconnected": [], "restarted": [], "errors": []}

    monkeypatch.setattr(FaultInjector, "revert_all_faults", mock_revert)

    # Mock TelemetryCollector invariant harvest
    from experiments.core.telemetry_collector import TelemetryCollector, ClusterTelemetrySummary

    def mock_harvest(self):
        lifecycle_events.append("invariant_harvest")
        return ClusterTelemetrySummary(
            node_count=3,
            coordinator_id=3,
            election_term=1,
            algorithm="bully",
            replication_policy="all",
            total_cluster_election_messages=3,
            election_messages_sent=1,
            ok_messages_sent=1,
            coord_messages_sent=1,
            last_election_duration_ms=10.0,
            total_committed_votes=10,
            tally={"Alice": 10},
            ghost_votes_demoted=0,
            committed_vote_ids={"v1", "v2"},
            invariants_passed=True,
            invariant_errors=[],
        )

    monkeypatch.setattr(TelemetryCollector, "harvest_cluster_telemetry", mock_harvest)

    # Run experiment
    res = runner.run()

    # Verify lifecycle ordering
    expected_order = [
        "cluster_start",
        "cluster_settled",
        "sampler_start",
        "workload_execute",
        "invariant_harvest",
        "sampler_stop",
        "fault_revert",
        "cluster_stop",
    ]
    assert lifecycle_events == expected_order

    # Verify successful completion
    assert res.success is True
    assert res.status == "PASSED"
    assert os.path.isfile(res.summary_path)
    assert os.path.isfile(res.manifest_path)


def test_experiment_runner_fault_cleanup_on_exception(tmp_path, monkeypatch):
    """Verify that if an unhandled exception occurs during workload, cleanup is guaranteed and status is FAILED."""
    cfg = ExperimentConfig(
        exp_id="EXP-01",
        node_count=3,
        request_count=10,
        output_dir=str(tmp_path / "run_fail"),
    )
    runner = ExperimentRunner(cfg)

    cleanup_events = []

    from experiments.core.cluster_manager import ClusterManager
    from experiments.core.fault_injector import FaultInjector
    from experiments.core.telemetry_collector import ContainerTelemetrySampler
    from experiments.core.workload_client import WorkloadClient

    monkeypatch.setattr(ClusterManager, "start_cluster", lambda self, **kwargs: True)
    monkeypatch.setattr(ClusterManager, "ensure_cluster_settled", lambda self, **kwargs: (3, 5003))

    def mock_stop_cluster(self, **kwargs):
        cleanup_events.append("cluster_stop")
        return True

    monkeypatch.setattr(ClusterManager, "stop_cluster", mock_stop_cluster)

    def mock_sampler_stop(self):
        cleanup_events.append("sampler_stop")

    monkeypatch.setattr(ContainerTelemetrySampler, "start", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "stop", mock_sampler_stop)
    monkeypatch.setattr(ContainerTelemetrySampler, "get_summary", lambda self: {})

    def mock_revert_faults(self):
        cleanup_events.append("fault_revert")
        return {"errors": []}

    monkeypatch.setattr(FaultInjector, "revert_all_faults", mock_revert_faults)

    # Simulate catastrophic workload failure
    def mock_bench_fail(self, **kwargs):
        raise ConnectionResetError("Connection dropped mid-benchmark")

    monkeypatch.setattr(WorkloadClient, "run_benchmark", mock_bench_fail)

    res = runner.run()

    assert res.success is False
    assert res.status == "FAILED"
    assert any("Connection dropped" in err for err in res.errors)

    # Verify cleanup ran in finally block
    assert "sampler_stop" in cleanup_events
    assert "fault_revert" in cleanup_events
    assert "cluster_stop" in cleanup_events

    # Verify summary and manifest are still generated on failure
    assert os.path.isfile(res.summary_path)
    assert os.path.isfile(res.manifest_path)

    with open(res.summary_path, "r", encoding="utf-8") as f:
        s_data = json.load(f)
    assert s_data["status"] == "FAILED"
    assert s_data["success"] is False


def test_experiment_runner_manifest_schema_and_checksums(tmp_path, monkeypatch):
    """Verify manifest.json contains valid artifact paths, sha256 checksums, and record counts."""
    cfg = ExperimentConfig(
        exp_id="EXP-03",
        node_count=1,
        request_count=5,
        output_dir=str(tmp_path / "run_manifest"),
        manage_cluster=False,
    )
    runner = ExperimentRunner(cfg)

    from experiments.core.cluster_manager import ClusterManager
    from experiments.core.telemetry_collector import ContainerTelemetrySampler, TelemetryCollector, ClusterTelemetrySummary
    from experiments.core.workload_client import WorkloadClient

    monkeypatch.setattr(ClusterManager, "is_cluster_running", lambda self: True)
    monkeypatch.setattr(ClusterManager, "ensure_cluster_settled", lambda self, **kwargs: (1, 5000))
    monkeypatch.setattr(ContainerTelemetrySampler, "start", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "stop", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "get_summary", lambda self: {"total_samples": 0})

    def mock_bench(self, **kwargs):
        # Create raw trace file with 3 lines
        with open(runner.raw_workload_path, "w", encoding="utf-8") as f:
            f.write('{"r":1}\n{"r":2}\n{"r":3}\n')
        return BenchmarkSummary(
            total_requests=3,
            successful_requests=3,
            rejected_requests=0,
            failed_requests=0,
            duration_sec=0.5,
            throughput_ops_sec=6.0,
            p50_ms=4.0,
            p90_ms=5.0,
            p95_ms=5.0,
            p99_ms=5.0,
            mean_ms=4.0,
            stddev_ms=0.5,
            min_ms=3.0,
            max_ms=5.0,
        )

    monkeypatch.setattr(WorkloadClient, "run_benchmark", mock_bench)

    monkeypatch.setattr(
        TelemetryCollector,
        "harvest_cluster_telemetry",
        lambda self: ClusterTelemetrySummary(
            node_count=1,
            coordinator_id=1,
            election_term=1,
            algorithm="bully",
            replication_policy="majority",
            total_cluster_election_messages=0,
            election_messages_sent=0,
            ok_messages_sent=0,
            coord_messages_sent=0,
            last_election_duration_ms=0.0,
            total_committed_votes=3,
            tally={"Alice": 3},
            ghost_votes_demoted=0,
            invariants_passed=True,
        ),
    )

    res = runner.run()
    assert res.success is True

    # Inspect manifest.json
    with open(res.manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    assert manifest["manifest_version"] == "1.0"
    assert manifest["run_id"] == runner.run_id
    assert manifest["status"] == "PASSED"
    assert "python_version" in manifest["environment"]

    artifacts = manifest["artifacts"]
    assert "raw_workload_ndjson" in artifacts
    assert "summary_json" in artifacts

    workload_art = artifacts["raw_workload_ndjson"]
    assert workload_art["record_count"] == 3
    assert len(workload_art["sha256"]) == 64  # valid SHA-256 hex string


def test_experiment_runner_fails_on_invariant_violation(tmp_path, monkeypatch):
    """Verify that if safety invariants fail, runner records status FAILED even if workload succeeded."""
    cfg = ExperimentConfig(
        exp_id="EXP-01",
        node_count=3,
        request_count=5,
        output_dir=str(tmp_path / "run_inv_fail"),
        manage_cluster=False,
    )
    runner = ExperimentRunner(cfg)

    from experiments.core.cluster_manager import ClusterManager
    from experiments.core.telemetry_collector import ContainerTelemetrySampler, TelemetryCollector, ClusterTelemetrySummary
    from experiments.core.workload_client import WorkloadClient

    monkeypatch.setattr(ClusterManager, "is_cluster_running", lambda self: True)
    monkeypatch.setattr(ClusterManager, "ensure_cluster_settled", lambda self, **kwargs: (3, 5003))
    monkeypatch.setattr(ContainerTelemetrySampler, "start", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "stop", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "get_summary", lambda self: {})

    monkeypatch.setattr(
        WorkloadClient,
        "run_benchmark",
        lambda self, **kwargs: BenchmarkSummary(
            total_requests=5,
            successful_requests=5,
            rejected_requests=0,
            failed_requests=0,
            duration_sec=0.5,
            throughput_ops_sec=10.0,
            p50_ms=4.0,
            p90_ms=5.0,
            p95_ms=5.0,
            p99_ms=5.0,
            mean_ms=4.0,
            stddev_ms=0.5,
            min_ms=3.0,
            max_ms=5.0,
        ),
    )

    # Simulate split-brain invariant violation
    monkeypatch.setattr(
        TelemetryCollector,
        "harvest_cluster_telemetry",
        lambda self: ClusterTelemetrySummary(
            node_count=3,
            coordinator_id=3,
            election_term=2,
            algorithm="bully",
            replication_policy="majority",
            total_cluster_election_messages=4,
            election_messages_sent=2,
            ok_messages_sent=1,
            coord_messages_sent=1,
            last_election_duration_ms=12.0,
            total_committed_votes=5,
            tally={"Alice": 5},
            ghost_votes_demoted=0,
            invariants_passed=False,
            invariant_errors=["Split-Brain Violation: Multiple coordinators claimed: [2, 3]"],
        ),
    )

    res = runner.run()

    # Must be marked FAILED despite 100% successful requests!
    assert res.success is False
    assert res.status == "FAILED"
    assert any("Split-Brain Violation" in err for err in res.errors)

    with open(res.summary_path, "r", encoding="utf-8") as f:
        summary_data = json.load(f)
    assert summary_data["status"] == "FAILED"
    assert summary_data["success"] is False


def test_experiment_runner_partial_run_artifact_preservation(tmp_path, monkeypatch):
    """Verify partial workload and telemetry traces are preserved on disk and registered in manifest when run aborts."""
    cfg = ExperimentConfig(
        exp_id="EXP-01",
        node_count=3,
        request_count=20,
        output_dir=str(tmp_path / "run_partial_artifacts"),
        manage_cluster=False,
    )
    runner = ExperimentRunner(cfg)

    from experiments.core.cluster_manager import ClusterManager
    from experiments.core.telemetry_collector import ContainerTelemetrySampler, TelemetryCollector, ClusterTelemetrySummary
    from experiments.core.workload_client import WorkloadClient

    monkeypatch.setattr(ClusterManager, "is_cluster_running", lambda self: True)
    monkeypatch.setattr(ClusterManager, "ensure_cluster_settled", lambda self, **kwargs: (1, 5000))
    monkeypatch.setattr(ContainerTelemetrySampler, "start", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "stop", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "get_summary", lambda self: {"total_samples": 2})

    def mock_bench_partial_fail(self, **kwargs):
        # Simulate partial trace written before failure
        trace_path = kwargs.get("raw_trace_path")
        with open(trace_path, "w", encoding="utf-8") as f:
            f.write('{"req_id": 1, "success": true}\n')
            f.write('{"req_id": 2, "success": true}\n')
        # Simulate background telemetry also wrote 2 lines
        with open(runner.raw_telemetry_path, "w", encoding="utf-8") as f:
            f.write('{"timestamp": 1.0, "node_id": 1}\n')
            f.write('{"timestamp": 1.0, "node_id": 2}\n')
        raise RuntimeError("Worker process killed")

    monkeypatch.setattr(WorkloadClient, "run_benchmark", mock_bench_partial_fail)

    res = runner.run()

    assert res.success is False
    assert res.status == "FAILED"

    # Both raw files must exist and be preserved
    assert os.path.isfile(runner.raw_workload_path)
    assert os.path.isfile(runner.raw_telemetry_path)
    assert os.path.isfile(runner.manifest_path)
    assert os.path.isfile(runner.summary_path)

    # Manifest must correctly report partial record counts and hashes
    with open(runner.manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    artifacts = manifest["artifacts"]
    assert "raw_workload_ndjson" in artifacts
    assert artifacts["raw_workload_ndjson"]["record_count"] == 2
    assert "raw_telemetry_ndjson" in artifacts
    assert artifacts["raw_telemetry_ndjson"]["record_count"] == 2


def test_experiment_runner_fault_scenario_follower_crash(tmp_path, monkeypatch):
    """Verify follower crash scenario triggers FaultInjector.stop_node and records fault metrics."""
    cfg = ExperimentConfig(
        exp_id="EXP-03",
        node_count=3,
        algorithm="bully",
        replication_policy="majority",
        fault_scenario="follower_crash",
        request_count=10,
        output_dir=str(tmp_path / "run_follower_crash"),
        manage_cluster=False,
    )
    runner = ExperimentRunner(cfg)

    from experiments.core.cluster_manager import ClusterManager
    from experiments.core.fault_injector import FaultInjector
    from experiments.core.telemetry_collector import ContainerTelemetrySampler, TelemetryCollector, ClusterTelemetrySummary
    from experiments.core.workload_client import WorkloadClient

    monkeypatch.setattr(ClusterManager, "is_cluster_running", lambda self: True)
    monkeypatch.setattr(ClusterManager, "ensure_cluster_settled", lambda self, **kwargs: (3, 5003))
    monkeypatch.setattr(ContainerTelemetrySampler, "start", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "stop", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "get_summary", lambda self: {})

    stopped_nodes = []
    monkeypatch.setattr(FaultInjector, "stop_node", lambda self, nid: stopped_nodes.append(nid))
    monkeypatch.setattr(FaultInjector, "revert_all_faults", lambda self: {"errors": []})

    def mock_bench(self, **kwargs):
        return BenchmarkSummary(
            total_requests=10,
            successful_requests=10,
            rejected_requests=0,
            failed_requests=0,
            duration_sec=1.0,
            throughput_ops_sec=10.0,
            p50_ms=4.0,
            p90_ms=5.0,
            p95_ms=5.0,
            p99_ms=5.0,
            mean_ms=4.0,
            stddev_ms=0.5,
            min_ms=3.0,
            max_ms=5.0,
        )

    monkeypatch.setattr(WorkloadClient, "run_benchmark", mock_bench)
    monkeypatch.setattr(
        TelemetryCollector,
        "harvest_cluster_telemetry",
        lambda self: ClusterTelemetrySummary(
            node_count=3,
            coordinator_id=3,
            election_term=1,
            algorithm="bully",
            replication_policy="majority",
            total_cluster_election_messages=0,
            election_messages_sent=0,
            ok_messages_sent=0,
            coord_messages_sent=0,
            last_election_duration_ms=0.0,
            total_committed_votes=10,
            tally={"Alice": 10},
            ghost_votes_demoted=0,
            invariants_passed=True,
        ),
    )

    res = runner.run()

    assert res.success is True
    assert res.status == "PASSED"
    # Coordinator is 3, follower crashed should be 1
    assert stopped_nodes == [1]
    assert res.fault_metrics["scenario"] == "follower_crash"
    assert res.fault_metrics["crashed_follower_id"] == 1
    assert res.fault_metrics["policy"] == "majority"


def test_experiment_runner_fault_scenario_cascading_crash(tmp_path, monkeypatch):
    """Verify cascading crash scenario terminates consecutive coordinators and completes remaining benchmark."""
    cfg = ExperimentConfig(
        exp_id="EXP-07",
        node_count=5,
        algorithm="bully",
        replication_policy="majority",
        fault_scenario="cascading_crash",
        request_count=20,
        output_dir=str(tmp_path / "run_cascade"),
        manage_cluster=False,
    )
    runner = ExperimentRunner(cfg)

    from experiments.core.cluster_manager import ClusterManager
    from experiments.core.fault_injector import FaultInjector
    from experiments.core.telemetry_collector import ContainerTelemetrySampler, TelemetryCollector, ClusterTelemetrySummary
    from experiments.core.workload_client import WorkloadClient, RequestResult

    monkeypatch.setattr(ClusterManager, "is_cluster_running", lambda self: True)
    monkeypatch.setattr(ClusterManager, "ensure_cluster_settled", lambda self, **kwargs: (5, 5005))
    monkeypatch.setattr(ContainerTelemetrySampler, "start", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "stop", lambda self: None)
    monkeypatch.setattr(ContainerTelemetrySampler, "get_summary", lambda self: {})

    stopped_nodes = []
    monkeypatch.setattr(FaultInjector, "stop_node", lambda self, nid: stopped_nodes.append(nid))
    monkeypatch.setattr(FaultInjector, "revert_all_faults", lambda self: {"errors": []})

    # Mock election polling for cascading failover:
    # After node 5 is stopped, surviving ports query returns node 4 as coordinator.
    # After node 4 is stopped, surviving ports query returns node 3 as coordinator.
    import urllib.request
    from io import BytesIO

    class MockHTTPResponse:
        def __init__(self, data):
            self.data = json.dumps(data).encode("utf-8")
            self.status = 200

        def read(self):
            return self.data

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    def mock_urlopen(url_or_req, timeout=1.0):
        url = url_or_req.get_full_url() if hasattr(url_or_req, "get_full_url") else str(url_or_req)
        if "5004" in url and 5 in stopped_nodes and 4 not in stopped_nodes:
            return MockHTTPResponse({"is_coordinator": True, "accepting_votes": True, "node_id": 4})
        if "5003" in url and 4 in stopped_nodes:
            return MockHTTPResponse({"is_coordinator": True, "accepting_votes": True, "node_id": 3})
        return MockHTTPResponse({"is_coordinator": False, "accepting_votes": False, "node_id": 1})

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    monkeypatch.setattr(
        WorkloadClient,
        "submit_single_vote",
        lambda self, cid, choice, req_id=0, is_warmup=False, run_id="": RequestResult(
            req_id=req_id, run_id=run_id, client_id=cid, choice=choice, status_code=201,
            start_time=0.0, end_time=0.01, latency_ms=10.0, success=True, vote_id="v1"
        )
    )

    def mock_bench(self, **kwargs):
        return BenchmarkSummary(
            total_requests=15,
            successful_requests=15,
            rejected_requests=0,
            failed_requests=0,
            duration_sec=1.5,
            throughput_ops_sec=10.0,
            p50_ms=4.0,
            p90_ms=5.0,
            p95_ms=5.0,
            p99_ms=5.0,
            mean_ms=4.0,
            stddev_ms=0.5,
            min_ms=3.0,
            max_ms=5.0,
        )

    monkeypatch.setattr(WorkloadClient, "run_benchmark", mock_bench)
    monkeypatch.setattr(
        TelemetryCollector,
        "harvest_cluster_telemetry",
        lambda self: ClusterTelemetrySummary(
            node_count=5,
            coordinator_id=3,
            election_term=3,
            algorithm="bully",
            replication_policy="majority",
            total_cluster_election_messages=10,
            election_messages_sent=4,
            ok_messages_sent=3,
            coord_messages_sent=3,
            last_election_duration_ms=15.0,
            total_committed_votes=15,
            tally={"Alice": 15},
            ghost_votes_demoted=0,
            invariants_passed=True,
        ),
    )

    res = runner.run()

    assert res.success is True
    assert res.status == "PASSED"
    assert stopped_nodes == [5, 4]
    assert res.fault_metrics["scenario"] == "cascading_crash"
    assert res.fault_metrics["crashed_coordinators"] == [5, 4]
    assert res.fault_metrics["surviving_coordinator_id"] == 3
