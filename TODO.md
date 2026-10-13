# TODO.md
## Fault-Tolerant Distributed Voting System — Build Checklist

---

## Phase 0 — Setup
- [x] Initialize repo structure (`/node`, `/client`, `/docker`, `/experiments`, `/docs`)
- [x] Write `.proto` file (NodeService: SubmitVote, Heartbeat, Election, Coordinator, ReplicateVote, SyncLog)
- [x] Generate gRPC Python stubs (`grpcio-tools`)
- [x] Set up MySQL schema (`votes`, `election_log`) + init script per container

## Phase 1 — Single Node (no clustering yet)
- [x] Python gRPC server skeleton
- [x] `SubmitVote` writes to local MySQL, returns Vote ID
- [x] Vote ID generation (`client_id + lamport_ts`)
- [x] Lamport clock module (increment, send, receive rules)
- [x] Unit tests: Lamport clock, Vote ID uniqueness

## Phase 2 — Multi-Node Communication
- [x] Peer config (static list of node addresses via env var)
- [x] Heartbeat sender (coordinator → peers, on interval)
- [x] Heartbeat timeout detection (peer side, time.monotonic())
- [x] `ReplicateVote` RPC + peer-side idempotent ingestion + local rollback on failure
- [x] Integration test: 3-node cluster, vote replicates to all over real gRPC with isolated SQLite DBs

## Phase 3 — Leader Election
- [ ] Define common ElectionStrategy interface
- [ ] Implement BullyElection (ELECTION/OK/COORDINATOR handling)
- [ ] Implement RingElection (ring ordering, ELECTION/COORDINATOR handling)
- [ ] Wire `ELECTION_ALGORITHM` env var to select strategy at startup
- [ ] Trigger election automatically on heartbeat timeout
- [ ] Test: kill coordinator manually, confirm new coordinator elected (both algorithms)

## Phase 4 — Recovery
- [ ] `SyncLog` RPC: new coordinator pulls logs from surviving peers
- [ ] Merge logic: dedupe by vote_id, sort by lamport_ts
- [ ] Resume vote acceptance after recovery
- [ ] Test: votes submitted during election are not lost or duplicated

## Phase 5 — Client-Facing Layer
- [ ] Flask REST bridge (`/api/vote`, `/api/results`, `/api/cluster/status`)
- [ ] Bridge forwards to current coordinator (lookup/refresh logic)
- [ ] `/api/admin/kill/{node_id}` endpoint for demo

## Phase 6 — React Frontend
- [ ] Login page (voter ID entry)
- [ ] Ballot page (candidate list, submit)
- [ ] Confirmation page (show Vote ID)
- [ ] Admin dashboard: coordinator status, live tally, kill-node button
- [ ] Wire up to Flask REST API

## Phase 7 — Dockerization
- [ ] Dockerfile for node app
- [ ] docker-compose.yml: N app containers + N MySQL containers on shared network
- [ ] Support 3/5/7-node profiles via `.env` or compose profiles
- [ ] Verify cold start: cluster comes up, elects initial coordinator

## Phase 8 — Experiments
- [ ] Failure-injection script (`docker stop <coordinator>` at a known point)
- [ ] Metric capture: election time, message overhead, vote processing time, recovery time, throughput, lost votes, duplicate votes
- [ ] Run matrix: {Bully, Ring} × {3, 5, 7 nodes}, multiple trials each
- [ ] Aggregate results (pandas), plot comparisons (matplotlib)

## Phase 9 — Documentation & Writeup
- [ ] Update PROJECT_MEMORY.md with final decisions/deviations
- [ ] Insert experiment results into paper (Results section)
- [ ] Final review of DESIGN.md / ARCHITECTURE.md against actual implementation
- [ ] Record demo video / prepare live-failover demo script

---

## Current Status
> Update this section as you go.

- [x] Phase 0 — Design & Amendments Approved
- [x] Phase 1 — Single-Node Foundation Complete
- [x] Phase 2 — Multi-Node Communication, Replication & Heartbeat
- [x] Phase 3 — Leader Election (Bully & Ring)
- [x] Phase 4 — Crash-Recovery Log Reconciliation & Ghost-Vote Prevention
- [x] Phase 5 — Flask REST Bridge
- [x] Phase 6 — React Frontend & Dockerized Multi-Node Clusters (1, 3, 5, 7 nodes)
- [x] Phase 7.1 — Experimental Plan Design
- [x] Phase 7.2 — Automated Experiment Framework & Runner Tooling
- [ ] Phase 7.3 — Empirical Matrix Execution & Benchmark Analysis
- [ ] Phase 8 — Research Documentation & Writeup

