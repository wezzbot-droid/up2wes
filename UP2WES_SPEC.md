# UP2WES_SPEC.md — Contrato v0.1

> **Status**: CONGELADO  
> **Versão**: 0.1  
> **Data**: 2026-02-04  
> **Regra-mãe**: contratos > prompts > código

---

## 1. Objetivo e Limites

**UpToWes** é uma linha de montagem de 5 camadas para transformar 513 arquivos médicos em um dataset estruturado, estável e auditável.

**NÃO É**:
- CDS clínico definitivo
- Oráculo que "sabe medicina"
- Sistema que requer LLM para funcionar

**É**:
- Pipeline determinístico: mesma entrada → mesma saída
- Evidence-first: toda resposta cita trechos
- Dataset-centric: a fonte da verdade é `dataset.jsonl`

---

## 2. Arquitetura de 5 Camadas

| Camada | Objetivo | Saída |
|--------|----------|-------|
| **1. Dataset** | Transformar raw.md em chunks estruturados | `dataset.jsonl` |
| **2. Indexação** | Permitir busca rápida | SQLite + embeddings local |
| **3. Retrieval** | Achar o trecho certo | top_k chunks + section_path |
| **4. Answering** | Responder com evidência | JSON: answer + citations[] |
| **5. Interface** | Exibir resultados | CLI (MVP), UI depois |

**Regra**: Cada camada só lê a saída da anterior. Nenhuma camada pula etapas.

---

## 3. Contrato do Dataset (`dataset.jsonl`)

### 3.1 Campos Obrigatórios (Core Imutável)

```json
{
  "schema_version": "0.1",
  "chunk_id": "DOC0001#L0123-L0158#001",
  "doc_id": "DOC0001",
  "source": {
    "path": "cirurgia/abdome_agudo/colangite.md",
    "locator": "L123-L158"
  },
  "section_path": ["CIRURGIA", "ABDOME AGUDO", "COLANGITE", "Diagnóstico"],
  "title": "Diagnóstico",
  "chunk_type": "text",
  "subtype": null,
  "tags": ["high_yield"],
  "text_raw": "texto original do trecho...",
  "text_canonical": "COLANGITE — Diagnóstico: ... (trecho autossuficiente)",
  "bold_spans": [
    { "start": 14, "end": 27, "text": "Tokyo Guidelines" }
  ],
  "table": null,
  "algorithm": null,
  "quality_flags": [],
  "priority": "normal",
  "hash": {
    "raw_sha1": "a1b2c3...",
    "canonical_sha1": "d4e5f6..."
  }
}
```

### 3.2 Chunk Types (Enum Fechado v0.1)

| Type | Uso |
|------|-----|
| `text` | Parágrafo genérico |
| `definition` | Definição de termo/conceito |
| `criteria` | Critérios diagnósticos (Tokyo, BISAP, etc.) |
| `classification` | Classificação/estadiamento |
| `dose` | Dosagem de medicamento |
| `contraindication` | Contraindicação |
| `procedure` | Procedimento/técnica |
| `algorithm_step` | Passo de fluxograma (Se-Então) |
| `table_row` | Linha de tabela desnormalizada |

**Regra**: Se não tiver certeza, usa `text` + `subtype`/`tags`. Não inventa tipo novo.

### 3.3 Subtypes (String Livre)

Exemplos: `"epidemiology"`, `"diagnosis"`, `"treatment"`, `"complication"`, `"staging"`, `"prognosis"`

### 3.4 Tags (Lista de Strings)

Exemplos: `["tokyo", "tnm", "high_yield", "peds", "emergency"]`

---

## 4. Extensões Estruturadas

### 4.1 Tabela (`chunk_type: "table_row"`)

```json
"table": {
  "table_id": "TNM_8_RIM",
  "row_key": "T1a",
  "cells": [
    { "col": "Definição", "value_raw": "<4 cm, limitado ao rim" }
  ],
  "row_text_canonical": "Câncer renal (TNM 8ª) — T1a: tumor <4 cm, limitado ao rim."
}
```

### 4.2 Algoritmo (`chunk_type: "algorithm_step"`)

```json
"algorithm": {
  "algo_id": "COLANGITE_TOKYO",
  "step": 3,
  "if": "Suspeita de colangite grave (Tokyo III)",
  "then": "Drenagem biliar urgente (CPRE ou alternativa) + antibiótico",
  "else": "Tratar e estratificar gravidade"
}
```

---

## 5. Regras Duras (Não Negociáveis)

### 5.1 Autossuficiência

- Todo chunk deve ser autossuficiente
- ❌ Proibido: "como acima", "na tabela abaixo", "conforme mencionado"
- ✅ Correto: `text_canonical` inclui contexto necessário

### 5.2 Determinismo

