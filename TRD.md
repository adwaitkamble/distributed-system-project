# Technical Requirements Document (TRD)
## Fault-Tolerant Distributed Voting System

---

## 1. Tech Stack

| Layer | Technology | Notes |
|---|---|---|
| Node backend | Python 3.11+ | gRPC server + election/heartbeat logic |
| Inter-node communication | gRPC + Protocol Buffers | Election, heartbeat, vote replication, log sync |
| Node storage | MySQL 8 — **one instance per node** | Never shared across nodes; mirrors the no-single-point-of-failure design |
| Client-to-coordinator bridge | Flask (REST) | Wraps gRPC calls so React can call plain HTTP |
| Frontend | React | Voter UI + Admin dashboard |
| Deployment | Docker + Docker Compose | 1 app container + 1 MySQL container per node |
| Experiment tooling | Python scripts (`subprocess`, `time`), `matplotlib`, `pandas` | Failure injection, metric capture, result plots |

## 2. Non-Functional Requirements
- **Fault tolerance:** system must survive the crash of any single node, including the current coordinator, without data loss.
- **Consistency:** no vote is counted twice (unique `vote_id` enforced at DB level) and no accepted vote is dropped during recovery.
- **Recovery time:** new coordinator must be confirmed by all surviving nodes within a few seconds of failure (measured, not fixed — this is an experiment output).
- **Configurability:** election algorithm (Bully/Ring), cluster size (3/5/7), heartbeat interval, and timeout must be configurable without code changes (env vars / CLI flags).
- **Observability:** every node logs election events, heartbeat timeouts, and replication actions with Lamport timestamps for later analysis.

## 3. gRPC Service Definition (summary)

```protobuf
service NodeService {
  rpc SubmitVote (VoteRequest) returns (VoteAck);
  rpc Heartbeat (HeartbeatPing) returns (HeartbeatPong);
  rpc Election (ElectionMessage) returns (ElectionAck);
  rpc Coordinator (CoordinatorAnnouncement) returns (Ack);
  rpc ReplicateVote (VoteRecord) returns (Ack);
  rpc SyncLog (SyncRequest) returns (SyncResponse);
}

message VoteRequest {
  string client_id = 1;
  string choice = 2;
}

message VoteRecord {
  string vote_id = 1;
  int64 lamport_ts = 2;
  string choice = 3;
  int32 node_id = 4;
}
```

## 4. Data Model (per-node MySQL)

```sql
CREATE TABLE votes (
    vote_id      VARCHAR(64) PRIMARY KEY,   -- client_id + lamport_ts
    lamport_ts   BIGINT NOT NULL,
    choice       VARCHAR(100) NOT NULL,
    node_id      INT NOT NULL,
    received_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE election_log (
    id           INT AUTO_INCREMENT PRIMARY KEY,
    event_type   VARCHAR(30),   -- ELECTION_STARTED, COORDINATOR_ELECTED, HEARTBEAT_TIMEOUT
    lamport_ts   BIGINT,
    details      TEXT,
    logged_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## 5. REST API (Flask layer, client-facing)

| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/api/vote` | Submit a vote `{client_id, choice}` → forwards to current coordinator via gRPC |
| GET | `/api/results` | Returns live tally |
| GET | `/api/cluster/status` | Returns current coordinator, active nodes, algorithm in use |
| POST | `/api/admin/kill/{node_id}` | Demo-only: stop a container to simulate failure |

## 6. Configuration Parameters

| Parameter | Example | Description |
|---|---|---|
| `NODE_ID` | `3` | Unique integer ID per node |
| `ELECTION_ALGORITHM` | `bully` / `ring` | Selected at cluster startup |
| `HEARTBEAT_INTERVAL_MS` | `1000` | Coordinator heartbeat frequency |
| `HEARTBEAT_TIMEOUT_MS` | `3000` | ~3x interval before marking coordinator failed |
| `PEERS` | `node1:50051,node2:50051,...` | Peer addresses |

## 7. Deployment Topology
- 3 / 5 / 7 app containers (one per node), each paired with its own MySQL container.
- All containers on one Docker bridge network (`voting-net`).
- `docker-compose.yml` parameterized by `ELECTION_ALGORITHM` and node count profile.

## 8. Metrics Captured (for experiments)
Election time, message overhead, vote processing time, recovery time, throughput, lost votes, duplicate votes — see `DESIGN.md §6` for exact definitions and measurement method.

## 9. Testing Requirements
- Unit tests: Lamport clock increment rule, Vote ID generation/uniqueness, Bully/Ring message handling logic.
- Integration tests: full election cycle on a running Docker cluster.
- Failure-injection tests: kill coordinator mid-vote-stream, verify zero lost/duplicate votes at the end.
