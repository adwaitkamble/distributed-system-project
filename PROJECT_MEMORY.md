# PROJECT_MEMORY.md
## Fault-Tolerant Distributed Voting System — Decision Log

Purpose: a running record of decisions made and *why*, so future work (or anyone picking this up) doesn't have to re-derive the reasoning. Append new entries at the bottom with a date; don't delete old ones even if later superseded — mark them superseded instead.

---

## Decision Log

### D1 — Core concept
**Decision:** Build a multi-node voting system (not single-server) that tolerates coordinator crash failures.  
**Why:** The paper's whole argument is eliminating the single point of failure in a centralized voting server.

### D2 — Election algorithms: implement both Bully and Ring
**Decision:** Implement both, selectable per run, rather than picking just one.  
**Why:** The project's research goal is an experimental *comparison* of the two algorithms (election time, message overhead, etc. across 3/5/7-node clusters), not just a working system with one fixed algorithm.

### D3 — Algorithm switch is a startup-time choice, not per-node
**Decision:** `ELECTION_ALGORITHM` is set once per cluster run (env var / CLI flag), identical across all nodes in that run. No runtime hot-switching built for MVP.  
**Why:** Simpler to implement and defend; matches how the experiments are actually run (one full algorithm × cluster-size matrix, not switching mid-run).

### D4 — Failure detection: heartbeat + timeout, not external failure detector
**Decision:** Coordinator broadcasts heartbeats; peers use local elapsed-time timeout (~3x interval) using `time.monotonic()` to declare failure.  
**Why:** Simple, doesn't require synchronized clocks, immune to wall-clock / NTP jumps, standard approach for this class of system, matches what's already written into the paper (Fig. 2).

### D5 — Lamport clocks for ordering, not vector clocks or physical time
**Decision:** Use Lamport logical clocks on every node for vote/election/replication event ordering.  
**Why:** Sufficient for this system's needs (total ordering for tie-breaking and merge-sort during recovery); vector clocks would add complexity without a clear benefit here, and physical clocks can't be trusted to be synchronized across containers.

### D6 — Duplicate prevention: unique Vote ID + per-node replication, not a shared lock/queue
**Decision:** `vote_id = client_id:origin_node_id:lamport_ts`, enforced unique at the DB layer per node with explicit query-then-insert duplicate handling (no `INSERT IGNORE`).  
**Why:** Avoids needing a distributed lock or a single arbiter. Distinguishes idempotent replays (identical vote_id + payload) from conflicting double-voting attempts by the same client.

### D7 — Storage: MySQL, one instance per node (not shared, not MongoDB)
**Decision:** MySQL, one dedicated instance per node container (SQLite used for isolated automated test runs).  
**Why:**
- Storage must be per-node, never one shared instance for the whole cluster — a shared DB would recreate the exact single point of failure this project eliminates.
- Relational constraints (`PRIMARY KEY (vote_id)` and `UNIQUE KEY (client_id)`) enforce invariants directly in the storage engine.

### D8 — Backend language: Python
**Decision:** Python 3.11+ for node services.  
**Why:** Minimizes boilerplate for gRPC setup, lets the project focus on leader election and replication logic rather than language plumbing.

### D9 — Communication: gRPC for inter-node AND the primary RPC contract
**Decision:** All inter-node calls (heartbeat, election, replication) use gRPC with Protocol Buffers.  
**Why:** Strongly typed, language-neutral, contract-first interface (`proto/voting.proto`).

### D10 — Frontend: React, bridged via Flask REST (not direct gRPC-Web)
**Decision:** React client talks REST to a Flask layer, which forwards to gRPC on the coordinator node.  
**Why:** Direct gRPC-Web from React would require an Envoy proxy and more setup; Flask-as-bridge is simpler for a course-project timeline.

### D11 — Deployment: Docker Compose, single host, N app + N DB containers
**Decision:** One app container + one MySQL container per node; 3/5/7-node profiles via Compose.  
**Why:** Matches the paper's stated experimental setup (single Docker host, controlled failure injection via `docker stop`).

### D12 — Voter Identification: Free-text non-empty voter IDs (2026-10-02)
**Decision:** Free-text string for `client_id`, required to be non-empty and stripped of surrounding whitespace. Colons (`:`) are strictly rejected.  
**Why:** Eliminates the administrative burden of maintaining a pre-registered voter enrollment whitelist while preserving the deterministic receipt format `client_id:origin_node_id:lamport_ts` against splitting ambiguities.

### D13 — Tally Visibility: Real-time administrative tally (2026-10-02)
**Decision:** Every node may expose `GetResults`, but the Flask bridge and admin dashboard must resolve and query the current coordinator for the authoritative real-time tally. Replica results serve as recovery and verification data and may be stale before replication completes.  
**Why:** The coordinator is the authoritative source for the published tally within this project’s single-host, crash-fault model.

### D14 — Coordinator Discovery & Caching in Bridge (2026-10-02)
**Decision:** The Flask REST bridge caches the current coordinator's gRPC address. When a node returns `FAILED_PRECONDITION: not_coordinator:<id>`, the bridge updates its cache using the redirect hint.  
**Why:** Clients don't need a heavy service discovery mesh; follower redirection is fast and self-healing.

### D15 — Candidate List: Configured at startup (2026-10-02)
**Decision:** Fixed ballot choices configured via `CANDIDATES` environment variable (comma-separated, default: `Alice,Bob,Charlie`).  
**Why:** Simple, deterministic validation at admission control. Prevents arbitrary write injection.

