"""Flask Blueprint routes for the Distributed Voting System REST bridge.

This module acts exclusively as an adapter layer over the existing NodeRuntime.
All distributed consensus, election, replication, and recovery logic remain
in the underlying backend services.
"""

import logging
from typing import Optional
from flask import Blueprint, current_app, jsonify, request

from api.errors import make_error_response
from api.schemas import validate_vote_payload
from node.models import NodeRole

logger = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api")


def get_runtime():
    """Retrieve the injected NodeRuntime instance from the current Flask app context."""
    runtime = current_app.config.get("RUNTIME")
    if runtime is None:
        raise RuntimeError("NodeRuntime is not configured in Flask app")
    return runtime


# ── STEP 3: Health API ──────────────────────────────────────────

@bp.route("/health", methods=["GET"])
def health():
    """Basic node health check."""
    runtime = get_runtime()
    return jsonify({
        "status": "ok",
        "node_id": runtime.config.node_id,
    }), 200


# ── STEP 4: Node / Cluster Status API ───────────────────────────

@bp.route("/node", methods=["GET"])
def get_node():
    """Expose this node's runtime state and cluster coordination metadata."""
    runtime = get_runtime()
    role_val = runtime.state.role.value
    return jsonify({
        "node_id": runtime.config.node_id,
        "role": role_val,
        "state": role_val.upper(),
        "coordinator_id": runtime.state.coordinator_id,
        "election_term": runtime.state.election_term,
        "initiator_id": runtime.state.initiator_id,
        "is_coordinator": runtime.state.is_coordinator(),
        "accepting_votes": runtime.state.is_accepting_votes(),
        "active_peers": sorted(list(runtime.state.active_peers)),
        "election_algorithm": runtime.config.election_algorithm,
        "replication_policy": runtime.config.replication_policy,
        "candidates": runtime.config.candidates,
        "address": runtime.address,
    }), 200


@bp.route("/nodes", methods=["GET"])
def get_nodes():
    """Expose cluster-wide topology and peer status."""
    runtime = get_runtime()
    all_node_ids = sorted(runtime.config.all_node_ids)
    coordinator_id = runtime.state.coordinator_id
    active_peers = runtime.state.active_peers

    nodes_info = []
    for nid in all_node_ids:
        is_self = (nid == runtime.config.node_id)
        if is_self:
            role = runtime.state.role.value
            is_active = True
            addr = runtime.address
        else:
            role = "coordinator" if nid == coordinator_id else "follower"
            is_active = (nid in active_peers)
            peer_cfg = runtime.config.peers.get(nid)
            addr = peer_cfg.address if hasattr(peer_cfg, "address") else str(peer_cfg or "")

        nodes_info.append({
            "node_id": nid,
            "role": role,
            "is_self": is_self,
            "is_active": is_active,
            "is_coordinator": (nid == coordinator_id),
            "address": addr,
        })

    return jsonify({
        "success": True,
        "nodes": nodes_info,
        "total_nodes": len(nodes_info),
        "current_coordinator_id": coordinator_id,
    }), 200


@bp.route("/nodes/<int:node_id>", methods=["GET"])
def get_single_node(node_id: int):
    """Expose status of a specific cluster node."""
    runtime = get_runtime()
    if node_id not in runtime.config.all_node_ids:
        return make_error_response("node_not_found", f"Node {node_id} is not part of this cluster configuration", 404)

    is_self = (node_id == runtime.config.node_id)
    coordinator_id = runtime.state.coordinator_id
    active_peers = runtime.state.active_peers

    if is_self:
        node_data = {
            "node_id": node_id,
            "role": runtime.state.role.value,
            "state": runtime.state.role.value.upper(),
            "is_self": True,
            "is_active": True,
            "is_coordinator": runtime.state.is_coordinator(),
            "accepting_votes": runtime.state.is_accepting_votes(),
            "coordinator_id": coordinator_id,
            "election_term": runtime.state.election_term,
            "initiator_id": runtime.state.initiator_id,
            "active_peers": sorted(list(active_peers)),
            "address": runtime.address,
        }
    else:
        peer_cfg = runtime.config.peers.get(node_id)
        addr = peer_cfg.address if hasattr(peer_cfg, "address") else str(peer_cfg or "")
        node_data = {
            "node_id": node_id,
            "role": "coordinator" if node_id == coordinator_id else "follower",
            "state": "COORDINATOR" if node_id == coordinator_id else "FOLLOWER",
            "is_self": False,
            "is_active": (node_id in active_peers),
            "is_coordinator": (node_id == coordinator_id),
            "address": addr,
        }

    return jsonify({
        "success": True,
        "node": node_data,
    }), 200


# ── STEP 5: Voting API ──────────────────────────────────────────

