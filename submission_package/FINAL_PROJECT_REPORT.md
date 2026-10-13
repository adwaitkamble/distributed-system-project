# Distributed Fault-Tolerant Voting System with Pluggable Leader Election
## Final Academic Project Report

---

### Section 1: Title Page

**PROJECT TITLE:** Distributed Fault-Tolerant Voting System with Pluggable Leader Election  
**INSTITUTION:** Pimpri Chinchwad Education Trust's  
**COLLEGE:** Pimpri Chinchwad College of Engineering (PCCoE), Pune  
*(An Autonomous Institute Affiliated to Savitribai Phule Pune University — SPPU)*  
**DEPARTMENT:** Department of Computer Engineering  
**ACADEMIC YEAR:** 2025–2026  

**PROJECT GROUP MEMBERS:**
* **Adwait Kamble** — Roll No: `123B1D002`
* **Advait Nathe** — Roll No: `123B1D029`
* **Nikhil Puppalwar** — Roll No: `123B1D040`

**PROJECT GUIDE:**
* **Mr. Ganesh Deshmukh**, Assistant Professor, Department of Computer Engineering

---

### Section 2: Certificate & Declaration Placeholders

#### Certificate of Approval
> This is to certify that the project report entitled **"Distributed Fault-Tolerant Voting System with Pluggable Leader Election"** submitted by **Adwait Kamble [123B1D002]**, **Advait Nathe [123B1D029]**, and **Nikhil Puppalwar [123B1D040]** is a bonafide record of work carried out by them under my guidance and supervision in partial fulfillment of the requirements for the Degree of Bachelor of Technology in Computer Engineering of Savitribai Phule Pune University during the academic year 2025–2026.
>
> _____________________________  
> **Mr. Ganesh Deshmukh**  
> Project Guide  
> Department of Computer Engineering  
>
> _____________________________  
> **Dr. [HOD Name Placeholder]**  
> Head of Department  
> Department of Computer Engineering  
>
> _____________________________  
> **Internal Examiner**  
>
> _____________________________  
> **External Examiner**  

#### Candidate Declaration
> We hereby declare that the project work presented in this report entitled **"Distributed Fault-Tolerant Voting System with Pluggable Leader Election"** is an authentic record of our own research and engineering implementation carried out under the supervision of **Mr. Ganesh Deshmukh**. Any work, data, or concepts derived from existing academic literature or open-source software have been duly attributed and referenced.
>
> *Adwait Kamble [123B1D002]*  
> *Advait Nathe [123B1D029]*  
> *Nikhil Puppalwar [123B1D040]*  

---

### Section 3: Acknowledgements

We express our sincere gratitude to our project guide, **Mr. Ganesh Deshmukh**, for his continuous mentorship, insightful technical feedback, and invaluable guidance throughout the conception, architecture, and benchmarking of this distributed systems project.

We extend our deep appreciation to the **Department of Computer Engineering** and the leadership of **Pimpri Chinchwad College of Engineering (PCCoE)** for providing computational infrastructure, high-performance computing facilities, and an encouraging academic environment. Finally, we thank our peers and families for their unwavering encouragement during this research and development effort.

---

### Section 4: Abstract & Keywords

#### Abstract
Centralized electronic voting architectures inherently suffer from single points of failure, where hardware crashes, server reboots, or network partitions immediately halt election processes and risk uncommitted vote loss. This project designs, implements, and empirically evaluates a **Distributed Fault-Tolerant Voting System** featuring pluggable leader election (**Bully** and **Ring**), two-phase gRPC replication, monotonic Lamport logical clocks, automated crash-recovery with durable log reconciliation, dedicated physical database isolation per node, and an interactive React web dashboard.

The cluster operates across symmetric nodes deployed in independent Docker containers, each paired with its own isolated MySQL database instance with zero shared storage. To evaluate algorithmic trade-offs, a rigorous 99-trial factorial benchmark campaign was executed across 3, 5, and 7-node cluster profiles under steady-state and fault-injected conditions (coordinator crash, follower crash, cascading failures, node rejoin, and network partitions). 

Empirical results demonstrate:
1. Leader failover convergence latency is strictly bounded between $2.94\text{s}$ and $3.68\text{s}$, dominated by the $3.0\text{s}$ monotonic failure detection latch, with post-election write readiness established within $39.8\text{ms}-97.9\text{ms}$.
2. Empirical message complexity confirms theoretical scaling bounds: the Bully algorithm scales quadratically $O(N^2)$ ($5.0 \to 19.0 \to 40.3$ messages for $N=3,5,7$), whereas the Ring algorithm scales linearly $O(N)$ ($10.7 \to 23.7 \to 33.3$ messages), demonstrating an empirical crossover advantage for Ring at $N=7$.
3. Majority quorum replication guarantees 100% write availability during follower failures and completely prevents split-brain tallies under network partitions.
4. Across 97 successful experimental trials, **zero ballots were lost, zero duplicate votes were accepted, zero ghost votes emerged, and 100% database WAL parity was achieved**.

