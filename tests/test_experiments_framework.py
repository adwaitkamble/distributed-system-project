"""Unit tests for Phase 7 experimental framework, statistical math, and configurations."""

import pytest
from experiments.config.benchmark_config import CLUSTER_PROFILES
from experiments.config.matrix_definitions import EXPERIMENT_CATALOG, get_experiment_by_id
from experiments.core.cluster_manager import ClusterManager
from experiments.core.fault_injector import FaultInjector
from experiments.core.workload_client import WorkloadClient
from experiments.analysis.aggregate_metrics import calculate_ci95, aggregate_raw_trials


def test_cluster_profiles_configuration():
    assert 3 in CLUSTER_PROFILES
    assert 5 in CLUSTER_PROFILES
    assert 7 in CLUSTER_PROFILES

    p3 = CLUSTER_PROFILES[3]
    assert len(p3.http_ports) == 3
    assert p3.http_ports[1] == 5001
    assert p3.http_ports[3] == 5003

    p7 = CLUSTER_PROFILES[7]
    assert len(p7.http_ports) == 7
    assert p7.http_ports[7] == 5007


def test_cluster_manager_invalid_node_count():
    with pytest.raises(ValueError, match="Unsupported node count"):
        ClusterManager(4)


def test_experiment_catalog_specifications():
    assert len(EXPERIMENT_CATALOG) >= 9
    exp01 = get_experiment_by_id("EXP-01")
    assert exp01 is not None
    assert exp01.algorithms == ["bully"]
    assert exp01.policies == ["all"]
    assert 7 in exp01.node_sizes

    exp05 = get_experiment_by_id("EXP-05")
    assert exp05 is not None
    assert "bully" in exp05.algorithms
    assert "ring" in exp05.algorithms
    assert exp05.fault_scenario == "coord_crash"


def test_percentile_calculation():
    data = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    p50 = WorkloadClient._percentile(data, 50)
    assert p50 == 55.0

    p100 = WorkloadClient._percentile(data, 100)
    assert p100 == 100.0

    p0 = WorkloadClient._percentile(data, 0)
    assert p0 == 10.0


def test_confidence_interval_math():
    sample = [20.0, 21.0, 19.0, 20.5, 19.5]
    ci = calculate_ci95(sample)
    assert ci > 0.0
    assert ci < 1.0

    # Less than 2 data points returns 0.0
    assert calculate_ci95([10.0]) == 0.0


def test_fault_injector_container_names():
    injector = FaultInjector()
    assert injector._container_name(1) == "voting-node1"
    assert injector._container_name(7) == "voting-node7"


def test_telemetry_collector_identity_parity(monkeypatch):
    from experiments.core.telemetry_collector import TelemetryCollector

    collector = TelemetryCollector(3)

    def mock_fetch(url, timeout=2.0):
        if "/api/node" in url:
            nid = int(url.split(":")[2].split("/")[0]) - 5000
            return {"node_id": nid, "is_coordinator": (nid == 3), "is_active": True, "election_term": 1}
        if "/api/election/status" in url:
            return {"message_counts": {"election": 1, "ok": 1, "coordinator": 1}}
        if "/api/recovery/status" in url:
            return {"last_recovery": {"rejected_partial_finalizations_count": 0}}
        if "/api/votes/tally" in url:
            return {"success": True, "total_votes": 2, "tally": {"Alice": 2}}
        if "/api/events" in url:
            # All nodes have identical committed votes v1 and v2
            return {"events": [{"vote_id": "v1", "status": "COMMITTED"}, {"vote_id": "v2", "status": "COMMITTED"}]}
        return None

    monkeypatch.setattr(collector, "_fetch_json", mock_fetch)
    summary = collector.harvest_cluster_telemetry()
    assert summary.invariants_passed is True
    assert len(summary.invariant_errors) == 0
    assert summary.committed_vote_ids == {"v1", "v2"}


def test_telemetry_collector_identity_parity_violation(monkeypatch):
    from experiments.core.telemetry_collector import TelemetryCollector

    collector = TelemetryCollector(3)

    def mock_fetch(url, timeout=2.0):
        if "/api/node" in url:
            nid = int(url.split(":")[2].split("/")[0]) - 5000
            return {"node_id": nid, "is_coordinator": (nid == 3), "is_active": True, "election_term": 1}
        if "/api/election/status" in url:
            return {"message_counts": {"election": 1, "ok": 1, "coordinator": 1}}
        if "/api/recovery/status" in url:
            return {"last_recovery": {"rejected_partial_finalizations_count": 0}}
        if "/api/votes/tally" in url:
            return {"success": True, "total_votes": 2, "tally": {"Alice": 2}}
        if "/api/events" in url:
            nid = int(url.split(":")[2].split("/")[0]) - 5000
            if nid == 2:
                # Node 2 is missing v2
                return {"events": [{"vote_id": "v1", "status": "COMMITTED"}]}
            return {"events": [{"vote_id": "v1", "status": "COMMITTED"}, {"vote_id": "v2", "status": "COMMITTED"}]}
        return None

    monkeypatch.setattr(collector, "_fetch_json", mock_fetch)
    summary = collector.harvest_cluster_telemetry()
    assert summary.invariants_passed is False
    assert any("Identity Parity Violation" in err for err in summary.invariant_errors)
    assert any("Node 2 is missing" in err for err in summary.invariant_errors)


def test_workload_client_ndjson_preservation(tmp_path, monkeypatch):
    import json
    from experiments.core.workload_client import RequestResult

    client = WorkloadClient(base_url="http://localhost:5001")

    def mock_submit(client_id, choice):
        return RequestResult(
            client_id=client_id,
            choice=choice,
            status_code=201,
            latency_ms=12.5,
            success=True,
            vote_id=f"vote_{client_id}",
            lamport_ts=42,
        )

    monkeypatch.setattr(client, "submit_single_vote", mock_submit)

    trace_file = tmp_path / "traces" / "test_run.ndjson"
    summary = client.run_benchmark(request_count=5, concurrency=2, raw_trace_path=str(trace_file))

    assert summary.successful_requests == 5
    assert trace_file.exists()

    with open(trace_file, "r", encoding="utf-8") as f:
        lines = [json.loads(line) for line in f]

    assert len(lines) == 5
    assert lines[0]["status_code"] == 201
    assert lines[0]["latency_ms"] == 12.5
    assert lines[0]["lamport_ts"] == 42


def test_fault_injector_state_tracking(monkeypatch):
    import subprocess

    injector = FaultInjector()
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert injector.stop_node(1) is True
    assert 1 in injector._stopped_nodes

    assert injector.pause_node(2) is True
    assert 2 in injector._paused_nodes

    assert injector.disconnect_network(3) is True
    assert 3 in injector._disconnected_nodes

    # Test revert all faults restores everything cleanly
    injector.revert_all_faults()
    assert len(injector._stopped_nodes) == 0
    assert len(injector._paused_nodes) == 0
    assert len(injector._disconnected_nodes) == 0

    # Verify expected restore docker commands were executed
    cmd_strs = [" ".join(c) for c in executed_cmds]
    assert any("docker unpause voting-node2" in s for s in cmd_strs)
    assert any("docker network connect voting-net voting-node3" in s for s in cmd_strs)
    assert any("docker start voting-node1" in s for s in cmd_strs)

