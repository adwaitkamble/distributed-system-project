"""Heartbeat subsystem — coordinator broadcaster and follower failure detector.

Invariants:
- Failure Detection: Uses time.monotonic() to eliminate wall-clock and NTP jumps.
- Monotonic Lamport ticks on heartbeat ping and pong events.
- Amendment 3: Active peer tracking through heartbeat acknowledgements.
"""

import logging
import threading
import time
from typing import Callable, Optional

from node.config import NodeConfig
from node.coordinator import CoordinatorState
from node.lamport import LamportClock
from node.logging_config import log_event
from node.models import NodeRole
from node.peer_client import PeerClient


class HeartbeatSender:
    """Runs on the coordinator: broadcasts periodic pings to all peers."""

    def __init__(
        self,
        node_id: int,
        state: CoordinatorState,
        clock: LamportClock,
        peer_clients: dict[int, PeerClient],
        config: NodeConfig,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._node_id = node_id
        self._state = state
        self._clock = clock
        self._peer_clients = peer_clients
        self._config = config
        self._logger = logger or logging.getLogger(f"heartbeat_sender.{node_id}")

        self._interval_sec = max(config.heartbeat_interval_ms / 1000.0, 0.05)
        self._timeout_sec = max(config.heartbeat_timeout_ms / 1000.0, 0.1)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        # Initialize follower last-ack times at sender startup (Req 4)
        self._last_ack_monotonic: dict[int, float] = {
            pid: time.monotonic() for pid in peer_clients if pid != node_id
        }

    def start(self) -> None:
        """Start the background broadcast thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._last_ack_monotonic = {
            pid: time.monotonic() for pid in self._peer_clients if pid != self._node_id
        }
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"HeartbeatSender-{self._node_id}",
        )
        self._thread.start()
        self._logger.debug("HeartbeatSender started with interval %.2fs", self._interval_sec)

    def stop(self) -> None:
        """Stop the background broadcast thread."""
        self._stop_event.set()
        if self._thread is not None:
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=2.0)
            self._thread = None
            self._logger.debug("HeartbeatSender stopped")

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            if self._state.acts_as_coordinator():
                self.send_single_round()
            self._stop_event.wait(self._interval_sec)

    def send_single_round(self) -> dict[int, bool]:
        """Broadcast one round of pings to all peers synchronously.

        Returns {peer_id: was_successful}.
        """
        results: dict[int, bool] = {}
        term = self._state.election_term
        initiator_id = self._state.initiator_id

        for pid, client in list(self._peer_clients.items()):
            if pid == self._node_id:
                continue

            # Call clock.send() separately for each outbound heartbeat RPC (Req 4)
            ts = self._clock.send()

            log_event(
                self._logger, "HEARTBEAT_SENT",
                lamport_ts=ts,
                coordinator_id=self._node_id,
                peer_id=pid,
                election_term=term,
            )

            pong = client.send_heartbeat(
                coordinator_id=self._node_id,
                election_term=term,
                lamport_ts=ts,
                initiator_id=initiator_id,
                timeout=min(self._interval_sec, 0.5),
            )
            now = time.monotonic()
            if pong is not None:
                results[pid] = True
                self._last_ack_monotonic[pid] = now
                self._state.mark_peer_active(pid)
                self._clock.receive(pong.lamport_ts)
                log_event(
                    self._logger, "HEARTBEAT_ACKNOWLEDGED",
                    lamport_ts=self._clock.value,
                    coordinator_id=self._node_id,
                    peer_id=pid,
                    remote_ts=pong.lamport_ts,
                )
            else:
                results[pid] = False
                last_ack = self._last_ack_monotonic.get(pid, 0.0)
                elapsed = now - last_ack
                if elapsed >= self._timeout_sec:
                    self._state.mark_peer_inactive(pid)
                    log_event(
                        self._logger, "HEARTBEAT_TIMEOUT",
                        lamport_ts=self._clock.value,
                        peer_id=pid,
                        elapsed_seconds=round(elapsed, 3),
                        timeout_threshold=self._timeout_sec,
                    )
                    log_event(
                        self._logger, "PEER_UNAVAILABLE",
                        lamport_ts=self._clock.value,
                        peer_id=pid,
                        reason="heartbeat_timeout",
                    )
                else:
                    log_event(
                        self._logger, "PEER_UNAVAILABLE",
                        lamport_ts=self._clock.value,
                        peer_id=pid,
                        reason="heartbeat_failed",
                    )

        return results


class HeartbeatMonitor:
    """Runs on followers: monitors coordinator liveness using monotonic time."""

    def __init__(
        self,
        node_id: int,
        state: CoordinatorState,
        clock: LamportClock,
        config: NodeConfig,
        on_timeout: Optional[Callable[[], None]] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._node_id = node_id
        self._state = state
        self._clock = clock
        self._config = config
        self._on_timeout = on_timeout
        self._logger = logger or logging.getLogger(f"heartbeat_monitor.{node_id}")

        self._timeout_sec = max(config.heartbeat_timeout_ms / 1000.0, 0.1)
        self._last_heartbeat_monotonic = time.monotonic()
        self._timeout_latched = False  # One-time timeout latch (Req 4)
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._first_heartbeat_received = False
        self._lock = threading.Lock()

    @property
    def last_heartbeat_time(self) -> float:
        with self._lock:
            return self._last_heartbeat_monotonic

    def set_on_timeout(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._on_timeout = callback

    def set_on_coordinator_adopted(self, callback: Optional[Callable[[], None]]) -> None:
        with self._lock:
            self._on_coordinator_adopted = callback

    def reset_timeout_latch(self) -> None:
        """Reset the one-time timeout latch (e.g. after election or new coordinator)."""
        with self._lock:
            self._timeout_latched = False
            self._last_heartbeat_monotonic = time.monotonic()

    def record_heartbeat(
        self,
        coordinator_id: int,
        election_term: int,
        lamport_ts: int,
        initiator_id: int = 0,
    ) -> bool:
        """Called when a HeartbeatPing RPC is received from a coordinator.

        Returns True if accepted, False if rejected (e.g. stale term or competing coordinator).
        """
        adopt_cb = None
        with self._lock:
            if coordinator_id not in self._config.all_node_ids:
                self._logger.warning("Rejected heartbeat from unauthorized/unknown node %d", coordinator_id)
                return False

            current_term = self._state.election_term
            if election_term < current_term:
                self._logger.warning(
                    "Rejected stale heartbeat from %d: term %d < current %d",
                    coordinator_id, election_term, current_term,
                )
                return False

            # For equal election term, accept only from the already-known coordinator (Req 4)
            if election_term == current_term:
                if self._state.coordinator_id is not None and coordinator_id != self._state.coordinator_id:
                    self._logger.warning(
                        "Rejected competing coordinator %d for equal term %d (known=%d)",
                        coordinator_id, election_term, self._state.coordinator_id,
                    )
                    return False

            self._last_heartbeat_monotonic = time.monotonic()
            self._timeout_latched = False  # Reset latch upon valid heartbeat

            first_hb = not self._first_heartbeat_received
            if first_hb:
                self._first_heartbeat_received = True

            if election_term > current_term or self._state.role in (NodeRole.FOLLOWER, NodeRole.CANDIDATE):
                if (
                    self._state.coordinator_id != coordinator_id
                    or election_term > current_term
                    or self._state.role != NodeRole.FOLLOWER
                    or first_hb
                ):
                    self._state.become_follower(
                        coordinator_id=coordinator_id,
                        election_term=election_term,
                        initiator_id=initiator_id or coordinator_id,
                    )
                    adopt_cb = getattr(self, "_on_coordinator_adopted", None)

        if adopt_cb:
            adopt_cb()
        return True

    def check_timeout(self) -> bool:
        """Check if coordinator heartbeat has expired using monotonic time.

        Triggers on_timeout() exactly once via a one-time timeout latch.
        Returns True if timed out, False otherwise.
        """
        if self._state.acts_as_coordinator():
            return False

        cb = None
        timed_out = False
        with self._lock:
            elapsed = time.monotonic() - self._last_heartbeat_monotonic
            if elapsed > self._timeout_sec:
                timed_out = True
                if not self._timeout_latched:
                    self._timeout_latched = True
                    log_event(
                        self._logger, "HEARTBEAT_TIMEOUT",
                        lamport_ts=self._clock.tick(),
                        coordinator_id=self._state.coordinator_id,
                        elapsed_seconds=round(elapsed, 3),
                        timeout_threshold=self._timeout_sec,
                    )
                    cb = self._on_timeout
            else:
                return False

        if cb:
            cb()
        return timed_out

    def start(self) -> None:
        """Start the background monitor thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        with self._lock:
            self._last_heartbeat_monotonic = time.monotonic()
        self._thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"HeartbeatMonitor-{self._node_id}",
        )
        self._thread.start()
        self._logger.debug("HeartbeatMonitor started with timeout %.2fs", self._timeout_sec)

    def stop(self) -> None:
        """Stop the background monitor thread."""
        self._stop_event.set()
        if self._thread is not None:
            if threading.current_thread() != self._thread:
                self._thread.join(timeout=2.0)
            self._thread = None
            self._logger.debug("HeartbeatMonitor stopped")

    def _run_loop(self) -> None:
        check_interval = min(self._timeout_sec / 4.0, 0.2)
        while not self._stop_event.is_set():
            self.check_timeout()
            self._stop_event.wait(check_interval)
