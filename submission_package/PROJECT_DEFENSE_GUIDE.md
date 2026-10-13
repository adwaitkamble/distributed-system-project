# Final Project Defense & Viva Voce Guide
## Distributed Fault-Tolerant Voting System with Pluggable Leader Election

**Target Academic Assessment:** B.Tech Computer Engineering Capstone Oral Defense  
**Institution:** Pimpri Chinchwad College of Engineering (PCCoE), Pune — Savitribai Phule Pune University (SPPU)  
**Authors:** Adwait Kamble [123B1D002], Advait Nathe [123B1D029], Nikhil Puppalwar [123B1D040]  
**Faculty Guide:** Mr. Ganesh Deshmukh  
**Date:** October 2026  

---

## 1. Two-Minute Elevator Pitch / Project Introduction

> *"Good morning, respected examiners and faculty members. Our capstone project presents a **Distributed Fault-Tolerant Voting System with Pluggable Leader Election**.
>
> In conventional electronic polling systems, a centralized server is a single point of failure. If that server crashes during voting, the entire election is suspended, and uncommitted votes can be permanently lost.
>
> To solve this fundamental problem, our project distributes polling across symmetric, containerized nodes running in Docker. Each node maintains its own independent physical MySQL database—there is **zero shared storage**. The nodes communicate over high-performance gRPC, elect an active coordinator dynamically using pluggable **Bully** or **Ring** election algorithms, and order all distributed events deterministically using **Lamport logical clocks**.
>
> Ballots are replicated using two-phase replication with **Majority Quorum** consensus, ensuring that as long as a majority of nodes are alive, the system continues accepting votes without interruption. If the coordinator crashes, surviving nodes detect missing heartbeats using a monotonic timer latch and automatically elect a successor within approximately 3.1 seconds, achieving write-readiness in less than 100 milliseconds. When the crashed node recovers, our **AutoFollowerSync** protocol automatically reconciles missing votes to achieve 100% database write-ahead log parity.
>
> We evaluated our system across 3, 5, and 7-node cluster topologies through a rigorous 99-trial factorial benchmark campaign. Across all 97 successful trials, we observed **zero lost votes, zero duplicate votes, zero ghost votes, and zero split-brain states**, empirically verifying the fault-tolerance guarantees of our design."*

---

## 2. Problem Statement & Research Motivation

* **The Problem:** Centralized polling systems suffer from:
  1. *Single Point of Failure (SPOF):* Hardware or OS panics cause prolonged service outages.
  2. *Data Loss Risk:* In-flight votes buffered in volatile server memory are lost upon sudden crash.
  3. *Split-Brain Vulnerability:* Naive replication without quorum consensus can create conflicting tallies across surviving partitions.
* **The Research Motivation:** Provide a concrete, observable, and measurable implementation of foundational distributed systems concepts (leader election, logical clocks, failure detection, and quorum replication) within an interactive web application that students and evaluators can inspect in real time.

---

## 3. Architecture Overview

The system operates across three cohesive tiers:
1. **Client Tier:** React 18 Single-Page Application (Vite + Tailwind CSS) providing real-time cluster topology maps, ballot casting, and live verified tallies.
2. **Application & Protocol Tier:**
   * *Flask REST Bridge:* Hosted on each node's local HTTP port (5001–5007), providing RESTful endpoints (`/api/node`, `/api/votes`, `/api/votes/tally`) and proxying client writes to the coordinator.
   * *NodeRuntime & gRPC Server:* Houses the core state machine, pluggable election engines (`node/election/`), monotonic heartbeat detector (`node/heartbeat.py`), and Lamport clock manager (`node/lamport.py`). Inter-node communication runs on gRPC port `50051`.
3. **Storage Tier:**
   * Dedicated MySQL 8.0 instances (`voting-node{id}-db`) per node with zero shared storage volumes. Enforces atomic uniqueness on `client_id` and durable audit trails via `sync_log`.

---