- `chunk_id` é determinístico: `{doc_id}#L{start}-L{end}#{ordinal}`
- `hash.raw_sha1` = SHA1 do `text_raw`
- `hash.canonical_sha1` = SHA1 do `text_canonical`
- Mesma entrada → mesma saída (sempre)

### 5.3 Rastreabilidade

- `source.path` aponta para arquivo original
- `source.locator` indica linhas exatas (L123-L158)
- Auditoria deve ser possível: chunk → arquivo original

### 5.4 Tabelas

- Tabelas viram chunks `table_row` (uma linha = um chunk)
- `row_text_canonical` é frase completa, não dados crus
- Exemplo: `"Câncer renal (TNM 8ª) — T1a: tumor <4 cm, limitado ao rim."`

### 5.5 Algoritmos/Mermaid

- Mermaid vira chunks `algorithm_step`
- Formato Se-Então-Senão explícito
- Numeração sequencial por algoritmo

### 5.6 Higiene

- Corrigir entidades HTML (`&lt;` → `<`)
- Corrigir OCR (`ﬁ` → `fi`, `ﬂ` → `fl`)
- Remover headers/footers de página
- Normalizar bullets (`•`, `–`, `*` → `-`)

---

## 6. Normalização v0.1 (Determinística, Sem LLM)

Pipeline obrigatório antes do chunking:

1. **Entidades HTML**: `&lt;` → `<`, `&gt;` → `>`, `&amp;` → `&`
2. **Ligaduras OCR**: `ﬁ` → `fi`, `ﬂ` → `fl`
3. **Headers/Footers**: Remover linhas de email, numeração de página
4. **Bullets**: `•`, `–`, `*` → `-`
5. **Whitespace**: Colapsar `\n\n\n+` → `\n\n`
6. **Mermaid**: Preservar ou converter para Se-Então (determinístico)

**LLM não entra aqui.** Normalização é 100% regex.

---

## 7. Validação (Invariantes do Validator)

O validator (`validate.py`) DEVE verificar:

| Campo | Regra |
|-------|-------|
| `schema_version` | Exatamente `"0.1"` |
| `chunk_id` | Formato `DOC{n}#L{start}-L{end}#{ordinal}` |
| `chunk_type` | Um do enum fechado |
| `text_raw` | Não vazio |
| `text_canonical` | Não vazio, autossuficiente |
| `source.path` | Arquivo existe |
| `source.locator` | Formato válido |
| `hash.canonical_sha1` | Recalculado deve bater |
| `bold_spans[].start/end` | Válidos dentro do texto |

### Exit Codes

- `0`: PASS
- `1`: FAIL (com lista de erros)

---

## 8. Corte Vertical v0.1 (Definition of Done)

```
normalize(raw.md)     →  normalized.md       # Regex/determinístico
chunk(normalized.md)  →  dataset.jsonl       # Um chunk por linha
validate(dataset.jsonl) →  PASS/FAIL         # Invariantes
query(q)              →  top_k + citations   # BM25 primeiro
```

**Se isso roda em 5 fixtures, o projeto funciona.** O resto é otimização.

---

## 9. Fixtures Obrigatórias (5 Casos Feios)

| # | Fixture | Características |
|---|---------|-----------------|
| 1 | `tnm_staging.md` | Tabela TNM/FIGO complexa |
| 2 | `mermaid_algorithm.md` | Fluxograma Mermaid |
| 3 | `ocr_dirty.md` | Entidades HTML, símbolos quebrados |
| 4 | `dose_list.md` | Lista de doses/posologias |
| 5 | `deep_headers.md` | Subtítulos profundos (5+ níveis) |

Cada fixture tem:
- `fixtures/raw/{name}.md`
- `fixtures/expected/{name}.jsonl`

**Regra**: Refactor que quebra expected JSONL é proibido sem bump de versão.

---

## 10. Regra do Projeto (Lei)

| ✅ Pode | ❌ Não Pode |
|---------|-------------|
| Refatorar código | Quebrar contrato |
| Adicionar testes | Mudar dataset sem versão |
| Melhorar performance | Mexer em UI agora |
| Expandir fixtures | Inventar taxonomia grande |

---

## 11. Segurança Clínica

Se a pergunta envolver:
- Dose
- Contraindicação
- Conduta crítica

A resposta **TEM QUE** citar trechos originais.

```json
{
  "final_answer": "...",
  "citations": [
    { "chunk_id": "DOC0001#L45-L52#003", "source_excerpt": "..." }
  ],
  "uncertainties": ["..."],
  "safety_note": "Verificar protocolo institucional"
}
```

**Sem citação = resposta inválida.**

---

## 12. Changelog

| Versão | Data | Mudança |
|--------|------|---------|
| 0.1 | 2026-02-04 | Versão inicial congelada |

---

## 13. Referências

- `schemas/dataset_chunk.schema.json` — JSON Schema validável
- `fixtures/` — Casos de teste obrigatórios
- `src/uptowes/validate.py` — Validador de contrato
