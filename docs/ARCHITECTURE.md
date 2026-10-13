# Distributed Fault-Tolerant Voting System — System Architecture Specification

## 1. Executive Summary

This document provides the formal architectural specification of the **Distributed Fault-Tolerant Voting System**. The system is engineered to eliminate single points of failure in electronic polling by distributing consensus, replication, and storage across independent containerized server nodes.

The core runtime architecture implements:
1. **Tiered Client-to-Cluster Bridging**: A React Single-Page Application communicating via HTTP REST to a local Flask adapter bridge, which interfaces with the cluster coordinator via high-throughput gRPC.
2. **Physical Storage Isolation**: Dedicated MySQL database instances per node with zero shared storage volumes or common database servers.
3. **Pluggable Leader Election**: Deterministic Bully and Ring election algorithms maintaining monotonic terms and Lamport logical timestamps.
4. **Fault-Tolerant Two-Phase Replication**: Quorum-gated commit semantics supporting both strict all-peer (`all`) and majority-quorum (`majority`) consensus.
5. **State Reconciliation & AutoFollowerSync**: Monotonic timeout failure detection, log-gap detection, and automated catch-up synchronization.

---

## 2. Overall System Architecture

The distributed voting system deploys a symmetric cluster topology where each node contains an independent application container and a paired, isolated MySQL container. All nodes communicate across an internal Docker bridge network (`voting-net`).

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

### Component Layer Responsibilities
- **Frontend SPA**: React 18 application hosted on every node's Flask root `/`. Provides real-time cluster visualization, ballot submission, live committed tally queries, and audit logs.
- **Flask REST Bridge**: Translates client JSON requests to internal gRPC invocations. If the local node is a follower, it transparently returns HTTP 307 redirect hints or proxies vote submissions directly to the active coordinator.
- **NodeRuntime**: Core state machine managing role transitions (`FOLLOWER`, `CANDIDATE`, `COORDINATOR`), election timeouts, logical clock advancement, and consensus evaluation.
- **gRPC Server / Client**: High-performance binary RPC layer executing protobuf service definitions for inter-node replication, heartbeats, elections, and log sync.
- **Isolated Storage**: MySQL 8.0 (containerized) or SQLite (test suite isolation) enforcing unique voter constraints (`UNIQUE KEY (client_id)`) and atomic transaction logs.

---

## 3. Vote Submission and Commitment Workflow

Ballots undergo a two-phase replication procedure before transitioning from `PENDING` to `COMMITTED`. Uncommitted votes are never exposed in public tallies.

```mermaid
sequenceDiagram
    autonumber
    actor Voter as Voter (Client / Browser)
    participant Bridge as Flask REST Bridge (Follower)
    participant Coord as Coordinator Node (Runtime & gRPC)
    participant CoordDB as Coordinator MySQL DB
    participant Peer1 as Follower Node 1
    participant Peer1DB as Follower 1 MySQL DB
    participant Peer2 as Follower Node 2
    participant Peer2DB as Follower 2 MySQL DB

    Voter->>Bridge: POST /api/votes {voter_id: "V101", choice: "Alice"}
    Note over Bridge: Check local role: FOLLOWER<br/>Target coordinator: Node 3
    Bridge->>Coord: gRPC SubmitVote(client_id="V101", choice="Alice")
    
    Note over Coord: Lamport Clock L := L + 1<br/>Generate vote_id = V101:3:L<br/>Validate duplicate (client_id)
    Coord->>CoordDB: INSERT INTO votes VALUES (..., status='PENDING')
    
    par Concurrent Replication Fan-out
        Coord->>Peer1: gRPC ReplicateVote(vote_id, client_id, choice, L)
        Note over Peer1: Validate choice & uniqueness<br/>Advance L1 := max(L1, L) + 1
        Peer1->>Peer1DB: INSERT INTO votes (status='PENDING')
        Peer1-->>Coord: ReplicateVoteResponse(success=True)
    and
        Coord->>Peer2: gRPC ReplicateVote(vote_id, client_id, choice, L)
        Note over Peer2: Validate choice & uniqueness<br/>Advance L2 := max(L2, L) + 1
        Peer2->>Peer2DB: INSERT INTO votes (status='PENDING')
        Peer2-->>Coord: ReplicateVoteResponse(success=True)
    end

    Note over Coord: Evaluate Quorum Policy:<br/>MAJORITY: Q = floor(N/2) + 1 = 2 ACKs (Met!)<br/>ALL: 3 ACKs (Met!)
    Coord->>CoordDB: UPDATE votes SET status='COMMITTED' WHERE vote_id=...
    
    par Async Commit Notification
        Coord--)Peer1: Background Commit / Heartbeat update
        Peer1->>Peer1DB: UPDATE votes SET status='COMMITTED'
    and
        Coord--)Peer2: Background Commit / Heartbeat update
        Peer2->>Peer2DB: UPDATE votes SET status='COMMITTED'
    end

    Coord-->>Bridge: SubmitVoteResponse(success=True, receipt={vote_id, L})
    Bridge-->>Voter: HTTP 201 Created {status: "COMMITTED", vote_id: "V101:3:L"}
```

