# 7-Node Distributed System Implementation & Live Demonstration Manual

**Project Title:** Distributed Fault-Tolerant Voting System with Pluggable Leader Election  
**Institution:** Pimpri Chinchwad College of Engineering (PCCoE), Pune  
*(An Autonomous Institute Affiliated to Savitribai Phule Pune University — SPPU)*  
**Department:** Department of Computer Engineering  
**Academic Year:** 2025–2026  
**Course:** Distributed Systems / Capstone Project  
**Faculty Guide:** Mr. Ganesh Deshmukh (Assistant Professor)  
**Project Group Members:**
* **Adwait Kamble** — Roll No: `123B1D002`
* **Advait Nathe** — Roll No: `123B1D029`
* **Nikhil Puppalwar** — Roll No: `123B1D040`

---

## 1. Executive Summary & Purpose

This document provides a comprehensive, step-by-step engineering and demonstration manual for evaluating the **7-Node Distributed Fault-Tolerant Voting Cluster**. It is specifically structured for academic defense and project evaluation before faculty examiners.

The 7-node cluster represents the maximum scaled topology of this project, featuring:
* **14 Docker Containers**: 7 application runtime nodes + 7 physically isolated MySQL databases.
* **Shared-Nothing Persistence**: Dedicated physical database instances per node with zero shared volumes.
* **Pluggable Consensus & Election**: Bully ($O(N^2)$ message complexity) and Ring ($O(N)$ message complexity) algorithms.
* **Monotonic Failure Detection**: Sub-3-second leader failure detection with single-fire latches.
* **Majority Quorum Replication**: Quorum threshold $Q = \lfloor 7/2 \rfloor + 1 = 4$ nodes, tolerating up to 3 simultaneous follower crashes without loss of write availability.
* **Durable Catch-Up Reconciliation (`AutoFollowerSync`)**: Recovered nodes automatically achieve 100% database WAL parity via delta synchronization.

---

## 2. 7-Node Cluster Architectural Specification

### 2.1 Cluster Topology & Port Mapping

| Node | Service Container | Database Container | HTTP REST Port (Web UI) | Host gRPC Port | Host MySQL Port | Initial Role |
|:---:|:---|:---|:---:|:---:|:---:|:---:|
| **Node 1** | `voting-node1` | `voting-node1-db` | **5001** | 55051 | 33061 | Follower |
| **Node 2** | `voting-node2` | `voting-node2-db` | **5002** | 55052 | 33062 | Follower |
| **Node 3** | `voting-node3` | `voting-node3-db` | **5003** | 55053 | 33063 | Follower |
| **Node 4** | `voting-node4` | `voting-node4-db` | **5004** | 55054 | 33064 | Follower |
| **Node 5** | `voting-node5` | `voting-node5-db` | **5005** | 55055 | 33065 | Follower |
| **Node 6** | `voting-node6` | `voting-node6-db` | **5006** | 55056 | 33066 | Follower (Highest Survivor) |
| **Node 7** | `voting-node7` | `voting-node7-db` | **5007** | 55057 | 33067 | **Initial Coordinator** |

### 2.2 Network & Communication Boundaries
* **Bridge Network**: `docker_voting-net` (subnet: `172.19.0.0/16`).
* **Inter-Node gRPC (Port 50051)**: Internal peer discovery uses Docker container DNS names (`node1:50051` through `node7:50051`).
* **Database Connection**: Each node connects strictly to its paired database container (e.g. `node1` $\to$ `node1-db:3306`, DB: `voting_node`, User: `root`, Pass: `votingpass`).

---

## 3. Pre-Demonstration Checklist

Before starting the 7-node demonstration, ensure no conflicting containers are running:

```powershell
# 1. Navigate to the project root
cd "d:\Studies\B.Tech first sem\Distributed System\Distributed Voting System"

# 2. Stop any existing 3-node cluster and clean ephemeral volumes
docker compose -f docker/docker-compose.3node.yml down -v

# 3. Verify Docker Desktop is active
docker ps
```

