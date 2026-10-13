# Product Requirements Document (PRD)
## Fault-Tolerant Distributed Voting System

---

## 1. Problem Statement
Conventional voting applications rely on a single centralized server to receive, validate, store, and tally votes. If that server fails, the voting service becomes unavailable and recovering the latest voting state is difficult. There is no built-in mechanism for continuing service, detecting failure, or electing a replacement coordinator.

## 2. Goal
Build a small-scale voting platform where **multiple server nodes** cooperate to provide the voting service. If the current coordinator node fails, the remaining nodes detect the failure, elect a new coordinator (using Bully or Ring algorithm), and resume accepting/tallying votes **without losing votes or counting any vote twice**.

## 3. Target Users
| User | Need |
|---|---|
| Voter | Cast exactly one vote, get confirmation it was recorded, trust the result is accurate even if something goes wrong behind the scenes |
| Admin / Demo operator | Start the cluster, observe which node is coordinator, deliberately kill a node to demonstrate failover, view live results and cluster health |
| Evaluator (project grading) | Verify the system tolerates node failure, correctly elects a new leader, and produces a consistent, duplicate-free tally |

## 4. User Stories
1. As a voter, I can enter my voter ID and cast a vote for one candidate.
2. As a voter, I cannot vote twice — a second attempt is rejected.
3. As a voter, I receive a Vote ID as a receipt after voting.
4. As an admin, I can see which node is currently the coordinator.
5. As an admin, I can kill the coordinator node and watch the system elect a new one automatically.
6. As an admin, I can switch the election algorithm (Bully vs Ring) before starting a cluster.
7. As an admin, I can view the live tally and confirm no votes were lost or duplicated after a failover.
8. As an evaluator, I can run the same failure scenario against a 3-, 5-, and 7-node cluster and see measured election/recovery times.

## 5. Scope (MVP)
- Voter login (ID entry, no full auth)
- Ballot screen with candidate list and single-choice submission
- Vote confirmation receipt (Vote ID)
- Backend: multi-node cluster (Python + gRPC), Bully and Ring election, heartbeat failure detection, Lamport clocks, per-node MySQL storage, vote replication
- Admin dashboard: cluster status, current coordinator, kill-node button, live tally
- Docker Compose deployment for 3/5/7-node clusters
- Experiment scripts to measure election time, recovery time, message overhead, throughput, lost/duplicate votes

## 6. Out of Scope
- Production-grade authentication/security (OTP, JWT, RBAC)
- Byzantine fault tolerance (only crash faults are handled)
- Multi-host / multi-datacenter deployment (single Docker host only)
- Horizontal UI scaling, load balancing of client traffic
- Persisting results beyond the current cluster run (no long-term archival)

## 7. Success Metrics
- Zero lost votes and zero duplicate votes across all tested failover scenarios
- Election + recovery completes automatically without manual intervention
- Measurable, repeatable comparison data for Bully vs Ring across 3/5/7-node clusters
- Demo-able live failover (kill a container, system recovers within a few seconds, visible in UI)

## 8. Assumptions & Constraints
- All nodes run on a single Docker host (course-project scale, not production).
- Only crash failures are simulated (a node stops responding entirely, not sending corrupt data).
- Voter identity is self-asserted (ID entered by the voter), not independently verified.
- Cluster size and election algorithm are fixed for the duration of one run (chosen at startup).

## 9. Open Questions
- Do we need persistent voter-eligibility list (predefined list of allowed voter IDs) or is any ID acceptable for the demo?
- Should results be visible to voters in real time, or only after voting "closes"?
