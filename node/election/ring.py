"""Ring leader election algorithm implementation."""

import threading
import time
from typing import Optional

from node.election.base import BaseElection
from node.models import NodeRole


class RingElection(BaseElection):
    """Concrete implementation of the Ring Leader Election algorithm.

    Rules:
    - Ring constructed from configured node IDs in sorted order.
    - Node tries the next configured successor first.
    - If unreachable, mark it inactive, record RING_SUCCESSOR_SKIPPED, and try next successor (wrap around).
    - Token carries the highest candidate ID seen so far.
    - Prevent duplicate forwarding loops for the same (election_term, initiator_id) token.
    - When token returns to initiator, the winning node announces itself to all reachable active peers.
    - Count only logical sent Election, OK, and Coordinator messages.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._coordinator_announced_event = threading.Event()
        self._forwarded_tokens: set[tuple[int, int]] = set()
        self._seen_tokens: set[tuple[int, int]] = set()
        self._token_first_seen_time: dict[tuple[int, int], float] = {}
        self._ring_lock = threading.Lock()

    def get_ring_successor_id(self) -> Optional[int]:
        """Return next reachable active successor in the ring, skipping inactive peers."""
        ring = sorted(self._config.all_node_ids)
        if not ring:
            return None
        try:
            idx = ring.index(self._node_id)
        except ValueError:
            return None

        n = len(ring)
        active = self._state.active_peers
        for i in range(1, n):
            candidate = ring[(idx + i) % n]
            if candidate in active:
                return candidate
            self._record_event(
                "RING_SUCCESSOR_SKIPPED",
                lamport_ts=self._clock.tick(),
                election_term=self._state.election_term,
                initiator_id=self._state.initiator_id,
                skipped_peer_id=candidate,
            )
        return None

    def _wait_for_coordinator_announcement(self, term: int, deadline: float) -> bool:
        while time.monotonic() < deadline:
            wait_time = max(deadline - time.monotonic(), 0.01)
            if self._coordinator_announced_event.wait(timeout=min(wait_time, 0.1)):
                if self._state.role in (NodeRole.FOLLOWER, NodeRole.RECOVERING) and self._state.election_term >= term:
                    return True
                self._coordinator_announced_event.clear()
            if self._state.role in (NodeRole.FOLLOWER, NodeRole.RECOVERING) and self._state.election_term >= term:
                return True
        return False

    def _notify_coordinator_announced(self) -> None:
        self._coordinator_announced_event.set()

    def _forward_token_around_ring(
        self,
        candidate_id: int,
        election_term: int,
        initiator_id: int,
    ) -> bool:
        """Forward election token to the next reachable successor in cyclic order."""
        ring = sorted(self._config.all_node_ids)
        try:
            idx = ring.index(self._node_id)
        except ValueError:
            return False

        n = len(ring)
        for i in range(1, n):
            succ_id = ring[(idx + i) % n]
            if succ_id == self._node_id:
                break

            client = self._peer_clients.get(succ_id)
            if not client:
                self._state.mark_peer_inactive(succ_id)
                self._record_event(
                    "RING_SUCCESSOR_SKIPPED",
                    lamport_ts=self._clock.tick(),
                    election_term=election_term,
                    initiator_id=initiator_id,
                    skipped_peer_id=succ_id,
                )
                continue

            self._count_sent("election")
            ts = self._clock.send()
            self._record_event(
                "ELECTION_MESSAGE_SENT",
                lamport_ts=ts,
                election_term=election_term,
                initiator_id=initiator_id,
                peer_id=succ_id,
            )

            resp = client.send_election(
                sender_id=self._node_id,
                candidate_id=candidate_id,
                election_term=election_term,
                initiator_id=initiator_id,
                lamport_ts=ts,
                timeout=min(self._election_timeout_sec, 0.5),
            )

            if resp is None:
                self._state.mark_peer_inactive(succ_id)
                self._record_event(
                    "RING_SUCCESSOR_SKIPPED",
                    lamport_ts=self._clock.tick(),
                    election_term=election_term,
                    initiator_id=initiator_id,
                    skipped_peer_id=succ_id,
                )
            else:
                self._clock.receive(resp.lamport_ts)
                self._state.mark_peer_active(succ_id)
                return True

        return False

    def _run_algorithm(self, start_mono: float) -> tuple[int, int]:
        """Execute one attempt of the Ring election as initiator."""
        self._coordinator_announced_event.clear()

        # Derive fresh Lamport election term
        current_term = self._state.election_term
        new_term = max(self._clock.tick(), current_term + 1)
        initiator_id = self._node_id

        entered, _ = self._state.enter_election(new_term, initiator_id)
        if not entered:
            return (self._state.election_term, self._state.initiator_id)

        with self._ring_lock:
            self._forwarded_tokens.add((new_term, initiator_id))

        self._record_event(
            "ELECTION_STARTED",
            lamport_ts=self._clock.value,
            election_term=new_term,
            initiator_id=initiator_id,
        )

        # Forward token containing self as candidate
        delivered = self._forward_token_around_ring(
            candidate_id=self._node_id,
            election_term=new_term,
            initiator_id=initiator_id,
        )

        if not delivered:
            # No other reachable node in the ring: this node wins immediately
            self._record_event(
                "ELECTION_WON",
                lamport_ts=self._clock.tick(),
                election_term=new_term,
                initiator_id=initiator_id,
            )
            self._state.win_election(new_term, initiator_id)
            if self._lifecycle:
                self._lifecycle.apply_role()
            self._announce_coordinator_to_peers(new_term, initiator_id)
            if getattr(self, "_on_win_callback", None):
                try:
                    self._on_win_callback(new_term, initiator_id)
                except Exception as exc:
                    self._logger.warning("Error in _on_win_callback: %s", exc)
            return (new_term, initiator_id)

        # Wait for election completion (either winning or coordinator announced)
        deadline = time.monotonic() + (self._election_timeout_sec * 2.0)
        announced = self._wait_for_coordinator_announcement(new_term, deadline)
        if announced:
            return (new_term, initiator_id)

        # If timed out, retry
        self._logger.warning("Ring election timed out waiting for token/announcement, retrying")
        return self._run_algorithm(start_mono)

    def on_election_message(
        self,
        sender_id: int,
        candidate_id: int,
        election_term: int,
        initiator_id: int,
        msg_lamport_ts: int,
    ) -> tuple[bool, int, int]:
        """Handle incoming Election token in Ring algorithm."""
        self._clock.receive(msg_lamport_ts)
        self._state.mark_peer_active(sender_id)
        current_term = self._state.election_term
        current_init = self._state.initiator_id

        # Reject stale tuple
        if (election_term, initiator_id) < (current_term, current_init):
            self._record_event(
                "STALE_ELECTION_REJECTED",
                lamport_ts=self._clock.tick(),
                election_term=election_term,
                initiator_id=initiator_id,
                reason="stale_tuple",
                current_term=current_term,
                current_initiator=current_init,
                sender_id=sender_id,
            )
            return False, self._node_id, self._clock.tick()

        token_key = (election_term, initiator_id)

        # Track new election token on participant and reset per-election counters
        with self._ring_lock:
            if token_key not in self._seen_tokens:
                self._seen_tokens.add(token_key)
                self._token_first_seen_time[token_key] = time.monotonic()
                if not self._election_in_progress:
                    self.reset_message_counts()

        # Sending OK response to sender
        self._count_sent("ok")
        reply_ts = self._clock.send()
        self._record_event(
            "ELECTION_OK_SENT",
            lamport_ts=reply_ts,
            election_term=election_term,
            initiator_id=initiator_id,
            to_node=sender_id,
        )

        if initiator_id == self._node_id:
            # Token returned to initiator!
            winner_id = max(candidate_id, self._node_id)
            if winner_id == self._node_id:
                # We won!
                self._record_event(
                    "ELECTION_WON",
                    lamport_ts=self._clock.tick(),
                    election_term=election_term,
                    initiator_id=initiator_id,
                )
                self._state.win_election(election_term, initiator_id)
                if self._lifecycle:
                    self._lifecycle.apply_role()
                self._announce_coordinator_to_peers(election_term, initiator_id)
                self._notify_coordinator_announced()
                if getattr(self, "_on_win_callback", None):
                    try:
                        self._on_win_callback(election_term, initiator_id)
                    except Exception as exc:
                        self._logger.warning("Error in _on_win_callback: %s", exc)
            else:
                # Winner is a different node: notify the winner so it announces itself
                self._notify_winner(winner_id, election_term, initiator_id)
            return True, self._node_id, reply_ts

        # If this message was sent to notify us that we won:
        if candidate_id == self._node_id and sender_id == initiator_id:
            # We are the winner declared by the initiator!
            self._record_event(
                "ELECTION_WON",
                lamport_ts=self._clock.tick(),
                election_term=election_term,
                initiator_id=initiator_id,
            )
            self._state.win_election(election_term, initiator_id)
            if self._lifecycle:
                self._lifecycle.apply_role()
            self._announce_coordinator_to_peers(election_term, initiator_id)
            self._notify_coordinator_announced()
            if getattr(self, "_on_win_callback", None):
                try:
                    self._on_win_callback(election_term, initiator_id)
                except Exception as exc:
                    self._logger.warning("Error in _on_win_callback: %s", exc)

            counts = self.get_message_counts()
            first_seen = self._token_first_seen_time.get(token_key, time.monotonic())
            duration_ms = round((time.monotonic() - first_seen) * 1000, 2)
            self._record_completion(election_term, initiator_id, duration_ms, counts)
            return True, self._node_id, reply_ts

        # Token received by follower / other participant
        with self._ring_lock:
            if token_key in self._forwarded_tokens:
                # Prevent duplicate forwarding loops
                return True, self._node_id, reply_ts
            self._forwarded_tokens.add(token_key)

        # Adopt newer election term
        self._state.enter_election(election_term, initiator_id)

        # Update candidate ID to the highest seen so far
        highest_candidate = max(candidate_id, self._node_id)

        # Forward along ring asynchronously
        threading.Thread(
            target=self._forward_token_around_ring,
            args=(highest_candidate, election_term, initiator_id),
            daemon=True,
        ).start()

        return True, self._node_id, reply_ts

    def _notify_winner(self, winner_id: int, election_term: int, initiator_id: int) -> None:
        """Initiator notifies winning candidate so it announces itself to peers."""
        client = self._peer_clients.get(winner_id)
        if not client:
            return

        self._count_sent("election")
        ts = self._clock.send()
        self._record_event(
            "ELECTION_MESSAGE_SENT",
            lamport_ts=ts,
            election_term=election_term,
            initiator_id=initiator_id,
            peer_id=winner_id,
        )
        resp = client.send_election(
            sender_id=self._node_id,
            candidate_id=winner_id,
            election_term=election_term,
            initiator_id=initiator_id,
            lamport_ts=ts,
            timeout=min(self._election_timeout_sec, 0.5),
        )
        if resp is not None:
            self._clock.receive(resp.lamport_ts)
            self._state.mark_peer_active(winner_id)

    def on_coordinator_announcement(
        self,
        coordinator_id: int,
        election_term: int,
        initiator_id: int,
        msg_lamport_ts: int,
    ) -> bool:
        """Handle incoming AnnounceCoordinator RPC in Ring algorithm."""
        self._clock.receive(msg_lamport_ts)
        self._state.mark_peer_active(coordinator_id)
        accepted, reason = self._state.accept_coordinator(coordinator_id, election_term, initiator_id)

        if not accepted:
            self._record_event(
                "STALE_ELECTION_REJECTED",
                lamport_ts=self._clock.tick(),
                election_term=election_term,
                initiator_id=initiator_id,
                reason=reason,
                coordinator_id=coordinator_id,
            )
            return False

        self._record_event(
            "COORDINATOR_ACCEPTED",
            lamport_ts=self._clock.tick(),
            election_term=election_term,
            initiator_id=initiator_id,
            coordinator_id=coordinator_id,
        )

        if coordinator_id != self._node_id:
            self._record_event(
                "ELECTION_LOST",
                lamport_ts=self._clock.tick(),
                election_term=election_term,
                initiator_id=initiator_id,
                coordinator_id=coordinator_id,
            )

        if self._lifecycle:
            self._lifecycle.apply_role()

        self._notify_coordinator_announced()
        return True
