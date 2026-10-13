"""gRPC servicer — implements the NodeService interface.

Phase 1: SubmitVote, GetClusterStatus, GetResults are live.
Other RPCs return UNIMPLEMENTED until their phase.
"""

import grpc
import logging
from typing import Optional

from node.config import NodeConfig
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.lamport import LamportClock
from node.logging_config import log_event
from node.models import NodeRole
from node.vote_service import VoteService

from node.generated import voting_pb2
from node.generated import voting_pb2_grpc


class VotingServicer(voting_pb2_grpc.NodeServiceServicer):
    """Implements all NodeService RPCs."""

    def __init__(
        self,
        vote_service: VoteService,
        db: DatabaseManager,
        clock: LamportClock,
        state: CoordinatorState,
        config: NodeConfig,
        replication_manager=None,
        heartbeat_monitor=None,
        election_strategy=None,
        recovery_manager=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._vote_service = vote_service
        self._db = db
        self._clock = clock
        self._state = state
        self._config = config
        self._replication_manager = replication_manager
        self._heartbeat_monitor = heartbeat_monitor
        self._election_strategy = election_strategy
        self._recovery_manager = recovery_manager
        self._logger = logger or logging.getLogger(f"node.{config.node_id}")

    # ── Phase 1: Voting ──────────────────────────────────────────

    def SubmitVote(self, request, context):
        ts = self._clock.receive(0)  # treat incoming RPC as a receive-event
        log_event(
            self._logger, "VOTE_SUBMITTED",
            lamport_ts=ts,
            client_id=request.client_id, choice=request.choice,
        )

        # Reject if not coordinator (provide redirect hint)
        if not self._state.is_accepting_votes():
            coord_id = self._state.coordinator_id
            context.abort(
                grpc.StatusCode.FAILED_PRECONDITION,
                f"not_coordinator:{coord_id}",
            )

        result = self._vote_service.submit_vote(request.client_id, request.choice)

        return voting_pb2.VoteResponse(
            success=result["success"],
            vote_id=result["vote_id"],
            error=result["error"],
            lamport_ts=result["lamport_ts"],
        )

    # ── Phase 1: Query ───────────────────────────────────────────

    def GetClusterStatus(self, request, context):
        ts = self._clock.tick()
        role = self._state.role
        return voting_pb2.ClusterStatus(
            coordinator_id=self._state.coordinator_id,
            this_node_id=self._config.node_id,
            election_algorithm=self._config.election_algorithm,
            known_peers=sorted(self._config.peers.keys()),
            active_peers=sorted(self._state.active_peers),
            role=role.value,
            election_term=self._state.election_term,
            lamport_ts=ts,
            accepting_votes=self._state.is_accepting_votes(),
        )

    def GetResults(self, request, context):
        ts = self._clock.tick()
        tally = self._db.get_tally()
        total = sum(tally.values())
        return voting_pb2.TallyResponse(
            tally=tally,
            total_votes=total,
            lamport_ts=ts,
        )

    # ── Phase 2: Replication & Heartbeat ─────────────────────────

    def ReplicateVote(self, request, context):
        if not self._replication_manager:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, "ReplicateVote not initialized")

        success, error, out_ts = self._replication_manager.handle_replicate_vote(request)
        return voting_pb2.ReplicationAck(
            success=success,
            node_id=self._config.node_id,
            error=error,
            lamport_ts=out_ts,
        )

    def FinalizeVote(self, request, context):
        if not self._replication_manager:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, "FinalizeVote not initialized")

        success, error, out_ts = self._replication_manager.handle_finalize_vote(request)
        return voting_pb2.FinalizeAck(
            success=success,
            node_id=self._config.node_id,
            error=error,
            lamport_ts=out_ts,
        )

    def Heartbeat(self, request, context):
        self._clock.receive(request.lamport_ts)
        if self._heartbeat_monitor:
            accepted = self._heartbeat_monitor.record_heartbeat(
                coordinator_id=request.coordinator_id,
                election_term=request.election_term,
                lamport_ts=request.lamport_ts,
                initiator_id=getattr(request, "initiator_id", 0),
            )
            if not accepted:
                context.abort(
                    grpc.StatusCode.FAILED_PRECONDITION,
                    f"stale_heartbeat_term:{request.election_term}<{self._state.election_term}",
                )

        pong_ts = self._clock.tick()
        return voting_pb2.HeartbeatPong(
            node_id=self._config.node_id,
            lamport_ts=pong_ts,
        )

    # ── Phase 4: State Recovery / SyncLog ────────────────────────

    def SyncLog(self, request, context):
        if self._recovery_manager:
            return self._recovery_manager.handle_sync_request(request)

        # Direct DB fallback if recovery manager is not provided
        self._clock.receive(request.lamport_ts)
        self._state.mark_peer_active(request.requester_id)
        committed_votes = self._db.get_all_votes(committed_only=True)
        vote_pbs = [
            voting_pb2.VoteRecord(
                vote_id=v.vote_id,
                client_id=v.client_id,
                origin_node_id=v.origin_node_id,
                lamport_ts=v.lamport_ts,
                choice=v.choice,
                received_at_ms=v.received_at_ms,
                status=v.status,
            )
            for v in committed_votes
        ]
        return voting_pb2.SyncResponse(
            votes=vote_pbs,
            node_id=self._config.node_id,
            lamport_ts=self._clock.send(),
        )

    def Election(self, request, context):
        if not self._election_strategy:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, "Election not initialized")

        ok, node_id, reply_ts = self._election_strategy.on_election_message(
            sender_id=request.sender_id,
            candidate_id=request.candidate_id,
            election_term=request.election_term,
            initiator_id=request.initiator_id,
            msg_lamport_ts=request.lamport_ts,
        )
        return voting_pb2.ElectionResponse(
            ok=ok,
            node_id=node_id,
            lamport_ts=reply_ts,
        )

    def AnnounceCoordinator(self, request, context):
        if not self._election_strategy:
            context.abort(grpc.StatusCode.UNIMPLEMENTED, "AnnounceCoordinator not initialized")

        accepted = self._election_strategy.on_coordinator_announcement(
            coordinator_id=request.coordinator_id,
            election_term=request.election_term,
            initiator_id=request.initiator_id,
            msg_lamport_ts=request.lamport_ts,
        )
        ack_ts = self._clock.send()
        return voting_pb2.Ack(
            success=accepted,
            lamport_ts=ack_ts,
        )