#### Keywords
Distributed Systems, Fault Tolerance, Pluggable Leader Election, Bully Algorithm, Ring Algorithm, Lamport Logical Clocks, Two-Phase Replication, State Machine Replication, Physical Database Isolation, Docker Containerization.

---

### Section 5: Introduction & Problem Statement

#### 5.1 Introduction
Electronic voting and polling platforms serve as critical infrastructure across academic institutions, civic organizations, and corporate governance. The standard commercial architecture relies on a centralized client-server model wherein all client requests terminate at a single centralized database and application server. While simple to implement, centralized systems exhibit fundamental reliability defects:
- **Single Point of Failure (SPOF):** Any hardware fault, power interruption, operating system panic, or network disruption completely incapacitates the polling service.
- **Vote Loss & Uncommitted Inconsistency:** In-flight votes received right before an unexpected crash can be permanently lost if not synchronously flushed to persistent disk across multiple machines.
- **Lack of High Availability:** Restoring a crashed centralized server requires manual intervention, during which voters experience prolonged service denial.

#### 5.2 Problem Statement
To design, implement, containerize, and empirically evaluate a distributed, fault-tolerant electronic voting system that:
1. Automatically detects coordinator crashes using monotonic heartbeat timers.
2. Dynamically elects a valid successor coordinator using selectable leader election algorithms (Bully or Ring) without human intervention.
3. Orders distributed events deterministically using Lamport logical clocks.
4. Guarantees safety invariants (zero lost writes, zero duplicate votes, single active leader per term, and identical committed tallies) using two-phase gRPC replication and dedicated physical database isolation per node.
5. Enables recovering nodes to automatically catch up their missing vote logs via durable state synchronization (`AutoFollowerSync`).

---

### Section 6: Project Objectives & Scope

#### 6.1 Project Objectives
1. **Literature Synthesis:** Review contemporary research in distributed consensus, election optimizations, and fault-tolerant voting systems ([1]–[15]).
2. **Pluggable Election Implementation:** Implement both classical Bully [12] and Ring [13] election algorithms in Python 3.11 with gRPC transport.
3. **Replication & Quorum Engine:** Implement two-phase replication supporting strict All-Replication (`all`) and Majority-Quorum (`majority`) policies.
4. **Isolated Storage Architecture:** Pair each node container with an independent MySQL container to eliminate shared-storage vulnerabilities.
5. **State Recovery Mechanism:** Implement monotonic Lamport clocks [14], durable `sync_log` journaling, and automated follower catch-up synchronization.
6. **Empirical Factorial Benchmarking:** Benchmark throughput, commit latency, election overhead, failover downtime, and partition tolerance across 3, 5, and 7-node topologies.

#### 6.2 Project Scope
* **Fault Model:** The system operates strictly under the **Crash-Stop** and **Crash-Recovery** models with crash-recovery persistence. Nodes may crash abruptly at any moment and later rejoin.
* **Network Assumptions:** Asynchronous packet-switched communication over TCP/IP (Docker bridge network). Messages may experience variable delays and temporary network partitions.
* **Out of Scope:** **Byzantine (malicious/arbitrary) failures** are explicitly out of scope. The nodes are assumed to be non-adversarial. Cryptographic voter identity blinding, zero-knowledge proofs, and nation-state election security are outside the scope of this educational and experimental prototype.

---

### Section 7: Background & Related Work

Distributed consensus and coordinator election have been extensively studied since the foundational work of Garcia-Molina [12], Chang and Roberts [13], and Lamport [14].

#### 7.1 Classical Foundations
* **Bully Algorithm (Garcia-Molina, 1982 [12]):** Operates in a synchronous or partially synchronous environment where nodes possess unique, totally ordered identifiers. When a coordinator fails, a node broadcasts `ELECTION` messages to all peers with higher IDs. Higher nodes suppress lower candidates with `OK` messages. If no higher node responds within a bounded timeout, the candidate declares itself coordinator and broadcasts a `COORDINATOR` announcement to all lower nodes. Message complexity is worst-case $O(N^2)$.
* **Ring Algorithm (Chang & Roberts, 1979 [13]):** Arranges nodes into a logical unidirectional ring. An election initiator constructs a message containing its own identifier and forwards it clockwise. Each active node appends its identifier to the message. When the token completes a full circle, the highest identified node is elected coordinator, followed by a coordinator announcement message. Message complexity is strictly bounded by $O(N)$ or $O(N \log N)$.
* **Lamport Logical Clocks (Lamport, 1978 [14]):** Assigns a monotonically increasing integer counter $L$ to every distributed event. For internal events, $L := L + 1$. For inter-node message transmission, the sender includes $L_{\text{msg}}$; upon receipt, the receiver advances its clock:
  $$L_{\text{recv}} := \max(L_{\text{recv}}, L_{\text{msg}}) + 1$$
  Ties between concurrent events are deterministically broken using unique node identifiers, establishing a total order: $(L_A, \text{ID}_A) < (L_B, \text{ID}_B)$ iff $L_A < L_B$ or ($L_A = L_B$ and $\text{ID}_A < \text{ID}_B$).