### D16 — Testing Architecture: Subprocess and in-process gRPC integration (2026-10-02)
**Decision:** Multi-node cluster testing uses real gRPC channels over loopback ports with isolated SQLite database files per node, backed by live MySQL smoke tests in Docker.  
**Why:** Validates true network serialization, error codes, and thread concurrency without requiring heavy full-VM clusters for fast test feedback.

### D17 — State Recovery & SyncLog Architecture (2026-10-05)
**Decision:** Implement a dual-phase state recovery mechanism backed by a durable, append-only `sync_log` table:
1. **Local State Restoration:** Upon boot/restart, each node performs local log verification/restoration and restores its volatile in-memory `LamportClock` monotonically to `max(persisted_lamport_ts)`.
2. **Coordinator Remote Sync:** Newly elected coordinators transition to `RECOVERING`, poll surviving peers via the gRPC `SyncLog` RPC (`SyncRequest`/`SyncResponse`), merge missing committed votes deterministically sorted by `(lamport_ts, origin_node_id, vote_id)`, persist missing entries locally, replicate to out-of-sync peers, and transition to `COORDINATOR`.
3. **Execution Guard (`auto_recover`):** Default `auto_recover=False` preserves manual/test invocation guarantees for Phase 3 election tests, while `auto_recover=True` automates post-election catch-up and role promotion during live multi-process cluster failover.  
**Why:** In-memory Lamport clocks and unpersisted pending state are volatile across node crashes. Monotonic clock restoration prevents clock regression, while deterministic peer log synchronization ensures that unacknowledged or un-replicated committed votes survive coordinator failover without split-brain or duplicate ballot corruption.

### D18 — Recovery-Authority Rule, Ghost-Vote Prevention & Policy-Gated Promotion (2026-10-05)
**Decision:** Recovery promotion and vote acceptance must be policy-gated and strictly protected against resurrecting partial-finalization ghost votes:
1. **Recovery-Authority Rule:** A replica's status alone is never sufficient to make a vote authoritative.
   - If the supervising coordinator is present, the vote is authoritative if and only if the coordinator durably recorded `COMMITTED`. If coordinator is `PENDING`, the vote is rejected as an unacknowledged partial-finalization.
   - If the supervising coordinator is dead, unanimous agreement among surviving replicas without any `PENDING` records is required under the `all` policy. Any single replica with `PENDING` status proves finalization was incomplete and rejects the vote.
   - Unauthoritative ghost votes are demoted locally from `COMMITTED` to `PENDING` so they are never counted in tallies.
2. **Policy-Gated Promotion:** At recovery start, an immutable snapshot of target peers is taken. Promotion to `COORDINATOR` succeeds if and only if every peer in the snapshot succeeds (`all` policy) or quorum is satisfied (`majority` policy), and all repairs (`replicate_vote` and `finalize_vote`) complete without failure. If policy fails, the node remains in `RECOVERING`, continues rejecting votes, and logs `RECOVERY_FAILED`.
3. **Audit Trail & Conflict Preservation:** Recovery tracks and logs `accepted_votes_count`, `rejected_partial_finalizations_count`, and `client_id_conflicts_count`. Pre-existing committed votes are never overwritten by conflicting choices.  
**Why:** Guarantees zero phantom votes and strictly prevents unacknowledged client votes from being promoted after coordinator crash, maintaining the project's single-host crash-fault safety invariants.

### D19 — Flask REST Bridge Adapter & React UI Architecture (2026-10-05)
**Decision:** Build a thin Flask REST bridge (`api/`) as a strict adapter layer over `NodeRuntime`, and a modular React frontend (`frontend/`) communicating exclusively over HTTP/JSON:
1. **Zero Consensus Logic in Flask/React:** Consistently maintain that all distributed decisions (leader elections, failure detection, replication fan-out, two-phase finalization, recovery authority, and ghost-vote prevention) remain exclusively within the backend `NodeRuntime` and its subsystems. Flask merely maps HTTP requests to runtime methods and translates domain errors to appropriate HTTP status codes (201 Created, 400 Bad Request, 404 Not Found, 409 Conflict, 503 Service Unavailable).
2. **Committed-Only Tally Semantics:** `GET /api/votes/tally` strictly delegates to `db.get_tally()` and `db.count_votes(status="COMMITTED")`, guaranteeing that in-flight or abandoned `PENDING` votes never taint published results.
3. **No Direct Node/DB Access from UI:** React client communicates solely with `/api/...` endpoints on the bridge. The bridge forwards to the coordinator node and caches leader coordinates.
4. **Demonstrable Observability:** The React Admin/Voting UI provides dedicated interactive views for Dashboard, Voting (with ballot verification), Cluster Nodes Topology, Leader Election triggers/metrics, Phase 4 State Recovery audits (ghost-vote demotions, snapshot peer contacts), and Live Observability Events.  
**Why:** Maintains clean separation of concerns, guarantees that distributed invariants cannot be bypassed or compromised via the web layer, and provides full visual demonstrability of fault tolerance and consensus.

