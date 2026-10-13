# Distributed Fault-Tolerant Voting System

A resilient, multi-node distributed electronic voting system designed to eliminate single points of failure. The system features pluggable leader election algorithms (**Bully** and **Ring**), multi-node gRPC replication, monotonic Lamport logical clocks, automated crash-recovery with log reconciliation, dedicated physical database isolation per node, and an interactive React web dashboard.

---

## Architecture Overview

```mermaid
graph TD
    subgraph Client Layer
        Browser[Web Browser / React Single-Page Application]
    end

    subgraph Node 1 Container
        Web1[Flask REST Bridge :5001]
        Runtime1[NodeRuntime 1]
        gRPC1[gRPC Server :50051]
        DB1[(Dedicated MySQL 1)]
    end

    subgraph Node 2 Container
        Web2[Flask REST Bridge :5002]
        Runtime2[NodeRuntime 2]
        gRPC2[gRPC Server :50051]
        DB2[(Dedicated MySQL 2)]
    end

    subgraph Node 3 Container (Coordinator)
        Web3[Flask REST Bridge :5003]
        Runtime3[NodeRuntime 3]
        gRPC3[gRPC Server :50051]
        DB3[(Dedicated MySQL 3)]
    end

    Browser -->|HTTP REST| Web1
    Browser -->|HTTP REST| Web2
    Browser -->|HTTP REST| Web3

    Web1 --> Runtime1
    Web2 --> Runtime2
    Web3 --> Runtime3

    Runtime1 --- gRPC1
    Runtime2 --- gRPC2
    Runtime3 --- gRPC3

    Runtime1 --> DB1
    Runtime2 --> DB2
    Runtime3 --> DB3

    gRPC3 -.->|Heartbeat / Replication| gRPC1
    gRPC3 -.->|Heartbeat / Replication| gRPC2
    gRPC1 <.-.->|Bully / Ring Election| gRPC2
```

### Key Distributed Systems Features
1. **Physical Database Isolation**: Every node container is paired with its own dedicated MySQL database container. There is **no shared database** and no shared storage volume, eliminating single points of failure at the storage layer.
2. **Pluggable Leader Election**:
   * **Bully Algorithm**: Higher node IDs suppress lower candidates (`ELECTION` / `OK` / `COORDINATOR`).
   * **Ring Algorithm**: Logical token ring passing with deterministic traversal and coordinator broadcast.
3. **Monotonic Heartbeats & Failure Detection**: The coordinator streams heartbeats every 500ms. Followers use a monotonic timer latch (`time.monotonic()`) to detect failure in ~3.0s.
4. **Atomic Replication & Quorums**:
   * Two-phase commit style replication: `PENDING` $\rightarrow$ gRPC replication fan-out $\rightarrow$ ACK collection $\rightarrow$ `COMMITTED`.
   * **Policies**: `all` (replicates to all active peers) or `majority` (requires $\lfloor N/2 \rfloor + 1$ quorum acknowledgments).
5. **Crash Recovery & AutoFollowerSync**: Rejoining nodes automatically adopt the active coordinator and execute state reconciliation to pull missing committed votes into their local database and durable `sync_log`.
6. **Unified Web Experience**: Flask REST bridge compiles and hosts the production React single-page application at root `/` on every node.

---

## Technology Stack & Prerequisites

### Prerequisites
* **Operating System**: Windows 10/11, macOS, or Linux.
* **Docker & Docker Compose**: Docker Desktop (Windows/macOS) or Docker Engine with Compose plugin (Linux). *Note: Ensure the Docker daemon is running before starting container profiles.*
* **Python**: Python 3.10+ (tested on Python 3.11.9) for local development and non-Docker testing.
* **Node.js & npm**: Node.js 18+ and npm for frontend development and asset building.

### Technology Stack
* **Distributed Runtime & Messaging**: Python 3.11, gRPC (`grpcio`, `protobuf`), concurrent thread pools.
* **Web & API Layer**: Flask, Flask-CORS, Werkzeug.
* **Database & Persistence**: MySQL 8.0 (containerized production), SQLite (local test isolation), SQLAlchemy / PyMySQL.
* **Frontend**: React 18, Vite, Lucide React icons, Vanilla CSS / Tailwind tokens.
* **Testing & Orchestration**: Pytest, Docker Compose, PyYAML.