---

## 4. Leader Election and Coordinator Failure Sequence

When the active coordinator crashes, surviving followers detect missing heartbeats using a monotonic timer latch and initiate deterministic leader election.

```mermaid
sequenceDiagram
    autonumber
    participant Coord as Coordinator (Node 3)
    participant Node2 as Follower (Node 2)
    participant Node1 as Follower (Node 1)

    Coord->>Node2: Heartbeat(term=1, coordinator_id=3)
    Coord->>Node1: Heartbeat(term=1, coordinator_id=3)
    
    Note over Coord: 💥 Hard Crash / Power Loss / Container Stop
    
    Note over Node2: Monotonic Timer Latch:<br/>now() - last_hb >= 3000ms
    Note over Node1: Monotonic Timer Latch:<br/>now() - last_hb >= 3000ms

    par Timeout Triggered
        Note over Node1: Node 1 detects timeout<br/>Transitions to CANDIDATE (term=2)
        Node1->>Node2: gRPC Election(candidate_id=1, term=2)
    and
        Note over Node2: Node 2 detects timeout<br/>Transitions to CANDIDATE (term=2)
    end

    Note over Node2: Bully Algorithm Rule:<br/>Node 2 ID > Candidate 1 ID
    Node2-->>Node1: gRPC ElectionAck(status=OK / SUPPRESSED)
    Note over Node1: Yields election to higher Node 2

    Node2->>Node2: Candidate 2 finds no higher peers alive
    Note over Node2: Declares Victory!<br/>Role := COORDINATOR<br/>Term := 2

    par Broadcast New Coordinator
        Node2->>Node1: gRPC Coordinator(new_coordinator_id=2, term=2)
        Note over Node1: Adopts Coordinator 2<br/>Role := FOLLOWER<br/>Term := 2
    end

    Note over Node2: Resumes Heartbeat broadcasts (500ms)<br/>Activates Write-Readiness (~35-95ms)
    Node2->>Node1: Heartbeat(term=2, coordinator_id=2)
```

---

## 5. Follower Crash Recovery & AutoFollowerSync

A recovered node rejoining the cluster must reconcile missing committed ballots before it can service consistent queries or participate in quorums.

