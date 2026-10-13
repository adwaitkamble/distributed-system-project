# Academic Research Paper Revision Plan & Gap Analysis

**Working Paper Title:** Distributed Fault-Tolerant Voting System with Leader Election  
**Target Venue:** IEEE / Springer Conference or Scopus-Indexed Distributed Computing Journal  
**Institutional Affiliation:** Pimpri Chinchwad College of Engineering (PCCoE), Pune — Savitribai Phule Pune University (SPPU)  
**Authors:** Adwait Kamble [123B1D002], Advait Nathe [123B1D029], Nikhil Puppalwar [123B1D040]  
**Faculty Guide:** Mr. Ganesh Deshmukh  
**Baseline Document:** `DS_Paper_Distributed_Voting_System (1).docx` (Draft Text: 204 paragraphs, ~19,500 characters)

---

## 1. Executive Summary & Purpose

An academic review of the existing paper draft (`DS_Paper_Distributed_Voting_System (1).docx`) was conducted against the implementation, Phase 7 empirical benchmark data (EXP-01 through EXP-09), and the Phase 8 release verification audit. 

While the draft introduces the distributed voting concept and features a literature review of 11 recent studies alongside classical foundations [12]–[15], it was authored before the execution of the full 99-trial experimental matrix. Consequently, it lacks empirical data, formal mathematical formulations of quorum boundaries, and nuanced distinctions between failover downtime and post-election write readiness.

This document establishes a concrete, peer-review-standard revision plan to upgrade the draft into a publication-ready manuscript.

---

## 2. Technical & Methodological Gaps in Current Draft

### Gap 1: Undifferentiated Failover Downtime Metrics
* **Current Draft Limitation:** The draft refers generically to "recovery time" or "election time" without decomposing the lifecycle phases of a leader failure.
* **Empirical Reality from Phase 7.3:** Total failover consists of three distinct phases:
  $$\Delta T_{\text{total}} = T_{\text{detect}} + T_{\text{election}} + \Delta T_{\text{readiness}}$$
  1. *Detection Latency ($T_{\text{detect}}$):* Dominated by the monotonic heartbeat timeout latch latching at $\approx 3000\text{ms}$ ($6 \times 500\text{ms}$ heartbeat intervals).
  2. *Election Latency ($T_{\text{election}}$):* The duration required for message exchange and victory declaration (Bully: $50-680\text{ms}$; Ring: $395-630\text{ms}$).
  3. *Post-Election Write Readiness ($\Delta T_{\text{readiness}}$):* The delay between leader victory broadcast and accepting the first client HTTP write probe ($39.8\text{ms}-97.9\text{ms}$).
* **Action Required:** Introduce formal metric definitions in Section IV (Methodology) and present the decomposed values in Section V (Results).

### Gap 2: Informal Quorum & Replication Formulation
* **Current Draft Limitation:** Mentions "votes are replicated across nodes" without formalizing the quorum consensus equations or comparing policies.
* **Empirical Reality:** The system implements two distinct replication policies:
  * **Strict All-Replication (`all`):** Requires acknowledgments from all $N-1$ active peers. Quorum size $Q = N$. Fails if a single node crashes ($F = 0$).
  * **Majority Quorum (`majority`):** Requires acknowledgments from a strict majority:
    $$Q = \left\lfloor \frac{N}{2} \right\rfloor + 1$$
    Tolerates up to $F = \lfloor (N - 1) / 2 \rfloor$ crash failures. ($F=1$ for $N=3,5$; $F=3$ for $N=7$).
* **Action Required:** Add a formal "Consensus & Replication Policies" subsection explaining two-phase commit replication (`PENDING` $\rightarrow$ gRPC fan-out $\rightarrow$ `COMMITTED`).

### Gap 3: Absence of Experimental Data & Tables
* **Current Draft Limitation:** Sections on performance evaluation are written in the future tense ("The system will be tested...").
* **Empirical Reality:** The 99-trial factorial matrix has been executed, reconciled, and audited (`benchmark_summary.csv`).
* **Action Required:** Convert all future-tense evaluation promises into concrete empirical findings, complete with mean throughput, Student's $t$ 95% confidence intervals, order-statistic percentiles ($p50, p95, p99$), and message complexity curves.

### Gap 4: Disclosure of Environmental Limitations
* **Current Draft Limitation:** Does not discuss virtualization artifacts or host scheduling effects.
* **Empirical Reality:** 
  1. Testing occurred on a single physical host running Docker Desktop; communication reflects loopback bridge latency rather than physical multi-machine network hops.
  2. In EXP-04 $N=5$, two trials encountered transient Windows socket recycling latency (`55054/tcp` port bind contention) during rapid automated container recreation. Valid throughput was computed over $K_{\text{valid}}=1$.
* **Action Required:** Add a dedicated "Threats to Validity & System Boundaries" subsection disclosing single-host Docker evaluation and the EXP-04 socket recycling limitation to uphold scientific integrity.

