from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path


GOLDEN_FIXTURE_FILENAMES = [
    "deep_headings.md",
    "table_with_br.md",
    "table_critical_t2t3.md",
]


def load_subset(jsonl_path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        ch = json.loads(line)
        rows.append(
            {
                "chunk_id": ch["chunk_id"],
                "text_canonical": ch["text_canonical"],
                "hash": ch["hash"],
            }
        )
    return sorted(rows, key=lambda r: r["chunk_id"])


def test_golden_fixtures(local_tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]

    # Copia APENAS as 3 fixtures golden para um input temporário,
    # para não ser afetado por outros .md dentro de fixtures/ (ex.: fixture_colangite_raw.md)
    input_dir = local_tmp_path / "golden_input"
    input_dir.mkdir(parents=True, exist_ok=True)

    fixtures_dir = repo_root / "fixtures"
    for name in GOLDEN_FIXTURE_FILENAMES:
        src = fixtures_dir / name
        assert src.exists(), f"Missing fixture: {src}"
        shutil.copyfile(src, input_dir / name)

    out_jsonl = local_tmp_path / "chunks.jsonl"
    report_json = local_tmp_path / "build_report.json"

    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "build_dataset.py"),
        "--input",
        str(input_dir),
        "--schema",
        str(repo_root / "schemas" / "dataset_chunk.schema.json"),
        "--out",
        str(out_jsonl),
        "--report",
        str(report_json),
    ]

    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    assert proc.returncode == 0, (
        "build_dataset.py failed\n"
        f"STDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )

    actual = load_subset(out_jsonl)

    expected_path = repo_root / "fixtures" / "expected" / "golden_expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8"))

    assert actual == expected