---

## Fresh-Checkout Environment Setup

Follow these steps to set up the project on a fresh machine:

### 1. Clone or Download Repository
Ensure you are in the project root directory:
```bash
cd "Distributed Voting System"
```

### 2. Python Virtual Environment Setup
Create and activate an isolated virtual environment:
```powershell
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\Activate.ps1

# Linux / macOS (Bash/Zsh)
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies
```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. (Optional) Recompile Protobuf Contracts
If you modify `proto/voting.proto`, regenerate the gRPC and Protobuf bindings:
```bash
python generate_proto.py
```

---

## Environment Configuration & Development Credentials

### Development Database Credentials
When running inside Docker, each node container connects to its paired MySQL container using the following development credentials:
* **Database Host**: `voting-node{id}-db` (internal Docker network) or `127.0.0.1` (external host port)
* **Database Name**: `voting_node`
* **Database User**: `root`
* **Database Password**: `votingpass` *(configured in `docker/init.sql` and `docker/docker-compose.*.yml`)*

### Environment Variables Reference
The system runtime (`node.main`) is configured through environment variables:

| Variable | Description | Default / Example |
|---|---|---|
| `NODE_ID` | Unique positive integer identifier for this node | `1` |
| `PEER_CONFIGURATION` | Comma-delimited list of peer mappings (`id:host:port`) | `1:127.0.0.1:50051,2:127.0.0.1:50052,3:127.0.0.1:50053` |
| `INITIAL_COORDINATOR_ID` | Node ID to assume initial coordinator role | `3` (or highest node ID) |
| `ELECTION_ALGORITHM` | Election algorithm to use: `bully` or `ring` | `bully` |
| `REPLICATION_POLICY` | Vote replication policy: `all` or `majority` | `majority` |
| `GRPC_PORT` | Port for internal peer-to-peer gRPC communication | `50051` |
| `HTTP_PORT` | Port for client REST API and Web Dashboard | `5001` |
| `ENABLE_WEB_BRIDGE` | Whether to mount the Flask REST bridge | `true` |
| `USE_SQLITE` | Use SQLite instead of MySQL (`true` for local tests) | `false` |
| `DB_HOST` | MySQL hostname or container DNS | `127.0.0.1` |
| `DB_PORT` | MySQL database port | `3306` |
| `DB_USER` | MySQL database username | `root` |
| `DB_PASSWORD` | MySQL database password | `votingpass` |
| `DB_NAME` | MySQL database name | `voting_node` |
| `CANDIDATES` | Comma-separated list of ballot candidate names | `Alice,Bob,Charlie` |

---

## Supported Docker Profiles

The system includes preconfigured Docker Compose profiles for **Single-Node**, **3-Node**, **5-Node**, and **7-Node** clusters.

| Profile | Compose File | Node Count | Web / REST Ports | External gRPC Ports | Host MySQL Ports | Initial Coordinator |
|---|---|:---:|---|---|---|:---:|
| **Single-Node** | `docker/docker-compose.single.yml` | 1 | `5000` | `50051` | `33060` | Node 1 |
| **Three-Node** | `docker/docker-compose.3node.yml` | 3 | `5001–5003` | `55051–55053` | `33061–33063` | Node 3 |
| **Five-Node** | `docker/docker-compose.5node.yml` | 5 | `5001–5005` | `55051–55055` | `33061–33065` | Node 5 |
| **Seven-Node** | `docker/docker-compose.7node.yml` | 7 | `5001–5007` | `55051–55057` | `33061–33067` | Node 7 |

---

## Application Startup, Health Checks, and Teardown

### 1. Cluster Startup
Ensure Docker Desktop is running, then launch any profile:
```bash
# 3-node profile (Standard recommended demo)
docker compose -f docker/docker-compose.3node.yml up -d --build

# 5-node profile
docker compose -f docker/docker-compose.5node.yml up -d --build

# 7-node profile
docker compose -f docker/docker-compose.7node.yml up -d --build

# Single-node profile
docker compose -f docker/docker-compose.single.yml up -d --build
```