#### 7.2 Contemporary Related Literature Matrix

| Ref | Study & Authors | Year | Venue | Architecture | Key Findings | Limitations | Relevance to This Project |
|:---:|---|:---:|---|---|---|---|---|
| **[1]** | S. Patel & G. Tere | 2025 | IJARCS | Enhanced Bully/Ring | 30–40% message reduction vs classical Bully | Simulation only; no container deployment | Baseline comparison for election message scaling |
| **[2]** | Y. Wang et al. (SCRaft) | 2024 | IEEE HPCC | Pre-designated Raft leader | 50–70% election latency reduction | Raft-specific; does not evaluate Bully/Ring | Benchmark comparison for leader failover readiness |
| **[3]** | J. Chalopin et al. | 2024 | LIPIcs DISC | Self-stabilizing election | $O(1)$ memory self-stabilization | Targeted to nano-scale programmable matter | Informs state recovery after arbitrary node crashes |
| **[4]** | J. Ballweg (PureLottery) | 2024 | TUM Thesis | Cryptographic election | Fair, randomized leader election | High cryptographic overhead | Contrasts highest-ID Bully deterministic bias |
| **[5]** | Y. Hu (FTI-TMR) | 2025 | arXiv | Max-heap majority voting | Tolerates $f$ faults in $3f+1$ system | Multicore focus; not tested for web voting | Quorum replication and failure detection design |
| **[6]** | A. D. Kshemkalyani et al. | 2025 | AAMAS | Multiagent election | Near-linear $O(n \log n)$ message cost | Synchronous assumption | Message complexity comparison for ring traversal |
| **[7]** | X. Deng et al. (CB-Raft) | 2024 | J. Supercomput. | Byzantine-tolerant Raft | 25–35% consensus throughput boost | Heavy reputation scoring overhead | Distinguishes CFT crash model from BFT models |
| **[8]** | S. Mohammedi Taieb et al. | 2025 | Sci. Eng. Technol. | GFEA Hybrid Paxos | Bully + Paxos hybrid facilitator | Wireless Ad-Hoc network focus | Informs integration of election with heartbeat timeouts |
| **[9]** | Z. Xu et al. | 2023 | IEEE IPDPS | Exact fault-tolerant consensus | Formal validity proofs under voting | Purely theoretical; no real implementation | Supports committed-vote tally verification rules |
| **[10]** | R. C. von Seck | 2025 | TUM Dissertation | Consensus robustness | Protocol bounds under varied fault models | Thesis format | Theoretical foundation for safety and liveness |
| **[11]** | Riga Tech. University | 2025 | RTU Thesis | Fault-tolerant algorithms | Comprehensive survey of elections & consensus | Survey format | Broad taxonomy of crash-stop recovery paradigms |
| **[15]** | D. Ongaro & J. Ousterhout | 2014 | USENIX ATC | Raft Consensus Algorithm | Understandable state machine replication | Full Raft requires complex log-matching logic | Baseline for leader election & replicated state |

---

### Section 8: Requirements & System Design

#### 8.1 Functional Requirements (FR)
* **FR-1 (Ballot Submission):** The system must accept vote submissions containing voter ID and candidate choice, rejecting empty fields or illegal characters (e.g. colons used in internal serialization).
* **FR-2 (Single Active Coordinator):** Exactly one node must act as the active coordinator during any given operational term.
* **FR-3 (Automated Election):** If the coordinator stops sending heartbeats for $\ge 3000\text{ms}$, active peers must elect a new coordinator within $5.0\text{s}$ using the configured algorithm (`bully` or `ring`).
* **FR-4 (Replication & Commitment):** Ballots must be replicated to peer nodes using two-phase semantics (`PENDING` $\to$ `COMMITTED`), committing only when the selected policy (`all` or `majority`) is met.
* **FR-5 (State Catch-Up):** A recovering follower must automatically pull all committed votes missing from its local database upon receiving a heartbeat from the active coordinator.
* **FR-6 (Verified Live Tally):** Clients must be able to query committed vote totals in real time from any running node.

#### 8.2 Non-Functional Requirements (NFR)
* **NFR-1 (Physical Isolation):** Every node must maintain independent storage with no shared volumes or centralized databases.
* **NFR-2 (Safety / Zero Lost Writes):** Any ballot acknowledged with HTTP 201 must persist in storage and appear in the final tally across all healthy nodes.
* **NFR-3 (Idempotency):** Submitting the identical ballot repeatedly must return the original receipt without double-counting. Submitting a conflicting ballot with the same voter ID must be rejected.
* **NFR-4 (Observability):** Each node must expose real-time metrics, cluster topologies, and event logs via REST endpoints.
* **NFR-5 (Containerized Portability):** The entire multi-node cluster must build and run deterministically on standard container runtimes using Docker Compose.

---

