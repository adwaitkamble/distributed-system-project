"""Unit tests for Phase 7.2B ClusterManager and FaultInjector components.

Tests mock all Docker subprocess and HTTP calls to verify:
1. Support for 1, 3, 5, and 7 node cluster profiles.
2. Safe rejection of invalid node counts and fault targets.
3. Health and readiness verification with diagnostic reporting on failure.
4. Process pause, crash-stop, and network partition lifecycles.
5. Context manager cleanup and idempotent fault recovery.
6. Absence of blanket system/volume pruning.
"""

import json
import subprocess
import urllib.error
import urllib.request
import pytest

from experiments.config.benchmark_config import (
    CLUSTER_PROFILES,
    ClusterProfileConfig,
)
from experiments.core.cluster_manager import ClusterManager
from experiments.core.fault_injector import FaultInjector


# ── ClusterManager Unit Tests ─────────────────────────────────────────


def test_cluster_profiles_support_single_node():
    """Verify single-node profile is configured and loaded properly."""
    assert 1 in CLUSTER_PROFILES
    p1 = CLUSTER_PROFILES[1]
    assert p1.node_count == 1
    assert "docker-compose.single.yml" in p1.compose_file
    assert p1.http_ports == {1: 5000}
    assert p1.grpc_ports == {1: 50051}

    cm = ClusterManager(1)
    assert cm.node_count == 1
    assert cm.profile.http_ports[1] == 5000


def test_cluster_manager_unsupported_node_counts():
    """Verify unsupported node sizes are rejected with descriptive ValueError."""
    for invalid_n in (0, 2, 4, 6, 8, -1, 10):
        with pytest.raises(ValueError, match="Unsupported node count"):
            ClusterManager(invalid_n)


def test_cluster_manager_start_cluster_success_mocked(monkeypatch):
    """Verify start_cluster constructs scoped compose up command, checks health, and verifies leader."""
    cm = ClusterManager(3)
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append((cmd, kwargs.get("env", {})))
        class MockRes:
            returncode = 0
            stdout = "Container started"
            stderr = ""
        return MockRes()

    monkeypatch.setattr(cm, "check_docker_available", lambda timeout_sec=5.0: True)
    monkeypatch.setattr(subprocess, "run", mock_run)
    monkeypatch.setattr(cm, "wait_for_health", lambda timeout=30.0: True)
    monkeypatch.setattr(cm, "ensure_cluster_settled", lambda timeout=15.0: (3, 5003))

    success = cm.start_cluster(algorithm="bully", policy="majority", clean=True)
    assert success is True

    # Check down -v was called for clean start
    down_call = [c for c, _ in executed_cmds if "down" in c]
    assert len(down_call) >= 1
    assert any("docker-compose.3node.yml" in str(arg) for arg in down_call[0])

    # Check up -d call with env vars
    up_call = [(c, e) for c, e in executed_cmds if "up" in c]
    assert len(up_call) == 1
    cmd_args, env = up_call[0]
    assert any("docker-compose.3node.yml" in str(arg) for arg in cmd_args)
    assert "-d" in cmd_args
    assert env.get("ELECTION_ALGORITHM") == "bully"
    assert env.get("REPLICATION_POLICY") == "majority"
    assert env.get("AUTO_RECOVER") == "true"


def test_cluster_manager_start_cluster_docker_unavailable(monkeypatch):
    """Verify start_cluster raises RuntimeError when Docker daemon is not available."""
    cm = ClusterManager(3)
    monkeypatch.setattr(cm, "check_docker_available", lambda timeout_sec=5.0: False)

    with pytest.raises(RuntimeError, match="Docker daemon is not reachable"):
        cm.start_cluster()


def test_cluster_manager_start_cluster_failure_capture_diagnostics(monkeypatch):
    """Verify start_cluster captures error message and returns False when compose up fails."""
    cm = ClusterManager(5)

    def mock_run(cmd, **kwargs):
        class MockRes:
            returncode = 1
            stderr = "Bind for 0.0.0.0:5001 failed: port is already allocated"
            stdout = ""
        return MockRes()

    monkeypatch.setattr(cm, "check_docker_available", lambda timeout_sec=5.0: True)
    monkeypatch.setattr(cm, "stop_cluster", lambda purge_volumes=True: True)
    monkeypatch.setattr(subprocess, "run", mock_run)

    success = cm.start_cluster(clean=False)
    assert success is False
    assert "already allocated" in cm.last_error