---

## 4. Complete Step-by-Step Live Demonstration Script

Follow these steps sequentially during the presentation to demonstrate the system's fault-tolerant behavior.

---

### Phase 1: Cluster Startup & Health Verification

#### Step 1.1: Launch the 7-Node Cluster with Majority Quorum
Execute in PowerShell:

```powershell
$env:REPLICATION_POLICY="majority"
$env:ELECTION_ALGORITHM="bully"
docker compose -f docker/docker-compose.7node.yml up -d --build
```

> **Examiner Talking Point:**  
> *"Sir, we are launching 14 separate containers. Notice that each node has its own dedicated MySQL database container. There is no shared database or shared disk volume. Furthermore, we are configuring the cluster with majority quorum replication, which requires 4 acknowledgments out of 7 nodes."*

#### Step 1.2: Verify Container Health & Topology Discovery
Wait approximately 15–20 seconds for MySQL databases to initialize, then check all nodes:

```powershell
# Check health of all 7 nodes:
1..7 | ForEach-Object {
    $port = 5000 + $_
    $health = Invoke-RestMethod "http://localhost:$port/api/health"
    Write-Host "Node $_ on Port $port : Status = $($health.status)"
}
```

**Expected Output:**
```
Node 1 on Port 5001 : Status = ok
Node 2 on Port 5002 : Status = ok
Node 3 on Port 5003 : Status = ok
Node 4 on Port 5004 : Status = ok
Node 5 on Port 5005 : Status = ok
Node 6 on Port 5006 : Status = ok
Node 7 on Port 5007 : Status = ok
```

#### Step 1.3: Inspect Cluster Roles
Query all 7 nodes to show that they agree on the active Coordinator:

```powershell
1..7 | ForEach-Object {
    $port = 5000 + $_
    $n = Invoke-RestMethod "http://localhost:$port/api/node"
    [PSCustomObject]@{
        Node = $n.node_id
        Role = $n.role
        IsCoordinator = $n.is_coordinator
        CoordID = $n.coordinator_id
        Term = $n.election_term
        Algorithm = $n.election_algorithm
    }
} | Format-Table -AutoSize
```

**Expected Output:**
```
Node Role        IsCoordinator CoordID Term Algorithm
---- ----        ------------- ------- ---- ---------
   1 follower            False       7    0 bully    
   2 follower            False       7    0 bully    
   3 follower            False       7    0 bully    
   4 follower            False       7    0 bully    
   5 follower            False       7    0 bully    
   6 follower            False       7    0 bully    
   7 coordinator          True       7    0 bully    
```
> **Examiner Talking Point:**  
> *"As you can see, Node 7 is the elected Coordinator with Term 0. Nodes 1 through 6 are Followers that have discovered Node 7 and are receiving periodic heartbeats every 500 milliseconds."*

---

### Phase 2: Steady-State Vote Ingestion & Replication

#### Step 2.1: Submit Ballot to Coordinator (Node 7)
Cast ballot `voter_01` voting for candidate `Alice`:

```powershell
Invoke-RestMethod -Uri "http://localhost:5007/api/votes" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"client_id": "voter_01", "choice": "Alice"}'
```

**Expected Output:**
```powershell
choice     : Alice
client_id  : voter_01
lamport_ts : 1
node_id    : 7
success    : True
vote_id    : voter_01:7:1
```

#### Step 2.2: Demonstrate Consensus Invariant: Follower Write Rejection
Show what happens if a client attempts to bypass the leader and submit a vote directly to a Follower (e.g. Node 1):

