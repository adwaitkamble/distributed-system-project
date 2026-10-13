"""Node role / state machine and coordinator tracking.

Amendment 1: deterministic bootstrap — highest configured ID is initial coordinator
             unless overridden by INITIAL_COORDINATOR_ID.
Amendment 2: election_term (int64 Lamport-derived) + initiator_id replace election_round.
Amendment 3: active_peers set — tracked via heartbeat acks and replication failures.
"""

import threading
from typing import Optional

from node.models import NodeRole


class CoordinatorState:
    """Thread-safe coordinator and role state for one node.

    State machine:
        FOLLOWER ──(heartbeat timeout)──► CANDIDATE
        CANDIDATE ──(won election)──────► RECOVERING
        CANDIDATE ──(lost election)─────► FOLLOWER
        RECOVERING ──(sync complete)────► COORDINATOR
        COORDINATOR ──(detected by peers via crash / docker stop)──► (dead)
    """

    def __init__(self, node_id: int, initial_coordinator_id: int, all_peer_ids: Optional[list] = None) -> None:
        self._node_id = node_id
        self._coordinator_id = initial_coordinator_id
        self._election_term: int = 0        # Lamport-derived (amendment 2)
        self._initiator_id: int = 0         # who started current term (amendment 2)
        self._lock = threading.Lock()

        # Start as COORDINATOR if we are the initial coordinator, else FOLLOWER
        if node_id == initial_coordinator_id:
            self._role = NodeRole.COORDINATOR
        else:
            self._role = NodeRole.FOLLOWER

        # Amendment 3: active_peers — initially all configured peers
        self._active_peers: set = set(all_peer_ids) if all_peer_ids else set()
        # Remove self from active peers (it tracks *other* nodes)
        self._active_peers.discard(node_id)

    # ── Read-only properties ─────────────────────────────────────

    @property
    def node_id(self) -> int:
        return self._node_id

    @property
    def role(self) -> NodeRole:
        with self._lock:
            return self._role

    @property
    def coordinator_id(self) -> int:
        with self._lock:
            return self._coordinator_id

    @property
    def election_term(self) -> int:
        with self._lock:
            return self._election_term

    @property
    def initiator_id(self) -> int:
        with self._lock:
            return self._initiator_id

    @property
    def active_peers(self) -> set:
        """Copy of current active peer IDs (amendment 3)."""
        with self._lock:
            return set(self._active_peers)

    # ── Query helpers ────────────────────────────────────────────

    def is_coordinator(self) -> bool:
        with self._lock:
            return self._role == NodeRole.COORDINATOR

    def acts_as_coordinator(self) -> bool:
        """True if coordinator or recovering (broadcasts heartbeats, never times out self)."""
        with self._lock:
            return self._role in (NodeRole.COORDINATOR, NodeRole.RECOVERING)

    def is_accepting_votes(self) -> bool:
        """True only when this node is coordinator and NOT recovering."""
        with self._lock:
            return self._role == NodeRole.COORDINATOR

    @property
    def election_tuple(self) -> tuple[int, int]:
        with self._lock:
            return (self._election_term, self._initiator_id)

    # ── State transitions (Phase 3/4) ────────────────────────────

    def enter_election(self, election_term: int, initiator_id: int) -> tuple[bool, str]:
        """Atomically attempt to enter election as CANDIDATE."""
        with self._lock:
            current_tuple = (self._election_term, self._initiator_id)
            new_tuple = (election_term, initiator_id)
            if new_tuple < current_tuple:
                return False, f"stale_tuple:{new_tuple}<{current_tuple}"
            if new_tuple > current_tuple:
                self._coordinator_id = None
            self._role = NodeRole.CANDIDATE
            self._election_term = election_term
            self._initiator_id = initiator_id
            return True, "entered"

    def win_election(self, election_term: int, initiator_id: int) -> bool:
        """Atomically transition candidate to RECOVERING coordinator."""
        with self._lock:
            current_tuple = (self._election_term, self._initiator_id)
            new_tuple = (election_term, initiator_id)
            if new_tuple < current_tuple:
                return False
            self._role = NodeRole.RECOVERING
            self._coordinator_id = self._node_id
            self._election_term = election_term
            self._initiator_id = initiator_id
            return True

    def accept_coordinator(self, coordinator_id: int, election_term: int, initiator_id: int) -> tuple[bool, str]:
        """Atomically evaluate and accept coordinator announcement.
        Rejects stale tuples and conflicting coordinators on equal terms.
        """
        with self._lock:
            current_tuple = (self._election_term, self._initiator_id)
            new_tuple = (election_term, initiator_id)
            if new_tuple < current_tuple:
                return False, f"stale_tuple:{new_tuple}<{current_tuple}"
            if new_tuple == current_tuple:
                if self._coordinator_id is not None and self._coordinator_id != coordinator_id:
                    return False, f"conflicting_coordinator:existing={self._coordinator_id},new={coordinator_id}"

            if coordinator_id == self._node_id:
                self._role = NodeRole.RECOVERING
                self._coordinator_id = self._node_id
            else:
                self._role = NodeRole.FOLLOWER
                self._coordinator_id = coordinator_id
            self._election_term = election_term
            self._initiator_id = initiator_id
            return True, "accepted"

    def become_candidate(self, election_term: int, initiator_id: int) -> None:
        with self._lock:
            self._role = NodeRole.CANDIDATE
            self._election_term = election_term
            self._initiator_id = initiator_id

    def become_recovering(self) -> None:
        with self._lock:
            self._role = NodeRole.RECOVERING
            self._coordinator_id = self._node_id

    def become_coordinator(self, election_term: int, initiator_id: int) -> None:
        with self._lock:
            self._role = NodeRole.COORDINATOR
            self._coordinator_id = self._node_id
            self._election_term = election_term
            self._initiator_id = initiator_id

    def become_follower(self, coordinator_id: int, election_term: int, initiator_id: int) -> None:
        with self._lock:
            self._role = NodeRole.FOLLOWER
            self._coordinator_id = coordinator_id
            self._election_term = election_term
            self._initiator_id = initiator_id

    # ── Amendment 2: election term ordering ──────────────────────

    def is_newer_election(self, term: int, initiator_id: int) -> bool:
        """True if (term, initiator_id) > current (election_term, initiator_id).
        Used to discard stale election/coordinator messages.
        """
        with self._lock:
            return (term, initiator_id) > (self._election_term, self._initiator_id)

    def is_same_or_newer_election(self, term: int, initiator_id: int) -> bool:
        with self._lock:
            return (term, initiator_id) >= (self._election_term, self._initiator_id)

    # ── Amendment 3: active peer tracking ────────────────────────

    def mark_peer_active(self, peer_id: int) -> None:
        with self._lock:
            self._active_peers.add(peer_id)

    def mark_peer_inactive(self, peer_id: int) -> None:
        with self._lock:
            self._active_peers.discard(peer_id)
