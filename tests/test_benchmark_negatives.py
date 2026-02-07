from __future__ import annotations

import json
from pathlib import Path

from uptowes.benchmark_negatives import audit_negative_queries


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    payload = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    path.write_text(payload, encoding="utf-8")


def test_negative_invalid_detected_when_token_exists_in_corpus(local_tmp_path: Path) -> None:
    corpus_path = local_tmp_path / "chunks.jsonl"
    _write_jsonl(
        corpus_path,
        [
            {
                "chunk_id": "c1",
                "source": {"path": "cirurgia/oncocirurgia_melanoma_clean.md"},
                "text_canonical": "Classificação de breslow para melanoma e margem cirúrgica",
            },
            {
                "chunk_id": "c2",
                "source": {"path": "cirurgia/abdomeagudo_apendiciteaguda_clean.md"},
                "text_canonical": "Escala de alvarado na apendicite",
            },
        ],
    )

    violations = audit_negative_queries(
        cases=[
            {
                "id": "NEG1",
                "bucket": "B",
                "query": "melanoma breslow margem ampliacao",
                "expect_hit": False,
            }
        ],
        corpus_jsonl=corpus_path,
        short_allowlist=set(),
    )

    assert violations
    assert violations[0].token in {"melanoma", "breslow"}
    assert violations[0].chunk_id == "c1"


def test_negative_valid_passes_when_tokens_absent(local_tmp_path: Path) -> None:
    corpus_path = local_tmp_path / "chunks.jsonl"
    _write_jsonl(
        corpus_path,
        [
            {
                "chunk_id": "c1",
                "source": {"path": "cirurgia/abdomeagudo_colangite_clean.md"},
                "text_canonical": "Critérios de tokyo para colangite",
            }
        ],
    )

    violations = audit_negative_queries(
        cases=[
            {
                "id": "NEG2",
                "bucket": "B",
                "query": "cetoacidose diabetica mucormicose anfotericina",
                "expect_hit": False,
            }
        ],
        corpus_jsonl=corpus_path,
        short_allowlist=set(),
    )

    assert violations == []


def test_negative_audit_respects_source_prefix_scope(local_tmp_path: Path) -> None:
    corpus_path = local_tmp_path / "chunks.jsonl"
    _write_jsonl(
        corpus_path,
        [
            {
                "chunk_id": "c1",
                "source": {"path": "clinica/oncologia_melanoma_clean.md"},
                "text_canonical": "melanoma e breslow em contexto clinico",
            }
        ],
    )

    violations = audit_negative_queries(
        cases=[
            {
                "id": "NEG3",
                "bucket": "B",
                "query": "melanoma breslow margem ampliacao",
                "expect_hit": False,
            }
        ],
        corpus_jsonl=corpus_path,
        short_allowlist=set(),
        source_prefixes=["cirurgia/"],
    )

    assert violations == []