@bp.route("/votes", methods=["POST"])
def submit_vote():
    """Submit a vote via the coordinator node."""
    runtime = get_runtime()

    if not request.is_json:
        return make_error_response("invalid_json", "Request content-type must be application/json", 400)

    data = request.get_json(silent=True)
    if data is None:
        return make_error_response("invalid_json", "Malformed JSON payload", 400)

    is_valid, err_code, err_msg, parsed = validate_vote_payload(data)
    if not is_valid:
        return make_error_response(err_code or "invalid_request", err_msg or "Invalid vote payload", 400)

    client_id, choice = parsed

    # Delegate strictly to existing backend vote_service
    res = runtime.vote_service.submit_vote(client_id=client_id, choice=choice)

    if res.get("success"):
        return jsonify({
            "success": True,
            "vote_id": res.get("vote_id", ""),
            "client_id": client_id,
            "choice": choice,
            "lamport_ts": res.get("lamport_ts", 0),
            "node_id": runtime.config.node_id,
        }), 201

    # Map backend errors to clean HTTP responses
    raw_error = res.get("error", "Unknown vote rejection")
    vote_id = res.get("vote_id", "")

    if raw_error.startswith("not_coordinator"):
        coord_id_str = raw_error.split(":")[-1] if ":" in raw_error else ""
        coord_id = int(coord_id_str) if coord_id_str.isdigit() else runtime.state.coordinator_id
        return make_error_response(
            "not_coordinator",
            "Node is not currently accepting votes (not coordinator or recovering)",
            409,
            coordinator_id=coord_id,
            role=runtime.state.role.value,
        )

    if "already voted" in raw_error:
        return make_error_response("duplicate_client", raw_error, 409, client_id=client_id)

    if "pending" in raw_error:
        return make_error_response("pending_conflict", raw_error, 409, client_id=client_id)

    if "invalid choice" in raw_error:
        return make_error_response("invalid_choice", raw_error, 400, valid_candidates=runtime.config.candidates)

    if "client_id" in raw_error:
        return make_error_response("invalid_client_id", raw_error, 400)

    if "replication failed" in raw_error or "finalization failed" in raw_error:
        return make_error_response(
            "replication_failed",
            raw_error,
            503,
            vote_id=vote_id,
        )

    return make_error_response("vote_rejected", raw_error, 400, vote_id=vote_id)


# ── STEP 6: Tally / Results API ─────────────────────────────────

@bp.route("/votes/tally", methods=["GET"])
def get_tally():
    """Retrieve committed vote tally. Strictly excludes pending records."""
    runtime = get_runtime()
    tally = runtime.db.get_tally()
    total_committed = runtime.db.count_votes(status="COMMITTED")

    return jsonify({
        "success": True,
        "tally": tally,
        "total_votes": total_committed,
        "node_id": runtime.config.node_id,
        "is_coordinator": runtime.state.is_coordinator(),
    }), 200


# ── STEP 7: Individual Vote Information ─────────────────────────

@bp.route("/votes/<vote_id>", methods=["GET"])
def get_vote(vote_id: str):
    """Retrieve individual vote details from the database."""
    runtime = get_runtime()
    record = runtime.db.get_vote_by_id(vote_id)
    if record is None:
        return make_error_response("vote_not_found", f"Vote '{vote_id}' not found", 404)

    return jsonify({
        "success": True,
        "vote": {
            "vote_id": record.vote_id,
            "client_id": record.client_id,
            "choice": record.choice,
            "status": record.status,
            "origin_node_id": record.origin_node_id,
            "lamport_ts": record.lamport_ts,
            "received_at_ms": record.received_at_ms,
            "commit_proof": record.commit_proof,
        },
    }), 200


# ── STEP 8: Election API ────────────────────────────────────────

@bp.route("/election/status", methods=["GET"])
def get_election_status():
    """Retrieve current coordinator, term, algorithm, and election metrics."""
    runtime = get_runtime()
    in_progress = getattr(runtime.election_strategy, "_election_in_progress", False)
    metrics = runtime.election_strategy.get_last_election_metrics()
    counts = runtime.election_strategy.get_message_counts()

    return jsonify({
        "success": True,
        "algorithm": runtime.config.election_algorithm,
        "current_coordinator": runtime.state.coordinator_id,
        "is_coordinator": runtime.state.is_coordinator(),
        "election_term": runtime.state.election_term,
        "initiator_id": runtime.state.initiator_id,
        "role": runtime.state.role.value,
        "election_in_progress": in_progress,
        "last_election_metrics": metrics,
        "message_counts": counts,
    }), 200


