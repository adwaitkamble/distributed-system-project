"""Vote acceptance, validation, and receipt generation.

Phase 1: single-node only — no replication fan-out.
Phase 2 will add replication-before-ack.
"""

import logging
import time
from typing import Optional

from node.config import NodeConfig
from node.coordinator import CoordinatorState
from node.db import DatabaseManager
from node.lamport import LamportClock
from node.logging_config import log_event
from node.models import InsertResult, VoteRecord, VoteStatus


class VoteService:
    """Handles vote submission on the coordinator node."""

    def __init__(
        self,
        db: DatabaseManager,
        clock: LamportClock,
        state: CoordinatorState,
        config: NodeConfig,
        replication_manager=None,
        logger: Optional[logging.Logger] = None,
    ) -> None:
        self._db = db
        self._clock = clock
        self._state = state
        self._config = config
        self._replication_manager = replication_manager
        self._logger = logger or logging.getLogger(f"node.{config.node_id}")

    def submit_vote(self, client_id: str, choice: str) -> dict:
        """Accept a vote on the coordinator.

        Returns a dict with keys:
            success (bool), vote_id (str), error (str), lamport_ts (int)

        Architectural rule 8: if the vote is not acknowledged, it is
        unavailable/retryable — never counted as accepted.
        """
        # ── Guard: must be coordinator and accepting votes ────────
        if not self._state.is_accepting_votes():
            coordinator_id = self._state.coordinator_id
            return {
                "success": False,
                "vote_id": "",
                "error": f"not_coordinator:{coordinator_id}",
                "lamport_ts": self._clock.value,
            }

        # ── Validate and normalize client_id ─────────────────────
        if not client_id or not client_id.strip():
            return {
                "success": False,
                "vote_id": "",
                "error": "client_id must be non-empty",
                "lamport_ts": self._clock.value,
            }

        client_id = client_id.strip()

        # Preserve receipt format: client:origin_node:lamport
        if ":" in client_id:
            return {
                "success": False,
                "vote_id": "",
                "error": "client_id must not contain ':'",
                "lamport_ts": self._clock.value,
            }

        # ── Validate choice ──────────────────────────────────────
        if choice not in self._config.candidates:
            return {
                "success": False,
                "vote_id": "",
                "error": f"invalid choice '{choice}'; must be one of {self._config.candidates}",
                "lamport_ts": self._clock.value,
            }

        # ── Check existing vote for this client ───────────────────
        existing = self._db.get_vote_by_client_id(client_id)
        if existing is not None:
            if existing.status == VoteStatus.COMMITTED.value:
                log_event(
                    self._logger, "VOTE_REJECTED",
                    lamport_ts=self._clock.value, correlation_id=existing.vote_id,
                    client_id=client_id, reason="client_already_voted",
                )
                return {
                    "success": False,
                    "vote_id": "",
                    "error": f"client '{client_id}' has already voted",
                    "lamport_ts": self._clock.value,
                }
            if existing.status == VoteStatus.PENDING.value:
                if existing.choice != choice:
                    log_event(
                        self._logger, "VOTE_REJECTED",
                        lamport_ts=self._clock.value, correlation_id=existing.vote_id,
                        client_id=client_id, reason="pending_conflict",
                    )
                    return {
                        "success": False,
                        "vote_id": "",
                        "error": f"client '{client_id}' has a pending vote with a different choice",
                        "lamport_ts": self._clock.value,
                    }
                # Resume/finalize the existing pending vote!
                vote = existing
        else:
            # ── Generate vote_id (receipt) & insert PENDING vote ──────
            ts = self._clock.tick()  # local event: increment
            vote_id = VoteRecord.make_vote_id(client_id, self._config.node_id, ts)
            now_ms = int(time.time() * 1000)

            vote = VoteRecord(
                vote_id=vote_id,
                client_id=client_id,
                origin_node_id=self._config.node_id,
                lamport_ts=ts,
                choice=choice,
                received_at_ms=now_ms,
                status=VoteStatus.PENDING.value,
            )

            result = self._db.insert_vote(vote)
            if result == InsertResult.VOTE_ID_CONFLICT:
                log_event(
                    self._logger, "VOTE_REJECTED",
                    lamport_ts=ts, correlation_id=vote_id,
                    client_id=client_id, reason="vote_id_conflict",
                    level=logging.ERROR,
                )
                return {
                    "success": False,
                    "vote_id": "",
                    "error": "internal error: vote_id conflict",
                    "lamport_ts": ts,
                }

        # ── Replicate pending vote to healthy peers ───────────────
        if self._replication_manager is not None:
            replicated, acks = self._replication_manager.replicate_vote(vote)
            if not replicated:
                # Do NOT delete partially replicated vote; leave as PENDING
                log_event(
                    self._logger, "VOTE_REJECTED",
                    lamport_ts=self._clock.value, correlation_id=vote.vote_id,
                    client_id=client_id, reason="replication_failed",
                    replication_acks=acks,
                    level=logging.WARNING,
                )
                return {
                    "success": False,
                    "vote_id": vote.vote_id,
                    "error": "replication failed (quorum not reached)",
                    "lamport_ts": self._clock.value,
                }

            # Send FinalizeVote to all peers that acknowledged the pending vote
            finalized, finalize_acks = self._replication_manager.finalize_vote(vote.vote_id, acks)
            if not finalized:
                log_event(
                    self._logger, "VOTE_REJECTED",
                    lamport_ts=self._clock.value, correlation_id=vote.vote_id,
                    client_id=client_id, reason="finalization_failed",
                    finalize_acks=finalize_acks,
                    level=logging.WARNING,
                )
                return {
                    "success": False,
                    "vote_id": vote.vote_id,
                    "error": "finalization failed",
                    "lamport_ts": self._clock.value,
                }

            # Local finalization ONLY after required remote finalization succeeds!
            self._db.finalize_vote(vote.vote_id)

            log_event(
                self._logger, "VOTE_ACCEPTED",
                lamport_ts=vote.lamport_ts, correlation_id=vote.vote_id,
                client_id=client_id, choice=choice,
                replication_acks=acks,
                finalize_acks=finalize_acks,
            )
            return {
                "success": True,
                "vote_id": vote.vote_id,
                "error": "",
                "lamport_ts": vote.lamport_ts,
            }

        # Fallback for standalone single-node tests without replication
        self._db.finalize_vote(vote.vote_id)
        log_event(
            self._logger, "VOTE_ACCEPTED",
            lamport_ts=vote.lamport_ts, correlation_id=vote.vote_id,
            client_id=client_id, choice=choice,
        )
        return {
            "success": True,
            "vote_id": vote.vote_id,
            "error": "",
            "lamport_ts": vote.lamport_ts,
        }
