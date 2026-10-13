# Final Academic Submission Package
**Project Title:** Distributed Fault-Tolerant Voting System with Pluggable Leader Election  
**Institution:** Pimpri Chinchwad College of Engineering (PCCoE), Pune  
**Department:** Department of Computer Engineering  
**Academic Year:** 2025–2026  
**Group Members:**
- Adwait Kamble (`123B1D002`)
- Advait Nathe (`123B1D029`)
- Nikhil Puppalwar (`123B1D040`)
**Project Guide:** Mr. Ganesh Deshmukh

---

## Folder Contents & Deliverables

This self-contained directory contains all materials required for final-year engineering evaluation, viva examination, and research presentation:

| File / Folder | Format | Description |
|---|:---:|---|
| **`Final_Project_Report.docx`** | Word (.docx) | **Primary academic report** formatted to university standards, complete with title page, approval certificates, structured tables, and all 5 embedded 300 DPI figures. |
| **`Project_Defense_Guide.docx`** | Word (.docx) | **Defense & viva voce preparation guide** containing 20 examiner Q&As, failover timelines, algorithmic proofs, and live demo commands. |
| **`Implementation_Details.docx`** | Word (.docx) | **Live 7-Node Demonstration Manual** (Word format) ready to present to faculty examiners. |
| **`IMPLEMENTATION_DETAILS.md`** | Markdown (.md) | **Live 7-Node Demonstration Manual** with step-by-step PowerShell commands, coordinator crash simulation, Bully failover, quorum writes, and follower sync. |
| **`FINAL_PROJECT_REPORT.md`** | Markdown (.md) | 25-section academic report source document. |
| **`PROJECT_DEFENSE_GUIDE.md`** | Markdown (.md) | Viva voce defense guide source document. |
| **`ARCHITECTURE.md`** | Markdown (.md) | In-depth engineering architectural specification and node runtime internals. |
| **`RESEARCH_PAPER_REVISION_PLAN.md`** | Markdown (.md) | Concrete revision roadmap for IEEE/ACM publication submission. |
| **`SUBMISSION_INVENTORY.md`** | Markdown (.md) | Deliverable audit and artifact reconciliation log. |
| **`benchmark_summary.csv`** | CSV Dataset | Complete empirical dataset from the 99-trial factorial benchmark campaign (EXP-01 through EXP-09). |
| **`diagrams/`** | PNG Directory | High-resolution publication-quality (300 DPI) diagrams: |
| ├── `fig1_system_architecture.png` | PNG | System Architecture: React SPA, Flask REST Bridges, NodeRuntime, gRPC, and Isolated MySQL containers. |
| ├── `fig2_vote_replication_workflow.png` | PNG | Vote Submission & Two-Phase Replication Workflow sequence diagram. |
| ├── `fig3_leader_election_failover.png` | PNG | Leader Failure Detection & Bully/Ring Election sequence diagram. |
| ├── `fig4_follower_recovery_sync.png` | PNG | Follower State Recovery & AutoFollowerSync catch-up sequence diagram. |
| └── `fig5_experimental_evaluation_harness.png` | PNG | Automated Benchmark Harness and Telemetry Pipeline architecture. |

---

## Quick Execution Reference

```powershell
# 1. Start 3-Node Cluster for Live Evaluation Demo
docker compose -f docker/docker-compose.3node.yml up -d --build

# 2. Access Web UI Dashboard
# Open browser to: http://localhost:3000

# 3. Safe Teardown
docker compose -f docker/docker-compose.3node.yml down -v
```