```powershell
try {
    Invoke-RestMethod -Uri "http://localhost:5001/api/votes" `
      -Method Post `
      -ContentType "application/json" `
      -Body '{"client_id": "voter_bypass", "choice": "Bob"}'
} catch {
    $stream = $_.Exception.Response.GetResponseStream()
    $reader = New-Object System.IO.StreamReader($stream)
    $reader.ReadToEnd()
}
```

**Expected Output:**
```json
{
  "coordinator_id": 7,
  "error": "not_coordinator",
  "message": "Node is not currently accepting votes (not coordinator or recovering)",
  "role": "follower",
  "success": false
}
```
> **Examiner Talking Point:**  
> *"Sir, this demonstrates strict write consistency. A follower node refuses direct writes with HTTP 409 and explicitly returns a redirect hint pointing to Coordinator Node 7. This prevents split-brain writes."*

#### Step 2.3: Verify Multi-Node Database WAL Replication
Query the tally from all 7 nodes to verify that ballot `voter_01` committed everywhere:

```powershell
1..7 | ForEach-Object {
    $port = 5000 + $_
    $t = Invoke-RestMethod "http://localhost:$port/api/votes/tally"
    [PSCustomObject]@{
        Node = $_
        Port = $port
        Alice = $t.tally.Alice
        TotalCommitted = $t.total_votes
    }
} | Format-Table -AutoSize
```

**Expected Output:**
```
Node  Port Alice TotalCommitted
----  ---- ----- --------------
   1  5001     1              1
   2  5002     1              1
   3  5003     1              1
   4  5004     1              1
   5  5005     1              1
   6  5006     1              1
   7  5007     1              1
```

---

### Phase 3: Coordinator Crash & Leader Election

#### Step 3.1: Simulate Abrupt Coordinator Death
Abruptly terminate Coordinator container `voting-node7`:

```powershell
Write-Host "Crashing active Coordinator Node 7..." -ForegroundColor Red
docker stop voting-node7
```

#### Step 3.2: Observe Leader Failure Detection & Bully Election
Wait approximately 4–5 seconds, then query the surviving nodes (1 through 6):

```powershell
1..6 | ForEach-Object {
    $port = 5000 + $_
    $n = Invoke-RestMethod "http://localhost:$port/api/node"
    [PSCustomObject]@{
        Node = $n.node_id
        Role = $n.role
        IsCoordinator = $n.is_coordinator
        NewCoordinatorID = $n.coordinator_id
        ElectionTerm = $n.election_term
    }
} | Format-Table -AutoSize
```

**Expected Output:**
```
Node Role        IsCoordinator NewCoordinatorID ElectionTerm
---- ----        ------------- ---------------- ------------
   1 follower            False                6            1
   2 follower            False                6            1
   3 follower            False                6            1
   4 follower            False                6            1
   5 follower            False                6            1
   6 coordinator          True                6            1
```

#### Step 3.3: What Happened Under the Hood (Explain to Sir)
1. **Heartbeat Interruption:** When Node 7 died, followers stopped receiving 500ms heartbeats.
2. **Monotonic Failure Detection Latch:** Followers track elapsed monotonic time:  
   $$\text{time.monotonic}() - \text{last\_heartbeat} \ge 3000\text{ms}$$  
   At $3.0\text{s}$, the single-fire latch tripped.
3. **Bully Election Execution:**
   - Lower nodes (Nodes 1 through 5) sent `ELECTION` probes to all nodes with higher IDs.
   - Node 6 received probes from Nodes 1..5, responded with `OK` (suppressing lower nodes), and attempted to probe higher Node 7.
   - Node 7 did not respond within the timeout.
   - Having no surviving higher peer, **Node 6 declared victory**.
4. **Term Increment & Victory Broadcast:**
   - Node 6 incremented the election term from `0` to `1`.
   - Node 6 transitioned its state to `COORDINATOR` and broadcasted a `Coordinator(new_coord=6, term=1)` message to Nodes 1..5.
   - Node 6 resumed 500ms heartbeat broadcasts and became write-ready within **$75.67\text{ms}$**.

---

### Phase 4: High Availability Under Failure (Quorum Writes)

#### Step 4.1: Submit New Vote to the New Coordinator (Node 6)
Even though Node 7 is dead, our cluster has 6 active nodes. With majority quorum $Q = \lfloor 7/2 \rfloor + 1 = 4$, the cluster has sufficient nodes ($6 \ge 4$) to achieve quorum consensus:

```powershell
Invoke-RestMethod -Uri "http://localhost:5006/api/votes" `
  -Method Post `
  -ContentType "application/json" `
  -Body '{"client_id": "voter_02", "choice": "Bob"}'
```

