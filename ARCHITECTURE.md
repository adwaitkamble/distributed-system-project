# ARCHITECTURE.md — Distributed Fault-Tolerant Voting System

> [!NOTE]
> For the comprehensive, publication-grade architectural specification containing detailed sequence workflows and component interactions, see [`docs/ARCHITECTURE.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docs/ARCHITECTURE.md).

---

## 1. High-Level Architecture Overview

The Distributed Fault-Tolerant Voting System implements a symmetric multi-node cluster architecture with physical database isolation, pluggable leader election (**Bully** and **Ring**), and two-phase gRPC replication.

```mermaid
graph TD
    subgraph Client Layer
        Browser["Web Browser / React Single-Page Application (Vite + Tailwind)"]
    end

    subgraph Node 1 Container ["Node 1 Container (Port 5001)"]
        Web1["Flask REST Bridge (:5001 -> :5000)"]
        Runtime1["NodeRuntime 1"]
        gRPC1["gRPC Server (:50051)"]
        DB1[("Dedicated MySQL 1 (voting_node)")]
    end

    subgraph Node 2 Container ["Node 2 Container (Port 5002)"]
        Web2["Flask REST Bridge (:5002 -> :5000)"]
        Runtime2["NodeRuntime 2"]
        gRPC2["gRPC Server (:50051)"]
        DB2[("Dedicated MySQL 2 (voting_node)")]
    end

    subgraph Node 3 Container ["Node 3 Container (Port 5003 - Active Coordinator)"]
        Web3["Flask REST Bridge (:5003 -> :5000)"]
        Runtime3["NodeRuntime 3 (Leader)"]
        gRPC3["gRPC Server (:50051)"]
        DB3[("Dedicated MySQL 3 (voting_node)")]
    end

    Browser -->|"HTTP REST (GET/POST)"| Web1
    Browser -->|"HTTP REST (GET/POST)"| Web2
    Browser -->|"HTTP REST (GET/POST)"| Web3

    Web1 -->|"In-Process Call"| Runtime1
    Web2 -->|"In-Process Call"| Runtime2
    Web3 -->|"In-Process Call"| Runtime3

    Runtime1 --- gRPC1
    Runtime2 --- gRPC2
    Runtime3 --- gRPC3

    Runtime1 -->|"TCP :3306"| DB1
    Runtime2 -->|"TCP :3306"| DB2
    Runtime3 -->|"TCP :3306"| DB3

    Web1 -.->|"gRPC SubmitVote (Forward to Leader)"| gRPC3
    Web2 -.->|"gRPC SubmitVote (Forward to Leader)"| gRPC3

    gRPC3 ==="Heartbeats (500ms) / ReplicateVote"===> gRPC1
    gRPC3 ==="Heartbeats (500ms) / ReplicateVote"===> gRPC2
    gRPC1 <.-.->|"Bully (ELECTION/OK) or Ring Token Passing"| gRPC2
```

---

## 2. Core Architectural Pillars

1. **Physical Database Isolation:**
   - Every node container is paired with its own dedicated MySQL database container (`voting-node{id}-db`).
   - There is **no shared database** and no shared storage volume, eliminating single points of failure at the storage layer.
2. **Pluggable Leader Election:**
   - **Bully Algorithm:** Higher node IDs suppress lower candidates (`ELECTION`, `OK`, `COORDINATOR`). Worst-case $O(N^2)$ message complexity.
   - **Ring Algorithm:** Logical token ring passing with deterministic traversal and coordinator announcement. Strictly bounded $O(N)$ message complexity.
3. **Monotonic Heartbeats & Failure Detection:**
   - The coordinator streams heartbeats every 500ms.
   - Followers employ a monotonic timer latch (`time.monotonic()`) tripping at 3000ms (~6 intervals) to detect coordinator crashes.
4. **Two-Phase Replication & Quorum Policies:**
   - Ballots are staged as `PENDING` across replicas before being promoted to `COMMITTED` once the quorum requirement is acknowledged.
   - **Policies:** Strict All-Replication (`all`, requires $Q = N$) or Majority Quorum (`majority`, requires $Q = \lfloor N/2 \rfloor + 1$).
5. **Crash Recovery & AutoFollowerSync:**
   - Rejoining nodes automatically detect the active coordinator via periodic heartbeats.
   - Followers query missing committed votes using gRPC `SyncLog` and reconcile their local database and durable `sync_log`, achieving 100% database WAL parity in $\approx 2.3\text{s}$.
6. **Unified Web Experience:**
   - Every node hosts the compiled React 18 single-page application at root `/`, exposing cluster status, live voting, real-time tallies, and audit logs.

---

## 3. Workflow Diagrams Reference

The full suite of architectural sequence and component workflows is available in [`docs/ARCHITECTURE.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docs/ARCHITECTURE.md):
- **Diagram 1:** Overall Cluster Architecture
- **Diagram 2:** Vote Submission and Commitment Sequence
- **Diagram 3:** Leader Election and Coordinator Failure Sequence
- **Diagram 4:** Follower Crash Recovery & AutoFollowerSync Sequence
- **Diagram 5:** Experimental Evaluation Harness & Telemetry Pipeline