---

## 3. Required Revisions by Paper Section

### Section I: Introduction
- Update contribution claims to reflect implemented software and evaluated metrics:
  * Multi-cluster Docker validation across 1, 3, 5, and 7-node topologies.
  * 99 experimental trials across 9 formal benchmark configurations (EXP-01 to EXP-09).
  * Empirical confirmation of $O(N^2)$ Bully vs $O(N)$ Ring message complexity.

### Section II: Related Work & Literature Review
- Retain the literature review matrix comparing the 11 recent studies [1]–[11] and classical foundations [12]–[15].
- Clarify the system boundary: the system targets **Crash-Fault-Tolerant (CFT)** distributed polling rather than Byzantine Fault-Tolerant (BFT) consensus, distinguishing it from studies like CB-Raft [7] or PureLottery [4].

### Section III: System Design & Architecture
- Replace informal descriptions with the formal 3-tier architecture:
  * Client: React SPA.
  * Node Runtime: Flask REST bridge + gRPC server + NodeRuntime state machine.
  * Storage: Per-node dedicated MySQL databases (`voting_node`) with zero shared storage.
- Insert **Figure 1**: System Architecture Diagram (from `docs/ARCHITECTURE.md`).
- Insert **Figure 2**: Vote Replication & Two-Phase Commitment Sequence.
- Insert **Figure 3**: Leader Failover & AutoFollowerSync Sequence.

### Section IV: Implementation Details
- Document exact technology stack: Python 3.11, gRPC (`grpcio`, `protobuf`), Flask, SQLAlchemy, MySQL 8.0, React 18, Vite.
- Detail the Lamport clock update rule:
  $$L_i := \max(L_i, L_{\text{msg}}) + 1$$
- Detail unique ballot receipt format:
  $$\text{vote\_id} = \text{client\_id} : \text{origin\_node\_id} : \text{lamport\_ts}$$

### Section V: Experimental Results & Analysis
- Insert the comprehensive results table extracted from `data/experiments/matrix/summary/benchmark_summary.csv`:

#### Table 1: Steady-State Baseline Performance (EXP-01 to EXP-04)
| Experiment ID | Algorithm | Policy | Cluster Size ($N$) | Mean Throughput (ops/s) | Latency $p50$ (ms) | Latency $p95$ (ms) |
|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **EXP-01** | Bully | ALL | 3 | $32.28 \pm 32.28$ | 103.80 | 150.46 |
| **EXP-01** | Bully | ALL | 5 | $23.20 \pm 23.39$ | 150.78 | 197.61 |
| **EXP-01** | Bully | ALL | 7 | $19.72 \pm 17.97$ | 167.50 | 238.71 |
| **EXP-02** | Bully | MAJORITY | 3 | $31.31 \pm 31.41$ | 109.86 | 144.51 |
| **EXP-02** | Bully | MAJORITY | 5 | $23.77 \pm 25.12$ | 149.17 | 208.65 |
| **EXP-02** | Bully | MAJORITY | 7 | $18.32 \pm 19.38$ | 193.93 | 247.87 |
| **EXP-03** | Ring | ALL | 3 | $39.42 \pm 32.50$ | 68.43 | 137.10 |
| **EXP-03** | Ring | ALL | 5 | $29.49 \pm 23.90$ | 92.97 | 188.27 |
| **EXP-03** | Ring | ALL | 7 | $19.18 \pm 19.52$ | 189.01 | 230.67 |
| **EXP-04** | Ring | MAJORITY | 3 | $32.16 \pm 28.26$ | 98.74 | 138.86 |
| **EXP-04\*** | Ring | MAJORITY | 5 | $17.67^*$ (valid trial) | 161.49 | 212.87 |
| **EXP-04** | Ring | MAJORITY | 7 | $18.01 \pm 16.39$ | 184.85 | 240.72 |

*\*EXP-04 $N=5$ note: 2 trials encountered transient Windows socket recycling collisions during rapid sequential Docker spin-up; valid throughput computed over $K_{\text{valid}}=1$.*

#### Table 2: Leader Failover & Message Overhead Comparison (EXP-05)
| Cluster Size ($N$) | Algorithm | Mean Messages Exchanged | Theoretical Complexity | Failover Downtime ($T_{\text{failover}}$, ms) | Post-Election Readiness ($\Delta T_{\text{readiness}}$, ms) |
|:---:|:---:|:---:|:---:|:---:|:---:|
| **3** | Bully | 5.0 | $O(N^2)$ | $3617.77 \pm 762.38$ | $39.75 \pm 31.49$ |
| **3** | Ring | 10.7 | $O(N)$ | $3395.65 \pm 28.04$ | $45.78 \pm 9.45$ |
| **5** | Bully | 19.0 | $O(N^2)$ | $2947.26 \pm 1891.02$ | $66.97 \pm 36.44$ |
| **5** | Ring | 23.7 | $O(N)$ | $3459.75 \pm 344.71$ | $65.89 \pm 51.37$ |
| **7** | Bully | 40.3 | $O(N^2)$ | $3679.70 \pm 526.32$ | $75.67 \pm 45.10$ |
| **7** | Ring | 33.3 | $O(N)$ | $3629.58 \pm 853.55$ | $97.94 \pm 37.24$ |

