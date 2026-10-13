"""Package all submission deliverables into submission_package/
and compile Project_Defense_Guide.docx.
"""

import os
import shutil
import re
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import parse_xml
from docx.oxml.ns import nsdecls

SUBMISSION_DIR = "submission_package"

def copy_deliverables():
    # 1. Copy markdown documents
    files_to_copy = [
        ("docs/FINAL_PROJECT_REPORT.md", os.path.join(SUBMISSION_DIR, "FINAL_PROJECT_REPORT.md")),
        ("docs/PROJECT_DEFENSE_GUIDE.md", os.path.join(SUBMISSION_DIR, "PROJECT_DEFENSE_GUIDE.md")),
        ("docs/ARCHITECTURE.md", os.path.join(SUBMISSION_DIR, "ARCHITECTURE.md")),
        ("docs/RESEARCH_PAPER_REVISION_PLAN.md", os.path.join(SUBMISSION_DIR, "RESEARCH_PAPER_REVISION_PLAN.md")),
        ("docs/SUBMISSION_INVENTORY.md", os.path.join(SUBMISSION_DIR, "SUBMISSION_INVENTORY.md")),
        ("data/experiments/matrix/summary/benchmark_summary.csv", os.path.join(SUBMISSION_DIR, "benchmark_summary.csv")),
    ]
    for src, dst in files_to_copy:
        if os.path.exists(src):
            shutil.copy2(src, dst)
            print(f"Copied {src} -> {dst}")
        else:
            print(f"Warning: source not found {src}")

def build_defense_guide_docx():
    src_md = "docs/PROJECT_DEFENSE_GUIDE.md"
    dst_docx = os.path.join(SUBMISSION_DIR, "Project_Defense_Guide.docx")
    if not os.path.exists(src_md):
        return

    doc = docx.Document()
    for s in doc.sections:
        s.top_margin = Inches(1.0)
        s.bottom_margin = Inches(1.0)
        s.left_margin = Inches(1.0)
        s.right_margin = Inches(1.0)

    # Title
    p_title = doc.add_paragraph()
    p_title.paragraph_format.space_before = Pt(12)
    p_title.paragraph_format.space_after = Pt(4)
    r = p_title.add_run("Project Defense & Viva Voce Preparation Guide")
    r.font.name = "Calibri"
    r.font.size = Pt(20)
    r.font.bold = True
    r.font.color.rgb = RGBColor(30, 58, 138)

    p_sub = doc.add_paragraph()
    p_sub.paragraph_format.space_before = Pt(2)
    p_sub.paragraph_format.space_after = Pt(18)
    r_sub = p_sub.add_run("Distributed Fault-Tolerant Voting System with Pluggable Leader Election\nPCCoE / SPPU — Academic Year 2025–2026")
    r_sub.font.name = "Calibri"
    r_sub.font.size = Pt(11)
    r_sub.font.italic = True
    r_sub.font.color.rgb = RGBColor(71, 85, 105)

    with open(src_md, "r", encoding="utf-8") as f:
        lines = f.readlines()

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            continue
        if stripped.startswith("## "):
            h = doc.add_heading(level=1)
            h.paragraph_format.space_before = Pt(14)
            h.paragraph_format.space_after = Pt(4)
            r = h.add_run(stripped[3:].strip())
            r.font.name = "Calibri"
            r.font.size = Pt(14)
            r.font.bold = True
            r.font.color.rgb = RGBColor(30, 58, 138)
        elif stripped.startswith("### "):
            h = doc.add_heading(level=2)
            h.paragraph_format.space_before = Pt(10)
            h.paragraph_format.space_after = Pt(3)
            r = h.add_run(stripped[4:].strip())
            r.font.name = "Calibri"
            r.font.size = Pt(11.5)
            r.font.bold = True
            r.font.color.rgb = RGBColor(15, 23, 42)
        elif stripped.startswith("#### "):
            h = doc.add_heading(level=3)
            h.paragraph_format.space_before = Pt(8)
            h.paragraph_format.space_after = Pt(2)
            r = h.add_run(stripped[5:].strip())
            r.font.name = "Calibri"
            r.font.size = Pt(10.5)
            r.font.bold = True
            r.font.color.rgb = RGBColor(71, 85, 105)
        elif stripped.startswith("* ") or stripped.startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.15
            tokens = re.split(r"(\*\*.*?\*\*)", stripped[2:].strip())
            for t in tokens:
                if t.startswith("**") and t.endswith("**"):
                    r = p.add_run(t[2:-2])
                    r.bold = True
                else:
                    r = p.add_run(t)
                r.font.name = "Calibri"
                r.font.size = Pt(10)
        elif re.match(r"^\d+\.\s+", stripped):
            num_match = re.match(r"^(\d+)\.\s+(.*)", stripped)
            p = doc.add_paragraph(style="List Number")
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.line_spacing = 1.15
            tokens = re.split(r"(\*\*.*?\*\*)", num_match.group(2).strip())
            for t in tokens:
                if t.startswith("**") and t.endswith("**"):
                    r = p.add_run(t[2:-2])
                    r.bold = True
                else:
                    r = p.add_run(t)
                r.font.name = "Calibri"
                r.font.size = Pt(10)
        elif stripped.startswith("> "):
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(4)
            r = p.add_run(stripped[2:].strip())
            r.font.name = "Calibri"
            r.font.size = Pt(9.5)
            r.font.italic = True
            r.font.color.rgb = RGBColor(71, 85, 105)
        else:
            p = doc.add_paragraph()
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(4)
            p.paragraph_format.line_spacing = 1.15
            tokens = re.split(r"(\*\*.*?\*\*)", stripped)
            for t in tokens:
                if t.startswith("**") and t.endswith("**"):
                    r = p.add_run(t[2:-2])
                    r.bold = True
                else:
                    r = p.add_run(t)
                r.font.name = "Calibri"
                r.font.size = Pt(10)

    doc.save(dst_docx)
    print(f"Generated {dst_docx}")

def create_readme():
    readme_path = os.path.join(SUBMISSION_DIR, "README.md")
    content = """# Final Academic Submission Package
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
"""
    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Generated {readme_path}")

if __name__ == "__main__":
    copy_deliverables()
    build_defense_guide_docx()
    create_readme()
    print("Submission package assembly complete!")