### Section 9: System Architecture & Component Responsibilities

The system adopts a 3-tier distributed architecture:
1. **Presentation Layer (React Single-Page Application):** Developed in React 18 with Vite. Features interactive views: Cluster Dashboard, Ballot Casting, Real-Time Tally, Leader Election monitor, and Event Audit logs.
2. **Application & Protocol Layer (Flask Bridge + NodeRuntime + gRPC):**
   * *Flask REST Bridge:* Hosted on each node's local HTTP port (5001–5007). Acts as a client gateway, converting incoming REST requests into internal gRPC calls. Follower nodes forward writes or return redirect hints pointing to the coordinator.
   * *NodeRuntime:* Coordinates the election state machine, Lamport clocks, heartbeat monitoring, and consensus quorum calculations.
   * *gRPC Server:* Serves internal inter-node RPCs defined in `proto/voting.proto`: `SubmitVote`, `ReplicateVote`, `Election`, `Coordinator`, `Heartbeat`, and `SyncLog`.
3. **Storage Layer (Dedicated MySQL Instances):**
   * Each node connects over the Docker bridge network to its own private database container (`voting-node{id}-db`). There is **zero shared storage**.

*(Detailed architectural diagrams and sequence workflows are documented in `docs/ARCHITECTURE.md`).*

---

### Section 10: Distributed-System Concepts Applied

1. **State Machine Replication (SMR):** Replicating operations deterministically across isolated nodes ensures that identical state machines reach identical states.
2. **Two-Phase Commit Style Replication:** Prevents "ghost votes" by ensuring a ballot is staged as `PENDING` across replicas before being promoted to `COMMITTED` once quorum is acknowledged.
3. **CAP Theorem Trade-Offs:**
   * Under `majority` policy, the system prioritizes **Consistency and Partition Tolerance (CP)**. In the event of a network partition, the majority partition continues accepting writes while the minority partition rejects writes with HTTP 503, preventing split-brain states.
   * Under `all` policy, the system enforces **Universal Consistency** at the complete expense of availability if even one node fails.
4. **Monotonic Clocks for Failure Detection:** Relying on `time.monotonic()` prevents false-positive failure detections caused by NTP synchronization jumps, leap seconds, or wall-clock shifts.

---

### Section 11: Leader Election: Bully and Ring Strategies

#### 11.1 Bully Algorithm Implementation
* **Rule:** Highest node identifier always wins.
* **Message Types:** `ELECTION`, `OK` (suppression), and `COORDINATOR` (victory).
* **Execution Flow:**
  1. Follower detects coordinator timeout.
  2. Candidate broadcasts `ELECTION` to all peers with $\text{ID} > \text{candidate\_id}$.
  3. If a higher node responds with `OK`, the candidate yields.
  4. If no response is received within the election timeout, the candidate declares itself leader, increments the term counter, and broadcasts `COORDINATOR` to all lower nodes.
* **Message Complexity:** Worst-case $O(N^2)$, requiring $\frac{(N-1)(N-2)}{2} + (N-1)$ messages when the lowest node initiates election.

#### 11.2 Ring Algorithm Implementation
* **Rule:** Nodes form a sorted unidirectional logical ring: $Node_1 \to Node_2 \to \dots \to Node_N \to Node_1$.
* **Message Types:** `RING_ELECTION` (token containing active candidate list) and `RING_COORDINATOR` (announcement token).
* **Execution Flow:**
  1. Initiator creates an election token containing its own ID and forwards it to its immediate active successor.
  2. If the successor is unresponsive, it skips to the next node in the ring.
  3. Each active peer appends its ID and forwards the token.
  4. When the token returns to the initiator, the highest ID in the list is selected as coordinator.
  5. The initiator circulates a coordinator announcement token around the ring.
* **Message Complexity:** Bounded strictly by $2(N - 1) = O(N)$ messages under single-initiator ring traversal.

---

### Section 12: Heartbeats, Failure Detection & Coordinator Changes

* **Heartbeat Stream:** The coordinator broadcasts a `Heartbeat` RPC every $500\text{ms}$ containing its `node_id`, active `term`, and current `lamport_ts`.
* **Monotonic Timeout Latch:** Followers track elapsed time using `time.monotonic()`. If:
  $$\text{elapsed} = \text{now}() - \text{last\_heartbeat\_time} \ge 3000\text{ms}$$
  the follower declares the coordinator failed.
* **Single-Trigger Latch:** To prevent election storms, the heartbeat monitor triggers the election routine exactly once per failure event, latching its state until a valid `COORDINATOR` announcement is received.

---

### Section 13: Replication Policies: ALL vs MAJORITY

#### 13.1 Strict All-Replication (`all`)
* **Quorum Requirement:** $Q = N$ (All active peers must acknowledge `ReplicateVote`).
* **Fault Tolerance:** $F = 0$. If any single follower crashes, subsequent vote submissions block and return HTTP 503 (`Quorum not reached`).

