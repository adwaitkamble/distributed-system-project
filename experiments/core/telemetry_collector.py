"""Telemetry collector and invariant verification auditor for experiment benchmarks."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Set, Tuple

from experiments.config.benchmark_config import CLUSTER_PROFILES

logger = logging.getLogger("experiments.telemetry_collector")


def parse_byte_size(val: str) -> Optional[int]:
    """Parse human-readable Docker byte size strings (e.g. '34.1MiB', '1.2GB', '500B') to integer bytes."""
    if not val or not isinstance(val, str):
        return None
    val = val.strip()
    if val in ("--", "N/A", "null", ""):
        return None
    units = {
        "b": 1,
        "kb": 1000,
        "kib": 1024,
        "mb": 1000**2,
        "mib": 1024**2,
        "gb": 1000**3,
        "gib": 1024**3,
        "tb": 1000**4,
        "tib": 1024**4,
    }
    m = re.match(r"^([0-9.]+)\s*([a-zA-Z]*)$", val)
    if not m:
        return None
    num_str, unit_str = m.groups()
    try:
        num = float(num_str)
    except ValueError:
        return None
    unit = unit_str.lower()
    multiplier = units.get(unit, 1)
    return int(num * multiplier)


def parse_percentage(val: str) -> Optional[float]:
    """Parse percentage strings (e.g. '0.45%', '12.3%') to float percentage."""
    if not val or not isinstance(val, str):
        return None
    val = val.strip().rstrip("%")
    if val in ("--", "N/A", "null", ""):
        return None
    try:
        return round(float(val), 3)
    except ValueError:
        return None


@dataclass
class ContainerSample:
    """Represents a single point-in-time telemetry sample for a containerized node."""

    timestamp: float
    run_id: str
    node_id: int
    container_name: str
    cpu_percent: Optional[float]
    memory_bytes: Optional[int]
    memory_limit_bytes: Optional[int]
    memory_percent: Optional[float]
    net_rx_bytes: Optional[int]
    net_tx_bytes: Optional[int]
    status: str
    restart_count: int
    health_status: Optional[str] = None
    sampling_interval_sec: float = 1.0
    unavailable_metrics: List[str] = field(
        default_factory=lambda: ["grpc_internal_queue_depth", "lock_wait_nanoseconds"]
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "run_id": self.run_id,
            "node_id": self.node_id,
            "container_name": self.container_name,
            "sampling_interval_sec": self.sampling_interval_sec,
            "cpu_percent": self.cpu_percent,
            "memory_bytes": self.memory_bytes,
            "memory_limit_bytes": self.memory_limit_bytes,
            "memory_percent": self.memory_percent,
            "net_rx_bytes": self.net_rx_bytes,
            "net_tx_bytes": self.net_tx_bytes,
            "status": self.status,
            "restart_count": self.restart_count,
            "health_status": self.health_status,
            "unavailable_metrics": self.unavailable_metrics,
        }


class ContainerTelemetrySampler:
    """Background sampler recording continuous container resource telemetry during benchmark runs."""

    def __init__(
        self,
        node_count: int,
        run_id: str,
        output_path: Optional[str] = None,
        sampling_interval_sec: float = 1.0,
        cluster_manager: Optional[Any] = None,
    ):
        self.node_count = node_count
        self.run_id = run_id
        self.output_path = output_path
        self.sampling_interval_sec = max(0.2, sampling_interval_sec)
        self.cluster_manager = cluster_manager

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._samples: List[ContainerSample] = []
        self._file_handle = None

        if self.output_path:
            os.makedirs(os.path.dirname(os.path.abspath(self.output_path)), exist_ok=True)
            self._file_handle = open(self.output_path, "a", encoding="utf-8")

    def _get_container_name(self, node_id: int) -> str:
        if self.cluster_manager is not None and hasattr(self.cluster_manager, "get_container_name"):
            return self.cluster_manager.get_container_name(node_id)
        return f"voting-node{node_id}"

    def sample_once(self) -> List[ContainerSample]:
        """Perform a single bounded snapshot of container resource usage across all profile nodes."""
        ts = time.time()
        cname_to_nid = {self._get_container_name(nid): nid for nid in range(1, self.node_count + 1)}
        cnames = list(cname_to_nid.keys())
        samples: List[ContainerSample] = []

        # 1. Fetch live stats via docker stats
        stats_map: Dict[str, Dict[str, Any]] = {}
        try:
            cmd = ["docker", "stats", "--no-stream", "--format", "{{json .}}"] + cnames
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5.0)
            if res.returncode == 0 and res.stdout.strip():
                for line in res.stdout.strip().splitlines():
                    try:
                        data = json.loads(line)
                        name = data.get("Name") or data.get("Container")
                        if name:
                            stats_map[name] = data
                    except Exception:
                        continue
        except Exception as exc:
            logger.debug("docker stats snapshot failed or timed out: %s", exc)

        # 2. Inspect individual containers (for state, restarts, or missing stats)
        for cname, nid in cname_to_nid.items():
            stat = stats_map.get(cname)
            inspect_state = self._inspect_container_state(cname)
            status = inspect_state.get("status", "unknown")
            restart_count = inspect_state.get("restart_count", 0)
            health = inspect_state.get("health")

            cpu_pct = None
            mem_bytes = None
            mem_limit = None
            mem_pct = None
            net_rx = None
            net_tx = None

            if stat:
                cpu_pct = parse_percentage(stat.get("CPUPerc", ""))
                mem_pct = parse_percentage(stat.get("MemPerc", ""))
                mem_usage_str = stat.get("MemUsage", "")
                if "/" in mem_usage_str:
                    parts = mem_usage_str.split("/")
                    mem_bytes = parse_byte_size(parts[0])
                    mem_limit = parse_byte_size(parts[1])

                net_str = stat.get("NetIO", "")
                if "/" in net_str:
                    parts = net_str.split("/")
                    net_rx = parse_byte_size(parts[0])
                    net_tx = parse_byte_size(parts[1])
                status = "running"

            sample = ContainerSample(
                timestamp=ts,
                run_id=self.run_id,
                node_id=nid,
                container_name=cname,
                cpu_percent=cpu_pct,
                memory_bytes=mem_bytes,
                memory_limit_bytes=mem_limit,
                memory_percent=mem_pct,
                net_rx_bytes=net_rx,
                net_tx_bytes=net_tx,
                status=status,
                restart_count=restart_count,
                health_status=health,
                sampling_interval_sec=self.sampling_interval_sec,
            )
            samples.append(sample)

            with self._lock:
                self._samples.append(sample)
                if self._file_handle:
                    self._file_handle.write(json.dumps(sample.to_dict()) + "\n")
                    self._file_handle.flush()

        return samples

    def _inspect_container_state(self, cname: str) -> Dict[str, Any]:
        """Query docker inspect for container execution status, restarts, and health."""
        try:
            cmd = ["docker", "inspect", cname, "--format", "{{json .State}}|||{{.RestartCount}}"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=3.0)
            if res.returncode == 0 and res.stdout.strip():
                parts = res.stdout.strip().split("|||", 1)
                state_data = json.loads(parts[0])
                restarts = int(parts[1]) if len(parts) > 1 and parts[1].strip().isdigit() else 0
                health_obj = state_data.get("Health")
                health_status = health_obj.get("Status") if health_obj else None
                return {
                    "status": state_data.get("Status", "unknown"),
                    "restart_count": restarts,
                    "health": health_status,
                }
        except Exception:
            pass
        return {"status": "unreachable", "restart_count": 0, "health": None}

    def _worker(self) -> None:
        while not self._stop_event.is_set():
            t0 = time.time()
            try:
                self.sample_once()
            except Exception as exc:
                logger.warning("Telemetry sampling tick encountered error: %s", exc)
            elapsed = time.time() - t0
            sleep_time = max(0.01, self.sampling_interval_sec - elapsed)
            self._stop_event.wait(timeout=sleep_time)

    def start(self) -> None:
        """Launch background sampling thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._worker, name=f"TelemetrySampler-{self.run_id}", daemon=True)
        self._thread.start()
        logger.info("Started background container telemetry sampler for run %s", self.run_id)

    def stop(self) -> None:
        """Signal sampling thread to stop and flush file handle."""
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        with self._lock:
            if self._file_handle:
                try:
                    self._file_handle.flush()
                    self._file_handle.close()
                except Exception:
                    pass
                self._file_handle = None
        logger.info("Stopped background telemetry sampler for run %s (%d samples)", self.run_id, len(self._samples))

    def get_samples(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [s.to_dict() for s in self._samples]

    def get_summary(self) -> Dict[str, Any]:
        """Compute aggregate container resource consumption metrics across all collected samples."""
        with self._lock:
            samples = list(self._samples)

        if not samples:
            return {
                "total_samples": 0,
                "containers": {},
                "unavailable_metrics": ["grpc_internal_queue_depth", "lock_wait_nanoseconds"],
            }

        per_node: Dict[int, Dict[str, Any]] = {}
        for s in samples:
            nid = s.node_id
            if nid not in per_node:
                per_node[nid] = {
                    "container_name": s.container_name,
                    "sample_count": 0,
                    "cpu_vals": [],
                    "mem_bytes_vals": [],
                    "max_mem_limit": s.memory_limit_bytes,
                    "max_net_rx": 0,
                    "max_net_tx": 0,
                    "restarts": s.restart_count,
                    "statuses_observed": set(),
                }
            entry = per_node[nid]
            entry["sample_count"] += 1
            if s.cpu_percent is not None:
                entry["cpu_vals"].append(s.cpu_percent)
            if s.memory_bytes is not None:
                entry["mem_bytes_vals"].append(s.memory_bytes)
            if s.net_rx_bytes is not None and s.net_rx_bytes > entry["max_net_rx"]:
                entry["max_net_rx"] = s.net_rx_bytes
            if s.net_tx_bytes is not None and s.net_tx_bytes > entry["max_net_tx"]:
                entry["max_net_tx"] = s.net_tx_bytes
            entry["statuses_observed"].add(s.status)
            if s.restart_count > entry["restarts"]:
                entry["restarts"] = s.restart_count

        summary_containers: Dict[str, Any] = {}
        for nid, data in sorted(per_node.items()):
            cpu_vals = data["cpu_vals"]
            mem_vals = data["mem_bytes_vals"]
            summary_containers[str(nid)] = {
                "container_name": data["container_name"],
                "sample_count": data["sample_count"],
                "cpu_mean_pct": round(sum(cpu_vals) / len(cpu_vals), 2) if cpu_vals else 0.0,
                "cpu_max_pct": max(cpu_vals) if cpu_vals else 0.0,
                "mem_mean_bytes": int(sum(mem_vals) / len(mem_vals)) if mem_vals else 0,
                "mem_max_bytes": max(mem_vals) if mem_vals else 0,
                "mem_limit_bytes": data["max_mem_limit"],
                "net_rx_peak_bytes": data["max_net_rx"],
                "net_tx_peak_bytes": data["max_net_tx"],
                "total_restarts": data["restarts"],
                "statuses": sorted(list(data["statuses_observed"])),
            }

        return {
            "total_samples": len(samples),
            "sampling_interval_sec": self.sampling_interval_sec,
            "containers": summary_containers,
            "unavailable_metrics": ["grpc_internal_queue_depth", "lock_wait_nanoseconds"],
        }


@dataclass
class ClusterTelemetrySummary:
    node_count: int
    coordinator_id: Optional[int]
    election_term: int
    algorithm: str
    replication_policy: str
    total_cluster_election_messages: int
    election_messages_sent: int
    ok_messages_sent: int
    coord_messages_sent: int
    last_election_duration_ms: float
    total_committed_votes: int
    tally: Dict[str, int]
    ghost_votes_demoted: int
    committed_vote_ids: Set[str] = field(default_factory=set)
    invariants_passed: bool = True
    invariant_errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "node_count": self.node_count,
            "coordinator_id": self.coordinator_id,
            "election_term": self.election_term,
            "algorithm": self.algorithm,
            "replication_policy": self.replication_policy,
            "total_cluster_election_messages": self.total_cluster_election_messages,
            "election_messages_sent": self.election_messages_sent,
            "ok_messages_sent": self.ok_messages_sent,
            "coord_messages_sent": self.coord_messages_sent,
            "last_election_duration_ms": self.last_election_duration_ms,
            "total_committed_votes": self.total_committed_votes,
            "tally": self.tally,
            "ghost_votes_demoted": self.ghost_votes_demoted,
            "committed_vote_count": len(self.committed_vote_ids),
            "invariants_passed": self.invariants_passed,
            "invariant_errors": self.invariant_errors,
        }


