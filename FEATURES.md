# FEATURES.md
## Fault-Tolerant Distributed Voting System — Feature List

---

## MVP Features (must-have for demo/grading)

### Voting
- [ ] Voter login via voter ID (no password, self-asserted)
- [ ] Ballot screen listing candidates/options
- [ ] Single-choice vote submission
- [ ] Duplicate-vote rejection (same client_id voting twice)
- [ ] Vote confirmation screen showing Vote ID receipt

### Distributed Core
- [ ] Bully algorithm implementation
- [ ] Ring algorithm implementation
- [ ] Startup-time switch between Bully/Ring (`ELECTION_ALGORITHM` flag)
- [ ] Heartbeat-based coordinator failure detection
- [ ] Lamport logical clock on every node
- [ ] Vote replication to all active nodes before ack
- [ ] Unique Vote ID generation (client_id + lamport_ts)
- [ ] Recovery: merge logs, dedupe, resume accepting votes after failover

### Admin / Demo
- [ ] Cluster status view (current coordinator, active nodes, algorithm in use)
- [ ] Live tally view
- [ ] "Kill node" action to simulate coordinator failure
- [ ] Last election/recovery time displayed after a failover

### Infrastructure
- [ ] Dockerfile for node app
- [ ] docker-compose.yml supporting 3/5/7-node profiles
- [ ] Per-node MySQL container with schema auto-init

### Experiments
- [ ] Failure-injection script (kill coordinator mid-run)
- [ ] Metric capture: election time, message overhead, vote processing time, recovery time, throughput, lost votes, duplicate votes
- [ ] Comparison report/plots: Bully vs Ring across 3/5/7 nodes

---

## Nice-to-Have (if time permits)

- [ ] gRPC-Web direct connection from React (skip Flask bridge)
- [ ] Real-time cluster status updates via WebSocket instead of polling
- [ ] Visual election animation on the admin dashboard (show messages passing between nodes)
- [ ] CSV export of experiment results
- [ ] Predefined voter-eligibility list (instead of free-text voter ID)
- [ ] Voting deadline / "close voting" admin action

---

## Explicitly Out of Scope (see PRD.md §6)
- Byzantine fault tolerance / malicious node handling
- Multi-host or multi-datacenter deployment
- Production authentication (OTP/JWT/RBAC)
- Long-term result archival beyond a single cluster run
- Load balancing of voter traffic across nodes

---

## Feature → Design/Code Traceability
| Feature | Covered in |
|---|---|
| Bully/Ring switch | DESIGN.md §3.3, TRD.md §6 |
| Heartbeat detection | DESIGN.md §4 |
| Lamport clocks | DESIGN.md §5 |
| Vote replication & dedupe | DESIGN.md §6, TRD.md §4 |
| Admin kill-node demo | ARCHITECTURE.md §5, TRD.md §5 |
| Experiment metrics | DESIGN.md §7, TRD.md §8 |