**Expected Output:**
```powershell
choice     : Bob
client_id  : voter_02
lamport_ts : 2
node_id    : 6
success    : True
vote_id    : voter_02:6:2
```

#### Step 4.2: Verify Tally on Surviving Nodes
```powershell
1..6 | ForEach-Object {
    $port = 5000 + $_
    $t = Invoke-RestMethod "http://localhost:$port/api/votes/tally"
    [PSCustomObject]@{
        Node = $_
        Alice = $t.tally.Alice
        Bob = $t.tally.Bob
        TotalCommitted = $t.total_votes
    }
} | Format-Table -AutoSize
```

**Expected Output:**
```
Node Alice Bob TotalCommitted
---- ----- --- --------------
   1     1   1              2
   2     1   1              2
   3     1   1              2
   4     1   1              2
   5     1   1              2
   6     1   1              2
```
> **Examiner Talking Point:**  
> *"Sir, this proves high availability and fault tolerance. Even after the coordinator crashed, the cluster elected a new leader without human intervention, and incoming votes continued committing with full consistency."*

---

### Phase 5: Follower Recovery & Log Synchronization (`AutoFollowerSync`)

At this moment, Node 7 is down and its local database is missing ballot `voter_02` (it only has `voter_01`).

#### Step 5.1: Restart Crashed Container Node 7
```powershell
Write-Host "Restarting recovering Node 7..." -ForegroundColor Green
docker start voting-node7
```

#### Step 5.2: Observe Automatic Reconciliation
Wait 3–4 seconds for Node 7 to start and synchronize, then check its role:

```powershell
Invoke-RestMethod http://localhost:5007/api/node
```

**Expected Output:**
```powershell
accepting_votes    : False
coordinator_id     : 6
election_term      : 1
is_coordinator     : False
node_id            : 7
role               : follower
state              : FOLLOWER
```
> **Examiner Talking Point:**  
> *"Notice that Node 7 did not attempt to reclaim leadership illegally. It recognized that Node 6 holds Term 1, demoted itself to a Follower, and accepted Node 6 as Coordinator."*

#### Step 5.3: Verify Full WAL Parity Across All 7 Nodes
Check the tally across all 7 nodes, specifically checking that Node 7 now contains both votes (`Alice: 1`, `Bob: 1`):

```powershell
1..7 | ForEach-Object {
    $port = 5000 + $_
    $t = Invoke-RestMethod "http://localhost:$port/api/votes/tally"
    [PSCustomObject]@{
        Node = $_
        Port = $port
        Alice = $t.tally.Alice
        Bob = $t.tally.Bob
        TotalCommitted = $t.total_votes
    }
} | Format-Table -AutoSize
```

**Expected Output:**
```
Node  Port Alice Bob TotalCommitted
----  ---- ----- --- --------------
   1  5001     1   1              2
   2  5002     1   1              2
   3  5003     1   1              2
   4  5004     1   1              2
   5  5005     1   1              2
   6  5006     1   1              2
   7  5007     1   1              2
```
> **Examiner Talking Point:**  
> *"Sir, Node 7 executed our `AutoFollowerSync` protocol. It inspected its local maximum Lamport timestamp (1), detected that Coordinator Node 6 possessed committed entries with timestamp > 1, streamed the missing delta entries via gRPC `SyncLog`, and caught up its write-ahead log. We now have 100% database WAL parity across all 7 nodes."*

---

### Phase 6: Interactive Web UI Demonstration