#### 13.2 Majority Quorum (`majority`)
* **Quorum Requirement:** 
  $$Q = \left\lfloor \frac{N}{2} \right\rfloor + 1$$
  * For $N=3$: $Q = 2$ ACKs. Tolerates $F = 1$ failure.
  * For $N=5$: $Q = 3$ ACKs. Tolerates $F = 2$ failures.
  * For $N=7$: $Q = 4$ ACKs. Tolerates $F = 3$ failures.
* **Fault Tolerance:** Survives up to $F = \lfloor (N - 1) / 2 \rfloor$ crash failures while sustaining live write operations.

---

### Section 14: Vote Lifecycle & Committed-Vote Tally Semantics

Every ballot transitions through strict lifecycle states:

```
[Client POST] 
     │
     ▼
[Validation] ──(Invalid / Duplicate)──> [HTTP 400 / 409 Rejected]
     │
     ▼
[PENDING] (Staged in Coordinator & Follower DBs)
     │
     ▼
[Replication Fan-out] ──(Quorum Failure)──> [HTTP 503 Rejected (Remains PENDING)]
     │
     ▼
[COMMITTED] (Quorum ACKs Satisfied)
     │
     ▼
[HTTP 201 Returned with Signed Receipt]
```

* **Tally Integrity:** The endpoint `GET /api/tally` executes:
  ```sql
  SELECT choice, COUNT(*) as votes FROM votes WHERE status = 'COMMITTED' GROUP BY choice;
  ```
  Uncommitted or orphaned `PENDING` votes are completely excluded from tally aggregation.

---

### Section 15: Lamport Logical Clocks & Deterministic Ordering

* **State:** Each node maintains an internal 64-bit integer $L$, initialized to 0.
* **Advancement Rules:**
  1. *Local Event (Ballot Receipt):* $L := L + 1$.
  2. *Message Ingestion (gRPC RPC):* $L := \max(L, L_{\text{msg}}) + 1$.
* **Unique Vote Identifier:** Ballots receive an immutable identifier encoding causal history:
  $$\text{vote\_id} = \text{client\_id} : \text{origin\_node\_id} : \text{lamport\_ts}$$
* **Deterministic Tie-Breaking:** When merging logs during recovery, votes with identical Lamport timestamps are ordered deterministically by `origin_node_id`.

---

### Section 16: Recovery, Synchronization & Fault Handling

* **Rejoining Lifecycle:** When a crashed follower container restarts, it initializes its storage engine and enters `RECOVERING` mode.
* **AutoFollowerSync Protocol:**
  1. Follower inspects its local database to find its highest committed Lamport timestamp:
     $$L_{\text{local}} = \max(\text{lamport\_ts})$$
  2. Upon receiving the first coordinator heartbeat, it verifies the coordinator's authority.
  3. Follower invokes gRPC `SyncLog(from_lamport_ts=L_local)`.
  4. Coordinator queries its MySQL database for all committed votes with $\text{lamport\_ts} > L_{\text{local}}$ and returns the delta.
  5. Follower validates and inserts missing votes into its local database, marks them `COMMITTED`, records an audit entry in `sync_log`, and sets its status to `ONLINE`.
  6. Verified database WAL parity is achieved within $\approx 2.3\text{s}$.

---

### Section 17: Database Design & Storage Responsibilities

Each node interacts with its own private database schema defined in `docker/init.sql`:

#### Table: `votes`
* `vote_id VARCHAR(128) PRIMARY KEY` — Unique ballot identifier (`client_id:origin:ts`).
* `client_id VARCHAR(64) NOT NULL UNIQUE KEY` — Enforces that a voter can never vote twice.
* `origin_node_id INT NOT NULL` — Node that received the client submission.
* `lamport_ts BIGINT NOT NULL` — Logical clock timestamp.
* `choice VARCHAR(100) NOT NULL` — Candidate selection.
* `received_at_ms BIGINT NOT NULL` — Unix millisecond wall-clock timestamp.
* `status VARCHAR(16) NOT NULL DEFAULT 'PENDING'` — State: `PENDING` or `COMMITTED`.

#### Table: `election_log`
* `id INT AUTO_INCREMENT PRIMARY KEY`
* `event_type VARCHAR(40)`, `node_id INT`, `lamport_ts BIGINT`, `election_term BIGINT`, `initiator_id INT`, `details JSON`, `logged_at_ms BIGINT`.

#### Table: `sync_log`
* `entry_id INT AUTO_INCREMENT PRIMARY KEY`
* `entry_type VARCHAR(40)`, `vote_id VARCHAR(128)`, `client_id VARCHAR(64)`, `origin_node_id INT`, `lamport_ts BIGINT`, `choice VARCHAR(100)`, `status VARCHAR(16)`, `details TEXT`, `created_at_ms BIGINT`.

---

### Section 18: Technology Stack & Implementation Architecture

