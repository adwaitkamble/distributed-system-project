# Phase 7 — Controlled Fault-Injection Experiments & Benchmark Analysis

This directory contains the automated, reproducible experimental framework for benchmarking the Distributed Fault-Tolerant Voting System under both steady-state workloads and controlled fault injections across 3, 5, and 7-node cluster topologies.

---

## 📁 Directory Structure

```
experiments/
├── README.md                          # This user guide and reference
├── config/
│   ├── benchmark_config.py            # Workload constants, timeouts, and port mappings
│   └── matrix_definitions.py          # Factorial experiment catalog (EXP-01 to EXP-09)
├── core/
│   ├── cluster_manager.py             # Docker Compose cluster manager & healthcheck waiter
│   ├── fault_injector.py              # Crash-stop, rejoin, freeze, and partition controller
│   ├── workload_client.py             # High-precision concurrent benchmark client (p50/p95/p99)
│   └── telemetry_collector.py         # REST & DB metrics harvester and safety invariant auditor
├── runners/
│   ├── run_benchmark.py               # Standalone steady-state write benchmark CLI
│   ├── run_fault_experiment.py        # Fault injection scenario runner (crash, rejoin, partition)
│   └── run_matrix.py                  # Full factorial matrix test runner
├── analysis/
│   ├── aggregate_metrics.py           # Statistical aggregator (mean, 95% CI, p50, p95, p99, CSV)
│   └── generate_charts.py             # Publication-ready SVG comparison chart generator
└── results/
    ├── raw/                           # Raw JSON event & latency records per trial
    └── summary/                       # Aggregated CSV summaries and publication charts
```

---

## 🚀 Quick Start Guide

### 1. Prerequisites
- **Docker Desktop**: Ensure Docker engine is running with Linux containers enabled.
- **Python**: Python 3.10+ on the host.

### 2. Run a Dry-Run Matrix Plan
Verify the experimental catalog without modifying containers:
```powershell
python -m experiments.runners.run_matrix --dry-run
```

### 2. Standalone Workload Client (Phase 7.2A)
Run a direct benchmark against an already-running cluster node or coordinator:
```powershell
python -m experiments.core.workload_client `
  --target http://localhost:5001 `
  --requests 50 `
  --concurrency 5 `
  --warmup 10 `
  --timeout 5.0 `
  --prefix bench `
  --output experiments/results/raw/workload_smoke.ndjson `
  --summary-output experiments/results/raw/workload_summary.json
```
Options:
- `--target`: Coordinator HTTP base URL (e.g., `http://localhost:5001`).
- `--requests`: Number of measured requests to submit (e.g., `50`).
- `--concurrency`: Number of concurrent worker threads (e.g., `5`).
- `--warmup`: Number of warmup requests executed and discarded from statistical metrics (e.g., `10`).
- `--timeout`: Request timeout in seconds (default: `5.0`).
- `--prefix`: Unique client ID prefix (sanitized, colon-free).
- `--output`: Path to write raw per-request NDJSON observations.
- `--summary-output`: (Optional) Path to write machine-readable summary JSON.

#### NDJSON Streaming Persistence & Crash Safety Boundaries
- **Real-Time Streaming**: Request records are written incrementally as each request finishes via `ThreadSafeNDJSONWriter` (guarded by an internal lock), preventing in-memory record accumulation across long benchmark trials.
- **Immediate User-Space Flush**: Each record write triggers `file.flush()`, transferring data from Python runtime buffers to the operating system kernel page cache immediately. In partial runs, aborted executions, or unexpected process termination, all requests completed up to the point of interruption are preserved and readable on disk.
- **Crash Safety Limits (`flush` vs `fsync`)**: The client intentionally relies on OS page cache flushing (`flush()`) rather than hardware storage flushes (`os.fsync()` / `FlushFileBuffers()`). Calling synchronous hardware flushes on every completed request would inject 1–15ms of storage I/O latency, bottlenecking worker threads and severely distorting network benchmark latency percentiles. Consequently, while protected against Python process crashes and SIGINT aborts, unflushed kernel page cache pages could still be lost in the event of an abrupt host power failure or kernel panic.

### 3. Run Steady-State Benchmark Runner
Start your desired cluster (e.g., 3-node profile) and execute the write benchmark:
```powershell
# 1. Start cluster
docker compose -f docker/docker-compose.3node.yml up -d

# 2. Run benchmark (100 requests, 5 concurrent workers)
python -m experiments.runners.run_benchmark --nodes 3 --requests 100 --concurrency 5 --output experiments/results/raw/exp01_3node.json
```

