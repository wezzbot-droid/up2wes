from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def test_qa_report_smoke(local_tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    dataset_path = local_tmp_path / "mini_chunks.jsonl"
    qa_out = local_tmp_path / "qa.md"

    rows = [
        {
            "chunk_id": "DOC_A#L1-L1#1",
            "doc_id": "DOC_A",
            "source": {"path": "a.md", "locator": "L1-L1"},
            "text_canonical": "Trecho com tabela degradada em T2",
            "quality_flags": ["table_empty_cell", "table_critical_degraded"],
        },
        {
            "chunk_id": "DOC_B#L2-L2#1",
            "doc_id": "DOC_B",
            "source": {"path": "b.md", "locator": "L2-L2"},
            "text_canonical": "Mermaid não parseado",
            "quality_flags": ["mermaid_unparsed"],
        },
        {
            "chunk_id": "DOC_C#L3-L3#1",
            "doc_id": "DOC_C",
            "source": {"path": "c.md", "locator": "L3-L3"},
            "text_canonical": "Sem flags",
            "quality_flags": [],
        },
    ]
    dataset_path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "qa_report.py"),
        "--dataset",
        str(dataset_path),
        "--out",
        str(qa_out),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    assert proc.returncode == 0, (
        "qa_report.py failed\n"
        f"STDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )
    assert qa_out.exists()

    content = qa_out.read_text(encoding="utf-8")
    assert "## A) Summary" in content
    assert "## B) Findings" in content
    assert "DOC_A#L1-L1#1" in content
    assert "TABLE_CRITICAL_DEGRADED" in content

