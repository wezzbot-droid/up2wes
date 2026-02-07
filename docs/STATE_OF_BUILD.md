# STATE_OF_BUILD — UpToWes

**Data-base:** 2026-02-07  
**Escopo:** Desktop-only (MVP)  
**Uso explícito:** estudo + triagem/QA do ResiBrain (**NÃO** plantão / decisão clínica)

---

## 0) TL;DR (fixo)

- [x] MVP com Search/Study + Ingest Update operacional localmente
- [ ] QA Triage humano completo (`scripts/qa_report.py` ainda não existe)
- [x] Gate explícito `NO_GO_TABLE_CRITICAL` implementado no validador
- [x] Regra evidence-first mantida (`chunk_id` + `path` + `locator`)
- [x] Artifacts de dataset não versionados (`.gitignore`)

---

## 1) Snapshot do repo (o que existe hoje)

### 1.1 Contratos e docs

- [x] `UP2WES_SPEC.md`
- [x] `schemas/dataset_chunk.schema.json` (`schema_version=0.1`)
- [ ] `README.md` com quickstart (arquivo existe, mas está vazio)
- [x] `docs/STATE_OF_BUILD.md`
- [ ] `dataset/README.md`

### 1.2 Pipeline (core)

- [x] `src/uptowes/normalize.py`
- [x] `src/uptowes/chunk.py`
- [x] `src/uptowes/validate.py`
- [x] `src/uptowes/ingest.py`
- [x] `scripts/build_dataset.py` como caminho de build principal

### 1.3 Retrieval

- [x] `src/uptowes/lexicon_runtime.py`
- [x] `src/uptowes/retrieval.py`
- [x] `src/uptowes/lexicon/ptbr_surgery_v1.py`
- [x] `scripts/query_lex.py` (sanity sem DB)
- [x] `scripts/run_queries_custom.py` (benchmark oficial; requer Postgres)

### 1.4 Testes e fixtures

- [x] `tests/test_golden_fixtures.py`
- [x] `tests/test_lexicon_contract.py`
- [x] `tests/test_validate_no_go_table_critical.py`
- [x] Fixtures críticas:
  - `fixtures/deep_headings.md`
  - `fixtures/table_with_br.md`
  - `fixtures/table_critical_t2t3.md`
  - `fixtures/expected/golden_expected.json`

---

## 2) Princípios de segurança (não negociáveis)

### UpToWes NÃO deve

- Decidir conduta clínica
- Reescrever guideline sem evidência rastreável
- Resolver conflito de guideline como verdade final

### UpToWes DEVE

- **Evidence-first:** saída com `chunk_id`, `source.path`, `source.locator`
- **Auditável:** trecho recuperado precisa voltar ao arquivo original
- **Determinístico:** IDs, canonicalização e gates críticos estáveis

---

## 3) Contratos de dados (v0.1)

### 3.1 Identidade e determinismo

- [x] `chunk_id` no padrão `DOC_ID#Lstart-Lend#ordinal`
- [x] `text_canonical` e hashes determinísticos
- [x] schema JSON validando campos obrigatórios e enum fechado

### 3.2 Tabelas (critério de risco)

- [x] `table_row` implementado no build
- [x] fixture crítica T2/T3 presente
- [x] gate `NO_GO_TABLE_CRITICAL` ativo em `validate.py`
- [x] teste dedicado cobrindo PASS/FAIL do gate

---

## 4) Evidências executadas nesta atualização

### 4.1 Ambiente e testes

- `pytest -q` → **PASS** (`6 passed`)
- `.\.venv\Scripts\python.exe -m pytest -q` → **PASS** (`6 passed`)
- Correção de devex aplicada em `pytest.ini` + fixture repo-local (`tests/conftest.py`)

### 4.2 Build/validate