### D20 — Docker Containerization & Deployment Topology (2026-10-05)
**Decision:** Multi-stage Docker containerization combining the NodeRuntime daemon (gRPC + election/replication engines) and the Flask REST bridge daemon into a unified node container process model, backed by isolated per-node database state:
1. **Multi-Stage Build:** Stage 1 uses `node:20-alpine` to compile the React SPA into static production assets (`dist/`). Stage 2 uses `python:3.11-slim`, compiles Protobuf/gRPC stubs via `generate_proto.py`, packages backend Python dependencies, and serves both the gRPC service (default port 50051) and the Flask REST bridge + SPA (default port 5000).
2. **Deterministic Database Startup:** `DatabaseManager.initialize()` implements a 20-attempt connection retry loop with 1.0s backoff for MySQL, avoiding race conditions during container healthcheck initialization.
3. **Environment-Driven Configuration:** Peer topology, election algorithms, ports, and database credentials are strictly parsed from environment variables (`NODE_ID`, `PEER_CONFIGURATION` / `PEERS`, `GRPC_PORT`, `HTTP_PORT`, `ELECTION_ALGORITHM`, `REPLICATION_POLICY`, `DB_HOST`, `DB_PORT`, `DB_NAME`, etc.), eliminating hard-coded network addresses.
4. **Per-Node Database Isolation:** Every node container is paired with its own isolated database instance (e.g. dedicated MySQL container or persistent volume) ensuring zero shared-storage failure coupling across cluster members.
**Why:** Guarantees that containerized distributed nodes run the real multi-process distributed algorithms with clean service isolation, reproducible builds, and deterministic startup behavior.

### D21 — Three-Node Docker Compose Cluster Topology & Election Safety (2026-10-05)
**Decision:** Implement the 3-node distributed cluster via Docker Compose ([docker/docker-compose.3node.yml](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docker/docker-compose.3node.yml)) with physical database isolation and strict election safety:
1. **Network & Service Isolation:** Nodes communicate over Docker bridge network `voting-net` via stable DNS names (`node1:50051`, `node2:50051`, `node3:50051`). Host ports are uniquely allocated: HTTP APIs on ports `5001`, `5002`, `5003`; gRPC interfaces on ports `55051`, `55052`, `55053` (avoiding host port collisions with in-process test fixtures on `50051-50052`).
2. **Dedicated Storage Per Node:** Three independent MySQL 8 containers (`node1-db`, `node2-db`, `node3-db`) ensure true physical isolation where stopping or killing any node/database leaves peer databases unaffected.
3. **Bully Election Superseded-Candidate Guard:** In `BullyElection._run_algorithm()`, the winner transition verifies `state.win_election(new_term, initiator_id)`. If an announcement from a higher tuple `(term, initiator)` was accepted during the election window, `win_election` returns `False` and candidate victory is aborted, preventing split-brain coordinator overwrite.
4. **Higher-Node OK Suppression:** In `BullyElection.on_election_message()`, an alive node with a higher ID (`node_id > candidate_id`) unconditionally sends an `OK` reply (even if the incoming election term is stale), guaranteeing that the lower candidate suppresses victory and yields leadership.
5. **Heartbeat Higher-Term Yield:** In `HeartbeatMonitor.record_heartbeat()`, any node (even one previously acting as coordinator) yields to `FOLLOWER` upon receiving a valid heartbeat with a higher term (`election_term > current_term`), ensuring instant cluster convergence after failover.
**Why:** Guarantees absolute absence of split-brain coordinators, enables seamless dynamic failover and recovery across actual containers, and ensures clean test isolation.

### D22 — Five-Node Docker Compose Cluster Profile & Follower Auto-Sync (2026-10-07)
**Decision:** Implement the 5-node distributed cluster via Docker Compose (`docker/docker-compose.5node.yml`) with physical database isolation and automatic follower catch-up on rejoin:
1. **Five-Node Topology:** Five distributed application nodes (`node1`..`node5`) paired with five independent MySQL 8 containers (`node1-db`..`node5-db`) interconnected across isolated Docker bridge network `voting-net`. Host port mappings: HTTP APIs on ports `5001`–`5005`, gRPC interfaces on ports `55051`–`55055`, and MySQL databases on host ports `33061`–`33065`.
2. **Follower Rejoin Auto-Sync:** In `HeartbeatMonitor.record_heartbeat()`, a newly booted follower adopts the coordinator on its first accepted heartbeat (`_first_heartbeat_received`). When `AUTO_RECOVER=true`, this adoption triggers a background `AutoFollowerSync` thread that invokes `RecoveryManager.sync_with_cluster()`, automatically pulling and ingesting missing committed votes into the local MySQL database and `sync_log`.
3. **Quorum Under Majority Policy:** Under `REPLICATION_POLICY=majority`, a 5-node cluster requires $\lfloor 5/2 \rfloor + 1 = 3$ nodes. Tested and verified that even when two follower nodes crash, votes are admitted and committed across the surviving 3-node quorum, and the failed nodes catch up completely upon restarting.
**Why:** Confirms that the distributed consensus, replication, and election engines scale from 3 to 5 nodes with zero code degradation, fully automated recovery, and robust fault tolerance.

### D23 — Phase 6.7 Edge-Case Hardening & Multi-Node Cluster Stability (2026-10-08)
**Decision:** Harden the 5-node distributed cluster against edge-case race conditions, simultaneous follower rejoins, quorum boundary transitions, and coordinator failover during catch-up:
1. **First-Heartbeat Security & Authority Verification:** `HeartbeatMonitor.record_heartbeat()` enforces strict rejection of unauthorized sender IDs (`coordinator_id not in all_node_ids`), stale terms, and competing coordinators for equal terms before any coordinator adoption or `_on_coordinator_adopted` trigger.
2. **Follower Rejoin Latch Release:** When a higher coordinator suppresses a lower candidate's election message in `BullyElection.on_election_message()`, it sends `OK` and asynchronously delivers `announce_to_peer()`, allowing the recovering node to immediately adopt the coordinator without waiting for election retry timeouts.
3. **AutoFollowerSync Thread Safety:** Added `_sync_lock` in `NodeRuntime` to serialize cluster synchronization threads, preventing duplicate concurrent `sync_with_cluster` runs on rapid heartbeat intervals.
4. **Majority Quorum Boundary Invariance:** Formalized and verified the exact majority quorum boundary on 5 nodes ($Q = 3$): 3 alive nodes commit votes ($3 \ge 3$), 2 alive nodes strictly reject votes with HTTP 503 ($2 < 3$), preventing split-brain writes during network partitions. Rejoin restores quorum immediately.
5. **Coordinator Failover During Follower Catch-Up:** Verified that if a coordinator crashes while a recovering follower is synchronizing, the follower cleanly detects the crash, converges on the newly elected coordinator (Node 4), and synchronizes all missing committed votes from the new coordinator.
**Why:** Guarantees absolute edge-case stability, election convergence speed, and quorum safety across multi-container topologies under concurrent network jitter, container crash/restart, and split-second failovers.