def test_cluster_manager_stop_cluster_scoped_cleanup(monkeypatch):
    """Verify stop_cluster only down-scales the specific profile's compose file."""
    cm = ClusterManager(7)
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    assert cm.stop_cluster(purge_volumes=True) is True
    assert len(executed_cmds) == 1
    cmd = executed_cmds[0]
    assert any("docker-compose.7node.yml" in str(arg) for arg in cmd)
    assert "down" in cmd
    assert "-v" in cmd

    # Calling cleanup() delegates to stop_cluster
    assert cm.cleanup() is True
    assert len(executed_cmds) == 2


def test_cluster_manager_wait_for_health_diagnostic_reporting(monkeypatch):
    """Verify wait_for_health captures per-node diagnostics and formats summary on timeout."""
    cm = ClusterManager(3)

    def mock_urlopen(url, timeout=1.0):
        if ":5001" in url or ":5003" in url:
            class MockResp:
                status = 200
                def __enter__(self):
                    return self
                def __exit__(self, *args):
                    pass
            return MockResp()
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    healthy = cm.wait_for_health(timeout=0.1)
    assert healthy is False
    assert 2 in cm.last_diagnostics
    assert cm.last_diagnostics[2]["status"] == "unreachable"
    assert "Connection refused" in cm.last_diagnostics[2]["error"]

    diag_summary = cm.get_diagnostic_summary()
    assert "Node 2 (:5002): UNREACHABLE" in diag_summary
    assert "Node 1 (:5001): HEALTHY" in diag_summary


