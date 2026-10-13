"""Node configuration — parsed from environment variables or constructed directly.

Validation rules:
- NODE_ID must be a positive integer and listed exactly once in PEERS.
- Peer IDs must be unique and positive integers.
- Heartbeat and election timeouts must be positive integers.
- INITIAL_COORDINATOR_ID, if set, must be a configured cluster member.
- Candidates list must be non-empty.
"""

from dataclasses import dataclass, field
from typing import Optional
import os


@dataclass(frozen=True)
class PeerInfo:
    """Connection information for one peer node."""

    node_id: int
    host: str
    port: int

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port}"


@dataclass
class NodeConfig:
    """Complete configuration for a single node."""

    node_id: int
    grpc_port: int
    election_algorithm: str          # "bully" | "ring"
    peers: dict                      # {int: PeerInfo}
    heartbeat_interval_ms: int
    heartbeat_timeout_ms: int
    election_timeout_ms: int
    replication_policy: str           # "all" | "majority"
    initial_coordinator_id: Optional[int]

    # Database
    db_host: str
    db_port: int
    db_user: str
    db_password: str
    db_name: str
    use_sqlite: bool
    sqlite_path: Optional[str]

    log_level: str
    candidates: list                  # list[str]
    auto_recover: bool = False

    # ── Derived helpers ──────────────────────────────────────────

    @property
    def peer_ids(self) -> list:
        """Sorted list of peer node IDs (excludes self)."""
        return sorted(pid for pid in self.peers if pid != self.node_id)

    @property
    def all_node_ids(self) -> list:
        """Sorted list of every node ID in the cluster (includes self)."""
        return sorted(set(self.peers.keys()) | {self.node_id})

    @property
    def default_coordinator_id(self) -> int:
        """Amendment 1: INITIAL_COORDINATOR_ID override, else highest ID."""
        if self.initial_coordinator_id is not None:
            return self.initial_coordinator_id
        return max(self.all_node_ids)

    # ── Validation ───────────────────────────────────────────────

    def validate(self) -> None:
        """Fail-fast on bad configuration."""
        if self.node_id <= 0:
            raise ValueError(f"NODE_ID must be a positive integer, got {self.node_id}")

        if not self.peers:
            raise ValueError("PEERS must contain at least one configured node")

        if self.node_id not in self.peers:
            raise ValueError(f"NODE_ID={self.node_id} must be listed in PEERS")

        for pid, pinfo in self.peers.items():
            if not isinstance(pid, int) or pid <= 0:
                raise ValueError(f"Peer ID must be a positive integer, got {pid}")
            if pinfo.node_id != pid:
                raise ValueError(f"PeerInfo node_id {pinfo.node_id} does not match key {pid}")

        # Heartbeat and election timeouts must be positive
        if self.heartbeat_interval_ms <= 0:
            raise ValueError(
                f"HEARTBEAT_INTERVAL_MS must be positive, got {self.heartbeat_interval_ms}"
            )
        if self.heartbeat_timeout_ms <= 0:
            raise ValueError(
                f"HEARTBEAT_TIMEOUT_MS must be positive, got {self.heartbeat_timeout_ms}"
            )
        if self.election_timeout_ms <= 0:
            raise ValueError(
                f"ELECTION_TIMEOUT_MS must be positive, got {self.election_timeout_ms}"
            )

        if self.election_algorithm not in ("bully", "ring"):
            raise ValueError(
                f"ELECTION_ALGORITHM must be 'bully' or 'ring', got '{self.election_algorithm}'"
            )
        if self.replication_policy not in ("all", "majority"):
            raise ValueError(
                f"REPLICATION_POLICY must be 'all' or 'majority', got '{self.replication_policy}'"
            )
        if not self.candidates:
            raise ValueError("CANDIDATES must contain at least one choice")

        # Reject an INITIAL_COORDINATOR_ID that is not a configured cluster member
        if self.initial_coordinator_id is not None:
            if self.initial_coordinator_id not in self.all_node_ids:
                raise ValueError(
                    f"INITIAL_COORDINATOR_ID={self.initial_coordinator_id} "
                    f"is not a configured cluster member (must be in {self.all_node_ids})"
                )

    # ── Factory ──────────────────────────────────────────────────

    @classmethod
    def from_env(cls) -> "NodeConfig":
        """Build config from environment variables. Fails fast on missing/bad values."""
        if "NODE_ID" not in os.environ:
            raise ValueError("NODE_ID environment variable is required")
        try:
            node_id = int(os.environ["NODE_ID"])
        except ValueError:
            raise ValueError(f"NODE_ID must be an integer, got '{os.environ['NODE_ID']}'")

        algorithm = os.environ.get("ELECTION_ALGORITHM", "bully").lower()

        # Parse PEERS / PEER_CONFIGURATION — format: "id:host:port,id:host:port,..."
        peers_str = os.environ.get("PEERS") or os.environ.get("PEER_CONFIGURATION", "")
        raw_entries = [e.strip() for e in peers_str.split(",") if e.strip()]
        if not raw_entries:
            raise ValueError("PEERS environment variable is required and must not be empty")

        seen_pids = []
        peers: dict = {}
        for entry in raw_entries:
            parts = entry.split(":")
            if len(parts) != 3:
                raise ValueError(f"PEERS entry must be id:host:port, got '{entry}'")
            try:
                pid = int(parts[0])
                port = int(parts[2])
            except ValueError:
                raise ValueError(f"PEERS entry id and port must be integers, got '{entry}'")

            seen_pids.append(pid)
            peers[pid] = PeerInfo(node_id=pid, host=parts[1].strip(), port=port)

        # Check unique peer IDs in raw list
        if len(seen_pids) != len(set(seen_pids)):
            raise ValueError(f"Peer IDs in PEERS must be unique, got duplicate in {seen_pids}")

        # NODE_ID must be listed exactly once in PEERS
        if seen_pids.count(node_id) != 1:
            raise ValueError(
                f"NODE_ID={node_id} must be listed exactly once in PEERS, found {seen_pids.count(node_id)}"
            )

        initial_coord_str = os.environ.get("INITIAL_COORDINATOR_ID")
        initial_coord = int(initial_coord_str) if initial_coord_str else None

        candidates_str = os.environ.get("CANDIDATES", "Alice,Bob,Charlie")
        candidates = [c.strip() for c in candidates_str.split(",") if c.strip()]

        # Database configuration (support individual DB_* or optional DATABASE_CONFIGURATION JSON)
        db_config_raw = os.environ.get("DATABASE_CONFIGURATION")
        db_cfg = {}
        if db_config_raw:
            try:
                import json
                db_cfg = json.loads(db_config_raw)
            except Exception:
                pass

        config = cls(
            node_id=node_id,
            grpc_port=int(os.environ.get("GRPC_PORT", "50051")),
            election_algorithm=algorithm,
            peers=peers,
            heartbeat_interval_ms=int(os.environ.get("HEARTBEAT_INTERVAL_MS", "1000")),
            heartbeat_timeout_ms=int(os.environ.get("HEARTBEAT_TIMEOUT_MS", "3000")),
            election_timeout_ms=int(os.environ.get("ELECTION_TIMEOUT_MS", "5000")),
            replication_policy=os.environ.get("REPLICATION_POLICY", "all"),
            initial_coordinator_id=initial_coord,
            db_host=db_cfg.get("host") or db_cfg.get("db_host") or os.environ.get("DB_HOST", "localhost"),
            db_port=int(db_cfg.get("port") or db_cfg.get("db_port") or os.environ.get("DB_PORT", "3306")),
            db_user=db_cfg.get("user") or db_cfg.get("db_user") or os.environ.get("DB_USER", "root"),
            db_password=db_cfg.get("password") or db_cfg.get("db_password") or os.environ.get("DB_PASSWORD", "votingpass"),
            db_name=db_cfg.get("database") or db_cfg.get("db_name") or os.environ.get("DB_NAME", "voting_node"),
            use_sqlite=os.environ.get("USE_SQLITE", "false").lower() == "true",
            sqlite_path=os.environ.get("SQLITE_PATH"),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            candidates=candidates,
            auto_recover=os.environ.get("AUTO_RECOVER", "false").lower() == "true",
        )
        config.validate()
        return config
