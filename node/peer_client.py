"""Thread-safe gRPC client for outgoing inter-node RPCs.

Handles connection reuse, channel lifecycle, bounded timeouts, and
graceful error handling (returns None on RPC error).
"""

import logging
import threading
from typing import Optional

import grpc

from node.models import VoteRecord
from node.generated import voting_pb2
from node.generated import voting_pb2_grpc


class PeerClient:
    """Wrapper around NodeServiceStub for communicating with one remote peer."""

    def __init__(
        self,
        node_id: int,
        address: str,
        default_timeout: float = 2.0,
        channel: Optional[grpc.Channel] = None,
        stub: Optional[voting_pb2_grpc.NodeServiceStub] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._node_id = node_id
        self._address = address.address if hasattr(address, "address") else str(address)
        self._default_timeout = default_timeout
        self._logger = logger or logging.getLogger(f"peer_client.{node_id}")

        self._channel = channel
        self._stub = stub
        self._owns_channel = channel is None
        self._lock = threading.Lock()

    @property
    def node_id(self) -> int:
        return self._node_id

    @property
    def address(self) -> str:
        return self._address

    def _get_stub(self) -> voting_pb2_grpc.NodeServiceStub:
        with self._lock:
            if self._stub is None:
                if self._channel is None:
                    self._channel = grpc.insecure_channel(self._address)
                self._stub = voting_pb2_grpc.NodeServiceStub(self._channel)
            return self._stub

    # ── Phase 2: Replication ─────────────────────────────────────

    def replicate_vote(
        self,
        vote: VoteRecord,
        timeout: Optional[float] = None,
    ) -> Optional[voting_pb2.ReplicationAck]:
        """Send ReplicateVote RPC to this peer.

        Returns ReplicationAck on success, or None on RPC failure/timeout.
        """
        stub = self._get_stub()
        req = voting_pb2.VoteRecord(
            vote_id=vote.vote_id,
            client_id=vote.client_id,
            origin_node_id=vote.origin_node_id,
            lamport_ts=vote.lamport_ts,
            choice=vote.choice,
            received_at_ms=vote.received_at_ms,
        )
        t = timeout if timeout is not None else self._default_timeout
        try:
            return stub.ReplicateVote(req, timeout=t)
        except grpc.RpcError as exc:
            self._logger.warning(
                "ReplicateVote to node %d (%s) failed: code=%s, details=%s",
                self._node_id, self._address, exc.code(), exc.details(),
            )
            return None

    def finalize_vote(
        self,
        vote_id: str,
        lamport_ts: int = 0,
        timeout: Optional[float] = None,
    ) -> Optional[voting_pb2.FinalizeAck]:
        """Send FinalizeVote RPC to this peer.

        Returns FinalizeAck on success, or None on RPC failure/timeout.
        """
        stub = self._get_stub()
        req = voting_pb2.FinalizeRequest(
            vote_id=vote_id,
            lamport_ts=lamport_ts,
        )
        t = timeout if timeout is not None else self._default_timeout
        try:
            return stub.FinalizeVote(req, timeout=t)
        except grpc.RpcError as exc:
            self._logger.warning(
                "FinalizeVote to node %d (%s) failed for %s: code=%s, details=%s",
                self._node_id, self._address, vote_id, exc.code(), exc.details(),
            )
            return None

    # ── Phase 2: Heartbeat ───────────────────────────────────────

    def send_heartbeat(
        self,
        coordinator_id: int,
        election_term: int,
        lamport_ts: int,
        initiator_id: int = 0,
        timeout: Optional[float] = None,
    ) -> Optional[voting_pb2.HeartbeatPong]:
        """Send HeartbeatPing RPC to this peer.

        Returns HeartbeatPong on success, or None on RPC failure/timeout.
        """
        stub = self._get_stub()
        req = voting_pb2.HeartbeatPing(
            coordinator_id=coordinator_id,
            lamport_ts=lamport_ts,
            election_term=election_term,
            initiator_id=initiator_id,
        )
        t = timeout if timeout is not None else 1.0
        try:
            return stub.Heartbeat(req, timeout=t)
        except grpc.RpcError as exc:
            self._logger.debug(
                "Heartbeat to node %d (%s) failed: code=%s",
                self._node_id, self._address, exc.code(),
            )
    # ── Phase 3: Election ────────────────────────────────────────

    def send_election(
        self,
        sender_id: int,
        candidate_id: int,
        election_term: int,
        initiator_id: int,
        lamport_ts: int,
        timeout: Optional[float] = None,
    ) -> Optional[voting_pb2.ElectionResponse]:
        """Send Election RPC to this peer.

        Returns ElectionResponse on success, or None on RPC failure/timeout.
        """
        stub = self._get_stub()
        req = voting_pb2.ElectionMessage(
            sender_id=sender_id,
            candidate_id=candidate_id,
            lamport_ts=lamport_ts,
            election_term=election_term,
            initiator_id=initiator_id,
        )
        t = timeout if timeout is not None else self._default_timeout
        try:
            return stub.Election(req, timeout=t)
        except grpc.RpcError as exc:
            self._logger.debug(
                "Election to node %d (%s) failed: code=%s",
                self._node_id, self._address, exc.code(),
            )
            return None

    def announce_coordinator(
        self,
        coordinator_id: int,
        election_term: int,
        initiator_id: int,
        lamport_ts: int,
        timeout: Optional[float] = None,
    ) -> Optional[voting_pb2.Ack]:
        """Send AnnounceCoordinator RPC to this peer.

        Returns Ack on success, or None on RPC failure/timeout.
        """
        stub = self._get_stub()
        req = voting_pb2.CoordinatorMessage(
            coordinator_id=coordinator_id,
            lamport_ts=lamport_ts,
            election_term=election_term,
            initiator_id=initiator_id,
        )
        t = timeout if timeout is not None else self._default_timeout
        try:
            return stub.AnnounceCoordinator(req, timeout=t)
        except grpc.RpcError as exc:
            self._logger.debug(
                "AnnounceCoordinator to node %d (%s) failed: code=%s",
                self._node_id, self._address, exc.code(),
            )
            return None

    # ── Phase 4: State Recovery / SyncLog ────────────────────────

    def sync_log(
        self,
        requester_id: int,
        election_term: int,
        initiator_id: int,
        lamport_ts: int,
        timeout: Optional[float] = None,
    ) -> Optional[voting_pb2.SyncResponse]:
        """Send SyncLog RPC to this peer to pull its committed vote log.

        Returns SyncResponse on success, or None on RPC failure/timeout.
        """
        stub = self._get_stub()
        req = voting_pb2.SyncRequest(
            requester_id=requester_id,
            lamport_ts=lamport_ts,
            election_term=election_term,
            initiator_id=initiator_id,
        )
        t = timeout if timeout is not None else self._default_timeout
        try:
            return stub.SyncLog(req, timeout=t)
        except grpc.RpcError as exc:
            self._logger.debug(
                "SyncLog to node %d (%s) failed: code=%s, details=%s",
                self._node_id, self._address, exc.code(), exc.details(),
            )
            return None

    # ── Cleanup ──────────────────────────────────────────────────

    def close(self) -> None:
        """Close gRPC channel if owned."""
        with self._lock:
            if self._owns_channel and self._channel is not None:
                self._channel.close()
                self._channel = None
                self._stub = None