### 4. Run a Fault-Injection Experiment
Execute controlled leader failure and failover benchmarking:
```powershell
python -m experiments.runners.run_fault_experiment --scenario coord_crash --nodes 3 --output experiments/results/raw/fault_coord_crash_3node.json
```

Other available scenarios:
- `follower_crash`: Evaluates write availability under `ALL` vs `MAJORITY` replication policy.
- `follower_rejoin`: Measures `AutoFollowerSync` catch-up duration and log reconciliation.

### 5. Aggregate Results & Export Summary CSV
```powershell
python -m experiments.analysis.aggregate_metrics --raw-dir experiments/results/raw --output-csv experiments/results/summary/benchmark_summary.csv
```

### 6. Generate SVG Comparison Charts
```powershell
python -m experiments.analysis.generate_charts --output-dir experiments/results/summary
```

---

## 🛠️ Cluster Manager & Fault Injector (Phase 7.2B)

### 1. Cluster Manager (`experiments.core.cluster_manager.ClusterManager`)
Manages reproducible Docker Compose cluster lifecycles across single-, 3-, 5-, and 7-node profiles:
- **Supported Profiles:**
  - `N=1`: `docker/docker-compose.single.yml` (Node 1 on port 5000, gRPC 50051).
  - `N=3`: `docker/docker-compose.3node.yml` (Ports 5001–5003, MySQL 33061–33063).
  - `N=5`: `docker/docker-compose.5node.yml` (Ports 5001–5005, MySQL 33061–33065).
  - `N=7`: `docker/docker-compose.7node.yml` (Ports 5001–5007, MySQL 33061–33067).
- **Two-Stage Readiness Gate:**
  1. *Container Health:* Polls `/api/health` across all profile ports until HTTP 200 is confirmed or bounded timeout expires.
  2. *Application Readiness:* Polls `/api/node` until leader election converges on an active coordinator accepting votes (`is_coordinator=True`, `accepting_votes=True`).
- **Scoped Teardown:**
  `stop_cluster(purge_volumes=True)` executes `docker compose -f <profile_file> down -v`, strictly isolating teardown to the experiment profile without affecting unrelated Docker resources.

```python
from experiments.core.cluster_manager import ClusterManager

cm = ClusterManager(3)
if cm.check_docker_available():
    cm.start_cluster(algorithm="bully", policy="majority", clean=True)
    coord_id, coord_port = cm.ensure_cluster_settled(timeout=15.0)
    print(f"Leader settled: Node {coord_id} on port {coord_port}")
    cm.stop_cluster(purge_volumes=True)
```

### 2. Fault Injector (`experiments.core.fault_injector.FaultInjector`)
Provides safe, deterministic, and idempotent fault injection across containerized nodes conforming to the Phase 7.1 experiment matrix:
- **Fault Capabilities:**
  - `stop_node(node_id, timeout_sec)`: Immediate crash-stop failure (`docker stop -t 1 voting-node{id}`).
  - `start_node(node_id)`: Rejoin / node recovery (`docker start voting-node{id}`).
  - `pause_node(node_id)` / `unpause_node(node_id)`: Process freeze / GC delay simulation (`docker pause/unpause`).
  - `disconnect_network(node_id)` / `reconnect_network(node_id)`: Bridge network partition (`docker network disconnect/connect voting-net`).
  - `partition_nodes(node_ids)` / `heal_partition()`: Compound multi-node partition (majority vs minority split).
- **Target Validation:** Validates `node_id` against configured cluster bounds (`1 <= node_id <= node_count`). Rejects negative, zero, non-integer, or out-of-range targets before issuing commands.
- **Idempotent Cleanup & Context Management:**
  Restores all altered states in safe order: unpause paused nodes $\rightarrow$ reconnect partitioned nodes $\rightarrow$ restart stopped nodes.
  ```python
  from experiments.core.fault_injector import FaultInjector

  with FaultInjector(node_count=5) as injector:
      injector.stop_node(5)            # Crash leader or follower
      injector.partition_nodes([4, 5]) # Partition minority
      # Automatic cleanup guaranteed on exit or exception!
  ```