### D24 — Phase 6.8 Seven-Node Docker Compose Cluster Profile & Scale Verification (2026-10-09)
**Decision:** Scale the distributed voting cluster to a 7-node topology (`docker/docker-compose.7node.yml`) and verify fault tolerance, leader election, quorum boundaries, and automated recovery across 14 containers:
1. **Seven-Node Topology:** Seven distributed application nodes (`node1`..`node7`) paired with seven dedicated MySQL 8 containers (`node1-db`..`node7-db`) interconnected across isolated Docker bridge network `voting-net`. Host port mappings: HTTP APIs on ports `5001`–`5007`, gRPC interfaces on ports `55051`–`55057`, and MySQL databases on host ports `33061`–`33067`.
2. **Physical Database Isolation:** Confirmed physical schema and storage isolation across all 7 MySQL instances via real-time probe insertion on `node1-db` and absence assertions across `node2-db` through `node7-db`.
3. **Leader Election at N=7:** Bully election verifies that upon coordinator failure, the highest surviving node (e.g. Node 6 when Node 7 fails) takes over smoothly and all surviving followers adopt the new coordinator with 0 split-brain. Ring election token traversal and victory announcement verified across 7 nodes.
4. **Majority Quorum Boundary for N=7:** Formalized and mathematically verified quorum requirement $Q = \lfloor 7/2 \rfloor + 1 = 4$:
   - 7, 6, 5, 4 alive nodes meet majority ($4 \ge 4$) $\rightarrow$ votes commit.
   - 3 alive nodes strictly fail quorum ($3 < 4$) $\rightarrow$ votes rejected with HTTP 503, preventing partition divergence.
5. **Replication & Recovery:** Verified `ALL` replication policy across all 7 databases. Follower crash and multi-follower simultaneous crash tested: coordinator continues admitting writes to surviving active peers, and rejoined followers automatically synchronize missing committed votes via `AutoFollowerSync`.
6. **Frontend & REST Bridge:** Verified compiled React SPA and REST endpoints served natively on Node 7.
7. **Regression Suite:** 211 tests collected: 189 passed, 22 profile-specific skips (8 single-node + 5 three-node + 9 five-node), 0 failures, 0 errors.
**Why:** Proves that the distributed architecture, replication consensus, Bully/Ring election algorithms, and AutoFollowerSync catch-up scale seamlessly from 5 nodes to 7 nodes with zero architectural redesign and complete fault-tolerance invariants intact.

### D25 — Phase 6.9 Final Multi-Cluster Deployment & Regression Verification (2026-10-09)
**Decision:** Execute comprehensive sequential multi-cluster deployment and regression audit across all four Docker profiles (single-node, 3-node, 5-node, and 7-node) and the entire non-Docker unit/integration test suite:
1. **Sequential Profile Verification:** Each profile was spun up in isolation, verified against its live containers, and cleanly torn down:
   - Single-Node Profile (`docker-compose.single.yml`): 8/8 passed (100%).
   - Three-Node Profile (`docker-compose.3node.yml`): 5/5 passed (100%).
   - Five-Node Profile (`docker-compose.5node.yml`): 9/9 passed (5 cluster + 4 edge cases, 100%).
   - Seven-Node Profile (`docker-compose.7node.yml`): 10/10 passed (100%).
2. **Non-Docker Regression Suite:** All 179 non-Docker unit, integration, Lamport clock, MySQL smoke, recovery, replication, and election correctness tests passed (179/179 passed, 32 deselected Docker tests, 0 failures, 0 errors).
3. **Audit Coverage Matrix:** Across all targeted executions, all 211 unique tests in the codebase were executed against their respective target environments with a 100% pass rate. When the full test suite runs against the active 7-node cluster, exactly 22 expected profile-specific guard skips occur for the other inactive cluster configurations.
4. **Production Code Zero-Mutation Freeze:** Confirmed zero modifications to production code; all consensus protocols, Recovery-Authority rules, PENDING/COMMITTED semantics, and Bully/Ring election algorithms remain frozen and fully backward-compatible across $N=1, 3, 5, 7$.
5. **Phase Gate:** PHASE 6.9 APPROVED & FROZEN. Phase 6 is formally concluded; recommended progression to Phase 7 (controlled fault injection and performance experiments).
**Why:** Confirms that all Docker compose topologies deploy reliably, isolate databases physically, converge rapidly, and satisfy every fault-tolerance guarantee established across Phases 1 through 6.8.