def test_cluster_manager_settlement_detection(monkeypatch):
    """Verify ensure_cluster_settled detects the active accepting coordinator."""
    cm = ClusterManager(3)

    def mock_urlopen(url, timeout=1.5):
        class MockResp:
            status = 200
            def read(self):
                if ":5003" in url:
                    return json.dumps({
                        "node_id": 3,
                        "is_coordinator": True,
                        "accepting_votes": True,
                    }).encode("utf-8")
                return json.dumps({
                    "node_id": 1,
                    "is_coordinator": False,
                    "accepting_votes": False,
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockResp()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    coord_info = cm.ensure_cluster_settled(timeout=1.0)
    assert coord_info == (3, 5003)


# ── FaultInjector Unit Tests ──────────────────────────────────────────


def test_fault_injector_target_validation():
    """Verify validate_target safely rejects out-of-bounds, non-integer, and negative node IDs."""
    injector = FaultInjector(node_count=3)

    # Valid targets
    injector.validate_target(1)
    injector.validate_target(2)
    injector.validate_target(3)

    # Out of bounds
    with pytest.raises(ValueError, match="out of bounds"):
        injector.validate_target(4)

    with pytest.raises(ValueError, match="out of bounds"):
        injector.validate_target(5)

    # Zero or negative
    with pytest.raises(ValueError, match="positive integer"):
        injector.validate_target(0)

    with pytest.raises(ValueError, match="positive integer"):
        injector.validate_target(-1)

    # Non-integer types
    with pytest.raises(TypeError, match="must be an integer"):
        injector.validate_target("2")  # type: ignore

    with pytest.raises(TypeError, match="must be an integer"):
        injector.validate_target(True)  # type: ignore


def test_fault_injector_crash_and_start_lifecycle(monkeypatch):
    """Verify stop_node, idempotent re-stop, and start_node state tracking."""
    injector = FaultInjector(node_count=5)
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    # 1. Stop node 2
    assert injector.stop_node(2, timeout_sec=2) is True
    assert 2 in injector._stopped_nodes
    assert len(executed_cmds) == 1
    assert executed_cmds[0] == ["docker", "stop", "-t", "2", "voting-node2"]

    # 2. Re-stop node 2 should be idempotent no-op without running new subprocess
    assert injector.stop_node(2) is True
    assert len(executed_cmds) == 1

    # 3. Start node 2
    assert injector.start_node(2) is True
    assert 2 not in injector._stopped_nodes
    assert len(executed_cmds) == 2
    assert executed_cmds[1] == ["docker", "start", "voting-node2"]


def test_fault_injector_pause_and_unpause_lifecycle(monkeypatch):
    """Verify pause_node, stopped-node rejection, and unpause_node state tracking."""
    injector = FaultInjector(node_count=3)
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    # 1. Pause node 1
    assert injector.pause_node(1) is True
    assert 1 in injector._paused_nodes
    assert executed_cmds[0] == ["docker", "pause", "voting-node1"]

    # 2. Unpause node 1
    assert injector.unpause_node(1) is True
    assert 1 not in injector._paused_nodes
    assert executed_cmds[1] == ["docker", "unpause", "voting-node1"]

    # 3. Cannot pause a node that is currently stopped
    injector._stopped_nodes.add(3)
    assert injector.pause_node(3) is False


def test_fault_injector_network_partition_and_reconnect(monkeypatch):
    """Verify disconnect_network and reconnect_network state tracking."""
    injector = FaultInjector(node_count=5, network_name="voting-net")
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    # 1. Disconnect node 4
    assert injector.disconnect_network(4) is True
    assert 4 in injector._disconnected_nodes
    disconn_cmds = [c for c in executed_cmds if "disconnect" in c]
    assert len(disconn_cmds) == 1
    assert disconn_cmds[0] == ["docker", "network", "disconnect", "voting-net", "voting-node4"]

    # 2. Reconnect node 4
    assert injector.reconnect_network(4) is True
    assert 4 not in injector._disconnected_nodes
    conn_cmds = [c for c in executed_cmds if "connect" in c and "disconnect" not in c]
    assert len(conn_cmds) == 1
    assert conn_cmds[0] == ["docker", "network", "connect", "voting-net", "voting-node4"]


def test_fault_injector_compound_partition_and_healing(monkeypatch):
    """Verify partition_nodes and heal_partition handle multiple nodes safely."""
    injector = FaultInjector(node_count=5)
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    # Partition nodes 4 and 5
    assert injector.partition_nodes([4, 5]) is True
    assert injector._disconnected_nodes == {4, 5}

    # Heal partition
    assert injector.heal_partition() is True
    assert len(injector._disconnected_nodes) == 0


def test_fault_injector_context_manager_cleanup_on_exception(monkeypatch):
    """Verify __exit__ calls revert_all_faults in safe order when an unhandled exception occurs."""
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    with pytest.raises(RuntimeError, match="Simulation aborted"):
        with FaultInjector(node_count=3) as fi:
            fi.stop_node(1)
            fi.pause_node(2)
            fi.disconnect_network(3)
            raise RuntimeError("Simulation aborted")

    # Verify all 3 altered nodes were safely restored
    cmd_strs = [" ".join(c) for c in executed_cmds]
    assert any("docker unpause voting-node2" in s for s in cmd_strs)
    assert any("docker network connect voting-net voting-node3" in s for s in cmd_strs)
    assert any("docker start voting-node1" in s for s in cmd_strs)


def test_fault_injector_idempotent_cleanup_with_partial_failure(monkeypatch):
    """Verify revert_all_faults continues to restore remaining containers even if one restore call fails."""
    injector = FaultInjector(node_count=3)
    injector._paused_nodes.add(1)
    injector._disconnected_nodes.add(2)
    injector._stopped_nodes.add(3)

    def mock_run(cmd, **kwargs):
        class MockRes:
            # Simulate failure when unpausing node 1 (container already terminated)
            returncode = 1 if "unpause" in cmd else 0
            stderr = "Error response from daemon: Container is not paused" if "unpause" in cmd else ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    report = injector.revert_all_faults()
    # Node 2 and Node 3 should still be restored despite Node 1 unpause failure
    assert 2 in report["reconnected"]
    assert 3 in report["restarted"]
    assert len(injector._stopped_nodes) == 0
    assert len(injector._disconnected_nodes) == 0
    assert len(report["errors"]) == 1


def test_no_blanket_system_prune_enforcement(monkeypatch):
    """Verify that ClusterManager and FaultInjector never execute blanket system/volume prunes."""
    all_cmds = []

    def mock_run(cmd, **kwargs):
        all_cmds.append(" ".join(cmd))
        class MockRes:
            returncode = 0
            stderr = ""
            stdout = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    cm = ClusterManager(3)
    cm.stop_cluster(purge_volumes=True)

    fi = FaultInjector(node_count=3)
    fi.stop_node(1)
    fi.revert_all_faults()

    for cmd_str in all_cmds:
        assert "system prune" not in cmd_str
        assert "volume prune" not in cmd_str
        assert "network prune" not in cmd_str
        assert "image prune" not in cmd_str


def test_cluster_manager_project_name_scoping(monkeypatch):
    """Verify that passing an explicit project_name adds -p to all Compose invocations."""
    cm = ClusterManager(3, project_name="dvs-isolated-exp")
    executed_cmds = []

    def mock_run(cmd, **kwargs):
        executed_cmds.append(cmd)
        class MockRes:
            returncode = 0
            stderr = ""
            stdout = ""
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)
    cm.stop_cluster(purge_volumes=True)

    assert len(executed_cmds) == 1
    cmd = executed_cmds[0]
    assert "-p" in cmd
    p_idx = cmd.index("-p")
    assert cmd[p_idx + 1] == "dvs-isolated-exp"
    assert "down" in cmd


def test_cluster_manager_convergence_split_opinions(monkeypatch):
    """Verify ensure_cluster_settled rejects split-brain coordinator views across reachable peers."""
    cm = ClusterManager(3)

    def mock_urlopen(url, timeout=1.5):
        class MockResp:
            status = 200
            def read(self):
                # Node 3 claims it is coordinator
                if ":5003" in url:
                    return json.dumps({
                        "node_id": 3,
                        "coordinator_id": 3,
                        "is_coordinator": True,
                        "accepting_votes": True,
                    }).encode("utf-8")
                # But Node 1 still thinks Node 2 is coordinator!
                return json.dumps({
                    "node_id": 1,
                    "coordinator_id": 2,
                    "is_coordinator": False,
                    "accepting_votes": False,
                }).encode("utf-8")
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
        return MockResp()

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    # Convergence must fail because Node 1 and Node 3 disagree
    converged, coord_info, states = cm.check_cluster_converged()
    assert converged is False
    assert coord_info is None

    # ensure_cluster_settled should return None and record diagnostic error
    settled = cm.ensure_cluster_settled(timeout=0.1)
    assert settled is None
    assert "did not converge" in cm.last_error


def test_fault_injector_cluster_manager_integration(monkeypatch):
    """Verify FaultInjector can initialize directly from a ClusterManager instance."""
    cm = ClusterManager(5, project_name="test-cluster")
    monkeypatch.setattr(cm, "get_network_name", lambda: "test-cluster_voting-net")
    monkeypatch.setattr(cm, "get_container_name", lambda nid: f"custom-node-{nid}")

    fi = FaultInjector(cluster_manager=cm)
    assert fi.node_count == 5
    assert fi.valid_node_ids == {1, 2, 3, 4, 5}
    assert fi.network_name == "test-cluster_voting-net"
    assert fi._container_name(2) == "custom-node-2"


def test_fault_injector_revert_leaves_failed_nodes_in_state(monkeypatch):
    """Verify that unpause failure keeps node recorded in _paused_nodes and returns error."""
    fi = FaultInjector(node_count=3)
    fi._paused_nodes.add(2)

    def mock_run(cmd, **kwargs):
        class MockRes:
            returncode = 1
            stderr = "Docker daemon error: container cannot be unpaused"
        return MockRes()

    monkeypatch.setattr(subprocess, "run", mock_run)

    report = fi.revert_all_faults()
    assert 2 in fi._paused_nodes
    assert len(report["errors"]) == 1
    assert "Failed to unpause node 2" in report["errors"][0]

