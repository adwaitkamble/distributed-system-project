"""Log replication module — coordinator fan-out and replica ingestion.

Invariants:
- INV-4: Replication-before-ack (success only after local + peer persistence).
- INV-5: No phantom acks (failure on insufficient replication ACKs rolls back local vote).
- INV-6: Idempotent replication (replaying same vote_id + payload is a no-op).
- Amendment 3: active_peers maintenance on replication failure/success.
"""

from concurrent import futures
import logging
import time
from typing import Optional

from node.config import NodeConfig
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.lamport import LamportClock
from node.logging_config import log_event
from node.models import InsertResult, VoteRecord
from node.peer_client import PeerClient
from node.generated import voting_pb2


class ReplicationManager:
    """Manages outgoing ReplicateVote fan-out and incoming replica ingestion."""

    def __init__(
        self,
        node_id: int,
        db: DatabaseManager,
        clock: LamportClock,
        state: CoordinatorState,
        config: NodeConfig,
        peer_clients: dict[int, PeerClient],
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._node_id = node_id
        self._db = db
        self._clock = clock
        self._state = state
        self._config = config
        self._peer_clients = peer_clients
        self._logger = logger or logging.getLogger(f"replication.{node_id}")

    # ── Coordinator Side: Fan-Out ────────────────────────────────

    def replicate_vote(
        self,
        vote: VoteRecord,
        target_peer_ids: Optional[list[int]] = None,
        timeout: float = 2.0,
    ) -> tuple[bool, list[int]]:
        """Fan out ReplicateVote to target peers in parallel.

        Args:
            vote: The VoteRecord to replicate.
            target_peer_ids: Specific peer IDs to target, or None to target active peers.
            timeout: Per-RPC timeout in seconds.

        Returns:
            (success, list_of_acked_peer_ids)
        """
        if target_peer_ids is not None:
            targets = [pid for pid in target_peer_ids if pid in self._peer_clients]
        else:
            # Healthy peer policy: Take a snapshot of active_peers at vote admission
            targets = [pid for pid in sorted(self._state.active_peers) if pid in self._peer_clients]

        if not targets:
            # Single-node cluster or all other peers currently inactive: local commit suffices
            return True, []

        log_event(
            self._logger, "REPLICATION_STARTED",
            lamport_ts=vote.lamport_ts,
            correlation_id=vote.vote_id,
            target_peers=targets,
        )

        acked_peers: list[int] = []

        def _send(pid: int):
            client = self._peer_clients[pid]
            ack = client.replicate_vote(vote, timeout=timeout)
            return pid, ack

        # Parallel fan-out
        with futures.ThreadPoolExecutor(max_workers=max(len(targets), 1)) as executor:
            future_to_peer = {executor.submit(_send, pid): pid for pid in targets}
            for fut in futures.as_completed(future_to_peer):
                pid = future_to_peer[fut]
                try:
                    peer_id, ack = fut.result()
                    if ack is not None and ack.success:
                        acked_peers.append(peer_id)
                        self._state.mark_peer_active(peer_id)
                        self._clock.receive(ack.lamport_ts)
                    else:
                        self._state.mark_peer_inactive(peer_id)
                        log_event(
                            self._logger, "PEER_UNAVAILABLE",
                            lamport_ts=self._clock.value,
                            peer_id=peer_id,
                            reason="replication_failed",
                        )
                        self._logger.warning(
                            "Replication to peer %d failed or rejected for vote %s",
                            peer_id, vote.vote_id,
                        )
                except Exception as exc:
                    self._state.mark_peer_inactive(pid)
                    log_event(
                        self._logger, "PEER_UNAVAILABLE",
                        lamport_ts=self._clock.value,
                        peer_id=pid,
                        reason="replication_exception",
                    )
                    self._logger.error("Exception during replication to %d: %s", pid, exc)

        # Evaluate policy against snapshot of healthy targets
        policy = self._config.replication_policy.lower()
        if policy == "all":
            success = (len(acked_peers) == len(targets))
        elif policy == "majority":
            total_nodes = len(self._config.all_node_ids)
            quorum = (total_nodes // 2) + 1
            total_committed = 1 + len(acked_peers)
            success = (total_committed >= quorum)
        else:
            success = (len(acked_peers) == len(targets))

        if success:
            log_event(
                self._logger, "REPLICATION_SUCCEEDED",
                lamport_ts=self._clock.value,
                correlation_id=vote.vote_id,
                acked_peers=acked_peers,
                policy=policy,
            )
        else:
            log_event(
                self._logger, "REPLICATION_FAILED",
                lamport_ts=self._clock.value,
                correlation_id=vote.vote_id,
                acked_peers=acked_peers,
                policy=policy,
                level=logging.WARNING,
            )

        return success, acked_peers

    def finalize_vote(
        self,
        vote_id: str,
        target_peer_ids: list[int],
        timeout: float = 2.0,
    ) -> tuple[bool, list[int]]:
        """Send FinalizeVote RPC to all peers that acknowledged the pending vote."""
        if not target_peer_ids:
            return True, []

        acked_peers: list[int] = []

        def _send(pid: int):
            client = self._peer_clients[pid]
            ts = self._clock.send()
            ack = client.finalize_vote(vote_id, lamport_ts=ts, timeout=timeout)
            return pid, ack

        targets = [pid for pid in target_peer_ids if pid in self._peer_clients]
        with futures.ThreadPoolExecutor(max_workers=max(len(targets), 1)) as executor:
            future_to_peer = {executor.submit(_send, pid): pid for pid in targets}
            for fut in futures.as_completed(future_to_peer):
                pid = future_to_peer[fut]
                try:
                    peer_id, ack = fut.result()
                    if ack is not None and ack.success:
                        acked_peers.append(peer_id)
                        self._clock.receive(ack.lamport_ts)
                    else:
                        self._logger.warning("FinalizeVote to peer %d failed for %s", peer_id, vote_id)
                except Exception as exc:
                    self._logger.error("Exception during finalize to %d: %s", pid, exc)

        policy = self._config.replication_policy.lower()
        if policy == "all":
            success = (len(acked_peers) == len(targets))
        elif policy == "majority":
            total_nodes = len(self._config.all_node_ids)
            quorum = (total_nodes // 2) + 1
            success = (1 + len(acked_peers) >= quorum)
        else:
            success = (len(acked_peers) == len(targets))

        return success, acked_peers

    # ── Replica Side: Ingestion ──────────────────────────────────

    def handle_replicate_vote(self, vote_pb: voting_pb2.VoteRecord) -> tuple[bool, str, int]:
        """Ingest a replicated vote received from coordinator.

        Enforces:
        - INV-6: Idempotent replication.
        - INV-8: Lamport receive max-merge rule.

        Returns:
            (success: bool, error_message: str, current_lamport_ts: int)
        """
        ts = self._clock.receive(vote_pb.lamport_ts)

        vote = VoteRecord(
            vote_id=vote_pb.vote_id,
            client_id=vote_pb.client_id,
            origin_node_id=vote_pb.origin_node_id,
            lamport_ts=vote_pb.lamport_ts,
            choice=vote_pb.choice,
            received_at_ms=vote_pb.received_at_ms or int(time.time() * 1000),
            status=vote_pb.status or "PENDING",
        )

        res = self._db.insert_vote(vote)

        if res == InsertResult.INSERTED:
            log_event(
                self._logger, "VOTE_REPLICATED",
                lamport_ts=ts, correlation_id=vote.vote_id,
                client_id=vote.client_id, origin_node_id=vote.origin_node_id,
            )
            return True, "", self._clock.tick()

        if res in (InsertResult.IDEMPOTENT, InsertResult.PENDING_RETRY):
            log_event(
                self._logger, "IDEMPOTENT_REPLAY",
                lamport_ts=ts, correlation_id=vote.vote_id,
                client_id=vote.client_id, origin_node_id=vote.origin_node_id,
            )
            self._logger.info("Idempotent replication of vote %s", vote.vote_id)
            return True, "", self._clock.tick()

        if res == InsertResult.PENDING_CONFLICT:
            msg = f"client '{vote.client_id}' has pending vote with different choice"
            self._logger.warning("Replication rejected: %s", msg)
            return False, msg, self._clock.tick()

        if res == InsertResult.CLIENT_ALREADY_VOTED:
            msg = f"client '{vote.client_id}' already has a conflicting vote"
            self._logger.warning("Replication rejected: %s", msg)
            return False, msg, self._clock.tick()

        msg = f"vote_id conflict for '{vote.vote_id}'"
        self._logger.error("Replication error: %s", msg)
        return False, msg, self._clock.tick()

    def handle_finalize_vote(self, req: voting_pb2.FinalizeRequest) -> tuple[bool, str, int]:
        """Ingest FinalizeVote RPC on replica, marking the vote COMMITTED."""
        if req.lamport_ts > 0:
            self._clock.receive(req.lamport_ts)
        ok = self._db.finalize_vote(req.vote_id)
        if ok:
            log_event(
                self._logger, "VOTE_FINALIZED",
                lamport_ts=self._clock.value,
                correlation_id=req.vote_id,
            )
            return True, "", self._clock.tick()
        else:
            return False, f"vote '{req.vote_id}' not found", self._clock.tick()