### D26 — Phase 7.1 Experimental Design for Controlled Fault Injection & Benchmarks (2026-10-09)
**Decision:** Formalize a rigorous, reproducible experimental methodology for benchmarking and fault injection across $N \in \{3, 5, 7\}$, Bully vs Ring algorithms, and `ALL` vs `MAJORITY` replication policies:
1. **Zero Production Mutation:** Architecture is strictly preserved: React → Flask REST bridge → NodeRuntime → gRPC nodes → isolated per-node MySQL databases. All consensus protocols and Recovery-Authority invariants remain 100% frozen.
2. **Deterministic Metric Boundaries:** High-resolution client commit latency ($p50, p95, p99$, mean, $\sigma$) using `time.perf_counter()`; election convergence latency; write-readiness downtime; and exact logical message overhead ($M_{\text{election}} + M_{\text{ok}} + M_{\text{coord}}$).
3. **Environment Adaptation:** Explicitly avoid unsupported and unsafe Linux `tc/netem` in Windows Docker Desktop; instead use native, portable Docker container crashes (`docker stop -t 1`), rejoins (`docker start`), and bridge network partitions (`docker network disconnect/connect voting-net`).
4. **Safety & Invariant Gates:** Automated assertions for zero lost writes, zero duplicate client submissions, single coordinator authority, and tally mathematical integrity on every run.
**Why:** Establishes academic rigor, repeatable measurements, and explicit scientific boundary definitions prior to executing benchmark runs.

### D27 — Phase 7.2 Modular Experimentation Framework & Tooling (2026-10-09)
**Decision:** Implement a modular, object-oriented experimental framework in `experiments/` with zero mutation to existing production services:
1. **Package Architecture:** Organized into `config/` (cluster profiles, port maps, matrix catalog), `core/` (ClusterManager, FaultInjector, WorkloadClient, TelemetryCollector), `runners/` (`run_benchmark`, `run_fault_experiment`, `run_matrix`), and `analysis/` (`aggregate_metrics`, `generate_charts`).
2. **High-Precision Workload Client:** `WorkloadClient` manages thread pools for concurrent load ($C=5, 10$), executes warmup discarding, and calculates exact percentiles ($p50, p90, p95, p99$) with sub-millisecond precision.
3. **Safe Fault Injector:** `FaultInjector` tracks all mutated container states and guarantees complete rollback in `finally` blocks via `revert_all_faults()`.
4. **Self-Contained Visualization & Aggregation:** `generate_charts` generates dark-themed publication SVG charts with zero external GUI dependencies. `aggregate_metrics` computes means, sample standard deviations, and 95% confidence intervals across repeated trials ($K \ge 3$).
5. **Regression Verification:** Full test suite expanded to 221 tests (including 10 framework unit tests in `tests/test_experiments_framework.py`), passing with 100% success rate (182 passed, 39 container skips, 0 failures).
**Why:** Provides an automated, robust, and clean command-line harness that eliminates manual ad-hoc testing and enables push-button reproduction of the entire research study.

### D28 — Phase 7.1 Review: Quorum Formalization, Identity Parity & Tail Rigor (2026-10-09)
**Decision:** Revise experimental design and assertion rules to eliminate scalar count masking, quantile estimator distortion, and arbitrary convergence criteria:
1. **Three-Tier Quorum & Membership Model:** Formally distinguish Configured Static Membership ($M_{\text{static}}$), Active Peer Snapshot ($S_{\text{snapshot}}$), and Responsive Replicas ($R_{\text{acked}}$). Enforce that under `majority`, commit condition $(1 + |R_{\text{acked}}|) \ge \lfloor |M_{\text{static}}|/2 \rfloor + 1$ is immutable and cannot shrink due to unreachable peers.
2. **Exact Identity Parity:** Consistency assertions upgrade from scalar tally equality (`count == 50`) to full set equality of committed vote tuples: $\text{Set}(V_{\text{leader}}) \equiv \text{Set}(V_{\text{replica}})$ across vote ID, client ID, choice, and Lamport timestamp.
3. **Two-Tier Workload & NDJSON Trace Preservation:** Split workloads into Tier 1 (smoke validation: 200 requests) and Tier 2 (empirical benchmarks: $\ge 1,000$ requests to reduce $p99$ order statistic variance). Preserve raw per-request latency observations in NDJSON format.
4. **Separation of Safety Gates from Performance Baselines:** Safety invariants (0 lost votes, 0 duplicates, 0 ghost votes, single leader) remain strict hard failure gates. Performance criteria (write readiness $3.5\text{s}-5.5\text{s}$) are evaluated against empirical baselines derived from `heartbeat_timeout_ms=3000ms`.
5. **Docker Bridge Partition Realities:** Document that Docker port publishing (`-p 500X:5000`) allows host clients to probe partitioned containers directly, verifying that isolated minority coordinators reject writes with HTTP 503 while majority partitions sustain commits.
**Why:** Guarantees publication-level scientific rigor, eliminates split-brain blind spots, and aligns experimental boundaries with true timeout mechanics.

### D29 — Phase 7.2A High-Precision Workload Client & Raw NDJSON Schema (2026-10-10)
**Decision:** Implement the dedicated, high-precision benchmark workload client and raw-data schema with zero production mutations:
1. **Workload Client Architecture:** `WorkloadClient` uses `time.perf_counter()` for sub-millisecond request latency measurement and `time.time()` for wall-clock start/end timestamps.
2. **Strict Identity & Duplicate Rules:** Generates colon-free, globally unique client identities (`generate_client_id`) adhering to `VoteService` uniqueness and receipt delimiter rules.
3. **Warm-Up Isolation:** Dedicated warm-up phase cleanly separated from measured benchmark metrics. Warm-up observations are tagged with `is_warmup=True` and completely excluded from latency percentiles ($p50, p95, p99$) and throughput metrics.
4. **Per-Request NDJSON Schema:** Emits one valid JSON object per request to `experiments/results/raw/` containing `req_id`, `client_id`, `choice`, `start_time`, `end_time`, `latency_ms`, `status_code`, `success`, `vote_id`, `lamport_ts`, `error`, and `is_warmup`.
5. **Machine-Readable Summary:** Generates structured summary with attempted requests, successful commits, rejections (400/409/503), transport failures, duration, throughput, and percentiles ($p50, p90, p95, p99$, mean, $\sigma$, min, max).
6. **Regression Verification:** Added 14 unit tests in `tests/test_workload_client.py`. Full test suite expanded to 235 tests, passing with 100% success rate on executed tests under Python 3.11.9 (196 passed, 39 container skips, 0 failures, 0 errors).
**Why:** Establishes the foundational benchmark client and data logging schema required for repeatable, statistically sound workload generation before starting fault injection.