```mermaid
sequenceDiagram
    autonumber
    participant Follower as Recovering Follower (Node 1)
    participant FollowerDB as Follower 1 MySQL DB
    participant Coord as Active Coordinator (Node 2)
    participant CoordDB as Coordinator MySQL DB

    Note over Follower: 🔄 Container Bootstrapped / Restarted<br/>Loads local state from MySQL
    Follower->>FollowerDB: SELECT MAX(lamport_ts) FROM votes
    FollowerDB-->>Follower: Max local Lamport TS = 12

    Coord->>Follower: Periodic Heartbeat(term=2, coordinator_id=2, L=24)
    Note over Follower: Discovers active coordinator (Node 2)<br/>Heartbeat term (2) >= local term (1)<br/>Triggers AutoFollowerSync!

    Follower->>Coord: gRPC SyncLog(from_lamport_ts=12, follower_id=1)
    Note over Coord: Queries committed votes<br/>with lamport_ts > 12
    Coord->>CoordDB: SELECT * FROM votes WHERE status='COMMITTED' AND lamport_ts > 12
    CoordDB-->>Coord: Returns missing votes [V105, V106]
    Coord-->>Follower: SyncLogResponse(missing_votes=[V105, V106], coordinator_ts=24)

    loop Reconcile Missing Ballots
        Note over Follower: Idempotent duplicate check<br/>Insert into local database
        Follower->>FollowerDB: INSERT INTO votes VALUES (..., status='COMMITTED')
        Follower->>FollowerDB: INSERT INTO sync_log VALUES (..., type='CATCHUP_INSERT')
    end

    Note over Follower: Advance Lamport Clock: L1 := max(L1, 24)<br/>State := ONLINE_SYNCED
    Follower-->>Coord: SyncCompleteAck(success=True, local_count=total_count)
    Note over Follower: Verified local tally matches Coordinator perfectly!
```

---

## 6. Experimental Evaluation Architecture

The Phase 7 benchmark suite employs a decoupled measurement harness that drives factorial workloads, samples container performance, injects deterministic faults, and asserts safety invariants.

```mermaid
graph TD
    subgraph Test Harness Architecture
        Runner["Master Experiment Runner (run_matrix.py)"]
        Catalog["Experiment Catalog (EXP-01 .. EXP-09)"]
        Client["Workload Client (ThreadSafeNDJSONWriter)"]
        Injector["Fault Injector (Docker API / Subprocess)"]
        Sampler["Continuous Telemetry Collector (Docker Inspect/Stats)"]
        Aggregator["Statistical Aggregator (aggregate_metrics.py)"]
    end

    subgraph Target Cluster Infrastructure
        Compose["Docker Compose Profile (3, 5, or 7 Nodes)"]
        AppNodes["Containerized Python Nodes (1..N)"]
        DBNodes["Isolated MySQL Instances (1..N)"]
    end

    subgraph Verified Artifacts Storage
        Requests["Raw Request Traces (.ndjson)"]
        Telemetry["Continuous Telemetry (.ndjson)"]
        Summaries["Trial Summaries (.json)"]
        Manifests["Cryptographic Manifests (SHA-256)"]
        SummaryCSV["benchmark_summary.csv"]
    end

    Catalog --> Runner
    Runner -->|"1. Start Cluster"| Compose
    Compose --> AppNodes
    Compose --> DBNodes

    Runner -->|"2. Readiness Gate"| AppNodes
    Runner -->|"3. Background Sampling"| Sampler
    Sampler -.->|"Stream CPU, RAM, Net"| Telemetry

    Runner -->|"4. Concurrent Load"| Client
    Client -->|"SubmitBallot (HTTP)"| AppNodes
    Client -.->|"Flush Latencies"| Requests

    Runner -->|"5. Inject Fault (Crash/Partition/Rejoin)"| Injector
    Injector -->|"docker stop / network disconnect"| AppNodes

    Runner -->|"6. Audit Invariants"| AppNodes
    Runner -->|"7. Teardown Cluster"| Compose

    Runner -->|"8. Write Trial Manifest"| Manifests
    Runner -->|"8. Write Trial Summary"| Summaries

    Summaries --> Aggregator
    Aggregator -->|"Student's t CI95, Order Percentiles"| SummaryCSV
```