* **Backend Runtime:** Python 3.11.9.
* **RPC & Serialization:** gRPC (`grpcio 1.62+`), Protocol Buffers (`protobuf 4.25+`).
* **Web Framework:** Flask 3.0, Flask-CORS, Werkzeug.
* **Database Drivers:** SQLAlchemy 2.0, PyMySQL (MySQL 8.0), SQLite (automated unit tests).
* **Frontend:** React 18, Vite, Lucide React, Vanilla CSS / Tailwind tokens.
* **Container Orchestration:** Docker Engine 29.4+, Docker Compose v2.

---

### Section 19: Testing Methodology & Verification Results

The project enforces a multi-tier testing strategy combining fast in-memory unit tests, subprocess cluster tests, and multi-container Docker cluster integration tests.

```text
                  ▲
                 / \
                /   \     Live Docker Tests (39 tests)
               / Docker\   [3-node, 5-node, 7-node, single]
              /─────────\
             /Subprocess \ Subprocess Multi-Node Tests (7 tests)
            / Integration \ [test_integration.py]
           /───────────────\
          /   Unit Logic    \ State Machine, Storage, Clocks (228 tests)
         /───────────────────\
```

* **Total Test Cases Collected:** **274 tests**.
* **Non-Docker Automated Suite Result:** **235 passed, 39 skipped, 0 failed, 0 errors in 64.25s**.
* **Explanation of Skipped Tests:** All 39 skips are live Docker integration tests (`test_docker_cluster_3node.py`, `test_docker_cluster_5node.py`, `test_docker_cluster_7node.py`, `test_docker_single.py`, `test_mysql_smoke.py`). They are guarded by pytest conditional decorators that check whether their respective Docker container profiles are running on `localhost`. When containers are inactive, pytest skips them to avoid false negatives.

---

### Section 20: Phase 7 Experiment Design: EXP-01 through EXP-09

A full factorial experimental matrix was designed and executed using an automated, reproducible testing harness (`experiments/`):
* **Topologies ($N$):** 3, 5, and 7 nodes.
* **Algorithms:** Bully, Ring.
* **Replication Policies:** `all`, `majority`.
* **Repetitions:** 3 repeated trials per configuration ($K=3$).
* **Total Executions:** 33 distinct configurations $\times 3$ trials = **99 planned trial executions**.

#### Catalog Description
* **EXP-01:** Bully Baseline (ALL Policy) — Steady-state throughput & latency across $N=3,5,7$.
* **EXP-02:** Bully Baseline (MAJORITY Policy) — Quorum scaling without faults.
* **EXP-03:** Ring Baseline (ALL Policy) — Ring steady-state throughput & latency.
* **EXP-04:** Ring Baseline (MAJORITY Policy) — Ring quorum scaling.
* **EXP-05:** Coordinator Crash Failover Comparison — Measures election convergence, message overhead, and write-readiness following coordinator death.
* **EXP-06:** Follower Crash Quorum Sensitivity — Evaluates write availability under single follower failure (`all` blocks vs `majority` commits).
* **EXP-07:** Sequential Cascading Failover — Two consecutive coordinator terminations across $N=5,7$.
* **EXP-08:** Follower Rejoin & Catch-up Benchmark — AutoFollowerSync synchronization latency and WAL parity.
* **EXP-09:** Majority vs Minority Network Partition — Validates split-brain prevention.

---

### Section 21: Results, Empirical Analysis & Threats to Validity

All empirical values are sourced directly from the verified dataset [`benchmark_summary.csv`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/data/experiments/matrix/summary/benchmark_summary.csv).

#### 21.1 Steady-State Throughput & Latency Scaling
As cluster size scales from $N=3$ to $N=7$, write throughput decreases monotonically across all configurations due to network fan-out and multi-node acknowledgment synchronization:
* Bully ALL: Drops from $32.28\text{ ops/s}$ ($N=3$) to $23.20\text{ ops/s}$ ($N=5$) and $19.72\text{ ops/s}$ ($N=7$).
* Bully MAJORITY: Drops from $31.31\text{ ops/s}$ ($N=3$) to $23.77\text{ ops/s}$ ($N=5$) and $18.32\text{ ops/s}$ ($N=7$).
* Commit Latency ($p50$): Increases from $\sim 68-109\text{ms}$ at $N=3$ to $\sim 160-194\text{ms}$ at $N=7$.

#### 21.2 Algorithmic Message Overhead: Bully vs Ring (EXP-05)
The experimental results empirically substantiate the theoretical complexity bounds:
* **Bully Algorithm ($O(N^2)$):**
  * $N=3$: $5.0$ messages exchanged.
  * $N=5$: $19.0$ messages exchanged.
  * $N=7$: $40.3$ messages exchanged.
* **Ring Algorithm ($O(N)$):**
  * $N=3$: $10.7$ messages exchanged.
  * $N=5$: $23.7$ messages exchanged.
  * $N=7$: $33.3$ messages exchanged.
* **Complexity Crossover:** While Bully exchanges fewer messages in small 3-node clusters, Ring exchanges significantly fewer messages at $N=7$ ($33.3$ vs $40.3$), empirically observing the scalability advantage of the Ring topology at 7 nodes under the tested environment.