### D30 — Phase 7.2A Minimal Audit: TypeError Retry Elimination & Streaming NDJSON Persistence (2026-10-11)
**Decision:** Audit and remediate workload client execution safety and streaming persistence:
1. **Elimination of Broad TypeError Fallback:** Removed the runtime `except TypeError:` retry fallback in `_worker()` and warm-up loops that risked duplicate network vote submissions if an internal error occurred within `submit_single_vote`. Replaced with static upfront callable signature inspection (`_inspect_signature_supports_rich_args`), determining argument support prior to invocation without any retry fallback.
2. **Streaming NDJSON Persistence:** Implemented `ThreadSafeNDJSONWriter` with internal mutex lock. Rather than buffering all records in memory until benchmark conclusion, each completed request is atomically serialized, written as a single line, and immediately pushed to the operating system kernel page cache via `file.flush()`.
3. **Partial-Run Trace Preservation:** Ensured `finally: writer.close()` guarantees file integrity on premature aborts (e.g. SIGINT/KeyboardInterrupt). Verified partial runs retain all requests completed prior to termination.
4. **Crash Safety Boundary Documentation:** Documented the deliberate tradeoff between process-level safety (`file.flush()`) and storage-level safety (`os.fsync()`), establishing that per-request hardware fsyncs are intentionally omitted to avoid contaminating network benchmark latency percentiles with multi-millisecond disk I/O bottlenecks.
5. **Regression Verification:** Added regression test proving internal `TypeError` never triggers a second submission, stress test proving concurrent multi-threaded write integrity across 10 threads, and partial-run persistence test. Suite expanded to 238 tests, passing 100% on executed tests under Python 3.11.9 (199 passed, 39 container skips, 0 failures, 0 errors).
**Why:** Guarantees absolute network idempotency under internal handler errors and prevents benchmark trace loss during aborted or crashed runs without sacrificing microsecond latency precision.

### D31 — Phase 7.2B Cluster Manager, Fault Injector & Controlled Live Docker Validation (2026-10-11)
**Decision:** Complete, audit, and harden Phase 7.2B Cluster Manager and Fault Injector abstractions without modifying production code under `node/` or `api/`:
1. **Full Profile Support & Project Scoping:** Supported all configured Docker profiles: 1-node (`docker/docker-compose.single.yml`), 3-node (`docker/docker-compose.3node.yml`), 5-node (`docker/docker-compose.5node.yml`), and 7-node (`docker/docker-compose.7node.yml`). Added optional `project_name` scoping to isolate experiments from default or developer compose projects.
2. **Dynamic Container & Network Resolution:** Upgraded `ClusterManager` and `FaultInjector` to query Compose configuration (`docker compose config --format json`) and container network inspects rather than relying on brittle hardcoded network assumptions. Correctly resolves Compose project-prefixed bridge networks (e.g., `docker_voting-net`).
3. **True Distributed Cluster Convergence:** Enhanced `ensure_cluster_settled()` with `check_cluster_converged()`. Verifies not merely that a coordinator claims to accept votes, but that exactly one coordinator exists and all reachable peers mutually agree on `coordinator_id`. Captures structured diagnostic telemetry (`last_diagnostics`, `get_diagnostic_summary()`) upon settlement failure.
4. **Error-Preserving Fault State & Safe Ordered Cleanup:** In `revert_all_faults()`, failed container restorations are retained in active fault sets (`_paused_nodes`, `_disconnected_nodes`, `_stopped_nodes`) and reported in `cleanup_report["errors"]` rather than silently forgotten. Recovery executes in strict dependency order: unpause $\to$ reconnect network $\to$ start container.
5. **Controlled Live Docker Validation:** Executed live Docker validation across single-node and 3-node profiles:
   - *1-Node:* Profile up $\to$ health $\to$ coordinator settled $\to$ teardown $\to$ zero resource leak.
   - *3-Node:* Profile up $\to$ initial coordinator elected (Node 3) $\to$ pause fault injected on Node 2 $\to$ fault confirmed observable (Node 2 timed out) $\to$ unpause recovery $\to$ cluster re-converged on Node 3 $\to$ teardown.
   - *Resource Isolation:* Inspected container, network, and volume states before and after. Exactly zero unrelated containers, networks, or volumes were affected.
6. **Regression Verification:** Added 4 new unit tests (20 total in `tests/test_cluster_and_fault_manager.py`). Full regression suite expanded to **258 collected items (219 passed, 39 container skips, 0 failures, 0 errors)** under Python 3.11.9.
**Why:** Guarantees airtight resource isolation, dynamic network compatibility, observable fault recovery, and deterministic cluster convergence prior to telemetry and full benchmark orchestration.