- **Key Analytical Insight:**
  - At $N=3$ and $N=5$, Bully exchanges fewer messages than Ring.
  - At $N=7$, Ring exchanges significantly fewer messages ($33.3$ vs $40.3$), empirically confirming the crossover point where Ring's linear $O(N)$ scaling out-performs Bully's quadratic $O(N^2)$ scaling.

### Section VI: Fault Handling & Invariant Verification
- Discuss EXP-06 (Follower Crash): ALL policy blocks (HTTP 503) whereas MAJORITY policy continues committing votes.
- Discuss EXP-07 (Cascading Failures): Survives two consecutive coordinator crashes with multi-term Lamport advancement.
- Discuss EXP-08 (Follower Rejoin): Rejoining nodes achieve complete database WAL parity in $\approx 2.28-2.29\text{s}$ via `AutoFollowerSync`.
- Discuss EXP-09 (Network Partition): 100% of minority partition requests are rejected with HTTP 503, preventing split-brain tallies.
- Assert formal verified invariants: **0 lost votes, 0 double-counted ballots, 0 ghost votes, and 100% tally convergence across all 97 passing trials**.

---

## 4. Citation & Reference Verification Audit

All 15 references cited in the manuscript draft have been verified against academic databases:

1. **[1] S. Patel & G. Tere (2025)**: *Enhancing election algorithms for distributed systems...* Int. J. Soft Comput. Eng. (DOI: `10.35940/ijsce.F8203.15010325`). Verified.
2. **[2] Y. Wang et al. (2024)**: *SCRaft: Achieving fast and stable elections in Raft...* IEEE HPCC 2024 (DOI: `10.1109/HPCC64274.2024.00081`). Verified.
3. **[3] J. Chalopin et al. (2024)**: *Deterministic self-stabilising leader election...* LIPIcs DISC 2024 (DOI: `10.4230/LIPIcs.DISC.2024.13`). Verified.
4. **[4] J. Ballweg (2024)**: *PureLottery: Fair and bias-resistant leader election...* TUM Thesis (arXiv: `2402.17459`). Verified.
5. **[5] Y. Hu (2025)**: *FTI-TMR: A fault tolerance and isolation algorithm...* (arXiv: `2510.16896`). Verified.
6. **[6] A. D. Kshemkalyani et al. (2025)**: *Near-linear time leader election in multiagent networks...* AAMAS 2025 (DOI: `10.5555/3709347.3743753`). Verified.
7. **[7] X. Deng et al. (2024)**: *A novel Raft consensus algorithm (CB-Raft)...* J. Supercomput. (DOI: `10.1007/s11227-024-06438-6`). Verified.
8. **[8] S. Mohammedi Taieb & M. A. Laredj (2025)**: *GFEA: Leader election algorithm...* Sci. Eng. Technol. (DOI: `10.54327/set2025/v5.i2.216`). Verified.
9. **[9] Z. Xu et al. (2023)**: *Exact fault-tolerant consensus with voting validity...* IEEE IPDPS (DOI: `10.1109/IPDPS54959.2023.00089`). Verified.
10. **[10] R. C. von Seck (2025)**: *Robustness and performance of fault-tolerant consensus...* Ph.D. dissertation, TU Munich. Verified.
11. **[11] Riga Technical University (2025)**: *Analysis of fault-tolerant algorithms for distributed systems...* Ph.D. thesis. Verified.
12. **[12] H. Garcia-Molina (1982)**: *Elections in a distributed computing system.* IEEE Trans. Comput., C-31(1):48–59. Classical Bully Algorithm. Verified.
13. **[13] E. Chang & R. Roberts (1979)**: *An improved algorithm for decentralized extrema-finding in circular configurations.* Commun. ACM, 22(5):281–283. Classical Ring Algorithm. Verified.
14. **[14] L. Lamport (1978)**: *Time, clocks, and the ordering of events in a distributed system.* Commun. ACM, 21(7):558–565. Logical Clocks. Verified.
15. **[15] D. Ongaro & J. Ousterhout (2014)**: *In search of an understandable consensus algorithm.* USENIX ATC 2014. Raft Consensus. Verified.

---

## 5. Implementation Roadmap for Final Manuscript

1. **Step 1:** Revise document sections to incorporate empirical Tables 1 and 2.
2. **Step 2:** Insert SVG/PNG vector renderings of Architecture and Sequence diagrams.
3. **Step 3:** Reformat references into standard IEEE two-column conference format.
4. **Step 4:** Review author list, institutional affiliations, and student roll numbers.