## 4. Algorithmic Comparisons & Core Mechanisms

### 4.1 Bully Algorithm vs. Ring Algorithm
| Feature | Bully Algorithm [12] | Ring Algorithm [13] |
|---|---|---|
| **Topology** | Fully connected mesh | Logical unidirectional sorted ring |
| **Selection Criterion** | Highest node ID wins immediately | Highest node ID in circulated token list |
| **Message Complexity** | Worst-case quadratic $O(N^2)$ | Strictly linear $O(N)$ |
| **Observed Message Counts (EXP-05)** | $N=3: 5.0$, $N=5: 19.0$, $N=7: 40.3$ | $N=3: 10.7$, $N=5: 23.7$, $N=7: 33.3$ |
| **Crossover Insight** | Bully is faster and leaner in small clusters ($N \le 5$), but Ring scales significantly better at $N=7$ ($33.3$ vs $40.3$ msgs). | Ring avoids message storms by circulating single tokens. |

### 4.2 Replication Policies: ALL vs. MAJORITY
* **Strict All-Replication (`all`):** Quorum requires $Q = N$ acknowledgments. Fails immediately if even a single follower crashes ($F = 0$), prioritizing absolute universal consensus over availability.
* **Majority Quorum (`majority`):** Quorum requires $Q = \lfloor N/2 \rfloor + 1$ acknowledgments. Tolerates up to $F = \lfloor (N - 1)/2 \rfloor$ crash failures ($1$ crash in 3-node, $2$ in 5-node, $3$ in 7-node). Sustains live write commits during node failures.

### 4.3 Vote Commitment & Tally Semantics
1. Client submits ballot $\to$ coordinator stages local record as `PENDING`.
2. Coordinator fans out gRPC `ReplicateVote` RPCs to followers.
3. Followers validate candidate and uniqueness, staging locally as `PENDING`.
4. When quorum ACKs are received, coordinator promotes status to `COMMITTED` and returns HTTP 201 with signed receipt (`vote_id = client_id:origin:lamport_ts`).
5. **Ghost-Vote Absence:** Uncommitted `PENDING` votes are strictly excluded from `/api/votes/tally`.

### 4.4 Failure Detection & State Catch-up
* **Failure Detection:** 500ms coordinator heartbeat broadcast; followers detect crash via monotonic clock latch (`time.monotonic() - last_hb >= 3000ms`).
* **AutoFollowerSync:** Upon reconnecting, recovering followers query the coordinator with their local maximum Lamport timestamp: `SyncLog(from_lamport_ts)`. The coordinator returns all missing committed ballots, which the follower ingests idempotently before marking its state `ONLINE`.

---

## 5. Summary of Empirical Findings (Phase 7 & Phase 8)

| Metric / Dimension | Empirical Finding | Source / Experiment |
|---|---|---|
| **Failover Downtime ($T_{\text{failover}}$)** | $2.95\text{s} - 3.68\text{s}$ (Mean across topologies: $\approx 3.15\text{s}$) | EXP-05 & Phase 8.5 Live Demo |
| **Post-Election Write Readiness** | $39.8\text{ms} - 97.9\text{ms}$ following victory broadcast | EXP-05 ($N=3,5,7$) |
| **Steady-State Throughput** | $32.28$ ops/s ($N=3$) $\to 23.20$ ops/s ($N=5$) $\to 19.72$ ops/s ($N=7$) | EXP-01 (Bully ALL) |
| **State Catch-up Duration** | $2.26\text{s} - 2.29\text{s}$ to restore 100% database WAL parity | EXP-08 & Phase 8.5 Live Demo |
| **Split-Brain Tolerance** | 100% minority partition rejection; 0 split-brain tallies | EXP-09 (Network Partition) |
| **Safety Invariants Observed** | **0 lost votes, 0 double-counted ballots, 0 ghost votes** | 97 Passing Trials |
| **Automated Regression Suite** | **242 passed, 32 container skipped, 0 failed, 0 errors** | Pytest Suite Execution |