#### 21.3 Failover Downtime & Write-Readiness
* **Failover Downtime ($T_{\text{failover}}$):** Bounded tightly between $2947.26\text{ms}$ and $3679.70\text{ms}$ across all topologies. This duration is strictly dominated by the $3000\text{ms}$ monotonic heartbeat failure detection threshold.
* **Post-Election Write Readiness ($\Delta T_{\text{readiness}}$):** Following election victory broadcast, new coordinators become write-ready almost instantaneously:
  * $N=3$: $39.75\text{ms}$ (Bully), $45.78\text{ms}$ (Ring).
  * $N=5$: $66.97\text{ms}$ (Bully), $65.89\text{ms}$ (Ring).
  * $N=7$: $75.67\text{ms}$ (Bully), $97.94\text{ms}$ (Ring).

#### 21.4 Fault Invariant Verification
Across all executed fault injection experiments:
* **EXP-06 (Follower Crash):** Under `all` policy, follower loss instantly blocks writes with HTTP 503. Under `majority` policy, writes continue committing uninterrupted ($16.27-37.22\text{ ops/s}$).
* **EXP-07 (Cascading Crashes):** Survives two consecutive leader terminations ($T_{\text{failover}} \approx 6.9-7.9\text{s}$) with zero lost writes.
* **EXP-08 (Follower Rejoin):** Rejoining followers achieve complete WAL parity in $\approx 2281-2295\text{ms}$.
* **EXP-09 (Network Partition):** 100% of minority partition requests are rejected with HTTP 503; 100% of majority partition requests succeed. Zero split-brain states observed.

#### 21.5 Threats to Validity & Known Limitations
1. **Single-Host Virtualization:** All Docker containers ran on a single physical host sharing CPU, RAM, and the loopback bridge network. Host scheduling under peak load introduces virtualization artifacts not present in bare-metal deployments.
2. **Repetition Sample Size ($K=3$):** While Student's $t$ distributions were calculated, confidence intervals reflect sample sizes of 3 trials per cell.
3. **EXP-04 $N=5$ Execution Anomaly:** In EXP-04 $N=5$, two trials failed due to rapid Windows socket recycling latency (`55054/tcp` port bind contention) during automated container spin-up. These trials are preserved in the dataset as `FAILED` manifests for academic transparency, with valid throughput computed over $K_{\text{valid}}=1$ ($17.67\text{ ops/s}$).
4. **Empirical Observation vs Universal Guarantee:** The reported invariant safety (zero lost votes, zero duplicates, zero ghost votes) represents empirical verification across the 97 passing trials under the evaluated scenarios, and does not constitute a formal mathematical proof under arbitrary Byzantine conditions.

---

### Section 22: Security Considerations & Future Improvements

#### 22.1 Security & Threat Model
* **Crash-Fault Model:** The system guarantees safety against crash-stop and crash-recovery faults, but does not tolerate Byzantine (malicious or compromised) nodes. A rogue node could spoof higher terms or drop replication ACKs.
* **Voter Privacy:** Ballot receipts currently link `client_id` with `choice`. In high-stakes elections, cryptographic tally blinding (e.g. Paillier homomorphic encryption or blind signatures) must be implemented to preserve voter secrecy.

#### 22.2 Future Research Directions
1. **Raft Consensus Integration:** Transitioning from two-phase replication to full Raft consensus with persistent log term validation.
2. **Multi-Host Deployment:** Orchestration across geographically separated nodes using Kubernetes (K8s) or HashiCorp Nomad with dynamic service discovery (Consul).
3. **mTLS Encryption:** Enforcing mutual TLS certificate authentication across inter-node gRPC channels.

---

### Section 23: Conclusion

This project successfully designed, implemented, containerized, and experimentally benchmarked a **Distributed Fault-Tolerant Voting System with Pluggable Leader Election**. By deploying isolated per-node MySQL storage paired with gRPC runtimes, the system eliminated centralized points of failure while enforcing strict safety invariants.

Through a rigorous 99-trial factorial benchmark campaign, the project validated:
* Automated coordinator failover in $\approx 3.0-3.7\text{s}$ with instant write readiness ($39.8-97.9\text{ms}$).
* Empirical observation of Bully's quadratic $O(N^2)$ vs Ring's linear $O(N)$ message scaling crossover at $N=7$.
* High availability and split-brain immunity under majority quorum consensus.
* 100% database WAL parity via `AutoFollowerSync`.

The implementation, documentation, and experimental methodology provide a robust, evidence-backed foundation for final-year engineering evaluation and future research publications in distributed systems.

---

### Section 24: References

