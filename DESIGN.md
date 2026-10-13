# DESIGN.md
## Fault-Tolerant Distributed Voting System — System Design

---

## 1. Design Goals
- No single point of failure for vote acceptance or storage.
- Automatic recovery from coordinator crash with no manual intervention.
- No vote lost, no vote double-counted, across a failover.
- Election algorithm swappable without touching the rest of the system.

## 2. Node Roles
Every node runs identical code. At any moment exactly one node is the **coordinator** (accepts votes, runs the tally); the rest are **replicas** (store a copy of the vote log, participate in heartbeat monitoring and elections).

## 3. Leader Election

### 3.1 Bully Algorithm
- Every node has a unique numeric ID; highest ID among active nodes becomes coordinator.
- On detecting coordinator failure, a node sends `ELECTION` to all nodes with a higher ID.
- If no `OK` reply within a timeout, it declares itself coordinator and broadcasts `COORDINATOR`.
- If a higher node replies `OK`, that node takes over running the election.
- Worst-case message complexity: O(n²).

### 3.2 Ring Algorithm
- Nodes arranged in a logical ring (e.g., sorted by ID); each node knows only its successor.
- A node detecting failure sends `ELECTION` (with its ID) to its successor.
- Each node forwards the larger of (received ID, own ID); when a node sees its own ID return, it is the winner.
- Winner circulates `COORDINATOR` once around the ring.
- Message complexity: O(n) best case, up to O(2n) worst case.

### 3.3 Selecting the Algorithm
- Chosen **per cluster run**, not per node, via `ELECTION_ALGORITHM` env var / CLI flag at container startup.
- All nodes in a given cluster run must agree on the same algorithm — mismatched configs are a startup-time error.
- Both algorithms implement a common internal interface (`onCoordinatorFailureDetected`, `handleElectionMessage`, `handleCoordinatorMessage`, `handleOkMessage`) so the heartbeat monitor and replication logic never need to know which one is active.

## 4. Failure Detection
- Coordinator broadcasts a heartbeat every `HEARTBEAT_INTERVAL_MS`.
- Each node tracks the last heartbeat received time.
- If no heartbeat arrives within `HEARTBEAT_TIMEOUT_MS` (~3x interval), the node marks the coordinator failed and triggers an election.
- Purely local, elapsed-time based — no synchronized global clock required.

## 5. Logical Ordering — Lamport Clocks
- Each node keeps an integer counter.
- Increment before every local event.
- On send: increment, attach counter to message.
- On receive: `counter = max(local, received) + 1`.
- Applied to vote submissions, election messages, and replication messages, so causally related events can be ordered consistently across all replicas even without synchronized physical clocks.

## 6. Vote Replication & Duplicate Prevention
1. Client submits a vote to the current coordinator.
2. Coordinator generates `vote_id = client_id + lamport_ts`.
3. Coordinator writes the vote to its own MySQL instance.
4. Coordinator replicates `{vote_id, lamport_ts, choice, node_id}` to every other active node via `ReplicateVote`.
5. Each replica writes it to its own local MySQL (unique constraint on `vote_id` rejects accidental duplicates).
6. Coordinator acknowledges the client only after replication succeeds on a majority of nodes.

### Recovery after coordinator failure
1. New coordinator is elected (Section 3).
2. New coordinator issues `SyncLog` to surviving nodes to collect their vote logs.
3. Logs are merged: duplicate `vote_id`s are dropped, remaining entries sorted by `lamport_ts`.
4. Vote acceptance resumes from the newly elected coordinator.

## 7. Experiment / Metric Definitions
| Metric | Definition |
|---|---|
| Election time | Time from coordinator becoming unreachable to a new coordinator being confirmed by all surviving nodes |
| Message overhead | Total election-related messages exchanged in one election cycle |
| Vote processing time | Time from vote submission to replication-acknowledged |
| Recovery time | Time from failure detection to the system resuming normal vote acceptance |
| Throughput | Votes accepted/replicated per second under sustained load |
| Lost votes | Submitted votes absent from the final tally |
| Duplicate votes | Vote IDs counted more than once in the final tally |

## 8. UI Flow (Voter)
```
Login (enter voter ID)
  → Ballot (choose one candidate, Submit)
    → Confirmation (show Vote ID receipt)
```

## 9. UI Flow (Admin)
```
Dashboard
  → Current coordinator + active node list
  → Live tally
  → "Kill node" button (demo failover)
  → Election/recovery time of the last failover event
```

## 10. Known Limitations (by design, see PRD §6 Out of Scope)
- Only crash faults are handled, not Byzantine/malicious nodes.
- Single Docker host — no real network partition behavior.
- Voter identity is self-asserted, not independently verified.
