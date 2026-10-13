"""Lifecycle manager for node background tasks (HeartbeatSender and HeartbeatMonitor).

Handles clean transitions between FOLLOWER, CANDIDATE, RECOVERING, and COORDINATOR.
"""

import logging
import threading
from typing import Optional

from node.coordinator import CoordinatorState
from node.heartbeat import HeartbeatMonitor, HeartbeatSender
from node.models import NodeRole


class NodeLifecycle:
    """Coordinates background service threads across dynamic role transitions."""

    def __init__(
        self,
        node_id: int,
        state: CoordinatorState,
        sender: HeartbeatSender,
        monitor: HeartbeatMonitor,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._node_id = node_id
        self._state = state
        self._sender = sender
        self._monitor = monitor
        self._logger = logger or logging.getLogger(f"lifecycle.{node_id}")
        self._lock = threading.RLock()
        self._running = False

    def start(self) -> None:
        """Start lifecycle management and apply initial role configuration."""
        with self._lock:
            self._running = True
            self.apply_role()

    def stop(self) -> None:
        """Stop all managed background services."""
        with self._lock:
            self._running = False
            self._sender.stop()
            self._monitor.stop()

    def apply_role(self) -> None:
        """Inspect state.role and ensure sender/monitor are in appropriate running state.

        - COORDINATOR or RECOVERING: HeartbeatSender MUST run; HeartbeatMonitor MUST stop.
        - FOLLOWER: HeartbeatMonitor MUST run; HeartbeatSender MUST stop.
        - CANDIDATE: HeartbeatSender MUST stop; HeartbeatMonitor stops or waits.
        """
        with self._lock:
            if not self._running:
                return

            role = self._state.role
            if role in (NodeRole.COORDINATOR, NodeRole.RECOVERING):
                self._logger.debug("Applying role %s: stopping monitor, starting sender", role.value)
                self._monitor.stop()
                self._sender.start()
            elif role == NodeRole.FOLLOWER:
                self._logger.debug("Applying role FOLLOWER: stopping sender, starting monitor")
                self._sender.stop()
                self._monitor.reset_timeout_latch()
                self._monitor.start()
            elif role == NodeRole.CANDIDATE:
                self._logger.debug("Applying role CANDIDATE: stopping sender")
                self._sender.stop()