- `.\.venv\Scripts\python.exe scripts\build_dataset.py --input md_norm --schema schemas\dataset_chunk.schema.json --out dataset\chunks.jsonl --report dataset\build_report.json` → **OK**
  - docs=513
  - chunks=57.220
  - report sem erro fatal
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe src\uptowes\validate.py --jsonl dataset\chunks.jsonl --schema schemas\dataset_chunk.schema.json` → **OK**

### 4.3 Gate crítico T2/T3 (prova)

- Dataset T2/T3 degradado (valor crítico vazio + `table_empty_cell`) validado com:
  - `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe src\uptowes\validate.py --jsonl dataset\out\audit_t2t3_degraded.jsonl --schema schemas\dataset_chunk.schema.json`
  - Resultado: **FAIL** com `NO_GO_TABLE_CRITICAL`

### 4.4 Golden

- Build de fixtures golden + comparação com expected:
  - `golden_match=True`
  - `actual=6 expected=6`

### 4.5 Retrieval

- `.\.venv\Scripts\python.exe scripts\query_lex.py "apendicite alvarado escala" --dataset dataset\chunks.jsonl --lexicon src\uptowes\lexicon\ptbr_surgery_v1.py --top 5` → **OK** (`retrieval_mode=STRICT_GROUPS`)
- `.\.venv\Scripts\python.exe scripts\run_queries_custom.py --lex-only` → **OK** (`PASS total: mismatches=0/15`)

---

## 5) Mudanças recentes confirmadas

- [x] `STRICT_GROUPS` com 2-pass + rerank determinístico (`src/uptowes/retrieval.py`)
- [x] observabilidade de query (`lex_tsquery_groups_str`, `lex_rest_text`)
- [x] `min_cov_ratio = 2/3` em `scripts/run_queries_custom.py`
- [x] `build_dataset.py` garante `dataset/` e `dataset/out/`
- [x] `NO_GO_TABLE_CRITICAL` em `src/uptowes/validate.py`
- [x] output robusto do validator com `_safe_print` (evita crash de encoding no Windows)

---

## 6) Lacunas reais do MVP (hoje)

1. [ ] **QA triage humano (P1)**: falta `scripts/qa_report.py` (flags + ponteiros em markdown)
2. [ ] **Benchmark oficial reproduzível local**: requer Postgres ativo (`localhost:5432`) + migrações
3. [ ] **README operacional**: quickstart ainda ausente

---

## 7) Runbook (Windows/PowerShell)

### 7.1 Testes

```powershell
pytest -q
```

### 7.2 Build completo

```powershell
.\.venv\Scripts\python.exe scripts\build_dataset.py --input md_norm --schema schemas\dataset_chunk.schema.json --out dataset\chunks.jsonl --report dataset\build_report.json
```

### 7.3 Validação (schema + gate crítico)

```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe src\uptowes\validate.py --jsonl dataset\chunks.jsonl --schema schemas\dataset_chunk.schema.json
```

### 7.4 Sanity lexical sem DB

```powershell
.\.venv\Scripts\python.exe scripts\query_lex.py "apendicite alvarado escala" --dataset dataset\chunks.jsonl --lexicon src\uptowes\lexicon\ptbr_surgery_v1.py --top 5
```

### 7.5 Benchmark oficial (quando DB estiver no ar)

```powershell
$env:UPTOWES_LEXICON="src\uptowes\lexicon\ptbr_surgery_v1.py"
.\.venv\Scripts\python.exe scripts\run_queries_custom.py --lex-only
```

---

## 8) Sprint status (checkbox)

### Sprint 0 — Blindagem (P0)

- [x] Fixtures críticas mínimas
- [x] Golden test com expected fixo
- [x] `NO_GO_TABLE_CRITICAL` em `validate.py`
- [x] Teste dedicado do gate crítico
- [x] `build_dataset.py` criando `dataset/` e `dataset/out/`

### Sprint 1 — QA Triage (P1)

- [ ] `scripts/qa_report.py`
- [ ] relatório `dataset/out/reports/qa.md`
- [ ] consolidação de flags determinísticas de triagem

---

## 9) Veredito atual

**GO PARCIAL.**  
Core de build/validação/retrieval lexical está estável e testado localmente.  
MVP completo ainda depende de fechar QA triage e benchmark oficial com DB disponível.