- **Known Limitations:**
  - Windows Docker Desktop does not support Linux kernel `tc/netem` packet loss injection. Partitions are implemented via Docker bridge network disconnections (`docker network disconnect voting-net voting-node{id}`).
  - Never executes `docker system prune` or blanket deletions.

---

## 📈 Telemetry Collector & Experiment Orchestrator (Phase 7.2C)

### 1. Telemetry Collector (`experiments.core.telemetry_collector`)
Provides continuous background sampling of actual container resource usage and health state:
- **Metrics Collected:**
  - `cpu_percent`: Docker container CPU utilization percentage.
  - `memory_bytes` & `memory_limit_bytes`: Resident memory consumption and container memory limits.
  - `memory_percent`: Ratio of container memory used against memory limit.
  - `net_rx_bytes` & `net_tx_bytes`: Cumulative container network bytes received and transmitted over Docker bridge.
  - `status`, `restart_count`, `health_status`: Container process status (`running`, `paused`, `exited`), restart counter, and container healthcheck state.
- **Explicit Measurement Boundaries:**
  Only genuine Docker runtime metrics are measured. Unavailable internal metrics (`grpc_internal_queue_depth`, `lock_wait_nanoseconds`) are explicitly marked as unavailable in every sample record and aggregate summary rather than fabricating estimates.
- **Fault-Tolerant Fallback:**
  When a container is paused or stopped (which causes `docker stats` to return `--` or omit the container), the sampler automatically executes `docker inspect` with bounded timeouts to parse status, restart counts, and health status without crashing or blocking sampling loops.

### 2. Experiment Runner (`experiments.core.experiment_runner.ExperimentRunner`)
Composes the entire experimental toolchain into a robust, repeatable 10-step lifecycle:
1. **Config Validation**: Validates `ExperimentConfig` parameters (cluster profile, algorithm, policy, fault scenario, request count, concurrency, timeouts).
2. **Run-ID & Collision-Safe Paths**: Generates unique run identifiers (e.g. `exp01_3n_bully_majority_t1_YYYYMMDD_HHMMSS_<rand>`) and collision-safe artifact paths.
3. **Cluster Startup**: Starts the requested cluster topology via `ClusterManager`.
4. **Convergence Verification**: Confirms all nodes are healthy and exactly one coordinator is elected and accepted by all reachable peers (`ensure_cluster_settled()`).
5. **Continuous Telemetry Sampling**: Starts `ContainerTelemetrySampler` background thread streaming NDJSON observations to disk.
6. **Workload Execution**: Submits concurrent benchmark requests via `WorkloadClient`.
7. **Fault Injection Scenarios**: Injects and heals controlled fault scenarios (`coord_crash`, `follower_crash`, `pause_node`, `network_partition`, `follower_rejoin`).
8. **Invariant Verification**: Asserts single-leader invariance, tally consistency, database log convergence, and ghost-vote absence.
9. **Guaranteed Teardown**: In a `finally` block, stops telemetry sampling, reverts all injected faults, and tears down cluster containers with volume purging.
10. **Summary & Manifest Generation**: Generates `summary.json` and a cryptographically verified `manifest.json` containing SHA-256 hashes and line counts for every artifact.

#### Partial Failure Artifact Preservation
If an experiment fails due to an invariant violation, network drop, or unhandled exception, all partially completed requests and telemetry samples are preserved on disk. `summary.json` and `manifest.json` are written with `status="FAILED"` and detailed error diagnostics.

```python
from experiments.core.experiment_runner import ExperimentConfig, ExperimentRunner

config = ExperimentConfig(
    exp_id="EXP-01",
    node_count=3,
    algorithm="bully",
    replication_policy="majority",
    fault_scenario="none",
    request_count=100,
    concurrency=5,
    manage_cluster=True,
    output_dir="experiments/results/raw",
)

runner = ExperimentRunner(config)
result = runner.run()
print(f"Status: {result.status}, Manifest: {result.manifest_path}")
```

---

## 📊 Formal Invariants Asserted
Every benchmark trial automatically executes the following assertions:
1. **Single Leader Invariance**: Exactly one node claims `is_coordinator=True` for any given term.
2. **Zero Lost Writes**: All ballots confirmed to clients with HTTP 201 must exist in the database.
3. **Zero Duplicate Votes**: No client ID may be committed more than once.
4. **Tally Integrity**: The sum of candidate votes in `GET /api/votes/tally` equals the database `COMMITTED` count.
5. **Ghost-Vote Absence**: Unacknowledged pending votes are never counted in the published tally.