### D32 — Phase 7.2C Telemetry Collector & Experiment Orchestration (2026-10-11)
**Decision:** Implement continuous background telemetry collection and end-to-end experiment orchestration without touching production code under `node/` or `api/`:
1. **Continuous Container Telemetry Sampler:** Implemented `ContainerTelemetrySampler` in `experiments/core/telemetry_collector.py`. Spawns a background thread that periodically samples container metrics via `docker stats --no-stream` and fallback `docker inspect` for paused/stopped containers (using robust `|||` delimiter parsing). Atomically streams per-sample measurements to `_telemetry.ndjson` with immediate OS buffer flushing.
2. **Explicit Measurement Boundaries:** Strictly records genuine Docker runtime measurements: CPU%, memory usage (bytes), memory limit (bytes), memory %, network RX/TX (bytes), container status, restart count, and healthcheck status. Explicitly marks unavailable internal measurements (`grpc_internal_queue_depth`, `lock_wait_nanoseconds`) in every sample record and aggregate summary rather than fabricating estimates.
3. **Experiment Runner & Strict Lifecycle Ordering:** Implemented `ExperimentConfig` and `ExperimentRunner` in `experiments/core/experiment_runner.py`. Executes the strict 10-step lifecycle:
   1. Parameter validation (`ExperimentConfig.validate()`).
   2. Collision-safe run ID and output directory creation.
   3. Scoped cluster startup via `ClusterManager`.
   4. Cluster healthcheck and mutual peer convergence gate (`ensure_cluster_settled()`).
   5. Background continuous telemetry sampling start.
   6. Workload execution via `WorkloadClient` (`run_workload`/`run_benchmark`).
   7. Fault injection scenario execution (`coord_crash`, `follower_crash`, `pause_node`, `network_partition`, `follower_rejoin`).
   8. Application safety invariant harvest via `TelemetryCollector` (`harvest_cluster_telemetry()`).
   9. Guaranteed cleanup in `finally` block: stop telemetry sampler $\to$ revert all injected faults $\to$ teardown cluster with volume purging.
   10. Machine-readable artifact manifest (`manifest.json` with SHA-256 and line counts) and experiment summary (`summary.json`) generation.
4. **Partial Failure Artifact Preservation:** Guarantees that aborts, unexpected exceptions, or invariant violations preserve all completed request traces and telemetry samples on disk, recording `status="FAILED"` in `summary.json` and indexing them in `manifest.json`.
5. **Controlled Live Docker Validation:** Executed end-to-end live Docker smoke test (`SMOKE-72C`) on a single-node cluster. Successfully started cluster $\to$ settled coordinator on port 5000 $\to$ captured continuous telemetry $\to$ executed 5 requests (29.56 ops/sec, p50=34.66ms) $\to$ confirmed tally and invariants $\to$ generated SHA-256 checksummed manifest $\to$ verified zero residual containers or networks.
6. **Regression Verification:** Added 15 new unit tests across `tests/test_telemetry_collector.py` and `tests/test_experiment_runner.py`. Full test suite expanded to **273 collected items (234 passed, 39 container skips, 0 failures, 0 errors)** under Python 3.11.9.
**Why:** Provides an automated, fully reproducible, collision-safe, and crash-resilient harness for conducting controlled distributed systems experiments with verified data integrity.

### D33 — Phase 7.3 Full Experimental Matrix Execution & Statistical Analysis (2026-10-11)
**Decision:** Execute the full factorial experiment catalog (EXP-01 through EXP-09) across 3, 5, and 7-node topologies comparing Bully vs Ring and ALL vs MAJORITY under baseline and advanced fault injection scenarios:
1. **Full Factorial Execution (99 Trials):** Executed all 33 distinct experimental configurations across 3 independent trials each in three project-scoped batches: Batch 1 (Baselines EXP-01 to EXP-04), Batch 2 (Crash failures EXP-05 and EXP-06), Batch 3 (Advanced faults EXP-07, EXP-08, EXP-09). Total execution time: 4587.7 seconds.
2. **Empirical Distributed Findings:**
   - *Failover Downtime:* Bounded between $3.36\text{s} - 3.81\text{s}$, strictly dominated by the $3000\text{ms}$ heartbeat timeout, with immediate post-election write readiness ($35-95\text{ms}$).
   - *Message Complexity:* Empirically confirmed quadratic $O(N^2)$ scaling for Bully ($5 \to 19 \to 40.3$ msgs for $N=3,5,7$) and linear $O(N)$ scaling for Ring ($10.7 \to 23.7 \to 33.3$ msgs).
   - *Throughput Scaling:* Monotonically decreases with cluster size due to quorum fanout ($31-39$ ops/s at $N=3$, down to $18-20$ ops/s at $N=7$).
   - *Fault Invariants:* 100% minority partition rejection under majority quorum (EXP-09); clean cascading failover across two consecutive crashes (EXP-07); and full database WAL catch-up in $\approx 2.3\text{s}$ upon follower rejoin (EXP-08).
3. **Failure Accounting & Windows Port Settle Buffer:** Retained all trial records in full. Two trials in EXP-04 $N=5$ encountered transient host port `55054/tcp` bind collisions during rapid sequential Docker spin-up on Windows. Added a 2.0s inter-trial settlement grace period, eliminating host port bind collisions for all subsequent batches. Zero failed trials were discarded or hidden.
4. **Statistical Rigor:** Evaluated Student's $t$ CI95 confidence intervals and non-parametric order-statistic percentiles ($p50, p90, p95, p99$), distinguishing warm-up from measured requests.
5. **Zero Production Mutation:** Zero changes made to production code in `node/` or `api/`. All regression tests pass (235 passed, 39 container skips, 0 failures, 0 errors).
**Why:** Establishes definitive, reproducible, empirical evidence of consensus, election, and replication tradeoffs while proving invariant safety across all failure scenarios.