@bp.route("/election/start", methods=["POST"])
def start_election():
    """Trigger coordinator election using the configured election algorithm."""
    runtime = get_runtime()

    body = request.get_json(silent=True) or {}
    blocking = bool(body.get("blocking", False))

    if getattr(runtime.election_strategy, "_election_in_progress", False):
        return make_error_response("election_in_progress", "An election is already in progress", 409)

    try:
        won = runtime.election_strategy.start_election(blocking=blocking)
    except Exception as e:
        logger.exception("Failed to start election: %s", e)
        return make_error_response("election_failed", f"Failed to execute election: {e}", 500)

    result_status = "won" if runtime.state.is_coordinator() else ("in_progress" if not blocking else "lost")

    return jsonify({
        "success": True,
        "algorithm": runtime.config.election_algorithm,
        "election_term": runtime.state.election_term,
        "initiator_id": runtime.state.initiator_id,
        "role": runtime.state.role.value,
        "coordinator_id": runtime.state.coordinator_id,
        "result": result_status,
        "won": won if blocking else None,
    }), 200


# ── STEP 9: Recovery API ────────────────────────────────────────

@bp.route("/recovery/status", methods=["GET"])
def get_recovery_status():
    """Expose recovery state, policy, and Phase 4 audit metrics."""
    runtime = get_runtime()
    status_data = runtime.recovery_manager.get_recovery_status()
    status_data["success"] = True
    return jsonify(status_data), 200


@bp.route("/recovery/start", methods=["POST"])
def start_recovery():
    """Trigger coordinator state recovery and follower catch-up synchronization."""
    runtime = get_runtime()

    body = request.get_json(silent=True) or {}
    election_term = body.get("election_term")
    initiator_id = body.get("initiator_id")
    timeout = float(body.get("timeout", 2.0))
    target_peer_ids = body.get("target_peer_ids")

    try:
        if runtime.state.is_coordinator() or runtime.state.role.value == "recovering":
            summary = runtime.recover_coordinator(
                election_term=election_term,
                initiator_id=initiator_id,
                timeout=timeout,
                target_peer_ids=target_peer_ids,
            )
        else:
            summary = runtime.sync_with_cluster(
                timeout=timeout,
            )
    except Exception as e:
        logger.exception("Unexpected error during recovery: %s", e)
        return make_error_response("recovery_failed", f"Recovery error: {e}", 500)

    resp_data = {
        "success": summary.success,
        "role": runtime.state.role.value,
        "is_coordinator": runtime.state.is_coordinator(),
        "replayed_entries_count": summary.replayed_entries_count,
        "committed_votes_count": summary.committed_votes_count,
        "votes_synced_count": summary.votes_synced_count,
        "accepted_votes_count": summary.accepted_votes_count,
        "rejected_partial_finalizations_count": summary.rejected_partial_finalizations_count,
        "client_id_conflicts_count": summary.client_id_conflicts_count,
        "peers_contacted": summary.peers_contacted or [],
        "duration_ms": summary.duration_ms,
        "error": summary.error,
    }

    if not summary.success:
        return jsonify(resp_data), 409

    return jsonify(resp_data), 200


# ── STEP 10: Observability API ──────────────────────────────────

@bp.route("/events", methods=["GET"])
def get_events():
    """Retrieve audit and observability events (election and sync log)."""
    runtime = get_runtime()

    event_type = request.args.get("type")
    source = request.args.get("source", "all").lower()
    limit_str = request.args.get("limit", "100")
    try:
        limit = max(1, min(int(limit_str), 500))
    except ValueError:
        limit = 100

    combined_events = []

    if source in ("all", "election"):
        election_events = runtime.db.get_election_events(event_type=event_type)
        for e in election_events:
            combined_events.append({
                "source": "election",
                "id": f"el_{e['id']}",
                "event_type": e["event_type"],
                "node_id": e["node_id"],
                "lamport_ts": e["lamport_ts"],
                "election_term": e["election_term"],
                "initiator_id": e["initiator_id"],
                "details": e["details"],
                "timestamp_ms": e["logged_at_ms"],
            })

    if source in ("all", "sync"):
        sync_entries = runtime.db.get_sync_log(entry_type=event_type, limit=limit)
        for s in sync_entries:
            combined_events.append({
                "source": "sync",
                "id": f"sync_{s.entry_id}",
                "event_type": s.entry_type,
                "node_id": s.origin_node_id or runtime.config.node_id,
                "lamport_ts": s.lamport_ts,
                "vote_id": s.vote_id,
                "client_id": s.client_id,
                "choice": s.choice,
                "status": s.status,
                "details": s.details,
                "timestamp_ms": s.created_at_ms,
            })

    # Sort combined events by timestamp_ms descending (latest first)
    combined_events.sort(key=lambda x: x["timestamp_ms"], reverse=True)
    combined_events = combined_events[:limit]

    return jsonify({
        "success": True,
        "events": combined_events,
        "count": len(combined_events),
    }), 200