1. S. Patel and G. Tere, "Enhancing election algorithms for distributed systems: Reducing message complexity and improving fault tolerance," *Int. J. Soft Comput. Eng.*, vol. 15, no. 1, 2025, doi: 10.35940/ijsce.F8203.15010325.
2. Y. Wang, H. Luo, G. Sun, and H. Yu, "SCRaft: Achieving fast and stable elections in Raft consensus algorithm," in *Proc. IEEE Int. Conf. High Perform. Comput. Commun. (HPCC)*, 2024, pp. 561–568, doi: 10.1109/HPCC64274.2024.00081.
3. J. Chalopin, S. Das, and M. Kokkou, "Deterministic self-stabilising leader election for programmable matter with constant memory," in *Proc. 38th Int. Symp. Distrib. Comput. (DISC)*, LIPIcs vol. 319, 2024, pp. 13:1–13:17, doi: 10.4230/LIPIcs.DISC.2024.13.
4. J. Ballweg, "PureLottery: Fair and bias-resistant leader election with a novel single-elimination tournament algorithm," B.Sc. thesis, Tech. Univ. Munich, 2024, arXiv:2402.17459.
5. Y. Hu, "FTI-TMR: A fault tolerance and isolation algorithm for interconnected multicore systems," arXiv:2510.16896, 2025.
6. A. D. Kshemkalyani, M. Kumar, A. R. Molla, and G. Sharma, "Near-linear time leader election in multiagent networks," in *Proc. 24th Int. Conf. Auton. Agents Multiagent Syst. (AAMAS)*, 2025, pp. 1218–1226, doi: 10.5555/3709347.3743753.
7. X. Deng, Z. Yu, W. Xiong et al., "A novel Raft consensus algorithm combining comprehensive evaluation partitioning and Byzantine fault tolerance," *J. Supercomput.*, vol. 80, pp. 26363–26393, 2024, doi: 10.1007/s11227-024-06438-6.
8. S. Mohammedi Taieb and M. A. Laredj, "GFEA: Leader election algorithm for choosing a group decision support system facilitator," *Sci. Eng. Technol.*, vol. 5, no. 2, 2025, doi: 10.54327/set2025/v5.i2.216.
9. Z. Xu, Y. Li, C. Feng, and L. Zhang, "Exact fault-tolerant consensus with voting validity," in *Proc. IEEE Int. Parallel Distrib. Process. Symp. (IPDPS)*, 2023, pp. 842–852, doi: 10.1109/IPDPS54959.2023.00089.
10. R. C. von Seck, "Robustness and performance of fault-tolerant consensus," Ph.D. dissertation, Tech. Univ. Munich, Munich, Germany, 2025.
11. "Analysis of fault-tolerant algorithms for distributed systems," Ph.D. thesis, Riga Tech. Univ., Riga, Latvia, 2025.
12. H. Garcia-Molina, "Elections in a distributed computing system," *IEEE Trans. Comput.*, vol. C-31, no. 1, pp. 48–59, Jan. 1982.
13. E. Chang and R. Roberts, "An improved algorithm for decentralized extrema-finding in circular configurations of processes," *Commun. ACM*, vol. 22, no. 5, pp. 281–283, 1979.
14. L. Lamport, "Time, clocks, and the ordering of events in a distributed system," *Commun. ACM*, vol. 21, no. 7, pp. 558–565, 1978.
15. D. Ongaro and J. Ousterhout, "In search of an understandable consensus algorithm," in *Proc. USENIX Annu. Tech. Conf.*, 2014, pp. 305–319.

---

### Section 25: Appendices

#### Appendix A: Reproducible Execution Commands

```powershell
# 1. Environment Setup
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 2. Automated Regression Test Suite
pytest tests/ -q

# 3. Docker Cluster Launch (3-Node Demo)
docker compose -f docker/docker-compose.3node.yml up -d --build

# 4. Phase 7 Batch Benchmark Execution
python -m experiments.runners.run_matrix --batch 1  # Baselines
python -m experiments.runners.run_matrix --batch 2  # Failover & Quorums
python -m experiments.runners.run_matrix --batch 3  # Cascading & Partitions

# 5. Statistical Aggregation
python -m experiments.analysis.aggregate_metrics `
  --raw-dir data/experiments/matrix `
  --output-csv data/experiments/matrix/summary/benchmark_summary.csv

# 6. Safe Teardown
docker compose -f docker/docker-compose.3node.yml down -v
```

#### Appendix B: Topology Port Mapping Summary

| Node | Service Container | Database Container | HTTP Port | External gRPC Port | Host MySQL Port |
|:---:|---|---|:---:|:---:|:---:|
| **1** | `voting-node1` | `voting-node1-db` | 5001 | 55051 | 33061 |
| **2** | `voting-node2` | `voting-node2-db` | 5002 | 55052 | 33062 |
| **3** | `voting-node3` | `voting-node3-db` | 5003 | 55053 | 33063 |
| **4** | `voting-node4` | `voting-node4-db` | 5004 | 55054 | 33064 |
| **5** | `voting-node5` | `voting-node5-db` | 5005 | 55055 | 33065 |
| **6** | `voting-node6` | `voting-node6-db` | 5006 | 55056 | 33066 |
| **7** | `voting-node7` | `voting-node7-db` | 5007 | 55057 | 33067 |