### 2. Health Checks & Verification Endpoints
Once containers are healthy, inspect individual nodes via REST:
* **Web UI**: [http://localhost:5001](http://localhost:5001) *(or any active node port)*
* **Node Status**: `GET http://localhost:5001/api/status` — Returns node role (`COORDINATOR` or `FOLLOWER`), term, Lamport timestamp, election algorithm, and replication policy.
* **Cluster Status**: `GET http://localhost:5001/api/cluster` — Returns connectivity state and latency to all known peers.
* **Health Check**: `GET http://localhost:5001/api/health` — Returns `{"status": "ok"}` when the runtime is healthy.
* **Verified Tally**: `GET http://localhost:5001/api/tally` — Returns real-time committed vote count per candidate.

### 3. Safe Teardown
To cleanly stop containers and prune their ephemeral test volumes:
```bash
# Gracefully stop and remove containers and volumes for the active profile
docker compose -f docker/docker-compose.3node.yml down -v
```
> [!IMPORTANT]
> **Safe Teardown Rule**: Always target the specific compose file when tearing down (`docker compose -f docker/docker-compose.<profile>.yml down -v`). Never execute blanket `docker system prune` or manually delete the `data/experiments/matrix/` directory, which houses verified academic research artifacts.

---

## Interactive Web Dashboard

Each running node serves a compiled, responsive React Single-Page Application:

| Tab / View | Description |
|---|---|
| **Dashboard** | Displays current node status, cluster topology, role (`COORDINATOR` / `FOLLOWER`), term, and peer connectivity. |
| **Cast Vote** | Submit a ballot with voter ID (e.g. `voter_01`) and candidate selection (`Alice`, `Bob`, `Charlie`). Returns a signed cryptographic receipt. |
| **Live Tally** | Queries verified `COMMITTED` votes in real time across the database. |
| **Leader Election** | Visualizes active election algorithm (`bully` or `ring`), Lamport logical clocks, and manual election trigger. |
| **Recovery** | Inspects local recovery status and catch-up log (`sync_log`). |
| **Events** | Real-time audit log of heartbeats, replication ACKs, and leader transitions. |

---

## Algorithms & Distributed Mechanisms

### 1. Leader Election Algorithms
* **Bully Algorithm (`bully`)**:
  - When a follower detects a coordinator timeout, it sends `ELECTION` messages to all higher-numbered nodes.
  - If a higher node answers with `OK`, the sender defers.
  - If no higher node responds within the election timeout, the candidate declares itself coordinator and broadcasts a `COORDINATOR` message to all lower peers.
  - **Empirical Message Complexity**: Scales quadratically $O(N^2)$ (observed: 5 messages for $N=3$, 19 messages for $N=5$, 40.3 messages for $N=7$).
* **Ring Algorithm (`ring`)**:
  - Nodes form a logical unidirectional ring based on sorted node IDs.
  - An election message containing an active candidate list circulates around the ring until it returns to the initiator.
  - The highest active node ID in the candidate list is chosen as coordinator, followed by a coordinator announcement message around the ring.
  - **Empirical Message Complexity**: Scales linearly $O(N)$ (observed: 10.7 messages for $N=3$, 23.7 messages for $N=5$, 33.3 messages for $N=7$).

### 2. Replication Policies
* **Majority Quorum (`majority`)**:
  - Requires acknowledgment from a majority quorum $Q = \lfloor N/2 \rfloor + 1$ before committing a vote.
  - Tolerates up to $\lfloor (N-1)/2 \rfloor$ follower failures while remaining fully available for writes.
  - Quorum thresholds: $Q=2$ for $N=3$, $Q=3$ for $N=5$, $Q=4$ for $N=7$.
* **All-Replication (`all`)**:
  - Requires acknowledgment from *all* active peers in the cluster before committing.
  - If any single follower fails or becomes unreachable, write operations block and return HTTP 503 (`Quorum not reached`), preserving strict universal consistency at the expense of availability.

### 3. Crash Recovery & AutoFollowerSync
* When a crashed follower recovers and rejoins the cluster, it receives coordinator heartbeats.
* Upon verifying the coordinator's authority, the follower triggers `AutoFollowerSync`.
* The rejoining node requests all committed votes from the coordinator whose Lamport timestamp or transaction ID exceeds its local maximum.
* Missing votes are inserted into the follower's local database and recorded in its durable `sync_log`, ensuring exact WAL parity across all surviving and recovered nodes.

---

## Regression Testing & Verification

The repository contains **274 collected tests** covering unit logic, gRPC RPC handlers, Lamport clocks, election state machines, recovery managers, and Docker integration.

### Non-Docker Regression Suite
The non-Docker suite tests all distributed logic in complete isolation using in-memory or temporary SQLite databases and mock gRPC channels:
```bash
# Run complete non-Docker test suite
pytest tests/ -q
```
**Latest Verified Test Count**:
* **235 passed, 39 skipped, 0 failed, 0 errors** (Execution time: ~59s).

### Meaning of Skipped Tests
* The **39 skipped tests** are live container integration tests located in `tests/test_docker_cluster_3node.py`, `tests/test_docker_cluster_5node.py`, and `tests/test_docker_cluster_7node.py`.
* These tests are guarded with `@pytest.mark.skipif` checks that query the Docker daemon and cluster health endpoints. When a specific multi-node Docker profile is not running, pytest automatically skips those tests to prevent false failures.
* When a cluster profile is active, target its specific test suite:
  ```bash
  # Test live 3-node cluster:
  pytest tests/test_docker_cluster_3node.py -v

  # Test live 5-node cluster:
  pytest tests/test_docker_cluster_5node.py -v

  # Test live 7-node cluster:
  pytest tests/test_docker_cluster_7node.py -v
  ```

---

## Phase 7 Benchmark Experiments (EXP-01 to EXP-09)

The project includes an automated, reproducible experimental framework under `experiments/` to rigorously evaluate distributed performance, consensus, and fault tolerance.

### Experiment Catalog

| ID | Name | Topologies | Algorithm | Policy | Fault Scenario | Focus / Objective |
|:---:|---|:---:|:---:|:---:|:---:|---|
| **EXP-01** | Bully Baseline (ALL) | $N=3,5,7$ | Bully | ALL | None | Steady-state throughput and commit latency under ALL policy. |
| **EXP-02** | Bully Baseline (MAJORITY) | $N=3,5,7$ | Bully | MAJORITY | None | Steady-state throughput and commit latency under MAJORITY policy. |
| **EXP-03** | Ring Baseline (ALL) | $N=3,5,7$ | Ring | ALL | None | Ring algorithm steady-state comparison with ALL replication policy. |
| **EXP-04** | Ring Baseline (MAJORITY) | $N=3,5,7$ | Ring | MAJORITY | None | Ring algorithm steady-state comparison with MAJORITY policy. |
| **EXP-05** | Coordinator Crash Failover | $N=3,5,7$ | Bully, Ring | MAJORITY | `coord_crash` | Election convergence latency, message overhead, write readiness. |
| **EXP-06** | Follower Crash Quorum Sensitivity | $N=3,5,7$ | Bully | ALL, MAJORITY | `follower_crash` | Write availability: ALL blocks (HTTP 503) vs MAJORITY commits. |
| **EXP-07** | Sequential Cascading Failover | $N=5,7$ | Bully, Ring | MAJORITY | `cascading_crash` | Consecutive coordinator terminations & multi-term convergence. |
| **EXP-08** | Follower Rejoin & Catch-up | $N=3,5,7$ | Bully | MAJORITY | `follower_rejoin` | AutoFollowerSync catch-up latency, missing vote ingestion, WAL parity. |
| **EXP-09** | Network Partition (Split-Brain) | $N=5,7$ | Bully | MAJORITY | `network_partition` | Majority partition commits; minority rejects with HTTP 503. |

### Batch Execution Commands
Experiments are organized into three reproducible batches:

```powershell
# 1. Verify execution plan without modifying containers (dry-run):
python -m experiments.runners.run_matrix --dry-run

# 2. Batch 1: Steady-State Baselines (EXP-01 through EXP-04):
python -m experiments.runners.run_matrix --batch 1

# 3. Batch 2: Failover & Quorum Sensitivity (EXP-05, EXP-06):
python -m experiments.runners.run_matrix --batch 2

# 4. Batch 3: Cascading Failures, Recovery & Partitions (EXP-07, EXP-08, EXP-09):
python -m experiments.runners.run_matrix --batch 3

# Execute full 99-trial matrix (33 configurations × 3 repetitions):
python -m experiments.runners.run_matrix --all

# Execute a single experiment:
python -m experiments.runners.run_matrix --exp EXP-01
```

### Statistical Metric Aggregation
To aggregate raw JSON and NDJSON trial traces into statistical metrics (mean, Student's $t$ 95% confidence intervals, and order-statistic percentiles):
```powershell
python -m experiments.analysis.aggregate_metrics `
  --raw-dir data/experiments/matrix `
  --output-csv data/experiments/matrix/summary/benchmark_summary.csv
```

### Experiment Artifact Locations
All verified experimental outputs are preserved in `data/experiments/matrix/`:
* **Consolidated Benchmark Summary CSV**: `data/experiments/matrix/summary/benchmark_summary.csv`
* **Trial Manifests (with SHA-256 hashes)**: `data/experiments/matrix/manifests/<trial_id>_manifest.json`
* **Raw Request Latency Traces (NDJSON)**: `data/experiments/matrix/requests/<trial_id>_requests.ndjson`
* **Raw Continuous Telemetry Traces (NDJSON)**: `data/experiments/matrix/telemetry/<trial_id>_telemetry.ndjson`
* **Trial Summaries (JSON)**: `data/experiments/matrix/summaries/<trial_id>_summary.json`
* **Forensic Audit & Reconciliation Report**: See `phase7_3_report.md` in project artifacts.

---

## Known Limitations & Empirical Boundaries

To uphold scientific and academic integrity, the following boundaries and limitations of the experimental evaluation are explicitly documented:
1. **Single-Host Virtualization**: All 3, 5, and 7-node Docker container clusters were executed on a single physical host machine sharing CPU, RAM, and the local Docker bridge network. Inter-container communication latency reflects loopback virtualization rather than wide-area or bare-metal physical network switches.
2. **Repetition Sample Size ($K=3$)**: Each configuration was executed for three repeated trials ($K=3$). While Student's $t$ distributions were used to compute 95% confidence intervals, variance is evaluated based on 3 independent samples per cell.
3. **Preserved Empirical Failures**: In EXP-04 $N=5$, two trials (T1 and T2) encountered transient Windows socket recycling latency (`55054/tcp` port bind contention) during rapid automated container recreation, resulting in client write timeouts. Rather than discarding or masking these runs, they remain preserved as `FAILED` manifests in the dataset, with valid throughput computed over $K_{\text{valid}}=1$.
4. **Empirical Observation vs Universal Guarantee**: All stated invariants (e.g. zero split-brain, zero ghost votes, 100% election convergence) reflect empirical observations across the 99 executed experimental trials under the specified fault scenarios, and are distinguished from universal mathematical proofs under arbitrary asynchronous Byzantine conditions.

---

## Reproducible Final Demonstration Workflow

Follow this step-by-step procedure to demonstrate the full capabilities of the distributed voting system to an evaluation committee:

### Step 1: Launch 3-Node Cluster
Ensure Docker Desktop is running, then execute:
```bash
docker compose -f docker/docker-compose.3node.yml up -d --build
```
Wait ~10 seconds for containers to initialize and MySQL health checks to pass.

### Step 2: Verify Initial Cluster Topology
Open your browser to [http://localhost:5001](http://localhost:5001) or [http://localhost:5003](http://localhost:5003).
* Notice that **Node 3** is elected initial **COORDINATOR** (highest node ID in 3-node cluster).
* Nodes 1 and 2 are active **FOLLOWERS**.
* The **Dashboard** tab shows all 3 nodes healthy and connected.

### Step 3: Cast Initial Ballot
1. Navigate to the **Cast Vote** tab on Node 1 ([http://localhost:5001](http://localhost:5001)).
2. Enter Voter ID `voter_eval_01` and select candidate `Alice`.
3. Click **Cast Ballot**.
4. Observe that the vote is forwarded to Node 3, replicated via gRPC to all followers, committed to MySQL, and returns a verified ballot receipt.
5. Inspect the **Live Tally** tab: `Alice: 1`.

### Step 4: Simulate Coordinator Crash & Failover
Simulate an abrupt hardware failure of the leader:
```bash
docker stop voting-node3
```
* Within ~3.0 seconds, Node 1 and Node 2 detect missing heartbeats via their monotonic timer latches.
* An election triggers automatically. **Node 2** (highest surviving ID) is elected new **COORDINATOR**.
* Refresh [http://localhost:5001](http://localhost:5001) or [http://localhost:5002](http://localhost:5002): Node 2 now shows as **COORDINATOR**.
* Cast another ballot for `Bob` via Node 2 ([http://localhost:5002](http://localhost:5002)) with Voter ID `voter_eval_02`.
* The vote succeeds under majority quorum ($2/3$ nodes alive).

### Step 5: Recover Crashed Node & Verify State Catch-Up
Recover the crashed node:
```bash
docker start voting-node3
```
* Node 3 boots up, receives Node 2's coordinator heartbeat, and yields as a follower.
* Node 3's `AutoFollowerSync` automatically contacts Node 2, detects the missing ballot `voter_eval_02`, and inserts it into its local database.
* Open [http://localhost:5003](http://localhost:5003) and inspect the **Live Tally**: `Alice: 1, Bob: 1` — tallies match identically across all three physical databases!

### Step 6: Clean Teardown
```bash
docker compose -f docker/docker-compose.3node.yml down -v
```

---

## Project Directory Layout

```text
├── api/                                      # Flask REST bridge & HTTP route handlers
├── docker/                                   # Docker Compose profiles & MySQL init scripts
│   ├── docker-compose.single.yml             # 1-node profile
│   ├── docker-compose.3node.yml              # 3-node profile (Standard demo)
│   ├── docker-compose.5node.yml              # 5-node profile
│   ├── docker-compose.7node.yml              # 7-node profile
│   └── init.sql                              # Database schema & initial table creation
├── experiments/                              # Phase 7 automated experimental framework
│   ├── analysis/                             # aggregate_metrics.py, generate_charts.py
│   ├── config/                               # benchmark_config.py, matrix_definitions.py
│   ├── core/                                 # cluster_manager.py, fault_injector.py, workload_client.py, telemetry_collector.py
│   ├── runners/                              # run_matrix.py, run_benchmark.py, run_fault_experiment.py
│   └── README.md                             # Experimental framework guide
├── data/experiments/matrix/                 # Verified Phase 7 benchmark research artifacts
│   ├── manifests/                            # Cryptographic SHA-256 JSON trial manifests
│   ├── requests/                             # Raw per-request NDJSON latency traces
│   ├── summaries/                            # Per-trial JSON execution summaries
│   ├── summary/                              # benchmark_summary.csv (Aggregated results)
│   └── telemetry/                            # Raw continuous container telemetry NDJSON
├── frontend/                                 # React single-page frontend (Vite + Tailwind/CSS)
│   ├── src/components/                       # Dashboard, Ballot, Election, Recovery, Events components
│   └── index.html
├── node/                                     # Core distributed system runtime (FROZEN)
│   ├── election/                             # Bully & Ring election implementations
│   ├── config.py                             # Node configuration & peer topology parser
│   ├── heartbeat.py                          # Heartbeat sender & monotonic timeout detector
│   ├── lamport.py                            # Monotonic Lamport logical clock
│   ├── main.py                               # Node runtime entry point
│   ├── models.py                             # Distributed enums & data models (Role, Term, Policy)
│   ├── recovery.py                           # State recovery manager & AutoFollowerSync
│   ├── runtime.py                            # Central NodeRuntime coordinator
│   └── storage.py                            # Storage engine abstraction (MySQL & SQLite)
├── proto/                                    # Protocol Buffers contract (voting.proto)
├── tests/                                    # 274 automated regression & Docker tests (235 passed, 39 skipped)
├── Dockerfile                                # Multi-stage production container build
├── generate_proto.py                         # Protobuf compilation script
├── PROJECT_MEMORY.md                         # Engineering decision log (D1 through D34)
├── requirements.txt                          # Python dependencies
└── README.md                                 # This project documentation
```
