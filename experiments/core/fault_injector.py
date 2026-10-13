"""Controlled fault injection module for crash-stop, rejoin, and network partition experiments."""

import logging
import subprocess
import time
from typing import Any, Dict, List, Optional, Set

from experiments.config.benchmark_config import NETWORK_NAME, NODE_CONTAINER_PREFIX

logger = logging.getLogger("experiments.fault_injector")


class FaultInjector:
    """Provides safe, deterministic, and idempotent fault injection across containerized nodes."""

    def __init__(
        self,
        node_count: Optional[int] = None,
        valid_node_ids: Optional[List[int]] = None,
        network_name: Optional[str] = None,
        cluster_manager: Optional[Any] = None,
    ):
        self.cluster_manager = cluster_manager
        if cluster_manager is not None:
            self.node_count = cluster_manager.node_count if node_count is None else node_count
            self.network_name = network_name or cluster_manager.get_network_name()
        else:
            self.node_count = node_count
            self.network_name = network_name or NETWORK_NAME

        if valid_node_ids is not None:
            self.valid_node_ids: Optional[Set[int]] = set(valid_node_ids)
        elif self.node_count is not None:
            self.valid_node_ids = set(range(1, self.node_count + 1))
        else:
            self.valid_node_ids = None

        self._stopped_nodes: Set[int] = set()
        self._paused_nodes: Set[int] = set()
        self._disconnected_nodes: Set[int] = set()
        self._fault_history: List[Dict[str, Any]] = []
        self._resolved_networks: Dict[int, str] = {}

    def validate_target(self, node_id: int) -> None:
        """Validate that requested fault target is a valid node ID within bounds.

        Rejects invalid targets (negative, zero, non-integer, or out of range) safely.
        """
        if not isinstance(node_id, int) or isinstance(node_id, bool):
            raise TypeError(f"Target node_id must be an integer, got {type(node_id).__name__}: {node_id}")

        if node_id <= 0:
            raise ValueError(f"Invalid node_id {node_id}: Node ID must be a positive integer.")

        if self.valid_node_ids is not None and node_id not in self.valid_node_ids:
            raise ValueError(
                f"Target node_id {node_id} is out of bounds for cluster. Valid targets: {sorted(list(self.valid_node_ids))}"
            )

    def _container_name(self, node_id: int) -> str:
        if self.cluster_manager is not None and hasattr(self.cluster_manager, "get_container_name"):
            return self.cluster_manager.get_container_name(node_id)
        return f"{NODE_CONTAINER_PREFIX}{node_id}"

    def _resolve_network_name(self, node_id: int) -> str:
        """Dynamically resolve the Docker bridge network name."""
        if node_id in self._resolved_networks:
            return self._resolved_networks[node_id]

        cname = self._container_name(node_id)
        try:
            res = subprocess.run(
                ["docker", "inspect", cname, "--format", "{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}"],
                capture_output=True,
                text=True,
                timeout=5.0,
            )
            if res.returncode == 0 and res.stdout.strip():
                nets = res.stdout.strip().split()
                for net in nets:
                    if self.network_name in net or "voting-net" in net:
                        self._resolved_networks[node_id] = net
                        return net
                if nets:
                    self._resolved_networks[node_id] = nets[0]
                    return nets[0]
        except Exception:
            pass

        if self.cluster_manager is not None and hasattr(self.cluster_manager, "get_network_name"):
            net = self.cluster_manager.get_network_name()
            self._resolved_networks[node_id] = net
            return net

        return self.network_name

    # ── Crash-Stop & Restart ──────────────────────────────────────────

    def stop_node(self, node_id: int, timeout_sec: int = 1) -> bool:
        """Crash a node container immediately (simulating node crash-stop failure)."""
        self.validate_target(node_id)
        if node_id in self._stopped_nodes:
            logger.info("Node %d is already stopped; stop_node is idempotent no-op.", node_id)
            return True

        cname = self._container_name(node_id)
        logger.info("Fault injection: Stopping container %s (timeout=%ds)...", cname, timeout_sec)
        try:
            res = subprocess.run(
                ["docker", "stop", "-t", str(timeout_sec), cname],
                capture_output=True,
                text=True,
                timeout=max(10.0, float(timeout_sec + 5)),
            )
            if res.returncode == 0:
                self._stopped_nodes.add(node_id)
                self._fault_history.append({"action": "stop", "node_id": node_id, "timestamp": time.time()})
                return True
            logger.error("Failed to stop container %s: %s", cname, res.stderr)
            return False
        except Exception as exc:
            logger.error("Exception stopping container %s: %s", cname, exc)
            return False

    def start_node(self, node_id: int, timeout_sec: float = 15.0) -> bool:
        """Restart a previously stopped node container (simulating recovery/rejoin)."""
        self.validate_target(node_id)
        cname = self._container_name(node_id)
        logger.info("Fault injection: Starting container %s...", cname)
        try:
            res = subprocess.run(
                ["docker", "start", cname],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if res.returncode == 0:
                self._stopped_nodes.discard(node_id)
                self._fault_history.append({"action": "start", "node_id": node_id, "timestamp": time.time()})
                return True
            logger.error("Failed to start container %s: %s", cname, res.stderr)
            return False
        except Exception as exc:
            logger.error("Exception starting container %s: %s", cname, exc)
            return False

    def restart_node(self, node_id: int, timeout_sec: int = 1) -> bool:
        """Quickly reboot a node container."""
        self.validate_target(node_id)
        cname = self._container_name(node_id)
        logger.info("Fault injection: Restarting container %s...", cname)
        try:
            res = subprocess.run(
                ["docker", "restart", "-t", str(timeout_sec), cname],
                capture_output=True,
                text=True,
                timeout=max(15.0, float(timeout_sec + 5)),
            )
            if res.returncode == 0:
                self._stopped_nodes.discard(node_id)
                self._fault_history.append({"action": "restart", "node_id": node_id, "timestamp": time.time()})
                return True
            return False
        except Exception as exc:
            logger.error("Exception restarting container %s: %s", cname, exc)
            return False

    # ── Process Pause / Freeze ────────────────────────────────────────

    def pause_node(self, node_id: int, timeout_sec: float = 10.0) -> bool:
        """Pause a node container process (simulating kernel freeze or extreme GC pause)."""
        self.validate_target(node_id)
        if node_id in self._stopped_nodes:
            logger.warning("Cannot pause stopped node %d.", node_id)
            return False
        if node_id in self._paused_nodes:
            return True

        cname = self._container_name(node_id)
        logger.info("Fault injection: Pausing container %s...", cname)
        try:
            res = subprocess.run(["docker", "pause", cname], capture_output=True, text=True, timeout=timeout_sec)
            if res.returncode == 0:
                self._paused_nodes.add(node_id)
                self._fault_history.append({"action": "pause", "node_id": node_id, "timestamp": time.time()})
                return True
            return False
        except Exception as exc:
            logger.error("Exception pausing container %s: %s", cname, exc)
            return False

    def unpause_node(self, node_id: int, timeout_sec: float = 10.0) -> bool:
        """Unpause a frozen node container."""
        self.validate_target(node_id)
        cname = self._container_name(node_id)
        logger.info("Fault injection: Unpausing container %s...", cname)
        try:
            res = subprocess.run(["docker", "unpause", cname], capture_output=True, text=True, timeout=timeout_sec)
            if res.returncode == 0:
                self._paused_nodes.discard(node_id)
                self._fault_history.append({"action": "unpause", "node_id": node_id, "timestamp": time.time()})
                return True
            return False
        except Exception as exc:
            logger.error("Exception unpausing container %s: %s", cname, exc)
            return False

    # ── Network Partition ─────────────────────────────────────────────

    def disconnect_network(self, node_id: int, timeout_sec: float = 10.0) -> bool:
        """Disconnect a node container from the cluster bridge network (simulating network partition)."""
        self.validate_target(node_id)
        if node_id in self._disconnected_nodes:
            return True

        cname = self._container_name(node_id)
        net_name = self._resolve_network_name(node_id)
        self._resolved_networks[node_id] = net_name
        logger.info("Fault injection: Disconnecting %s from network %s...", cname, net_name)
        try:
            res = subprocess.run(
                ["docker", "network", "disconnect", net_name, cname],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if res.returncode == 0:
                self._disconnected_nodes.add(node_id)
                self._fault_history.append({"action": "disconnect", "node_id": node_id, "timestamp": time.time()})
                return True
            logger.error("Failed to disconnect container %s from %s: %s", cname, net_name, res.stderr)
            return False
        except Exception as exc:
            logger.error("Exception disconnecting container %s: %s", cname, exc)
            return False

    def reconnect_network(self, node_id: int, timeout_sec: float = 10.0) -> bool:
        """Reconnect a partitioned container back to the cluster bridge network."""
        self.validate_target(node_id)
        cname = self._container_name(node_id)
        net_name = self._resolved_networks.get(node_id) or self._resolve_network_name(node_id)
        logger.info("Fault injection: Reconnecting %s to network %s...", cname, net_name)
        try:
            res = subprocess.run(
                ["docker", "network", "connect", net_name, cname],
                capture_output=True,
                text=True,
                timeout=timeout_sec,
            )
            if res.returncode == 0:
                self._disconnected_nodes.discard(node_id)
                self._fault_history.append({"action": "reconnect", "node_id": node_id, "timestamp": time.time()})
                return True
            logger.error("Failed to reconnect container %s to %s: %s", cname, net_name, res.stderr)
            return False
        except Exception as exc:
            logger.error("Exception reconnecting container %s: %s", cname, exc)
            return False

    # ── Multi-Node Compound Fault Scenarios ───────────────────────────

    def partition_nodes(self, node_ids: List[int]) -> bool:
        """Disconnect multiple nodes simultaneously to partition the cluster."""
        for nid in node_ids:
            self.validate_target(nid)
        all_ok = True
        for nid in node_ids:
            if not self.disconnect_network(nid):
                all_ok = False
        return all_ok

    def heal_partition(self, node_ids: Optional[List[int]] = None) -> bool:
        """Reconnect partitioned nodes back to the cluster network."""
        targets = node_ids or list(self._disconnected_nodes)
        all_ok = True
        for nid in targets:
            if not self.reconnect_network(nid):
                all_ok = False
        return all_ok

    # ── Safe Idempotent Cleanup ───────────────────────────────────────

    def revert_all_faults(self, all_node_ids: Optional[List[int]] = None) -> Dict[str, Any]:
        """Ensure all paused, stopped, and disconnected containers are safely restored.

        Cleanup order guarantees proper state resumption:
        1. Unpause paused containers.
        2. Reconnect disconnected containers to the network.
        3. Start stopped containers.

        Strictly limits operations to experiment-controlled nodes and never executes
        blanket system pruning or wildcard deletion.
        """
        nodes = set(all_node_ids or []) | self._stopped_nodes | self._paused_nodes | self._disconnected_nodes
        logger.info("Reverting all active fault injections for nodes %s...", sorted(list(nodes)))
        cleanup_report = {
            "unpaused": [],
            "reconnected": [],
            "restarted": [],
            "errors": [],
        }

        # 1. Unpause
        for nid in list(self._paused_nodes):
            try:
                if self.unpause_node(nid):
                    cleanup_report["unpaused"].append(nid)
                else:
                    cleanup_report["errors"].append(f"Failed to unpause node {nid}")
            except Exception as exc:
                cleanup_report["errors"].append(f"Failed to unpause node {nid}: {exc}")

        # 2. Reconnect network
        for nid in list(self._disconnected_nodes):
            try:
                if self.reconnect_network(nid):
                    cleanup_report["reconnected"].append(nid)
                else:
                    cleanup_report["errors"].append(f"Failed to reconnect node {nid}")
            except Exception as exc:
                cleanup_report["errors"].append(f"Failed to reconnect node {nid}: {exc}")

        # 3. Start stopped nodes
        for nid in list(self._stopped_nodes):
            try:
                if self.start_node(nid):
                    cleanup_report["restarted"].append(nid)
                else:
                    cleanup_report["errors"].append(f"Failed to start node {nid}")
            except Exception as exc:
                cleanup_report["errors"].append(f"Failed to start node {nid}: {exc}")

        if cleanup_report["errors"]:
            logger.warning("Fault reversion finished with errors: %s", cleanup_report["errors"])

        return cleanup_report

    def __enter__(self) -> "FaultInjector":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        report = self.revert_all_faults()
        if report.get("errors"):
            logger.error("FaultInjector context manager cleanup encountered errors: %s", report["errors"])
