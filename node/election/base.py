"""Base class and common infrastructure for election strategies."""

import logging
import threading
import time
from typing import Optional

from node.config import NodeConfig
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.election.strategy import ElectionStrategy
from node.lamport import LamportClock
from node.lifecycle import NodeLifecycle
from node.logging_config import log_event
from node.peer_client import PeerClient


class BaseElection(ElectionStrategy):
    """Provides common logging, persistent event recording, message counting, and concurrency control."""

    def __init__(
        self,
        node_id: int,
        state: CoordinatorState,
        clock: LamportClock,
        peer_clients: dict[int, PeerClient],
        config: NodeConfig,
        db: DatabaseManager,
        lifecycle: Optional[NodeLifecycle] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        super().__init__()
        self._node_id = node_id
        self._state = state
        self._clock = clock
        self._peer_clients = peer_clients
        self._config = config
        self._db = db
        self._lifecycle = lifecycle
        self._logger = logger or logging.getLogger(f"election.{node_id}")

        self._election_timeout_sec = max(config.election_timeout_ms / 1000.0, 0.2)
        self._count_lock = threading.RLock()
        self._election_lock = threading.RLock()
        self._election_in_progress = False
        self._current_election_thread: Optional[threading.Thread] = None

        # Tracking for latest completed election metrics
        self._last_election_metrics: dict = {}
        self._on_win_callback = None

    def set_on_win(self, callback) -> None:
        """Set callback invoked upon winning an election."""
        self._on_win_callback = callback

    def _count_sent(self, msg_type: str) -> None:
        with self._count_lock:
            super()._count_sent(msg_type)

    def get_message_counts(self) -> dict:
        with self._count_lock:
            return super().get_message_counts()

    def get_lifetime_message_counts(self) -> dict:
        with self._count_lock:
            return super().get_lifetime_message_counts()

    def reset_message_counts(self) -> None:
        with self._count_lock:
            super().reset_message_counts()

    def get_last_election_metrics(self) -> dict:
        with self._election_lock:
            return dict(self._last_election_metrics)

    def _record_event(
        self,
        event_type: str,
        lamport_ts: int,
        election_term: int,
        initiator_id: int,
        **details,
    ) -> None:
        """Emits structured JSON log and persists event to the election_log database table."""
        log_event(
            self._logger,
            event_type,
            lamport_ts=lamport_ts,
            election_term=election_term,
            initiator_id=initiator_id,
            node_id=self._node_id,
            **details,
        )
        try:
            self._db.log_election_event(
                event_type=event_type,
                node_id=self._node_id,
                lamport_ts=lamport_ts,
                election_term=election_term,
                initiator_id=initiator_id,
                details=details,
            )
        except Exception as exc:
            self._logger.warning("Failed to persist election event %s: %s", event_type, exc)

    def start_election(self, blocking: bool = False) -> None:
        """Trigger an election attempt. Protected by a lock to ensure one election per incident."""
        with self._election_lock:
            if self._election_in_progress:
                log_event(
                    self._logger,
                    "ELECTION_START_SUPPRESSED",
                    lamport_ts=self._clock.tick(),
                    node_id=self._node_id,
                    reason="election_already_in_progress",
                )
                return

            self._election_in_progress = True
            # Reset per-election message counters immediately after concurrency guard succeeds
            with self._count_lock:
                super().reset_message_counts()

        if blocking:
            self._execute_election_lifecycle()
        else:
            thread = threading.Thread(
                target=self._execute_election_lifecycle,
                daemon=True,
                name=f"Election-{self._node_id}",
            )
            self._current_election_thread = thread
            thread.start()

    def stop(self) -> None:
        """Stop background election thread gracefully."""
        thread = self._current_election_thread
        if thread and thread.is_alive() and threading.current_thread() != thread:
            thread.join(timeout=1.0)
        self._current_election_thread = None

    def _execute_election_lifecycle(self) -> None:
        start_mono = time.monotonic()
        term = 0
        initiator = self._node_id
        try:
            term, initiator = self._run_algorithm(start_mono)
        except Exception as exc:
            self._logger.exception("Unexpected error in election algorithm: %s", exc)
        finally:
            duration_ms = round((time.monotonic() - start_mono) * 1000, 2)
            counts = self.get_message_counts()
            self._record_completion(term, initiator, duration_ms, counts)
            with self._election_lock:
                self._election_in_progress = False

    def _record_completion(self, term: int, initiator: int, duration_ms: float, counts: dict) -> None:
        election_sent = counts.get("election", 0)
        ok_sent = counts.get("ok", 0)
        coordinator_sent = counts.get("coordinator", 0)
        total_logical_sent = election_sent + ok_sent + coordinator_sent

        metrics = {
            "duration_ms": duration_ms,
            "election_sent": election_sent,
            "ok_sent": ok_sent,
            "coordinator_sent": coordinator_sent,
            "total_logical_sent": total_logical_sent,
            "election_term": term,
            "initiator_id": initiator,
        }
        with self._election_lock:
            self._last_election_metrics = metrics

        self._record_event(
            "ELECTION_COMPLETED",
            lamport_ts=self._clock.tick(),
            election_term=term,
            initiator_id=initiator,
            completion_time_ms=duration_ms,
            duration_ms=duration_ms,
            election_sent=election_sent,
            ok_sent=ok_sent,
            coordinator_sent=coordinator_sent,
            total_logical_sent=total_logical_sent,
            total_sent_election=election_sent,
            total_sent_ok=ok_sent,
            total_sent_coordinator=coordinator_sent,
        )

    def announce_to_peer(self, peer_id: int, election_term: int, initiator_id: int) -> None:
        """Announce this node as coordinator to a specific peer."""
        client = self._peer_clients.get(peer_id)
        if not client:
            return

        self._count_sent("coordinator")
        ts = self._clock.send()
        self._record_event(
            "COORDINATOR_ANNOUNCED",
            lamport_ts=ts,
            election_term=election_term,
            initiator_id=initiator_id,
            peer_id=peer_id,
        )
        ack = client.announce_coordinator(
            coordinator_id=self._node_id,
            election_term=election_term,
            initiator_id=initiator_id,
            lamport_ts=ts,
            timeout=min(self._election_timeout_sec, 0.5),
        )
        if ack is not None:
            self._clock.receive(ack.lamport_ts)
            self._state.mark_peer_active(peer_id)
        else:
            self._state.mark_peer_inactive(peer_id)

    def _announce_coordinator_to_peers(self, election_term: int, initiator_id: int) -> None:
        """Announce this node as coordinator to all reachable active peers."""
        active_peers = self._state.active_peers
        threads = []
        for pid in sorted(active_peers):
            if pid == self._node_id:
                continue
            t = threading.Thread(target=self.announce_to_peer, args=(pid, election_term, initiator_id), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join(timeout=1.0)

    def _run_algorithm(self, start_mono: float) -> tuple[int, int]:
        """Subclasses implement algorithm-specific election steps. Returns (election_term, initiator_id)."""
        raise NotImplementedError