---

## 6. Top 20 Viva Questions & Expert Model Answers

### Q1: Why did you implement both Bully and Ring algorithms instead of choosing one?
**Answer:** The primary academic objective of this research is an empirical comparison of leader election trade-offs. Implementing both algorithms with identical gRPC transports allowed us to isolate the algorithmic message complexity under identical workloads across 3, 5, and 7-node clusters, empirically observing where the theoretical $O(N)$ vs $O(N^2)$ message crossover manifests under our evaluated topologies.

### Q2: How does your system prevent two nodes from believing they are both coordinator (split-brain)?
**Answer:** We prevent split-brain through three complementary mechanisms:
1. *Strict Majority Quorums:* A coordinator can only commit a vote if it receives $\lfloor N/2 \rfloor + 1$ acknowledgments. In any network partition, only one partition can contain a majority.
2. *Higher-Term Supression:* Heartbeats and election messages carry monotonic term numbers. Any node receiving a heartbeat from a coordinator with a higher or equal term yields immediately.
3. *Higher-ID OK Suppression in Bully:* A candidate yields if any higher-numbered node answers its election probe.

### Q3: Why did you use Lamport logical clocks instead of physical UTC timestamps?
**Answer:** Physical clocks in distributed systems drift and cannot be perfectly synchronized without specialized hardware like GPS or atomic clocks (as in Google Spanner). NTP adjustments can cause wall-clock time to jump backwards, violating monotonicity. Lamport logical clocks provide provable causal ordering ($e_1 \to e_2 \implies L(e_1) < L(e_2)$) and deterministic tie-breaking without relying on physical clock synchronization.

### Q4: What happens if the coordinator crashes while replicating a vote to followers?
**Answer:** The staged vote remains in status `PENDING`. Because the coordinator crashed before receiving quorum acknowledgments, it never returned an HTTP 201 receipt to the voter. When a new coordinator is elected, it only considers `COMMITTED` votes valid. The client receives a connection timeout and retries. If the retry reaches the new coordinator, it processes the ballot cleanly. The `PENDING` ghost vote on surviving followers is reconciled or superseded during recovery.

### Q5: How do you prevent a voter from voting twice?
**Answer:** Dual-layer enforcement:
1. *Application Layer:* `vote_id = client_id:origin_node_id:lamport_ts`. If the identical ballot is re-sent, the system recognizes an idempotent replay and returns the original receipt.
2. *Database Layer:* Each node's `votes` table defines `UNIQUE KEY (client_id)`. If a voter attempts to submit a different candidate choice with the same `client_id`, MySQL rejects the second transaction with a duplicate key error, which the Flask bridge returns as an HTTP 409 Conflict.

### Q6: Why did you isolate MySQL per container instead of using a single shared database?
**Answer:** A shared database would recreate the exact single point of failure this project eliminates. If multiple application nodes connect to one database server, a database crash halts the entire system regardless of how many application replicas exist. Physical database isolation ensures that every node possesses an autonomous, durable state machine.

### Q7: What is the purpose of the two-phase replication approach (`PENDING` vs `COMMITTED`)?
**Answer:** It guarantees atomicity across replicas. If a node wrote directly as `COMMITTED` before confirming that peers also acknowledged the write, a leader crash would leave that unacknowledged write counted in the leader's local tally but absent from all surviving followers, violating consistency. Staging as `PENDING` ensures only quorum-backed ballots appear in verified tallies.

### Q8: What is your failure detection timeout, and why did you choose 3.0 seconds?
**Answer:** The coordinator broadcasts heartbeats every $500\text{ms}$. Followers use a monotonic timer latch tripping at $3000\text{ms}$ ($6 \times \text{heartbeat interval}$). This $6\times$ buffer prevents false-positive failovers caused by temporary CPU scheduling jitter or transient Docker network pauses, while keeping failover convergence bounded to $\approx 3.1\text{s}$.

