from __future__ import annotations

from uptowes.llm.prompting import build_answer_prompt


def test_build_answer_prompt_contains_contract_and_json_requirements() -> None:
    prompt = build_answer_prompt(
        question="apendicite alvarado",
        evidence_items=[
            {
                "chunk_id": "DOC#L1-L1#1",
                "path": "cirurgia/doc.md",
                "locator": "L1-L1",
                "text": "Escala de Alvarado",
                "source_table": "chunks_text",
                "chunk_type": "text",
            }
        ],
        constraints={"evidence_only": True, "citation_required": True, "max_evidence": 1},
    )

    assert "# PAPEL E CONTRATO" in prompt
    assert "Use APENAS as evidências do EVIDENCE_JSON fornecido." in prompt
    assert "EVIDÊNCIA INSUFICIENTE" in prompt
    assert "JSON válido" in prompt
    assert '"answer_markdown"' in prompt
    assert '"citations"' in prompt
    assert '"supporting_quotes"' in prompt
    assert "quote literal" in prompt
    assert '"quote_source_text"' in prompt
    assert '"chunk_id"' in prompt
    assert "EVIDENCE_JSON:" in prompt
    assert "apendicite alvarado" in prompt
