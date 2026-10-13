"""Node runtime coordinator — encapsulates the full runtime lifecycle of a node."""

import logging
import threading
from concurrent import futures
from typing import Optional

import grpc

from node.config import NodeConfig
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.election import create_election_strategy
from node.election.strategy import ElectionStrategy
from node.heartbeat import HeartbeatMonitor, HeartbeatSender
from node.lamport import LamportClock
from node.lifecycle import NodeLifecycle
from node.logging_config import log_event, setup_logging
from node.models import RecoverySummary
from node.peer_client import PeerClient
from node.recovery import RecoveryManager
from node.replication import ReplicationManager
from node.service_impl import VotingServicer
from node.vote_service import VoteService
from node.generated import voting_pb2_grpc


class NodeRuntime:
    """Encapsulates all node subsystems, background threads, and gRPC server."""

    def __init__(
        self,
        config: NodeConfig,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self.config = config
        self.logger = logger or setup_logging(config.node_id, config.log_level)

        # ── Core state & components ──
        self.clock = LamportClock()

        if config.use_sqlite:
            self.db = DatabaseManager(use_sqlite=True, sqlite_path=config.sqlite_path)
        else:
            self.db = DatabaseManager(
                use_sqlite=False,
                mysql_config={
                    "host": config.db_host,
                    "port": config.db_port,
                    "user": config.db_user,
                    "password": config.db_password,
                    "database": config.db_name,
                },
            )

        self.state = CoordinatorState(
            node_id=config.node_id,
            initial_coordinator_id=config.default_coordinator_id,
            all_peer_ids=config.all_node_ids,
        )

        # ── Peer communication ──
        self.peer_clients = {
            pid: PeerClient(node_id=pid, address=addr.address if hasattr(addr, "address") else str(addr))
            for pid, addr in config.peers.items()
            if pid != config.node_id
        }

        # ── Subsystems ──
        self.replication_manager = ReplicationManager(
            node_id=config.node_id,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            peer_clients=self.peer_clients,
            logger=self.logger,
        )

        self.heartbeat_sender = HeartbeatSender(
            node_id=config.node_id,
            state=self.state,
            clock=self.clock,
            peer_clients=self.peer_clients,
            config=config,
            logger=self.logger,
        )

        self.heartbeat_monitor = HeartbeatMonitor(
            node_id=config.node_id,
            state=self.state,
            clock=self.clock,
            config=config,
            logger=self.logger,
        )

        self.lifecycle = NodeLifecycle(
            node_id=config.node_id,
            state=self.state,
            sender=self.heartbeat_sender,
            monitor=self.heartbeat_monitor,
            logger=self.logger,
        )

        # ── Election strategy ──
        self.election_strategy: ElectionStrategy = create_election_strategy(
            algorithm=config.election_algorithm,
            node_id=config.node_id,
            state=self.state,
            clock=self.clock,
            peer_clients=self.peer_clients,
            config=config,
            db=self.db,
            lifecycle=self.lifecycle,
            logger=self.logger,
        )

        # ── Recovery manager (Phase 4) ──
        self.recovery_manager = RecoveryManager(
            node_id=config.node_id,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            peer_clients=self.peer_clients,
            replication_manager=self.replication_manager,
            lifecycle=self.lifecycle,
            logger=self.logger,
        )

        if config.auto_recover:
            def _on_election_win(term: int, initiator_id: int) -> None:
                def _bg_recover() -> None:
                    self.recovery_manager.recover_coordinator(term, initiator_id)
                t = threading.Thread(target=_bg_recover, daemon=True, name=f"AutoRecover-{term}")
                t.start()

            self.election_strategy.set_on_win(_on_election_win)

        def _on_coordinator_timeout() -> None:
            log_event(
                self.logger,
                "COORDINATOR_TIMEOUT_TRIGGERED",
                lamport_ts=self.clock.tick(),
                node_id=config.node_id,
                coordinator_id=self.state.coordinator_id,
            )
            # Trigger election start upon coordinator timeout
            self.election_strategy.start_election(blocking=False)

        self._sync_lock = threading.Lock()

        def _on_coordinator_adopted() -> None:
            self.lifecycle.apply_role()
            if self.config.auto_recover and not self.state.is_coordinator():
                def _bg_sync() -> None:
                    if not self._sync_lock.acquire(blocking=False):
                        return
                    try:
                        self.recovery_manager.sync_with_cluster()
                    except Exception as exc:
                        self.logger.warning("Auto follower sync error: %s", exc)
                    finally:
                        self._sync_lock.release()
                t = threading.Thread(
                    target=_bg_sync,
                    daemon=True,
                    name=f"AutoFollowerSync-{self.config.node_id}",
                )
                t.start()

        self.heartbeat_monitor.set_on_timeout(_on_coordinator_timeout)
        self.heartbeat_monitor.set_on_coordinator_adopted(_on_coordinator_adopted)

        # ── Voting service & Servicer ──
        self.vote_service = VoteService(
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            replication_manager=self.replication_manager,
            logger=self.logger,
        )

        self.servicer = VotingServicer(
            vote_service=self.vote_service,
            db=self.db,
            clock=self.clock,
            state=self.state,
            config=config,
            replication_manager=self.replication_manager,
            heartbeat_monitor=self.heartbeat_monitor,
            election_strategy=self.election_strategy,
            recovery_manager=self.recovery_manager,
            logger=self.logger,
        )

        # ── gRPC Server ──
        self.server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
        voting_pb2_grpc.add_NodeServiceServicer_to_server(self.servicer, self.server)
        self.address = f"0.0.0.0:{config.grpc_port}"
        self.bound_port = self.server.add_insecure_port(self.address)

    def start(self) -> None:
        """Initialize database, replay log for recovery, start gRPC server and background threads."""
        self.db.initialize()
        self.recovery_manager.recover_local_state()
        self.server.start()
        self.lifecycle.start()

        log_event(
            self.logger,
            "NODE_STARTED",
            lamport_ts=self.clock.tick(),
            node_id=self.config.node_id,
            role=self.state.role.value,
            coordinator_id=self.state.coordinator_id,
            address=self.address,
            algorithm=self.config.election_algorithm,
        )

    def stop(self, grace: float = 2.0) -> None:
        """Gracefully stop lifecycle threads, gRPC server, and close connections."""
        self.lifecycle.stop()
        if hasattr(self.election_strategy, "stop"):
            self.election_strategy.stop()
        self.server.stop(grace=grace)
        for client in self.peer_clients.values():
            client.close()
        self.db.close()

    def recover_coordinator(
        self,
        election_term: Optional[int] = None,
        initiator_id: Optional[int] = None,
        timeout: float = 2.0,
        target_peer_ids: Optional[list[int]] = None,
    ) -> RecoverySummary:
        """Explicitly run coordinator recovery phase (promotes RECOVERING -> COORDINATOR)."""
        term = election_term if election_term is not None else self.state.election_term
        init_id = initiator_id if initiator_id is not None else self.state.initiator_id
        return self.recovery_manager.recover_coordinator(
            election_term=term,
            initiator_id=init_id,
            timeout=timeout,
            target_peer_ids=target_peer_ids,
        )

    def sync_with_cluster(
        self,
        coordinator_id: Optional[int] = None,
        timeout: float = 2.0,
    ) -> RecoverySummary:
        """Catch-up synchronization with cluster / coordinator."""
        return self.recovery_manager.sync_with_cluster(
            coordinator_id=coordinator_id,
            timeout=timeout,
        )

