"""Core data models shared across the node application.

Amendment 4: InsertResult distinguishes idempotent-success (same vote_id +
identical content) from conflicting-duplicate (same client_id, different vote).
Amendment 5: receipt format = client_id:origin_node_id:lamport_ts.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class VoteStatus(str, Enum):
    """Lifecycle states of a vote record."""

    PENDING = "PENDING"
    COMMITTED = "COMMITTED"


class InsertResult(Enum):
    """Outcome of a vote insert operation (amendment 4 + Phase 2 lifecycle)."""

    INSERTED = "inserted"                          # new pending row created
    IDEMPOTENT = "idempotent"                      # same vote_id, identical content
    CLIENT_ALREADY_VOTED = "client_already_voted"  # client already has a committed vote
    PENDING_RETRY = "pending_retry"                # client retrying same choice while pending
    PENDING_CONFLICT = "pending_conflict"          # client submitting different choice while pending
    VOTE_ID_CONFLICT = "vote_id_conflict"          # same vote_id, different content (bug)


class NodeRole(Enum):
    """Possible roles for a node in the cluster."""

    FOLLOWER = "follower"
    CANDIDATE = "candidate"
    RECOVERING = "recovering"
    COORDINATOR = "coordinator"


@dataclass
class VoteRecord:
    """A single persisted vote."""

    vote_id: str           # "client_id:origin_node_id:lamport_ts"
    client_id: str
    origin_node_id: int
    lamport_ts: int
    choice: str
    received_at_ms: int    # epoch millis — observability only, never for ordering
    status: str = VoteStatus.PENDING.value
    commit_proof: str = ""

    # ── Factory ──────────────────────────────────────────────────

    @staticmethod
    def make_vote_id(client_id: str, origin_node_id: int, lamport_ts: int) -> str:
        """Build the receipt / primary-key string."""
        return f"{client_id}:{origin_node_id}:{lamport_ts}"

    # ── Amendment 4 — content comparison for idempotency ─────────

    def content_matches(self, other: "VoteRecord") -> bool:
        """True if all fields match except received_at_ms (which may differ
        across replicas receiving the same vote at different wall-clock times).
        """
        return (
            self.vote_id == other.vote_id
            and self.client_id == other.client_id
            and self.origin_node_id == other.origin_node_id
            and self.lamport_ts == other.lamport_ts
            and self.choice == other.choice
        )

    # ── Merge ordering (amendment 9) ─────────────────────────────

    @property
    def merge_key(self) -> tuple:
        """Deterministic sort key for log merge / recovery.
        Order: (lamport_ts, origin_node_id, vote_id).
        """
        return (self.lamport_ts, self.origin_node_id, self.vote_id)


@dataclass
class SyncLogEntry:
    """An entry in the append-only durable sync log."""

    entry_id: int
    entry_type: str        # VOTE_PENDING, VOTE_COMMITTED, VOTE_FINALIZED, SYNC_APPLIED, RECOVERY
    vote_id: Optional[str]
    client_id: Optional[str]
    origin_node_id: Optional[int]
    lamport_ts: int
    choice: Optional[str]
    status: Optional[str]
    details: Optional[str]
    created_at_ms: int


@dataclass
class RecoverySummary:
    """Result of a state recovery or log replay execution."""

    success: bool
    replayed_entries_count: int
    committed_votes_count: int
    max_lamport_ts: int
    votes_synced_count: int = 0
    accepted_votes_count: int = 0
    rejected_partial_finalizations_count: int = 0
    client_id_conflicts_count: int = 0
    peers_contacted: list = None
    duration_ms: float = 0.0
    error: str = ""

    def __post_init__(self):
        if self.peers_contacted is None:
            self.peers_contacted = []

