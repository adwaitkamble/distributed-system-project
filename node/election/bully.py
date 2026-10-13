"""Bully leader election algorithm implementation."""

import threading
import time
from typing import Optional

from node.election.base import BaseElection
from node.models import NodeRole


class BullyElection(BaseElection):
    """Concrete implementation of the Bully Leader Election algorithm.

    Rules:
    - Node sends Election only to reachable higher-ID nodes in the active peers snapshot.
    - Each logical sent Election RPC increments the election-message counter once.
    - Higher live nodes reply with OK and independently initiate their own election.
    - Each logical sent OK reply increments the OK-message counter once.
    - If no higher live node responds within a bounded timeout, candidate wins.
    - Winner announces itself to all reachable active peers with AnnounceCoordinator.
    - Each logical sent coordinator announcement increments the coordinator-message counter once.
    - Unreachable nodes are marked inactive and excluded from subsequent sends.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._coordinator_announced_event = threading.Event()

    def _wait_for_coordinator_announcement(self, term: int, deadline: float) -> bool:
        """Wait until a coordinator announcement is accepted or deadline is reached."""
        while time.monotonic() < deadline:
            wait_time = max(deadline - time.monotonic(), 0.01)
            if self._coordinator_announced_event.wait(timeout=min(wait_time, 0.1)):
                if self._state.role == NodeRole.FOLLOWER and self._state.election_term >= term:
                    return True
                self._coordinator_announced_event.clear()
            if self._state.role == NodeRole.FOLLOWER and self._state.election_term >= term:
                return True
        return False

    def _notify_coordinator_announced(self) -> None:
        self._coordinator_announced_event.set()

    def _run_algorithm(self, start_mono: float) -> tuple[int, int]:
        """Execute one attempt of the Bully election."""
        self._coordinator_announced_event.clear()

        # Generate fresh Lamport-derived election term strictly greater than current
        current_term = self._state.election_term
        new_term = max(self._clock.tick(), current_term + 1)
        initiator_id = self._node_id

        # Atomically enter CANDIDATE state
        entered, _ = self._state.enter_election(new_term, initiator_id)
        if not entered:
            return (self._state.election_term, self._state.initiator_id)

        self._record_event(
            "ELECTION_STARTED",
            lamport_ts=self._clock.value,
            election_term=new_term,
            initiator_id=initiator_id,
        )

        # Snapshot active peers with higher ID
        active_snapshot = self._state.active_peers
        higher_peers = [p for p in sorted(active_snapshot) if p > self._node_id]

        higher_responded = False
        if higher_peers:
            for pid in higher_peers:
                client = self._peer_clients.get(pid)
                if not client:
                    self._state.mark_peer_inactive(pid)
                    continue

                self._count_sent("election")
                ts = self._clock.send()
                self._record_event(
                    "ELECTION_MESSAGE_SENT",
                    lamport_ts=ts,
                    election_term=new_term,
                    initiator_id=initiator_id,
                    peer_id=pid,
                )

                resp = client.send_election(
                    sender_id=self._node_id,
                    candidate_id=self._node_id,
                    election_term=new_term,
                    initiator_id=initiator_id,
                    lamport_ts=ts,
                    timeout=min(self._election_timeout_sec, 0.5),
                )

                if resp is None:
                    self._state.mark_peer_inactive(pid)
                else:
                    self._clock.receive(resp.lamport_ts)
                    self._state.mark_peer_active(pid)
                    if resp.ok:
                        higher_responded = True

        if higher_responded:
            # A higher node responded with OK. Wait for it to announce as coordinator.
            deadline = time.monotonic() + self._election_timeout_sec
            announced = self._wait_for_coordinator_announcement(new_term, deadline)
            if announced:
                return (new_term, initiator_id)

            # Bounded timeout expired without coordinator announcement: retry election
            self._logger.warning("Higher node timed out without coordinator announcement; retrying election")
            return self._run_algorithm(start_mono)

        # No higher live node responded: candidate wins
        if not self._state.win_election(new_term, initiator_id):
            return (self._state.election_term, self._state.initiator_id)

        self._record_event(
            "ELECTION_WON",
            lamport_ts=self._clock.tick(),
            election_term=new_term,
            initiator_id=initiator_id,
        )

        if self._lifecycle:
            self._lifecycle.apply_role()

        self._announce_coordinator_to_peers(new_term, initiator_id)
        if getattr(self, "_on_win_callback", None):
            try:
                self._on_win_callback(new_term, initiator_id)
            except Exception as exc:
                self._logger.warning("Error in _on_win_callback: %s", exc)
        return (new_term, initiator_id)

    def on_election_message(
        self,
        sender_id: int,
        candidate_id: int,
        election_term: int,
        initiator_id: int,
        msg_lamport_ts: int,
    ) -> tuple[bool, int, int]:
        """Handle incoming Election RPC in Bully algorithm."""
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
            # If candidate ID is lower than ours, we are higher and alive: send OK to suppress lower candidate
            if self._node_id > candidate_id:
                self._count_sent("ok")
                if self._state.is_coordinator():
                    t = threading.Thread(
                        target=self.announce_to_peer,
                        args=(sender_id, current_term, current_init),
                        daemon=True,
                    )
                    t.start()
                return True, self._node_id, self._clock.send()
            return False, self._node_id, self._clock.tick()

        # If candidate ID is lower than ours, reply OK and take over
        if self._node_id > candidate_id:
            self.start_election(blocking=False)
            self._count_sent("ok")
            reply_ts = self._clock.send()
            self._record_event(
                "ELECTION_OK_SENT",
                lamport_ts=reply_ts,
                election_term=election_term,
                initiator_id=initiator_id,
                to_node=sender_id,
            )
            return True, self._node_id, reply_ts

        return False, self._node_id, self._clock.tick()

    def on_coordinator_announcement(
        self,
        coordinator_id: int,
        election_term: int,
        initiator_id: int,
        msg_lamport_ts: int,
    ) -> bool:
        """Handle incoming AnnounceCoordinator RPC in Bully algorithm."""
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