Show the live cluster in the web browser:
1. Open **[http://localhost:5006](http://localhost:5006)** in Google Chrome or Edge.
2. Demonstrate the **Dashboard Tab**: Show that Node 6 displays the golden **COORDINATOR** badge and lists all 6 active peers.
3. Open **[http://localhost:5001](http://localhost:5001)**: Show that Node 1 displays the **FOLLOWER** badge and identifies `Coordinator: Node 6`.
4. Click the **"Live Tally" Tab**: Show the real-time distribution graph (`Alice: 1`, `Bob: 1`).
5. Click the **"Events" Tab**: Show the live event log tracking heartbeats, quorum ACKs, and the Term 1 leader transition.

---

### Phase 7: Safe Cluster Teardown

After completing the demonstration, cleanly stop the 7-node cluster:

```powershell
docker compose -f docker/docker-compose.7node.yml down -v
```

---

## 5. Algorithmic Comparison: Bully vs Ring on 7 Nodes

During your viva, highlight the mathematical and empirical trade-offs between the two algorithms:

| Metric | Bully Algorithm ($N=7$) | Ring Algorithm ($N=7$) | Significance |
|---|:---:|:---:|---|
| **Theoretical Message Complexity** | $O(N^2) \approx 42\text{ messages}$ | $O(N) \approx 21-28\text{ messages}$ | Linear vs Quadratic scaling |
| **Empirical Messages Exchanged** | **$40.33 \pm 1.15$ messages** | **$33.33 \pm 1.15$ messages** | Ring generates **17.4% fewer messages** at $N=7$ |
| **Failover Convergence Time** | $3283.74\text{ms}$ | $3354.26\text{ms}$ | Dominated by $3000\text{ms}$ failure latch |
| **Post-Election Write Readiness** | $75.67\text{ms}$ | $97.94\text{ms}$ | Bully achieves slightly faster broadcast |
| **Topology Assumption** | Fully connected graph | Logical unidirectional ring | Bully handles arbitrary link sets; Ring relies on successor routing |

---

## 6. Examiner Viva Q&A Cheat Sheet (7-Node Specific)

#### Q1: "Why did Node 6 become the new leader instead of Node 1 or Node 5?"
> **Answer:**  
> *"Under the Bully algorithm, nodes with higher numerical IDs have priority. When Node 7 crashed, surviving nodes initiated elections. Node 6, having the highest surviving ID among nodes 1 through 6, responded with `OK` to lower nodes (suppressing them), found no higher peer responding, and declared itself coordinator."*

#### Q2: "What happens if three nodes crash simultaneously in this 7-node cluster?"
> **Answer:**  
> *"In a 7-node cluster under the `majority` replication policy, the quorum threshold is $Q = \lfloor 7/2 \rfloor + 1 = 4$. If 3 nodes crash, 4 nodes remain alive ($4 \ge 4$), so the cluster continues committing votes without disruption. If a 4th node crashes, leaving only 3 nodes, the cluster halts writes with HTTP 503 to prevent split-brain inconsistency, strictly prioritizing safety over availability."*

#### Q3: "How do you prevent a split-brain scenario where two nodes claim to be coordinator?"
> **Answer:**  
> *"Three safeguards prevent split-brain:  
> 1. Strict quorum requirements: A coordinator cannot commit writes without $\lfloor N/2 \rfloor + 1$ ACKs. Two majorities cannot exist simultaneously in any partition.  
> 2. Monotonic election terms: Any message with an older term is rejected.  
> 3. Monotonic heartbeat latch: Followers only trigger elections if $3000\text{ms}$ elapse without a valid heartbeat, and the latch fires exactly once."*

#### Q4: "How does the rejoining node catch up on votes it missed while offline?"
> **Answer:**  
> *"Through our `AutoFollowerSync` protocol: upon container restart, Node 7 checks its local database for `MAX(lamport_ts)`. Upon receiving a heartbeat from the active leader (Node 6), it sends a gRPC `SyncLog` request containing its last known timestamp. Node 6 queries all committed votes greater than that timestamp and streams them back. Node 7 inserts them into its local MySQL database and `sync_log`, restoring 100% WAL parity."*
