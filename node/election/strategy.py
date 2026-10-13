"""Abstract base class for election strategies.

The heartbeat monitor and replication module hold a reference to
ElectionStrategy but never check the concrete type.

Amendment 2: election_term (int64 Lamport-derived) + initiator_id replace
the original int32 election_round.  The pair (election_term, initiator_id)
uniquely identifies and totally orders concurrent elections.

Amendment 3: Ring election must skip unreachable successors — see
get_ring_successor_id() and the active_peers parameter.

Amendment 6: message overhead is counted once per logical *sent* message.
Received events are a cross-check only.
"""

from abc import ABC, abstractmethod
from typing import Optional


class ElectionStrategy(ABC):
    """Common interface that Bully and Ring must implement."""

    def __init__(self) -> None:
        # Per-election sent counts (reset per election)
        self._sent_counts: dict = {
            "election": 0,
            "ok": 0,
            "coordinator": 0,
        }
        # Lifetime sent counts (monotonically increasing across all elections)
        self._lifetime_sent_counts: dict = {
            "election": 0,
            "ok": 0,
            "coordinator": 0,
        }

    # ── Core protocol ────────────────────────────────────────────

    @abstractmethod
    def start_election(self) -> None:
        """Initiate an election.  Called by the heartbeat monitor
        when a timeout fires."""
        ...

    @abstractmethod
    def on_election_message(
        self,
        sender_id: int,
        candidate_id: int,
        election_term: int,
        initiator_id: int,
        msg_lamport_ts: int,
    ) -> tuple:
        """Handle an incoming Election RPC.

        Returns (ok: bool, this_node_id: int, this_node_lamport_ts: int).
        - Bully: ok=True means "I am alive; I will take over."
        - Ring:  ok=True is simply an ack; forwarding happens internally.
        """
        ...

    @abstractmethod
    def on_coordinator_announcement(
        self,
        coordinator_id: int,
        election_term: int,
        initiator_id: int,
        msg_lamport_ts: int,
    ) -> bool:
        """Handle an incoming AnnounceCoordinator RPC.

        Returns True if the announcement is accepted (term is current or newer).
        """
        ...

    # ── Message counting (amendment 6) ───────────────────────────

    def get_message_counts(self) -> dict:
        """Return a copy of {type: count} for sent messages during the current/latest election."""
        return dict(self._sent_counts)

    def get_lifetime_message_counts(self) -> dict:
        """Return a copy of {type: count} for lifetime sent messages across all elections."""
        return dict(self._lifetime_sent_counts)

    def reset_message_counts(self) -> None:
        """Reset per-election sent message counts."""
        for key in self._sent_counts:
            self._sent_counts[key] = 0

    def _count_sent(self, msg_type: str) -> None:
        """Increment the counter for a sent message type."""
        if msg_type in self._sent_counts:
            self._sent_counts[msg_type] += 1
        if msg_type in self._lifetime_sent_counts:
            self._lifetime_sent_counts[msg_type] += 1

    # ── Ring helper (amendment 3) ────────────────────────────────

    def get_ring_successor_id(self) -> Optional[int]:
        """Return the next reachable node in the ring, or None.
        Only meaningful for Ring; Bully returns None.
        """
        return None