class TelemetryCollector:
    """Harvests telemetry across all active node REST bridges and verifies safety invariants."""

    def __init__(self, node_count: int):
        if node_count not in CLUSTER_PROFILES:
            raise ValueError(f"Unsupported node count: {node_count}")
        self.node_count = node_count
        self.profile = CLUSTER_PROFILES[node_count]
        self._sampler: Optional[ContainerTelemetrySampler] = None

    def _fetch_json(self, url: str, timeout: float = 2.0) -> Optional[dict]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                if resp.status == 200:
                    return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None
        return None

    def start_background_sampling(
        self,
        run_id: str,
        output_path: Optional[str] = None,
        interval_sec: float = 1.0,
        cluster_manager: Optional[Any] = None,
    ) -> ContainerTelemetrySampler:
        """Initialize and start background container resource sampling."""
        self._sampler = ContainerTelemetrySampler(
            node_count=self.node_count,
            run_id=run_id,
            output_path=output_path,
            sampling_interval_sec=interval_sec,
            cluster_manager=cluster_manager,
        )
        self._sampler.start()
        return self._sampler

    def stop_background_sampling(self) -> Optional[Dict[str, Any]]:
        """Stop background sampling and return aggregate container metrics."""
        if self._sampler:
            self._sampler.stop()
            summary = self._sampler.get_summary()
            self._sampler = None
            return summary
        return None

    def harvest_cluster_telemetry(self) -> ClusterTelemetrySummary:
        """Collect and cross-verify telemetry across all cluster nodes."""
        node_states = {}
        election_states = {}
        recovery_states = {}
        tallies = {}
        node_sync_events = {}

        # 1. Collect raw state and events from all nodes
        for nid, port in self.profile.http_ports.items():
            base = f"http://localhost:{port}"
            node_states[nid] = self._fetch_json(f"{base}/api/node")
            election_states[nid] = self._fetch_json(f"{base}/api/election/status")
            recovery_states[nid] = self._fetch_json(f"{base}/api/recovery/status")
            tallies[nid] = self._fetch_json(f"{base}/api/votes/tally")
            node_sync_events[nid] = self._fetch_json(f"{base}/api/events?source=sync&limit=500")

        # 2. Identify coordinator
        coordinator_id = None
        term = 0
        algorithm = "unknown"
        policy = "unknown"
        coord_tally = {}
        total_committed = 0

        for nid, s in node_states.items():
            if s and s.get("is_coordinator"):
                coordinator_id = nid
                term = s.get("election_term", 0)
                algorithm = s.get("election_algorithm", "unknown")
                policy = s.get("replication_policy", "unknown")
                break

        if coordinator_id and tallies.get(coordinator_id):
            coord_tally = tallies[coordinator_id].get("tally", {})
            total_committed = tallies[coordinator_id].get("total_votes", 0)

        # 3. Sum message overhead across all surviving nodes
        total_election_sent = 0
        total_ok_sent = 0
        total_coord_sent = 0
        last_duration_ms = 0.0

        for nid, es in election_states.items():
            if es:
                counts = es.get("message_counts", {})
                total_election_sent += counts.get("election", 0)
                total_ok_sent += counts.get("ok", 0)
                total_coord_sent += counts.get("coordinator", 0)

                metrics = es.get("last_election_metrics", {})
                if metrics.get("duration_ms", 0) > last_duration_ms:
                    last_duration_ms = metrics.get("duration_ms", 0)

        total_logical = total_election_sent + total_ok_sent + total_coord_sent

        # 4. Sum ghost votes demoted across all nodes
        ghost_votes_demoted = 0
        for nid, rs in recovery_states.items():
            if rs:
                last_rec = rs.get("last_recovery") or {}
                ghost_votes_demoted += last_rec.get("rejected_partial_finalizations_count", 0)

        # 5. Extract committed vote identities per node from sync log events
        node_committed_ids: Dict[int, Set[str]] = {}
        for nid, ev_data in node_sync_events.items():
            node_committed_ids[nid] = set()
            if ev_data and ev_data.get("events"):
                for ev in ev_data["events"]:
                    vid = ev.get("vote_id")
                    status = ev.get("status")
                    if vid and (status == "COMMITTED" or "VOTE" in ev.get("event_type", "")):
                        node_committed_ids[nid].add(vid)

        coord_vote_ids = node_committed_ids.get(coordinator_id, set()) if coordinator_id else set()

        # 6. Verify Safety Invariants
        invariant_errors = []

        # Invariant 1: Single Leader Invariance
        coord_claims = [nid for nid, s in node_states.items() if s and s.get("is_coordinator")]
        if len(coord_claims) > 1:
            invariant_errors.append(f"Split-Brain Violation: Multiple coordinators claimed: {coord_claims}")
        elif len(coord_claims) == 0:
            invariant_errors.append("Liveness Violation: No active coordinator found in cluster")

        # Invariant 2: Tally Mathematical Integrity
        sum_candidate_votes = sum(coord_tally.values())
        if sum_candidate_votes != total_committed:
            invariant_errors.append(
                f"Tally Integrity Violation: Sum of candidate votes ({sum_candidate_votes}) != total committed count ({total_committed})"
            )

        # Invariant 3: Peer Tally Agreement (for alive peers)
        for nid, t_data in tallies.items():
            if t_data and t_data.get("success"):
                peer_total = t_data.get("total_votes", 0)
                if peer_total != total_committed:
                    logger.warning(
                        "Peer Node %d tally (%d) differs from coordinator (%d)",
                        nid,
                        peer_total,
                        total_committed,
                    )

        # Invariant 4: Exact Vote Identity Parity Across Replicas
        if coordinator_id and coord_vote_ids:
            for nid, peer_ids in node_committed_ids.items():
                peer_state = node_states.get(nid)
                if nid != coordinator_id and isinstance(peer_state, dict) and peer_state.get("is_active"):
                    diff = coord_vote_ids - peer_ids
                    if diff:
                        invariant_errors.append(
                            f"Identity Parity Violation: Peer Node {nid} is missing {len(diff)} committed votes from Coordinator: {list(diff)[:3]}..."
                        )

        return ClusterTelemetrySummary(
            node_count=self.node_count,
            coordinator_id=coordinator_id,
            election_term=term,
            algorithm=algorithm,
            replication_policy=policy,
            total_cluster_election_messages=total_logical,
            election_messages_sent=total_election_sent,
            ok_messages_sent=total_ok_sent,
            coord_messages_sent=total_coord_sent,
            last_election_duration_ms=last_duration_ms,
            total_committed_votes=total_committed,
            tally=coord_tally,
            ghost_votes_demoted=ghost_votes_demoted,
            committed_vote_ids=coord_vote_ids,
            invariants_passed=(len(invariant_errors) == 0),
            invariant_errors=invariant_errors,
        )
