# Academic Submission Package Inventory & Release Verification Checklist

**Project:** Distributed Fault-Tolerant Voting System with Pluggable Leader Election  
**Phase:** 8.4 — Final Academic Report, Research Documentation and Submission Preparation  
**Target:** Final-Year B.Tech Computer Engineering Capstone Evaluation  
**Institution:** Pimpri Chinchwad College of Engineering (PCCoE), Pune — Savitribai Phule Pune University (SPPU)  
**Authors:** Adwait Kamble [123B1D002], Advait Nathe [123B1D029], Nikhil Puppalwar [123B1D040]  
**Faculty Guide:** Mr. Ganesh Deshmukh  
**Date:** October 2026  

---

## 1. Submission Package Master Inventory

This inventory enumerates all verified deliverables, research reports, diagrams, datasets, and codebase directories comprising the final evaluation submission. Large raw experiment datasets are referenced at their canonical on-disk locations without redundant duplication.

| Deliverable Item | Canonical Path | Description | Verification Status |
|---|---|---|:---:|
| **Final Academic Project Report** | [`docs/FINAL_PROJECT_REPORT.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docs/FINAL_PROJECT_REPORT.md) | Comprehensive 25-section academic report covering theoretical background, requirements, algorithms, testing, results, and limitations. | **Verified** |
| **System Architecture Specification** | [`docs/ARCHITECTURE.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docs/ARCHITECTURE.md) | Architectural reference with 5 Mermaid sequence & component diagrams. | **Verified** |
| **Research Paper Revision Plan** | [`docs/RESEARCH_PAPER_REVISION_PLAN.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docs/RESEARCH_PAPER_REVISION_PLAN.md) | Methodological gap analysis and publication roadmap reviewing `DS_Paper_Distributed_Voting_System (1).docx` and auditing references [1]–[15]. | **Verified** |
| **Project README & User Guide** | [`README.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/README.md) | Complete guide covering setup, Docker profiles, health checks, credentials (`votingpass`), database (`voting_node`), and live demo workflow. | **Verified** |
| **Engineering Decision Log** | [`PROJECT_MEMORY.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/PROJECT_MEMORY.md) | Complete chronological decision log from D1 through D34 with resolved questions. | **Verified** |
| **Consolidated Benchmark Summary CSV** | [`data/experiments/matrix/summary/benchmark_summary.csv`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/data/experiments/matrix/summary/benchmark_summary.csv) | Reconciled statistical dataset of all 33 configurations with Student's $t$ CI95 and order percentiles ($p50, p90, p95, p99$). | **Verified** |
| **Phase 7.3 Forensic Audit Report** | `phase7_3_report.md` *(in system artifacts)* | Detailed forensic audit and statistical reconciliation of the 99-trial experimental matrix. | **Verified** |
| **Phase 8.3 Preflight & Audit Manifest** | [`data/experiments/phase8_3/phase8_3_audit_manifest.json`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/data/experiments/phase8_3/phase8_3_audit_manifest.json) | Machine-readable JSON manifest recording environment, Docker daemon state, and test metrics. | **Verified** |
| **Automated Test Results (JUnit XML)** | [`data/experiments/phase8_3/test_results.xml`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/data/experiments/phase8_3/test_results.xml) | Machine-readable test execution report documenting 235 passes and 39 container skips. | **Verified** |
| **Docker Compose Profiles** | [`docker/`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docker) | Verified compose files for single-node, 3-node, 5-node, and 7-node profiles + `init.sql`. | **Verified** |
| **Core Distributed Runtime** | [`node/`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/node) | Bully/Ring election, Lamport clock, heartbeat, recovery, and storage logic (**FROZEN**). | **Preserved (Untouched)** |
| **Flask REST Bridge** | [`api/`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/api) | HTTP endpoints for status, health, ballots, and live tally (**FROZEN**). | **Preserved (Untouched)** |
| **React Web Dashboard** | [`frontend/`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/frontend) | Single-page application compiled into Flask root on each node. | **Verified** |
| **Protocol Buffers Contract** | [`proto/voting.proto`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/proto/voting.proto) | Service definitions for gRPC consensus, election, and replication. | **Verified** |
| **Project Defense & Viva Guide** | [`docs/PROJECT_DEFENSE_GUIDE.md`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/docs/PROJECT_DEFENSE_GUIDE.md) | Oral examination guide with 20 project-specific viva questions, 2-minute pitch, and demo checklist. | **Verified** |
| **Phase 8.5 Live Demo Evidence Log** | [`data/experiments/phase8_5/live_demo_log.json`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/data/experiments/phase8_5/live_demo_log.json) | Complete timestamped execution log of live 3-node cluster failover (3.15s) and recovery (2.26s). | **Verified (PASS)** |
| **Raw Phase 7 Research Manifests** | `data/experiments/matrix/manifests/` | 99 per-trial JSON manifests with SHA-256 cryptographic hashes. | **Preserved (Untouched)** |
| **Raw Request & Telemetry Traces** | `data/experiments/matrix/requests/` & `telemetry/` | 97 per-trial NDJSON latency and continuous container telemetry traces. | **Preserved (Untouched)** |

---

## 2. Packaging Exclusions (Hardened Isolation)

To ensure a clean, leak-free academic submission package, the project's [`.gitignore`](file:///d:/Studies/B.Tech%20first%20sem/Distributed%20System/Distributed%20Voting%20System/.gitignore) strictly excludes all transient, secret, or host-dependent files:
- **Virtual Environments:** `.venv/`, `venv/`, `env/`
- **Compiler & Test Caches:** `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.coverage`, `htmlcov/`
- **Local Database Files:** `*.db`, `*.db-wal`, `*.db-shm`, `*.sqlite`, `*.sqlite3`
- **Frontend Dependencies & Builds:** `node_modules/`, `frontend/node_modules/`, `frontend/dist/`
- **Credentials & Secrets:** `.env*`, `*.pem`, `*.key`, `*.cert`
- **Scratch Files & Logs:** `scratch/*.db*`, `*.log`, `*.tmp`

---

## 3. Reproduction Instructions for Evaluators

### Step 1: Fresh Environment Bootstrap
```powershell
# Clone or extract project repository
cd "Distributed Voting System"

# Initialize Python virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1

# Install exact pinned dependencies
pip install -r requirements.txt
```

### Step 2: Non-Docker Regression Suite Verification
```powershell
# Execute complete unit, integration, and Lamport state-machine suite:
pytest tests/ -q
# Expected Result: 235 passed, 39 skipped in ~64 seconds (0 failures, 0 errors).
```

### Step 3: Launch Live 3-Node Demonstration (Requires Docker Desktop Running)
```powershell
# Start 3-node cluster + 3 dedicated MySQL databases:
docker compose -f docker/docker-compose.3node.yml up -d --build

# Open Web UI:
# Node 1: http://localhost:5001
# Node 2: http://localhost:5002
# Node 3: http://localhost:5003 (Initial Coordinator)
```

### Step 4: Live Failover Demonstration
```powershell
# 1. Cast vote via Node 1 UI or CLI:
curl -X POST http://localhost:5001/api/votes -H "Content-Type: application/json" -d '{"voter_id": "voter_01", "choice": "Alice"}'

# 2. Simulate abrupt coordinator crash:
docker stop voting-node3

# 3. Observe failover election:
# Node 2 is elected coordinator within ~3.0s.

# 4. Cast second ballot via Node 2:
curl -X POST http://localhost:5002/api/votes -H "Content-Type: application/json" -d '{"voter_id": "voter_02", "choice": "Bob"}'

# 5. Recover Node 3 & verify automatic WAL synchronization:
docker start voting-node3
# Node 3 adopts Node 2, pulls voter_02 via AutoFollowerSync.
# Both Alice: 1 and Bob: 1 appear across all 3 nodes!

# 6. Clean Teardown:
docker compose -f docker/docker-compose.3node.yml down -v
```

---

## 4. Submission-Readiness Checklist

- [x] **Production Code Frozen:** No modifications to `node/` or `api/`.
- [x] **Consensus & Schemas Preserved:** Pluggable Bully/Ring, Lamport clocks, two-phase replication, and MySQL schemas untouched.
- [x] **Documentation Accurate:** `README.md` database name verified as `voting_node` matching `docker-compose.*.yml` and `init.sql`.
- [x] **25-Section Academic Report Completed:** `docs/FINAL_PROJECT_REPORT.md` written with complete institutional and technical depth.
- [x] **System Architecture Diagrams Completed:** `docs/ARCHITECTURE.md` populated with 5 verifiable Mermaid sequence & component diagrams.
- [x] **Research Paper Revision Plan Completed:** `docs/RESEARCH_PAPER_REVISION_PLAN.md` created with audit of references [1]–[15] and Phase 7 empirical integrations.
- [x] **Regression Suite Reconciled:** 274 collected tests: 235 passed, 39 container skips, 0 failures, 0 errors.
- [x] **Experiment Research Artifacts Preserved:** All 99 trial manifests, 97 request traces, 97 telemetry traces, and `benchmark_summary.csv` intact in `data/experiments/matrix/`.
- [x] **Git Isolation Preserved:** No nested `.git` initialized; parent `D:\` untouched; no unauthorized commits or pushes.
- [x] **Live Docker Cluster Verification (Phase 8.5):** Live 3-node cluster built and verified (`test_docker_cluster_3node.py` passed 5/5). Live failover (3.15s) and state catch-up (2.26s) demonstrated and logged to `data/experiments/phase8_5/live_demo_log.json` (VERDICT: PASS).
