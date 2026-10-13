"""State recovery and log synchronization module (Phase 4).

Coordinates:
- Local state restoration and Lamport clock recovery on node startup (durable-state verification/restoration).
- Durable state-change logging and log replay.
- SyncLog RPC handling and peer log polling.
- Recovery-Authority Rule: Never resurrect partial-finalization ghost votes; distinguish
  fully accepted votes, unresolved partial-finalization records, and client-ID conflicts.
- Policy-gated coordinator promotion: Evaluates snapshot against 'all' or 'majority' policy
  and checks all replication/finalization repairs before promoting RECOVERING -> COORDINATOR.
- Follower catch-up synchronization.
"""

from concurrent import futures
import logging
import threading
import time
from typing import Optional

from node.config import NodeConfig
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.generated import voting_pb2
from node.lamport import LamportClock
from node.lifecycle import NodeLifecycle
from node.logging_config import log_event
from node.models import InsertResult, NodeRole, RecoverySummary, VoteRecord, VoteStatus
from node.peer_client import PeerClient
from node.replication import ReplicationManager


class RecoveryManager:
    """Manages durable state recovery, log replay, and SyncLog synchronization."""

    def __init__(
        self,
        node_id: int,
        db: DatabaseManager,
        clock: LamportClock,
        state: CoordinatorState,
        config: NodeConfig,
        peer_clients: dict[int, PeerClient],
        replication_manager: Optional[ReplicationManager] = None,
        lifecycle: Optional[NodeLifecycle] = None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._node_id = node_id
        self._db = db
        self._clock = clock
        self._state = state
        self._config = config
        self._peer_clients = peer_clients
        self._replication_manager = replication_manager
        self._lifecycle = lifecycle
        self._logger = logger or logging.getLogger(f"recovery.{node_id}")
        self._recovery_lock = threading.Lock()
        self.last_recovery_summary: Optional[RecoverySummary] = None

    # ── Startup & Local Log Verification / Restoration ───────────

    def recover_local_state(self) -> RecoverySummary:
        """Verify durable storage and sync log on node startup and restore in-memory invariants.

        Restores:
        - Lamport clock monotonically to at least the max persisted Lamport timestamp.
        - Verifies committed and pending vote records.
        """
        start_time = time.monotonic()
        replay_info = self._db.replay_sync_log()
        max_ts = replay_info.get("max_lamport_ts", 0)

        # Restore Lamport clock monotonically
        if max_ts > self._clock.value:
            self._clock.set(max_ts)

        committed_count = replay_info.get("committed_votes", 0)
        replayed_count = replay_info.get("sync_log_entries", 0)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        log_event(
            self._logger,
            "LOCAL_STATE_RESTORED",
            lamport_ts=self._clock.value,
            node_id=self._node_id,
            replayed_entries=replayed_count,
            committed_votes=committed_count,
            max_lamport_ts=max_ts,
            duration_ms=duration_ms,
        )

        self._db.append_sync_log(
            entry_type="LOCAL_STATE_RESTORED",
            lamport_ts=self._clock.value,
            origin_node_id=self._node_id,
            details={
                "replayed_entries": replayed_count,
                "committed_votes": committed_count,
                "max_lamport_ts": max_ts,
            },
        )

        summary = RecoverySummary(
            success=True,
            replayed_entries_count=replayed_count,
            committed_votes_count=committed_count,
            max_lamport_ts=max_ts,
            duration_ms=duration_ms,
        )
        self.last_recovery_summary = summary
        return summary

    # ── gRPC SyncLog Request Handler ─────────────────────────────

    def handle_sync_request(self, request: voting_pb2.SyncRequest) -> voting_pb2.SyncResponse:
        """Handle incoming SyncLog RPC from peer.

        Returns all votes (both COMMITTED and PENDING) so the recovering coordinator
        has complete visibility into peer finalization status and never resurrects ghost votes.
        """
        self._clock.receive(request.lamport_ts)
        self._state.mark_peer_active(request.requester_id)

        log_event(
            self._logger,
            "SYNC_REQUEST_RECEIVED",
            lamport_ts=self._clock.value,
            requester_id=request.requester_id,
            election_term=request.election_term,
            initiator_id=request.initiator_id,
        )

        # Return all votes including PENDING so recovering nodes can detect partial finalization
        all_votes = self._db.get_all_votes(committed_only=False)
        vote_pbs = [
            voting_pb2.VoteRecord(
                vote_id=v.vote_id,
                client_id=v.client_id,
                origin_node_id=v.origin_node_id,
                lamport_ts=v.lamport_ts,
                choice=v.choice,
                received_at_ms=v.received_at_ms,
                status=v.status,
                commit_proof=v.commit_proof,
            )
            for v in all_votes
        ]

        reply_ts = self._clock.send()
        return voting_pb2.SyncResponse(
            votes=vote_pbs,
            node_id=self._node_id,
            lamport_ts=reply_ts,
        )

    # ── Peer Log Ingestion & Merge ───────────────────────────────

    def sync_from_peer(
        self,
        peer_id: int,
        election_term: int = 0,
        initiator_id: int = 0,
        timeout: float = 2.0,
    ) -> list[VoteRecord]:
        """Pull vote log from a specific peer via SyncLog RPC and merge locally."""
        client = self._peer_clients.get(peer_id)
        if not client:
            return []

        ts = self._clock.send()
        resp = client.sync_log(
            requester_id=self._node_id,
            election_term=election_term,
            initiator_id=initiator_id,
            lamport_ts=ts,
            timeout=timeout,
        )

        if resp is None:
            self._state.mark_peer_inactive(peer_id)
            return []

        self._state.mark_peer_active(peer_id)
        self._clock.receive(resp.lamport_ts)

        ingested_votes: list[VoteRecord] = []
        for v_pb in resp.votes:
            # Replicas only ingest votes marked COMMITTED by an authoritative peer
            if v_pb.status != VoteStatus.COMMITTED.value:
                continue
            v = VoteRecord(
                vote_id=v_pb.vote_id,
                client_id=v_pb.client_id,
                origin_node_id=v_pb.origin_node_id,
                lamport_ts=v_pb.lamport_ts,
                choice=v_pb.choice,
                received_at_ms=v_pb.received_at_ms or int(time.time() * 1000),
                status=VoteStatus.COMMITTED.value,
                commit_proof=v_pb.commit_proof,
            )
            res = self._db.insert_synced_vote(v)
            if res in (InsertResult.INSERTED, InsertResult.IDEMPOTENT):
                ingested_votes.append(v)
                self._clock.receive(v.lamport_ts)

        return ingested_votes

    # ── Coordinator State Recovery (Policy-Gated & Ghost-Protected) ──

    def recover_coordinator(
        self,
        election_term: int = 0,
        initiator_id: int = 0,
        timeout: float = 2.0,
        target_peer_ids: Optional[list[int]] = None,
    ) -> RecoverySummary:
        """Execute complete state recovery for a newly elected coordinator.

        Enforces:
        1. Immutable recovery-membership snapshot taken at recovery start.
        2. Recovery-Authority Rule:
           - A replica's status alone is never sufficient to make an unacknowledged vote authoritative.
           - If supervising coordinator has PENDING: vote was never finalized; rejected.
           - If supervising coordinator is dead: requires unanimous COMMITTED among surviving
             replicas under 'all' policy (zero PENDING votes permitted).
           - Demotes any local partial-finalization ghost votes to PENDING.
        3. Check and act on every replicate_vote() and finalize_vote() repair.
        4. Explicit policy gating:
           - 'all': every member of the recovery snapshot must succeed.
           - 'majority': documented quorum must be satisfied.
           - Failed recovery remains in RECOVERING, logs RECOVERY_FAILED, and rejects votes.
        5. Promotes RECOVERING -> COORDINATOR only after authority and policy both succeed.
        """
        with self._recovery_lock:
            start_time = time.monotonic()
            term = election_term or self._state.election_term
            init_id = initiator_id or self._state.initiator_id

            # ── 1. Immutable Recovery-Membership Snapshot ────────────
            if target_peer_ids is not None:
                snapshot_peers = tuple(sorted([
                    pid for pid in target_peer_ids
                    if pid in self._peer_clients and pid != self._node_id
                ]))
            elif self._state.active_peers:
                snapshot_peers = tuple(sorted([
                    pid for pid in self._state.active_peers
                    if pid in self._peer_clients and pid != self._node_id
                ]))
            else:
                snapshot_peers = tuple(sorted([
                    pid for pid in self._config.all_node_ids
                    if pid in self._peer_clients and pid != self._node_id
                ]))

            log_event(
                self._logger,
                "RECOVERY_STARTED",
                lamport_ts=self._clock.tick(),
                node_id=self._node_id,
                election_term=term,
                initiator_id=init_id,
                recovery_snapshot=list(snapshot_peers),
                policy=self._config.replication_policy,
            )

            peer_logs: dict[int, list[VoteRecord]] = {}
            contacted_peers: list[int] = []
            failed_peers: list[int] = []

            # ── 2. Pull logs from every peer in the immutable snapshot ──
            if snapshot_peers:
                def _pull_peer_log(pid: int):
                    client = self._peer_clients[pid]
                    ts = self._clock.send()
                    resp = client.sync_log(
                        requester_id=self._node_id,
                        election_term=term,
                        initiator_id=init_id,
                        lamport_ts=ts,
                        timeout=timeout,
                    )
                    return pid, resp

                with futures.ThreadPoolExecutor(max_workers=max(len(snapshot_peers), 1)) as executor:
                    fut_map = {executor.submit(_pull_peer_log, pid): pid for pid in snapshot_peers}
                    for fut in futures.as_completed(fut_map):
                        pid = fut_map[fut]
                        try:
                            peer_id, resp = fut.result()
                            if resp is not None:
                                self._clock.receive(resp.lamport_ts)
                                self._state.mark_peer_active(peer_id)
                                contacted_peers.append(peer_id)
                                votes = [
                                    VoteRecord(
                                        vote_id=v_pb.vote_id,
                                        client_id=v_pb.client_id,
                                        origin_node_id=v_pb.origin_node_id,
                                        lamport_ts=v_pb.lamport_ts,
                                        choice=v_pb.choice,
                                        received_at_ms=v_pb.received_at_ms or int(time.time() * 1000),
                                        status=v_pb.status or VoteStatus.PENDING.value,
                                        commit_proof=v_pb.commit_proof,
                                    )
                                    for v_pb in resp.votes
                                ]
                                peer_logs[peer_id] = votes
                            else:
                                failed_peers.append(pid)
                                self._state.mark_peer_inactive(pid)
                        except Exception as exc:
                            failed_peers.append(pid)
                            self._logger.warning("Error syncing log with peer %d: %s", pid, exc)
                            self._state.mark_peer_inactive(pid)

            contacted_peers.sort()
            failed_peers.sort()

            # ── 3. Recovery-Authority Rule & Ghost Vote Protection ─────
            local_votes = {v.vote_id: v for v in self._db.get_all_votes(committed_only=False)}
            all_vote_ids = set(local_votes.keys())
            for p_votes in peer_logs.values():
                for pv in p_votes:
                    all_vote_ids.add(pv.vote_id)

            authoritative_votes: dict[str, VoteRecord] = {}
            accepted_votes_count = 0
            rejected_partial_finalizations_count = 0
            client_id_conflicts_count = 0

            policy = self._config.replication_policy.lower()

            for vid in sorted(all_vote_ids):
                # Gather reports across cluster
                local_rec = local_votes.get(vid)
                peer_recs = {pid: v for pid, logs in peer_logs.items() for v in logs if v.vote_id == vid}

                all_known = [r for r in [local_rec] + list(peer_recs.values()) if r is not None]
                if not all_known:
                    continue
                sample = all_known[0]
                origin_node_id = sample.origin_node_id

                # Determine authority
                is_authoritative = False
                rejection_reason = ""

                # Case A: Supervising coordinator is present in recovery
                if origin_node_id == self._node_id:
                    if local_rec and local_rec.status == VoteStatus.COMMITTED.value:
                        is_authoritative = True
                    else:
                        is_authoritative = False
                        rejection_reason = "coordinator_status_pending_or_missing"
                elif origin_node_id in peer_logs:
                    coord_rec = peer_recs.get(origin_node_id)
                    if coord_rec and coord_rec.status == VoteStatus.COMMITTED.value:
                        is_authoritative = True
                    else:
                        is_authoritative = False
                        rejection_reason = "coordinator_status_pending_or_missing"
                else:
                    # Case B: Supervising coordinator is DEAD / unreachable
                    # Evaluate surviving replicas
                    committed_nodes = []
                    pending_nodes = []
                    if local_rec:
                        if local_rec.status == VoteStatus.COMMITTED.value:
                            committed_nodes.append(self._node_id)
                        elif local_rec.status == VoteStatus.PENDING.value:
                            pending_nodes.append(self._node_id)
                    for pid, pr in peer_recs.items():
                        if pr.status == VoteStatus.COMMITTED.value:
                            committed_nodes.append(pid)
                        elif pr.status == VoteStatus.PENDING.value:
                            pending_nodes.append(pid)

                    if policy == "all":
                        # Under 'all': Any pending node or single isolated replica proves incomplete finalization
                        if len(pending_nodes) > 0:
                            is_authoritative = False
                            rejection_reason = f"unanimous_finalization_unmet_pending_on_{pending_nodes}"
                        elif len(committed_nodes) <= 1 and len(snapshot_peers) >= 1:
                            is_authoritative = False
                            rejection_reason = "single_replica_status_insufficient_for_authority"
                        elif len(committed_nodes) > 1 and len(pending_nodes) == 0:
                            is_authoritative = True
                        else:
                            is_authoritative = False
                            rejection_reason = "insufficient_replica_commit_proof"
                    else:
                        # Under 'majority'
                        total_nodes = len(self._config.all_node_ids)
                        quorum = (total_nodes // 2) + 1
                        if len(pending_nodes) > 0 or len(committed_nodes) < quorum:
                            is_authoritative = False
                            rejection_reason = f"majority_commit_quorum_unmet: committed={committed_nodes}, pending={pending_nodes}"
                        else:
                            is_authoritative = True

                if not is_authoritative:
                    # Reject partial finalization / ghost vote
                    rejected_partial_finalizations_count += 1
                    log_event(
                        self._logger,
                        "PARTIAL_FINALIZATION_REJECTED",
                        lamport_ts=self._clock.value,
                        vote_id=vid,
                        client_id=sample.client_id,
                        origin_node_id=origin_node_id,
                        reason=rejection_reason,
                    )
                    self._db.append_sync_log(
                        entry_type="PARTIAL_FINALIZATION_REJECTED",
                        lamport_ts=self._clock.value,
                        vote_id=vid,
                        client_id=sample.client_id,
                        origin_node_id=origin_node_id,
                        status="REJECTED",
                        details={"reason": rejection_reason},
                    )
                    # If locally COMMITTED, demote to PENDING to prevent phantom tally
                    if local_rec and local_rec.status == VoteStatus.COMMITTED.value:
                        self._db.demote_vote(vid, new_status=VoteStatus.PENDING.value, reason=rejection_reason)
                else:
                    # Authoritative vote! Check for conflicting client-ID
                    client_id = sample.client_id
                    existing_client_vote = self._db.get_vote_by_client_id(client_id)
                    if (
                        existing_client_vote
                        and existing_client_vote.status == VoteStatus.COMMITTED.value
                        and existing_client_vote.choice != sample.choice
                    ):
                        # Do not overwrite already committed choice
                        client_id_conflicts_count += 1
                        log_event(
                            self._logger,
                            "CLIENT_ID_CONFLICT",
                            lamport_ts=self._clock.value,
                            vote_id=vid,
                            client_id=client_id,
                            choice=sample.choice,
                            existing_choice=existing_client_vote.choice,
                            reason="already_committed_choice_preserved",
                        )
                        self._db.append_sync_log(
                            entry_type="CLIENT_ID_CONFLICT",
                            lamport_ts=self._clock.value,
                            vote_id=vid,
                            client_id=client_id,
                            status="REJECTED",
                            details={
                                "existing_choice": existing_client_vote.choice,
                                "candidate_choice": sample.choice,
                            },
                        )
                    else:
                        authoritative_votes[vid] = sample
                        accepted_votes_count += 1
                        log_event(
                            self._logger,
                            "AUTHORITATIVE_VOTE_ACCEPTED",
                            lamport_ts=self._clock.value,
                            vote_id=vid,
                            client_id=client_id,
                            choice=sample.choice,
                        )

            # ── 4. Apply authoritative votes locally ─────────────────
            sorted_authoritative = sorted(authoritative_votes.values(), key=lambda v: v.merge_key)
            votes_synced_count = 0
            for vote in sorted_authoritative:
                vote.status = VoteStatus.COMMITTED.value
                res = self._db.insert_synced_vote(vote)
                if res == InsertResult.INSERTED:
                    votes_synced_count += 1
                    self._clock.receive(vote.lamport_ts)

            # ── 5. Push and verify repair calls on contacted peers ────
            failed_repair_peers: set[int] = set()
            if self._replication_manager:
                for peer_id in contacted_peers:
                    peer_committed_ids = {
                        v.vote_id for v in peer_logs.get(peer_id, [])
                        if v.status == VoteStatus.COMMITTED.value
                    }
                    missing_on_peer = [v for v in sorted_authoritative if v.vote_id not in peer_committed_ids]
                    for mv in missing_on_peer:
                        try:
                            repl_ok, _ = self._replication_manager.replicate_vote(
                                mv, target_peer_ids=[peer_id], timeout=timeout
                            )
                            fin_ok, _ = self._replication_manager.finalize_vote(
                                mv.vote_id, target_peer_ids=[peer_id], timeout=timeout
                            )
                            if not (repl_ok and fin_ok):
                                failed_repair_peers.add(peer_id)
                                self._logger.warning("Repair of vote %s to peer %d failed", mv.vote_id, peer_id)
                                break
                        except Exception as exc:
                            failed_repair_peers.add(peer_id)
                            self._logger.warning("Exception repairing vote %s to peer %d: %s", mv.vote_id, peer_id, exc)
                            break

            # ── 6. Policy Evaluation & Promotion Guard ───────────────
            successful_peers = [
                pid for pid in snapshot_peers
                if pid in contacted_peers and pid not in failed_repair_peers
            ]
            all_failed_peers = sorted(list(set(failed_peers) | failed_repair_peers))

            if policy == "all":
                policy_ok = (len(all_failed_peers) == 0)
            elif policy == "majority":
                total_nodes = len(self._config.all_node_ids)
                quorum = (total_nodes // 2) + 1
                total_participants = 1 + len(successful_peers)
                policy_ok = (total_participants >= quorum)
            else:
                policy_ok = (len(all_failed_peers) == 0)

            duration_ms = round((time.monotonic() - start_time) * 1000, 2)

            if not policy_ok:
                # MUST remain in RECOVERING; do not promote; do not emit RECOVERY_COMPLETED
                self._state._role = NodeRole.RECOVERING
                log_event(
                    self._logger,
                    "RECOVERY_FAILED",
                    lamport_ts=self._clock.tick(),
                    node_id=self._node_id,
                    failed_peers=all_failed_peers,
                    policy=policy,
                    reason=f"Recovery policy '{policy}' not satisfied with failed peers {all_failed_peers}",
                    duration_ms=duration_ms,
                )
                self._db.append_sync_log(
                    entry_type="RECOVERY_FAILED",
                    lamport_ts=self._clock.value,
                    origin_node_id=self._node_id,
                    details={
                        "failed_peers": all_failed_peers,
                        "policy": policy,
                        "snapshot_peers": list(snapshot_peers),
                    },
                )
                summary = RecoverySummary(
                    success=False,
                    replayed_entries_count=len(sorted_authoritative),
                    committed_votes_count=self._db.count_votes(status=VoteStatus.COMMITTED.value),
                    max_lamport_ts=self._clock.value,
                    votes_synced_count=votes_synced_count,
                    accepted_votes_count=accepted_votes_count,
                    rejected_partial_finalizations_count=rejected_partial_finalizations_count,
                    client_id_conflicts_count=client_id_conflicts_count,
                    peers_contacted=contacted_peers,
                    duration_ms=duration_ms,
                    error=f"Recovery policy '{policy}' failed: uncontacted or failed peers {all_failed_peers}",
                )
                self.last_recovery_summary = summary
                return summary

            # Policy satisfied & authority confirmed: promote to COORDINATOR
            self._state.become_coordinator(term, init_id)
            if self._lifecycle:
                self._lifecycle.apply_role()

            total_committed = self._db.count_votes(status=VoteStatus.COMMITTED.value)

            log_event(
                self._logger,
                "RECOVERY_COMPLETED",
                lamport_ts=self._clock.tick(),
                node_id=self._node_id,
                election_term=term,
                initiator_id=init_id,
                votes_synced=votes_synced_count,
                total_committed=total_committed,
                accepted_votes=accepted_votes_count,
                rejected_partial_finalizations=rejected_partial_finalizations_count,
                client_id_conflicts=client_id_conflicts_count,
                peers_contacted=contacted_peers,
                duration_ms=duration_ms,
            )

            self._db.append_sync_log(
                entry_type="RECOVERY_COMPLETED",
                lamport_ts=self._clock.value,
                origin_node_id=self._node_id,
                details={
                    "election_term": term,
                    "initiator_id": init_id,
                    "votes_synced": votes_synced_count,
                    "total_committed": total_committed,
                    "accepted_votes": accepted_votes_count,
                    "rejected_partial_finalizations": rejected_partial_finalizations_count,
                    "client_id_conflicts": client_id_conflicts_count,
                },
            )

            summary = RecoverySummary(
                success=True,
                replayed_entries_count=len(sorted_authoritative),
                committed_votes_count=total_committed,
                max_lamport_ts=self._clock.value,
                votes_synced_count=votes_synced_count,
                accepted_votes_count=accepted_votes_count,
                rejected_partial_finalizations_count=rejected_partial_finalizations_count,
                client_id_conflicts_count=client_id_conflicts_count,
                peers_contacted=contacted_peers,
                duration_ms=duration_ms,
            )
            self.last_recovery_summary = summary
            return summary

    # ── Follower / Lagging Node Catch-Up ─────────────────────────

    def sync_with_cluster(
        self,
        coordinator_id: Optional[int] = None,
        timeout: float = 2.0,
    ) -> RecoverySummary:
        """Catch up this node's state with the cluster coordinator or peers."""
        start_time = time.monotonic()
        target_coord = coordinator_id if coordinator_id is not None else self._state.coordinator_id

        # Target coordinator if known and active, otherwise all active peers
        if target_coord and target_coord != self._node_id and target_coord in self._peer_clients:
            targets = [target_coord]
        else:
            targets = sorted(self._state.active_peers)

        total_synced = 0
        contacted = []
        for pid in targets:
            if pid == self._node_id or pid not in self._peer_clients:
                continue
            ingested = self.sync_from_peer(pid, timeout=timeout)
            contacted.append(pid)
            total_synced += len(ingested)

        total_committed = self._db.count_votes(status=VoteStatus.COMMITTED.value)
        duration_ms = round((time.monotonic() - start_time) * 1000, 2)

        log_event(
            self._logger,
            "FOLLOWER_SYNC_COMPLETED",
            lamport_ts=self._clock.tick(),
            node_id=self._node_id,
            votes_synced=total_synced,
            total_committed=total_committed,
            peers_contacted=contacted,
            duration_ms=duration_ms,
        )

        summary = RecoverySummary(
            success=True,
            replayed_entries_count=total_committed,
            committed_votes_count=total_committed,
            max_lamport_ts=self._clock.value,
            votes_synced_count=total_synced,
            peers_contacted=contacted,
            duration_ms=duration_ms,
        )
        self.last_recovery_summary = summary
        return summary

    def get_recovery_status(self) -> dict:
        """Return a structured dictionary describing the current recovery state and last metrics."""
        summary_dict = None
        if self.last_recovery_summary:
            s = self.last_recovery_summary
            summary_dict = {
                "success": s.success,
                "replayed_entries_count": s.replayed_entries_count,
                "committed_votes_count": s.committed_votes_count,
                "max_lamport_ts": s.max_lamport_ts,
                "votes_synced_count": s.votes_synced_count,
                "accepted_votes_count": s.accepted_votes_count,
                "rejected_partial_finalizations_count": s.rejected_partial_finalizations_count,
                "client_id_conflicts_count": s.client_id_conflicts_count,
                "peers_contacted": s.peers_contacted or [],
                "duration_ms": s.duration_ms,
                "error": s.error,
            }
        return {
            "node_id": self._node_id,
            "role": self._state.role.value,
            "is_recovering": self._state.role == NodeRole.RECOVERING,
            "is_coordinator": self._state.is_coordinator(),
            "election_term": self._state.election_term,
            "initiator_id": self._state.initiator_id,
            "replication_policy": self._config.replication_policy,
            "last_recovery": summary_dict,
        }