### Q9: What is the difference between failover election time and post-election write readiness?
**Answer:** 
- *Failover Election Time ($T_{\text{failover}}$):* The duration from coordinator crash until the new coordinator broadcasts victory and increments the operational term ($\approx 2.95\text{s}-3.68\text{s}$, dominated by the $3.0\text{s}$ timeout).
- *Post-Election Write Readiness ($\Delta T_{\text{readiness}}$):* The sub-100ms interval ($39.8\text{ms}-97.9\text{ms}$) between victory broadcast and the moment the new coordinator's RPC channel successfully accepts and commits its first incoming client write.

### Q10: How does a recovered node catch up on missed votes?
**Answer:** Via our `AutoFollowerSync` protocol. When a restarted follower receives a heartbeat from the active coordinator, it extracts the coordinator's term and invokes the gRPC `SyncLog` RPC, sending its local maximum Lamport timestamp $L_{\text{local}}$. The coordinator streams all committed ballots with $L > L_{\text{local}}$. The follower inserts them into its local MySQL database, logs the catch-up in `sync_log`, and updates its local Lamport clock.

### Q11: In EXP-04 (Ring Majority, $N=5$), two trials failed. Why did they fail, and why didn't you re-run them?
**Answer:** They failed due to rapid Windows socket recycling port collisions (`55054/tcp`) when our automated harness tore down and recreated Docker containers within milliseconds on Windows. We preserved those failed trials in our dataset to uphold scientific and academic integrity. Hiding or discarding failed trials produces biased results. We reported valid throughput computed over $K_{\text{valid}}=1$ ($17.67\text{ ops/s}$) and added a 2.0s inter-trial port settlement buffer to resolve the issue for all subsequent batches.

### Q12: Why did message complexity for Ring scale better than Bully at 7 nodes?
**Answer:** In Bully, every candidate sends probes to all higher nodes, and higher nodes send suppression messages, leading to $O(N^2)$ message growth. At $N=7$, Bully exchanged an average of $40.3$ messages. In Ring, messages circulate sequentially around a unidirectional circle, requiring $2(N - 1)$ messages. At $N=7$, Ring exchanged only $33.3$ messages, empirically demonstrating the predicted $O(N)$ efficiency advantage.

### Q13: Does your system tolerate Byzantine faults (e.g., malicious nodes falsifying votes)?
**Answer:** No. Our system is explicitly designed for the **Crash-Fault-Tolerant (CFT)** model (Crash-Stop and Crash-Recovery). Tolerating Byzantine faults requires cryptographic signatures on all inter-node RPCs, Byzantine Agreement protocols (such as PBFT), and a minimum cluster size of $3f + 1$ rather than $2f + 1$. We have clearly stated CFT as our operational boundary.

### Q14: How does your Flask bridge know which node to forward votes to?
**Answer:** Each Flask bridge instance inspects its co-located `NodeRuntime`. If the local node is the coordinator, it executes `SubmitVote` locally. If the local node is a follower, it checks its cached coordinator ID, discovers the coordinator's gRPC endpoint from its static peer configuration, and forwards the gRPC call directly, returning the response transparently to the client.

### Q15: What is the significance of the monotonic clock latch in `time.monotonic()`?
**Answer:** Standard system time (`time.time()`) reads the operating system's wall clock, which can jump forwards or backwards during NTP synchronization or manual clock adjustments. `time.monotonic()` guarantees that the counter moves strictly forward at a fixed rate, ensuring that heartbeat timeout measurements are immune to physical clock drift.

### Q16: How do you verify database WAL parity across nodes?
**Answer:** In both our automated test harness and live demonstration, we execute SQL queries against all running database containers:
```sql
SELECT vote_id, client_id, choice, status FROM votes WHERE status = 'COMMITTED' ORDER BY lamport_ts ASC;
```
We compare the returned rows across all nodes; 100% parity is confirmed when all nodes return identical ordered record sets and hash digests.

