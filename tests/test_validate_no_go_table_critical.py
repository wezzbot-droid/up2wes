from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from uptowes.validate import load_schema, validate_chunks, validate_jsonl


def _build_single_fixture(local_tmp_path: Path, fixture_name: str) -> tuple[Path, Path]:
    repo_root = Path(__file__).resolve().parents[1]
    input_dir = local_tmp_path / "input"
    input_dir.mkdir(parents=True, exist_ok=True)

    src = repo_root / "fixtures" / fixture_name
    assert src.exists(), f"Missing fixture: {src}"
    shutil.copyfile(src, input_dir / fixture_name)

    out_jsonl = local_tmp_path / "chunks.jsonl"
    out_report = local_tmp_path / "build_report.json"
    schema_path = repo_root / "schemas" / "dataset_chunk.schema.json"

    cmd = [
        sys.executable,
        str(repo_root / "scripts" / "build_dataset.py"),
        "--input",
        str(input_dir),
        "--schema",
        str(schema_path),
        "--out",
        str(out_jsonl),
        "--report",
        str(out_report),
    ]
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True)
    assert proc.returncode == 0, (
        "build_dataset.py failed\n"
        f"STDOUT:\n{proc.stdout}\n"
        f"STDERR:\n{proc.stderr}"
    )
    return out_jsonl, schema_path


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_no_go_table_critical_accepts_valid_t2_t3_fixture(local_tmp_path: Path) -> None:
    out_jsonl, schema_path = _build_single_fixture(local_tmp_path, "table_critical_t2t3.md")
    rc = validate_jsonl(out_jsonl, schema_path)
    assert rc == 0


def test_no_go_table_critical_blocks_degraded_row_even_when_schema_is_valid(local_tmp_path: Path) -> None:
    out_jsonl, schema_path = _build_single_fixture(local_tmp_path, "table_critical_t2t3.md")
    rows = _read_jsonl(out_jsonl)
    assert rows

    # Degrada estrutura crítica: coluna "Definição" fica vazia e flag explícita de perda.
    row = rows[0]
    assert row["chunk_type"] == "table_row"
    for cell in row["table"]["cells"]:
        if str(cell.get("col", "")).strip().lower().startswith("defini"):
            cell["value_raw"] = ""
    row["quality_flags"] = sorted(set([*row.get("quality_flags", []), "table_empty_cell"]))

    degraded_jsonl = local_tmp_path / "degraded_critical.jsonl"
    _write_jsonl(degraded_jsonl, rows)

    schema = load_schema(schema_path)
    assert validate_chunks(rows, schema) == []
    assert validate_jsonl(degraded_jsonl, schema_path) == 2


def test_no_go_table_critical_does_not_block_non_critical_table_rows(local_tmp_path: Path) -> None:
    out_jsonl, schema_path = _build_single_fixture(local_tmp_path, "table_with_br.md")
    rows = _read_jsonl(out_jsonl)
    assert rows

    # Tabela não crítica (sem marcador T2/T3): mesmo com table_empty_cell, não dispara NO-GO.
    row = rows[0]
    assert row["chunk_type"] == "table_row"
    for cell in row["table"]["cells"]:
        if str(cell.get("col", "")).strip().lower() == "dose":
            cell["value_raw"] = ""
    row["quality_flags"] = sorted(set([*row.get("quality_flags", []), "table_empty_cell"]))

    non_critical_jsonl = local_tmp_path / "non_critical_with_empty_cell.jsonl"
    _write_jsonl(non_critical_jsonl, rows)

    schema = load_schema(schema_path)
    assert validate_chunks(rows, schema) == []
    assert validate_jsonl(non_critical_jsonl, schema_path) == 0