### D34 — Phase 8 Release Freeze, Forensic Audit & Safe Packaging (2026-10-12)
**Decision:** Formalize release freeze and packaging for final evaluation without altering production code or database schemas:
1. **Production Code Freeze:** Code under `node/` and `api/` is strictly frozen. All consensus, election, replication, and recovery invariants are preserved.
2. **Forensic Audit & Statistical Reconciliation:** Reconciled the 99-trial matrix across all 33 configurations. Reconciled $T_{\text{failover}}$ (crash-to-election downtime: $3.0\text{s}-3.7\text{s}$) with post-election write probe readiness ($\Delta T = 39.8\text{ms}-97.9\text{ms}$). Accounted for valid trial throughput ($17.67\text{ ops/s}$ on $K_{\text{valid}}=1$) in EXP-04 $N=5$ rather than averaging with zero.
3. **Evidence Distinction:** Explicitly distinguish observed empirical measurements across the tested scenarios (e.g. no lost votes or split-brain observed across 97 passing trials) from universal theoretical guarantees.
4. **Packaging & Ignore Rules:** Updated `.gitignore` to comprehensively exclude virtual environments, caches, local databases (`*.db`, `*.db-wal`, `*.db-shm`), temporary scratch files, and frontend `node_modules/` while explicitly preserving benchmark summaries (`benchmark_summary.csv`).
5. **Regression Verification:** Verified 274 collected tests (235 passed, 39 container skips, 0 failures, 0 errors).
**Why:** Ensures reproducible project delivery, transparent failure accounting, and safe packaging for academic evaluation and live demonstration.

---

## Resolved Questions
- **Voter eligibility**: Resolved by D12 (Free-text non-empty voter ID, no colons).
- **Tally visibility**: Resolved by D13 (Real-time live query via `GetResults`).
- **Coordinator discovery**: Resolved by D14 (Redirect hints with bridge-side caching).
- **Candidate configuration**: Resolved by D15 (Environment variable `CANDIDATES`).
- **State recovery & log replay**: Resolved by D17 (Durable `sync_log`, monotonic Lamport clock restoration, deterministic merge sorting, and gRPC `SyncLog` catch-up).
- **Ghost-vote prevention & policy gating**: Resolved by D18 (Explicit Recovery-Authority Rule, local ghost demotion, and immutable snapshot policy-gated promotion).
- **REST bridge and web architecture**: Resolved by D19 (Flask-as-adapter pattern, committed-only tally, and React single-page UI).
- **Docker process model & database topology**: Resolved by D20 (Multi-stage Dockerfile, unified gRPC+Flask runtime, and isolated per-node MySQL containers).
- **Cluster failover & split-brain prevention**: Resolved by D21 (Superseded candidate guard, higher-node OK suppression, and higher-term heartbeat yielding).
- **Five-node scaling & follower rejoin**: Resolved by D22 (5-node Compose profile, majority quorum tolerance, and first-heartbeat auto-sync).
- **Edge-case hardening & multi-node failure recovery**: Resolved by D23 (First-heartbeat authority verification, bully latch release, sync thread safety, and majority quorum boundary verification).
- **Seven-node scaling & majority quorum boundary ($Q=4$)**: Resolved by D24 (7-node Compose profile, physical database isolation, Bully/Ring scaling, $Q=4$ majority boundary, and 211-test regression verification).
- **Multi-cluster deployment & final release audit**: Resolved by D25 (Sequential verification of all 4 Docker profiles, 211/211 unique test execution, zero code mutations, and formal release gate approval).
- **Phase 7 experimental methodology & metric boundaries**: Resolved by D26 (Factorial matrix, non-parametric percentiles, and Windows Docker Desktop compatibility).
- **Phase 7 automated experiment framework & statistical tooling**: Resolved by D27 (Modular `experiments/` framework, WorkloadClient, FaultInjector, TelemetryCollector, and 221-test regression suite).
- **Phase 7 experimental corrections & identity parity**: Resolved by D28 (Three-tier quorum model, exact vote identity parity, NDJSON trace preservation, and two-tier workload sizing).
- **Phase 7.2A workload client & raw NDJSON schema**: Resolved by D29 (WorkloadClient, colon-free unique identities, warm-up separation, raw NDJSON schema, collision protection, 235-test regression suite under Python 3.11).
- **Phase 7.2A minimal final audit & streaming persistence**: Resolved by D30 (TypeError retry elimination, ThreadSafeNDJSONWriter, crash safety boundaries, 238-test regression suite under Python 3.11.9).
- **Phase 7.2B cluster manager & fault injector**: Resolved by D31 (Full 1/3/5/7-node profile support, two-stage readiness gates, diagnostic capture, target validation, context manager cleanup, 254-test regression suite under Python 3.11.9).
- **Phase 7.2C telemetry collector & experiment orchestration**: Resolved by D32 (Continuous ContainerTelemetrySampler, strict 10-step lifecycle ExperimentRunner, SHA-256 artifact manifest, 273-test regression suite under Python 3.11.9).
- **Phase 7.3 full experimental matrix execution & statistical analysis**: Resolved by D33 (Full factorial 99-trial execution of EXP-01 through EXP-09, Student's t CI95, empirical message complexity validation, zero safety violations, 274-test regression suite under Python 3.11.9).
- **Phase 8 release freeze, forensic audit & documentation packaging**: Resolved by D34 (Release audit, reconciled statistical metrics, updated comprehensive README, .gitignore packaging, verified 235-test regression suite under Python 3.11.9).




