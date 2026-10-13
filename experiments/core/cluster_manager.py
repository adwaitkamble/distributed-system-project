"""Docker Compose cluster management and health monitoring wrapper."""

import json
import logging
import os
import subprocess
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from experiments.config.benchmark_config import (
    CLUSTER_PROFILES,
    DEFAULT_HEALTHCHECK_TIMEOUT_SEC,
    DEFAULT_SETTLEMENT_TIMEOUT_SEC,
    ClusterProfileConfig,
)

logger = logging.getLogger("experiments.cluster_manager")


class ClusterManager:
    """Manages Docker Compose clusters for single (1), 3, 5, and 7 node topologies."""

    def __init__(
        self,
        node_count: int,
        project_root: Optional[str] = None,
        project_name: Optional[str] = None,
    ):
        if node_count not in CLUSTER_PROFILES:
            raise ValueError(
                f"Unsupported node count: {node_count}. Supported: {sorted(list(CLUSTER_PROFILES.keys()))}"
            )
        self.node_count = node_count
        self.profile: ClusterProfileConfig = CLUSTER_PROFILES[node_count]
        self.project_root = project_root or os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
        self.project_name = project_name
        self.last_diagnostics: Dict[int, Dict[str, Any]] = {}
        self.last_error: Optional[str] = None
        self._cached_container_names: Optional[Dict[int, str]] = None
        self._cached_network_name: Optional[str] = None

    def get_compose_cmd(self, action_args: List[str]) -> List[str]:
        """Construct scoped docker compose command using configured profile and optional project name."""
        cmd = ["docker", "compose"]
        if self.project_name:
            cmd.extend(["-p", self.project_name])
        compose_path = os.path.join(self.project_root, self.profile.compose_file)
        cmd.extend(["-f", compose_path])
        cmd.extend(action_args)
        return cmd

    def check_docker_available(self, timeout_sec: float = 5.0) -> bool:
        """Verify that Docker CLI and Docker engine are responsive with bounded timeout."""
        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=self.project_root,
                timeout=timeout_sec,
            )
            return res.returncode == 0
        except Exception as exc:
            self.last_error = f"Docker daemon unavailable: {exc}"
            return False

    def get_container_names(self) -> Dict[int, str]:
        """Inspect Compose configuration to resolve node_id -> container_name mapping."""
        if self._cached_container_names is not None:
            return self._cached_container_names

        mapping: Dict[int, str] = {}
        try:
            cmd = self.get_compose_cmd(["config", "--format", "json"])
            res = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True, timeout=10.0)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                for svc_name, svc_info in data.get("services", {}).items():
                    env = svc_info.get("environment", {})
                    nid_val = env.get("NODE_ID")
                    cname = svc_info.get("container_name")
                    if nid_val is not None and cname:
                        mapping[int(nid_val)] = cname
        except Exception as exc:
            logger.debug("Could not resolve container names from compose config: %s", exc)

        # Fallback to standard conventions
        for nid in range(1, self.node_count + 1):
            if nid not in mapping:
                mapping[nid] = f"voting-node{nid}"

        self._cached_container_names = mapping
        return mapping

    def get_container_name(self, node_id: int) -> str:
        """Resolve specific container name for a node ID."""
        return self.get_container_names().get(node_id, f"voting-node{node_id}")

    def get_network_name(self) -> str:
        """Resolve actual Docker bridge network name created by Compose."""
        if self._cached_network_name is not None:
            return self._cached_network_name

        resolved_name = None
        try:
            cmd = self.get_compose_cmd(["config", "--format", "json"])
            res = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True, timeout=10.0)
            if res.returncode == 0:
                data = json.loads(res.stdout)
                networks = data.get("networks", {})
                if "voting-net" in networks and isinstance(networks["voting-net"], dict):
                    resolved_name = networks["voting-net"].get("name")
        except Exception as exc:
            logger.debug("Could not resolve network name from compose config: %s", exc)

        if not resolved_name:
            if self.project_name:
                resolved_name = f"{self.project_name}_voting-net"
            else:
                resolved_name = "docker_voting-net"

        self._cached_network_name = resolved_name
        return resolved_name

    def start_cluster(
        self,
        algorithm: str = "bully",
        policy: str = "all",
        clean: bool = True,
        build: bool = False,
        timeout: float = DEFAULT_HEALTHCHECK_TIMEOUT_SEC,
        wait_for_settled: bool = True,
    ) -> bool:
        """Start the cluster using Docker Compose with the specified algorithm and policy.

        Verifies both container health (HTTP 200 on /api/health) and application readiness
        (coordinator settled and accepting votes) before returning success.
        """
        if not self.check_docker_available():
            raise RuntimeError("Docker daemon is not reachable. Ensure Docker Desktop is running.")

        if clean:
            self.stop_cluster(purge_volumes=True)

        env = os.environ.copy()
        env["ELECTION_ALGORITHM"] = algorithm.lower()
        env["REPLICATION_POLICY"] = policy.lower()
        env["AUTO_RECOVER"] = "true"

        cmd = self.get_compose_cmd(["up", "-d"])
        if build:
            cmd.append("--build")

        logger.info(
            "Starting %d-node cluster profile '%s' (algo=%s, policy=%s)...",
            self.node_count,
            self.profile.compose_file,
            algorithm,
            policy,
        )
        try:
            up_timeout = 180.0 if build else 60.0
            res = subprocess.run(cmd, cwd=self.project_root, env=env, capture_output=True, text=True, timeout=up_timeout)
        except subprocess.TimeoutExpired as exc:
            self.last_error = f"Timed out waiting for docker compose up: {exc}"
            logger.error(self.last_error)
            return False

        if res.returncode != 0:
            self.last_error = f"Failed to start cluster: {res.stderr.strip()}"
            logger.error(self.last_error)
            return False

        # 1. Verify container health across all nodes
        healthy = self.wait_for_health(timeout=timeout)
        if not healthy:
            logger.error(
                "Health verification failed for %d-node cluster. Diagnostics: %s",
                self.node_count,
                self.get_diagnostic_summary(),
            )
            return False

        # 2. Verify application readiness (coordinator elected and accepting votes)
        if wait_for_settled:
            settle_timeout = min(15.0, timeout)
            coord_info = self.ensure_cluster_settled(timeout=settle_timeout)
            if not coord_info:
                self.last_error = f"Cluster health passed but leader election did not settle within {settle_timeout}s."
                logger.error(self.last_error)
                return False
            coord_id, coord_port = coord_info
            logger.info(
                "Cluster readiness confirmed: Node %d on port %d is active coordinator accepting votes.",
                coord_id,
                coord_port,
            )

        return True

    def stop_cluster(self, purge_volumes: bool = True, timeout_sec: float = 30.0) -> bool:
        """Stop and tear down only the current profile's containers, networks, and volumes.

        Scoped strictly to self.profile.compose_file and self.project_name to ensure cleanup
        affects only the experiment's own resources and never touches unrelated Docker containers or volumes.
        """
        cmd_args = ["down"]
        if purge_volumes:
            cmd_args.append("-v")

        cmd = self.get_compose_cmd(cmd_args)
        logger.info("Tearing down %d-node cluster profile '%s' (purge_volumes=%s)...", self.node_count, self.profile.compose_file, purge_volumes)
        try:
            res = subprocess.run(cmd, cwd=self.project_root, capture_output=True, text=True, timeout=timeout_sec)
            if res.returncode != 0:
                self.last_error = f"Failed to stop cluster: {res.stderr.strip()}"
                logger.error(self.last_error)
                return False
            return True
        except subprocess.TimeoutExpired as exc:
            self.last_error = f"Timed out tearing down cluster: {exc}"
            logger.error(self.last_error)
            return False

    def wait_for_health(self, timeout: float = DEFAULT_HEALTHCHECK_TIMEOUT_SEC) -> bool:
        """Wait until all nodes in the profile report HTTP 200 OK via their REST bridge."""
        deadline = time.monotonic() + timeout
        logger.info("Waiting up to %.1fs for all %d nodes to become healthy...", timeout, self.node_count)

        while time.monotonic() < deadline:
            all_healthy = True
            current_diagnostics: Dict[int, Dict[str, Any]] = {}

            for nid, port in self.profile.http_ports.items():
                url = f"http://localhost:{port}/api/health"
                t0 = time.perf_counter()
                try:
                    with urllib.request.urlopen(url, timeout=1.0) as resp:
                        lat_ms = (time.perf_counter() - t0) * 1000.0
                        if resp.status == 200:
                            current_diagnostics[nid] = {
                                "status": "healthy",
                                "port": port,
                                "latency_ms": round(lat_ms, 2),
                                "code": resp.status,
                            }
                        else:
                            current_diagnostics[nid] = {
                                "status": "unhealthy",
                                "port": port,
                                "code": resp.status,
                            }
                            all_healthy = False
                except Exception as exc:
                    current_diagnostics[nid] = {
                        "status": "unreachable",
                        "port": port,
                        "error": str(exc),
                    }
                    all_healthy = False

            self.last_diagnostics = current_diagnostics

            if all_healthy:
                logger.info("All %d nodes report healthy status.", self.node_count)
                return True
            time.sleep(1.0)

        self.last_error = f"Timeout waiting {timeout}s for {self.node_count}-node cluster health."
        logger.warning("%s Diagnostics: %s", self.last_error, self.get_diagnostic_summary())
        return False

    def is_cluster_running(self) -> bool:
        """Fast check if all nodes in the current profile are reachable and reporting health 200."""
        for port in self.profile.http_ports.values():
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/api/health", timeout=0.8) as resp:
                    if resp.status != 200:
                        return False
            except Exception:
                return False
        return True

    def get_coordinator_info(self) -> Optional[Tuple[int, int]]:
        """Discover the active coordinator in the cluster. Returns (coordinator_id, port)."""
        for nid, port in self.profile.http_ports.items():
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=1.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        if data.get("is_coordinator") and data.get("accepting_votes"):
                            return data["node_id"], port
            except Exception:
                continue
        return None

    def check_cluster_converged(self) -> Tuple[bool, Optional[Tuple[int, int]], Dict[int, Any]]:
        """Verify cluster convergence: exactly 1 coordinator exists and all reachable peers agree."""
        node_states: Dict[int, Any] = {}
        coordinators: List[Tuple[int, int]] = []

        for nid, port in self.profile.http_ports.items():
            url = f"http://localhost:{port}/api/node"
            try:
                with urllib.request.urlopen(url, timeout=1.5) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8"))
                        node_states[nid] = data
                        if data.get("is_coordinator") and data.get("accepting_votes"):
                            coordinators.append((data.get("node_id", nid), port))
                    else:
                        node_states[nid] = {"status": "http_error", "code": resp.status}
            except Exception as exc:
                node_states[nid] = {"status": "unreachable", "error": str(exc)}

        if len(coordinators) != 1:
            return False, None, node_states

        coord_id, coord_port = coordinators[0]
        # In a converged cluster, all reachable nodes that returned node state must agree on coordinator_id
        for nid, state in node_states.items():
            if isinstance(state, dict) and "coordinator_id" in state:
                if state["coordinator_id"] != coord_id:
                    return False, None, node_states

        return True, (coord_id, coord_port), node_states

    def ensure_cluster_settled(self, timeout: float = DEFAULT_SETTLEMENT_TIMEOUT_SEC) -> Optional[Tuple[int, int]]:
        """Wait until leader election settles and a stable coordinator is converged and accepting votes."""
        deadline = time.monotonic() + timeout
        last_states: Dict[int, Any] = {}
        while time.monotonic() < deadline:
            converged, coord_info, last_states = self.check_cluster_converged()
            if converged and coord_info is not None:
                return coord_info
            time.sleep(0.5)

        self.last_diagnostics = last_states
        self.last_error = f"Leader election did not converge within {timeout}s."
        return None

    def get_all_node_states(self) -> Dict[int, dict]:
        """Fetch runtime status for all accessible nodes in the profile."""
        states = {}
        for nid, port in self.profile.http_ports.items():
            try:
                with urllib.request.urlopen(f"http://localhost:{port}/api/node", timeout=1.5) as resp:
                    if resp.status == 200:
                        states[nid] = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                states[nid] = {"node_id": nid, "error": str(e), "is_active": False}
        return states

    def get_diagnostic_summary(self) -> str:
        """Format a human-readable diagnostic summary of current per-node health statuses."""
        if not self.last_diagnostics:
            return "No diagnostics collected."
        parts = []
        for nid, diag in sorted(self.last_diagnostics.items()):
            port = self.profile.http_ports.get(nid)
            status = diag.get("status")
            if status == "healthy":
                parts.append(f"Node {nid} (:{port}): HEALTHY ({diag.get('latency_ms', 0)}ms)")
            elif status == "unreachable":
                parts.append(f"Node {nid} (:{port}): UNREACHABLE ({diag.get('error')})")
            elif "role" in diag or "coordinator_id" in diag:
                role = diag.get("role", "unknown")
                coord = diag.get("coordinator_id")
                accepting = diag.get("accepting_votes", False)
                parts.append(f"Node {nid} (:{port}): role={role}, coord={coord}, accepting={accepting}")
            else:
                err = diag.get("error", f"code {diag.get('code')}")
                parts.append(f"Node {nid} (:{port}): {status or 'UNKNOWN'} ({err})")
        return "; ".join(parts)

    def cleanup(self) -> bool:
        """Idempotent teardown of cluster resources."""
        return self.stop_cluster(purge_volumes=True)

    def __enter__(self) -> "ClusterManager":
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        pass
