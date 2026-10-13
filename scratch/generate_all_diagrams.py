"""Generate high-resolution publication-quality PNG diagrams for the Distributed Voting System."""

import os
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib.path import Path

OUTPUT_DIR = os.path.join("submission_package", "diagrams")
os.makedirs(OUTPUT_DIR, exist_ok=True)

plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Arial", "Helvetica"]

# ─────────────────────────────────────────────────────────────────────────────
# 1. OVERALL SYSTEM ARCHITECTURE DIAGRAM
# ─────────────────────────────────────────────────────────────────────────────
def draw_architecture_diagram():
    fig, ax = plt.subplots(figsize=(14, 9), dpi=300)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9)
    ax.axis("off")

    # Title
    ax.text(7, 8.6, "Distributed Fault-Tolerant Voting System — System Architecture", 
            fontsize=16, weight="bold", ha="center", va="center", color="#0f172a")

    # Client Layer Box
    client_box = patches.FancyBboxPatch((2, 7.3), 10, 0.9, boxstyle="round,pad=0.1,rounding_size=0.15", 
                                        ec="#2563eb", fc="#eff6ff", lw=2)
    ax.add_patch(client_box)
    ax.text(7, 7.75, "Client Layer: Web Browser / React 18 Single-Page Application (Vite + Tailwind)", 
            fontsize=12, weight="bold", ha="center", va="center", color="#1e40af")

    # Network Boundary Box
    net_box = patches.FancyBboxPatch((0.5, 0.4), 13, 6.4, boxstyle="round,pad=0.2,rounding_size=0.2", 
                                     ec="#94a3b8", fc="#f8fafc", lw=1.5, ls="--")
    ax.add_patch(net_box)
    ax.text(1.8, 6.6, "Docker Bridge Network (voting-net)", fontsize=10, weight="bold", color="#64748b")

    # Node containers (Node 1, Node 2, Node 3 Coordinator)
    nodes = [
        {"id": 1, "name": "Node 1 (Follower)", "x": 1.0, "port": "5001", "role": "FOLLOWER", "bg": "#f1f5f9", "ec": "#64748b"},
        {"id": 2, "name": "Node 2 (Follower)", "x": 5.2, "port": "5002", "role": "FOLLOWER", "bg": "#f1f5f9", "ec": "#64748b"},
        {"id": 3, "name": "Node 3 (Coordinator)", "x": 9.4, "port": "5003", "role": "COORDINATOR", "bg": "#fef3c7", "ec": "#d97706"},
    ]

    for n in nodes:
        nx = n["x"]
        # App Container Box
        app_box = patches.FancyBboxPatch((nx, 1.8), 3.6, 4.5, boxstyle="round,pad=0.1,rounding_size=0.15", 
                                         ec=n["ec"], fc=n["bg"], lw=2)
        ax.add_patch(app_box)
        ax.text(nx + 1.8, 6.0, n["name"], fontsize=11, weight="bold", ha="center", color="#0f172a")

        # Internal Modules: Flask REST Bridge
        flask_box = patches.FancyBboxPatch((nx + 0.3, 4.8), 3.0, 0.8, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                           ec="#0284c7", fc="#e0f2fe", lw=1.5)
        ax.add_patch(flask_box)
        ax.text(nx + 1.5, 5.2, f"Flask REST Bridge\n(Port :{n['port']})", fontsize=9, weight="bold", ha="center", va="center", color="#0369a1")

        # NodeRuntime Engine
        rt_box = patches.FancyBboxPatch((nx + 0.3, 3.4), 3.0, 1.1, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                        ec="#7c3aed", fc="#f3e8ff", lw=1.5)
        ax.add_patch(rt_box)
        ax.text(nx + 1.5, 3.95, "NodeRuntime State Machine\nBully / Ring Election | Lamport Clocks\nHeartbeat Monitor | Quorum Replication", 
                fontsize=7.5, weight="bold", ha="center", va="center", color="#6d28d9")

        # gRPC Server
        grpc_box = patches.FancyBboxPatch((nx + 0.3, 2.2), 3.0, 0.8, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                          ec="#059669", fc="#d1fae5", lw=1.5)
        ax.add_patch(grpc_box)
        ax.text(nx + 1.5, 2.6, "gRPC Server & Peer Client\n(Port :50051)", fontsize=9, weight="bold", ha="center", va="center", color="#047857")

        # Isolated MySQL Database Container
        db_box = patches.FancyBboxPatch((nx + 0.4, 0.6), 2.8, 0.9, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                        ec="#b45309", fc="#fef3c7", lw=1.5)
        ax.add_patch(db_box)
        ax.text(nx + 1.4, 1.05, f"Dedicated MySQL {n['id']} DB\nvoting-node{n['id']}-db (voting_node)\n[No Shared Storage]", 
                fontsize=8, weight="bold", ha="center", va="center", color="#92400e")

        # Internal App to DB connection
        ax.annotate("", xy=(nx + 1.4, 1.5), xytext=(nx + 1.4, 2.2),
                    arrowprops=dict(arrowstyle="<->", color="#b45309", lw=1.5))

    # Communication Arrows: Client to Flask
    for n in nodes:
        ax.annotate("", xy=(n["x"] + 1.8, 5.6), xytext=(n["x"] + 1.8, 7.3),
                    arrowprops=dict(arrowstyle="->", color="#2563eb", lw=1.5))
    ax.text(7, 6.85, "HTTP REST (GET /api/node, POST /api/votes, GET /api/votes/tally)", 
            fontsize=9, weight="bold", ha="center", color="#2563eb")

    # Coordinator Heartbeats & Replication (Node 3 -> Node 1, Node 2)
    ax.annotate("", xy=(4.6, 2.6), xytext=(9.4, 2.6),
                arrowprops=dict(arrowstyle="->", color="#059669", lw=2, ls="--"))
    ax.text(7.0, 2.85, "gRPC Heartbeats (500ms) & ReplicateVote Fan-out", fontsize=8.5, weight="bold", ha="center", color="#047857")

    ax.annotate("", xy=(8.8, 2.4), xytext=(4.6, 2.4),
                arrowprops=dict(arrowstyle="->", color="#6d28d9", lw=1.5, ls=":"))
    ax.text(6.7, 2.15, "gRPC SubmitVote Forwarding / Election Token Channel", fontsize=8, weight="bold", ha="center", color="#6d28d9")

    out_path = os.path.join(OUTPUT_DIR, "fig1_system_architecture.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print("Saved:", out_path)

# ─────────────────────────────────────────────────────────────────────────────
# 2. VOTE REPLICATION WORKFLOW SEQUENCE DIAGRAM
# ─────────────────────────────────────────────────────────────────────────────
def draw_vote_workflow_diagram():
    fig, ax = plt.subplots(figsize=(13, 8.5), dpi=300)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 9)
    ax.axis("off")

    ax.text(6.5, 8.6, "Vote Submission, Two-Phase Replication & Commitment Workflow", 
            fontsize=15, weight="bold", ha="center", va="center", color="#0f172a")

    # Lifelines
    actors = [
        {"name": "Voter (Client)", "x": 1.5, "color": "#2563eb"},
        {"name": "Flask Bridge\n(Follower N1)", "x": 4.0, "color": "#0284c7"},
        {"name": "Coordinator Node\n(Node 3 Runtime)", "x": 7.0, "color": "#d97706"},
        {"name": "Dedicated MySQL 3\n(Coordinator DB)", "x": 9.5, "color": "#b45309"},
        {"name": "Follower Replicas\n(Node 1 & Node 2)", "x": 11.8, "color": "#059669"},
    ]

    for a in actors:
        ax.plot([a["x"], a["x"]], [0.8, 7.8], color="#cbd5e1", lw=1.5, ls="--")
        box = patches.FancyBboxPatch((a["x"] - 1.0, 7.8), 2.0, 0.6, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                     ec=a["color"], fc="#f8fafc", lw=1.8)
        ax.add_patch(box)
        ax.text(a["x"], 8.1, a["name"], fontsize=9, weight="bold", ha="center", va="center", color=a["color"])

    # Step messages
    steps = [
        (1.5, 4.0, 7.2, "1. POST /api/votes {client_id, choice}", "#2563eb", "->"),
        (4.0, 7.0, 6.6, "2. gRPC SubmitVote (Forward to active Coordinator)", "#0284c7", "->"),
        (7.0, 9.5, 6.0, "3. Increment Lamport Clock & Stage 'PENDING' in DB", "#d97706", "->"),
        (7.0, 11.8, 5.3, "4. Concurrent gRPC ReplicateVote Fan-out", "#059669", "->"),
        (11.8, 7.0, 4.6, "5. Followers Stage 'PENDING' & return ACKs", "#059669", "<-"),
        (7.0, 7.0, 3.9, "6. Quorum Check: Majority Quorum Q = floor(N/2)+1 ACKs met!", "#d97706", "loop"),
        (7.0, 9.5, 3.2, "7. UPDATE status='COMMITTED' in Coordinator DB", "#b45309", "->"),
        (7.0, 11.8, 2.5, "8. Asynchronous / Piggybacked Commit Notification to Peers", "#059669", "--"),
        (7.0, 4.0, 1.8, "9. gRPC SubmitVoteResponse(success=True, receipt)", "#0284c7", "<-"),
        (4.0, 1.5, 1.2, "10. HTTP 201 Created {status: 'COMMITTED', vote_id: '...'}", "#2563eb", "<-"),
    ]

    for x1, x2, y, msg, color, arrow_type in steps:
        if arrow_type == "->":
            ax.annotate("", xy=(x2, y), xytext=(x1, y), arrowprops=dict(arrowstyle="->", color=color, lw=1.5))
            ax.text((x1 + x2) / 2, y + 0.15, msg, fontsize=8, weight="bold", ha="center", color=color)
        elif arrow_type == "<-":
            ax.annotate("", xy=(x2, y), xytext=(x1, y), arrowprops=dict(arrowstyle="->", color=color, lw=1.5))
            ax.text((x1 + x2) / 2, y + 0.15, msg, fontsize=8, weight="bold", ha="center", color=color)
        elif arrow_type == "--":
            ax.annotate("", xy=(x2, y), xytext=(x1, y), arrowprops=dict(arrowstyle="->", color=color, lw=1.2, ls="--"))
            ax.text((x1 + x2) / 2, y + 0.15, msg, fontsize=8, weight="bold", ha="center", color=color)
        elif arrow_type == "loop":
            loop_box = patches.FancyBboxPatch((x1 - 1.8, y - 0.25), 3.6, 0.45, boxstyle="round,pad=0.03,rounding_size=0.08", 
                                             ec="#d97706", fc="#fef3c7", lw=1.2)
            ax.add_patch(loop_box)
            ax.text(x1, y, msg, fontsize=7.8, weight="bold", ha="center", va="center", color="#92400e")

    out_path = os.path.join(OUTPUT_DIR, "fig2_vote_replication_workflow.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print("Saved:", out_path)

# ─────────────────────────────────────────────────────────────────────────────
# 3. LEADER ELECTION & FAILOVER SEQUENCE DIAGRAM
# ─────────────────────────────────────────────────────────────────────────────
def draw_election_failover_diagram():
    fig, ax = plt.subplots(figsize=(13, 8.5), dpi=300)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 9)
    ax.axis("off")

    ax.text(6.5, 8.6, "Leader Failure Detection & Bully / Ring Election Sequence", 
            fontsize=15, weight="bold", ha="center", va="center", color="#0f172a")

    actors = [
        {"name": "Coordinator (Node 3)\n[Initial Leader]", "x": 2.5, "color": "#d97706"},
        {"name": "Follower (Node 2)\n[Highest Surviving ID]", "x": 6.5, "color": "#7c3aed"},
        {"name": "Follower (Node 1)\n[Lower ID Peer]", "x": 10.5, "color": "#0284c7"},
    ]

    for a in actors:
        ax.plot([a["x"], a["x"]], [0.8, 7.8], color="#cbd5e1", lw=1.5, ls="--")
        box = patches.FancyBboxPatch((a["x"] - 1.2, 7.8), 2.4, 0.6, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                     ec=a["color"], fc="#f8fafc", lw=1.8)
        ax.add_patch(box)
        ax.text(a["x"], 8.1, a["name"], fontsize=9, weight="bold", ha="center", va="center", color=a["color"])

    # Normal heartbeats
    ax.annotate("", xy=(6.5, 7.2), xytext=(2.5, 7.2), arrowprops=dict(arrowstyle="->", color="#059669", lw=1.5))
    ax.annotate("", xy=(10.5, 7.2), xytext=(2.5, 7.2), arrowprops=dict(arrowstyle="->", color="#059669", lw=1.5))
    ax.text(6.5, 7.4, "Periodic Heartbeat broadcasts (500ms)", fontsize=8.5, weight="bold", ha="center", color="#059669")

    # Crash Box
    crash_box = patches.FancyBboxPatch((1.5, 6.3), 2.0, 0.6, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                       ec="#dc2626", fc="#fee2e2", lw=2)
    ax.add_patch(crash_box)
    ax.text(2.5, 6.6, "[CRASH] Coordinator Fails!\n(docker stop voting-node3)", fontsize=8, weight="bold", ha="center", va="center", color="#b91c1c")

    # Failure detection
    det_box = patches.FancyBboxPatch((4.5, 5.3), 7.0, 0.7, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                     ec="#ea580c", fc="#fff7ed", lw=1.5)
    ax.add_patch(det_box)
    ax.text(8.0, 5.65, "Monotonic Timer Latch Trips: now() - last_hb >= 3000ms\nTimeout latch fires exactly ONCE (preventing election storm)", 
            fontsize=8, weight="bold", ha="center", va="center", color="#c2410c")

    # Election Probes
    ax.annotate("", xy=(6.5, 4.4), xytext=(10.5, 4.4), arrowprops=dict(arrowstyle="->", color="#0284c7", lw=1.5))
    ax.text(8.5, 4.6, "Node 1 sends Election probe to higher Node 2", fontsize=8, weight="bold", ha="center", color="#0284c7")

    ax.annotate("", xy=(10.5, 3.8), xytext=(6.5, 3.8), arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=1.5))
    ax.text(8.5, 4.0, "Node 2 answers with OK (Suppresses lower Node 1)", fontsize=8, weight="bold", ha="center", color="#7c3aed")

    # Node 2 Victory
    vic_box = patches.FancyBboxPatch((5.0, 2.7), 3.0, 0.7, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                     ec="#7c3aed", fc="#f3e8ff", lw=1.8)
    ax.add_patch(vic_box)
    ax.text(6.5, 3.05, "Node 2 finds no higher peers alive\nDeclares Victory! Role:=COORDINATOR\nIncrements Term (Term := 2)", 
            fontsize=8, weight="bold", ha="center", va="center", color="#6d28d9")

    # Coordinator Broadcast
    ax.annotate("", xy=(10.5, 2.0), xytext=(6.5, 2.0), arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=1.8))
    ax.text(8.5, 2.2, "Broadcast Coordinator(new_coord=2, term=2)", fontsize=8.5, weight="bold", ha="center", color="#6d28d9")

    # Resume heartbeats
    ax.annotate("", xy=(10.5, 1.2), xytext=(6.5, 1.2), arrowprops=dict(arrowstyle="->", color="#059669", lw=1.5))
    ax.text(8.5, 1.4, "New Coordinator resumes Heartbeats; Write-ready in ~39-97ms", fontsize=8.5, weight="bold", ha="center", color="#059669")

    out_path = os.path.join(OUTPUT_DIR, "fig3_leader_election_failover.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print("Saved:", out_path)

# ─────────────────────────────────────────────────────────────────────────────
# 4. FOLLOWER RECOVERY & AUTOFOLLOWERSYNC SEQUENCE DIAGRAM
# ─────────────────────────────────────────────────────────────────────────────
def draw_recovery_sync_diagram():
    fig, ax = plt.subplots(figsize=(13, 8.5), dpi=300)
    ax.set_xlim(0, 13)
    ax.set_ylim(0, 9)
    ax.axis("off")

    ax.text(6.5, 8.6, "State Recovery & AutoFollowerSync Catch-up Protocol", 
            fontsize=15, weight="bold", ha="center", va="center", color="#0f172a")

    actors = [
        {"name": "Recovered Node (Node 3)\n[Rejoining Follower]", "x": 2.5, "color": "#0284c7"},
        {"name": "Local MySQL 3 DB\n(voting-node3-db)", "x": 6.0, "color": "#b45309"},
        {"name": "Active Coordinator (Node 2)\n[Current Leader]", "x": 9.5, "color": "#7c3aed"},
        {"name": "Coordinator MySQL 2 DB\n(voting-node2-db)", "x": 12.0, "color": "#b45309"},
    ]

    for a in actors:
        ax.plot([a["x"], a["x"]], [0.8, 7.8], color="#cbd5e1", lw=1.5, ls="--")
        box = patches.FancyBboxPatch((a["x"] - 1.1, 7.8), 2.2, 0.6, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                     ec=a["color"], fc="#f8fafc", lw=1.8)
        ax.add_patch(box)
        ax.text(a["x"], 8.1, a["name"], fontsize=9, weight="bold", ha="center", va="center", color=a["color"])

    # Node Restart
    start_box = patches.FancyBboxPatch((1.3, 7.0), 2.4, 0.55, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                       ec="#0284c7", fc="#e0f2fe", lw=1.5)
    ax.add_patch(start_box)
    ax.text(2.5, 7.27, "[RESTART] Container Restarts\n(docker start voting-node3)", fontsize=8, weight="bold", ha="center", va="center", color="#0369a1")

    # Inspect Local DB
    ax.annotate("", xy=(6.0, 6.3), xytext=(2.5, 6.3), arrowprops=dict(arrowstyle="->", color="#b45309", lw=1.5))
    ax.text(4.25, 6.5, "1. SELECT MAX(lamport_ts) FROM votes (Max TS = 12)", fontsize=8, weight="bold", ha="center", color="#b45309")

    # Heartbeat discovery
    ax.annotate("", xy=(2.5, 5.5), xytext=(9.5, 5.5), arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=1.5))
    ax.text(6.0, 5.7, "2. Receives Heartbeat(coord=2, term=2). Discovers active leader!", fontsize=8.5, weight="bold", ha="center", color="#6d28d9")

    # Trigger AutoFollowerSync
    ax.annotate("", xy=(9.5, 4.7), xytext=(2.5, 4.7), arrowprops=dict(arrowstyle="->", color="#0284c7", lw=1.8))
    ax.text(6.0, 4.9, "3. gRPC SyncLog(from_lamport_ts=12, follower_id=3)", fontsize=8.5, weight="bold", ha="center", color="#0284c7")

    # Coordinator Queries DB
    ax.annotate("", xy=(12.0, 4.0), xytext=(9.5, 4.0), arrowprops=dict(arrowstyle="->", color="#b45309", lw=1.5))
    ax.text(10.75, 4.2, "4. Query committed votes with TS > 12", fontsize=8, weight="bold", ha="center", color="#b45309")

    # Stream missing votes
    ax.annotate("", xy=(2.5, 3.2), xytext=(9.5, 3.2), arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=1.8))
    ax.text(6.0, 3.4, "5. SyncLogResponse(missing_votes=[V102, V103], coord_ts=24)", fontsize=8.5, weight="bold", ha="center", color="#6d28d9")

    # Ingest and WAL catchup
    ax.annotate("", xy=(6.0, 2.3), xytext=(2.5, 2.3), arrowprops=dict(arrowstyle="->", color="#b45309", lw=1.5))
    ax.text(4.25, 2.5, "6. Idempotent INSERT INTO votes & sync_log", fontsize=8, weight="bold", ha="center", color="#b45309")

    # Parity achieved box
    sync_box = patches.FancyBboxPatch((1.5, 1.0), 9.0, 0.7, boxstyle="round,pad=0.05,rounding_size=0.1", 
                                      ec="#059669", fc="#d1fae5", lw=1.8)
    ax.add_patch(sync_box)
    ax.text(6.0, 1.35, "[SYNC COMPLETE] Node 3 advances Lamport Clock & marks state ONLINE_SYNCED!\nFull Database WAL Parity achieved across all 3 nodes in ~2.26 seconds.", 
            fontsize=8.5, weight="bold", ha="center", va="center", color="#047857")

    out_path = os.path.join(OUTPUT_DIR, "fig4_follower_recovery_sync.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print("Saved:", out_path)

# ─────────────────────────────────────────────────────────────────────────────
# 5. EXPERIMENTAL EVALUATION HARNESS ARCHITECTURE
# ─────────────────────────────────────────────────────────────────────────────
def draw_experimental_harness_diagram():
    fig, ax = plt.subplots(figsize=(14, 8.5), dpi=300)
    ax.set_xlim(0, 14)
    ax.set_ylim(0, 9)
    ax.axis("off")

    ax.text(7, 8.6, "Automated Benchmark Harness & Telemetry Pipeline (Phase 7)", 
            fontsize=15, weight="bold", ha="center", va="center", color="#0f172a")

    # Orchestrator Box
    orch_box = patches.FancyBboxPatch((0.8, 4.5), 3.8, 3.5, boxstyle="round,pad=0.1,rounding_size=0.15", 
                                      ec="#7c3aed", fc="#f5f3ff", lw=2)
    ax.add_patch(orch_box)
    ax.text(2.7, 7.6, "Master Experiment Orchestrator\n(run_matrix.py)", fontsize=11, weight="bold", ha="center", color="#6d28d9")
    ax.text(2.7, 6.2, "• Experiment Catalog (EXP-01..09)\n• Factorial Grid (N=3,5,7; Bully/Ring)\n• Two-Tier Workload Sizing\n• Windows Port Settlement Buffer\n• SHA-256 Manifest Generator", 
            fontsize=8.5, color="#4c1d95")

    # Execution Components
    comps = [
        {"name": "ClusterManager", "desc": "Docker Compose profiles\nTwo-Stage Readiness Gate\nScoped Teardown (-v)", "y": 6.8, "c": "#0284c7", "bg": "#e0f2fe"},
        {"name": "ContainerTelemetrySampler", "desc": "Continuous background sampling\nCPU, RAM, Net RX/TX (1s)\nFault-tolerant inspect fallback", "y": 4.8, "c": "#059669", "bg": "#d1fae5"},
        {"name": "WorkloadClient", "desc": "ThreadSafeNDJSONWriter\nWarmup request separation\nKernel page cache flushing", "y": 2.8, "c": "#ea580c", "bg": "#fff7ed"},
        {"name": "FaultInjector", "desc": "Crash-stop (stop -t 1)\nNetwork partitions (disconnect)\nIdempotent context cleanup", "y": 0.8, "c": "#dc2626", "bg": "#fee2e2"},
    ]

    for c in comps:
        c_box = patches.FancyBboxPatch((5.4, c["y"]), 3.8, 1.5, boxstyle="round,pad=0.08,rounding_size=0.12", 
                                       ec=c["c"], fc=c["bg"], lw=1.8)
        ax.add_patch(c_box)
        ax.text(7.3, c["y"] + 1.15, c["name"], fontsize=10, weight="bold", ha="center", color=c["c"])
        ax.text(7.3, c["y"] + 0.5, c["desc"], fontsize=7.5, ha="center", color="#334155")
        # Arrow from orchestrator
        ax.annotate("", xy=(5.4, c["y"] + 0.75), xytext=(4.6, 6.2), 
                    arrowprops=dict(arrowstyle="->", color="#7c3aed", lw=1.5))

    # Output Artifacts Box
    out_box = patches.FancyBboxPatch((10.0, 1.8), 3.5, 6.2, boxstyle="round,pad=0.1,rounding_size=0.15", 
                                     ec="#2563eb", fc="#eff6ff", lw=2)
    ax.add_patch(out_box)
    ax.text(11.75, 7.5, "Verified Research Artifacts\n(data/experiments/matrix/)", fontsize=10.5, weight="bold", ha="center", color="#1e40af")
    ax.text(11.75, 4.6, "• 99 Trial Manifests (.json)\n  (with SHA-256 checksums)\n• Raw Request Latencies\n  (*_requests.ndjson)\n• Continuous Telemetry\n  (*_telemetry.ndjson)\n• Per-Trial Summaries\n  (*_summary.json)\n\n• Statistical Aggregator\n  (aggregate_metrics.py)\n  Mean ± 95% CI (Student's t)\n  Non-parametric p50, p95, p99\n\n• Consolidated Dataset\n  (benchmark_summary.csv)", 
            fontsize=8, color="#1e3a8a")

    for c in comps:
        ax.annotate("", xy=(10.0, c["y"] + 0.75), xytext=(9.2, c["y"] + 0.75), 
                    arrowprops=dict(arrowstyle="->", color=c["c"], lw=1.5))

    out_path = os.path.join(OUTPUT_DIR, "fig5_experimental_evaluation_harness.png")
    plt.tight_layout()
    plt.savefig(out_path, dpi=300)
    plt.close()
    print("Saved:", out_path)

if __name__ == "__main__":
    draw_architecture_diagram()
    draw_vote_workflow_diagram()
    draw_election_failover_diagram()
    draw_recovery_sync_diagram()
    draw_experimental_harness_diagram()
    print("All 5 diagrams generated successfully in:", OUTPUT_DIR)