### Q17: What happens under a network partition separating 2 nodes from 3 nodes in a 5-node cluster?
**Answer:** Under Majority Quorum ($Q = \lfloor 5/2 \rfloor + 1 = 3$):
- The 3-node majority partition contains enough nodes to achieve quorum. If the coordinator is in the majority, it continues committing writes. If the coordinator was in the minority, the majority partition elects a new coordinator and continues.
- The 2-node minority partition cannot assemble 3 ACKs. Any write attempt submitted to the minority partition fails with HTTP 503 (`Quorum not reached`).
- This guarantees that two divergent tallies can never be formed simultaneously.

### Q18: What are the primary threats to validity in your experimental results?
**Answer:** 
1. *Single-Host Virtualization:* All containers shared the host machine's CPU, memory, and Docker bridge network, meaning inter-node latencies reflect loopback communication rather than wide-area network latency.
2. *Sample Size:* While Student's $t$ confidence intervals were calculated, each configuration was evaluated across 3 repetitions ($K=3$).

### Q19: Why does steady-state write throughput decrease as cluster size grows from 3 to 7 nodes?
**Answer:** With larger clusters, the coordinator must initiate more concurrent gRPC network calls, wait for more quorum acknowledgments, and process more replication network packets over the Docker bridge network. The synchronization overhead increases from $Q=2$ ACKs at $N=3$ to $Q=4$ ACKs at $N=7$.

### Q20: If you had another six months on this project, what would you improve?
**Answer:**
1. Transition our two-phase replication into a full **Raft consensus state machine** with dynamic log compaction and snapshotting.
2. Deploy the cluster across multiple physical machines or cloud instances using **Kubernetes (K8s)** and service mesh mutual TLS (mTLS).
3. Introduce **cryptographic ballot blinding** (such as Paillier homomorphic encryption) so that even administrators inspecting the database cannot link a voter's identity to their candidate choice.

---

## 7. Live Demonstration Checklist & Fallback Plan

### Step-by-Step Live Demonstration Script
1. **Pre-Demo Check:** Confirm Docker Desktop is running (`docker info`).
2. **Launch 3-Node Cluster:**
   ```powershell
   docker compose -f docker/docker-compose.3node.yml up -d --build
   ```
3. **Open Browser Dashboard:** Navigate to [http://localhost:5001](http://localhost:5001) and [http://localhost:5003](http://localhost:5003). Show that Node 3 is Coordinator.
4. **Cast Initial Ballot:** Cast vote for `Alice` (`voter_01`) via Node 1 or Node 3. Show instant replication to all 3 nodes and verify live tally.
5. **Simulate Crash:** Execute `docker stop voting-node3`.
6. **Show Automated Failover:** Refresh [http://localhost:5002](http://localhost:5002) within ~3.2 seconds. Observe Node 2 elected Coordinator!
7. **Cast Second Ballot:** Cast vote for `Bob` (`voter_02`) via Node 2 under majority quorum. Show commit success.
8. **Recover Node 3:** Execute `docker start voting-node3`. Show Node 3 rejoining, adopting Node 2, and synchronizing `voter_02` within ~2.3 seconds.
9. **Verify Parity:** Show all 3 nodes display `{'Alice': 1, 'Bob': 1}` identically.
10. **Clean Teardown:**
    ```powershell
    docker compose -f docker/docker-compose.3node.yml down -v
    ```

### Fallback Plan (If Docker Daemon Fails or Laptop Power Cut)
If Docker cannot be launched during the viva:
1. Present the recorded live evidence manifest at [`data/experiments/phase8_5/live_demo_log.json`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/data/experiments/phase8_5/live_demo_log.json), which records every millisecond timestamp and HTTP response of the verified live run.
2. Run the non-Docker automated regression suite in SQLite isolation (`pytest tests/ -q`), demonstrating 242 passing tests of the core election, Lamport clock, and consensus logic in ~60 seconds.
3. Walk the committee through the sequence diagrams in [`docs/ARCHITECTURE.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docs/ARCHITECTURE.md).
