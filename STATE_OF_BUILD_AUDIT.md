# STATE_OF_BUILD_AUDIT — UpToWes

**Data:** 2026-02-07  
**Auditoria:** técnica + confiabilidade (evidência reproduzível)

## 1) Veredito

**GO PARCIAL**

- Core local está funcional e reproduzível: build, validação de schema, gate crítico T2/T3, sanity retrieval lexical e suíte `pytest`.
- Ainda não é **GO completo** por lacunas de produto (QA triage humano/`qa_report.py`) e por bloqueio de acesso ao Docker Compose no ambiente auditado.

---

## 2) Evidências executadas (comandos + output)

1. Mapeamento de arquivos-chave
- Comando:
```powershell
$targets = @('src/uptowes/normalize.py','src/uptowes/chunk.py','src/uptowes/validate.py','src/uptowes/ingest.py','src/uptowes/retrieval.py','scripts/build_dataset.py','scripts/query_lex.py','scripts/run_queries_custom.py','schemas/dataset_chunk.schema.json','tests','fixtures','docs/STATE_OF_BUILD.md','README.md'); foreach($t in $targets){"$t`t$(Test-Path $t)"}
```
- Resultado resumido: todos os targets retornaram `True`.

2. Testes (devex corrigido)
- Comando:
```powershell
pytest -q
```
- Resultado: `...... [100%]` (6 testes passando).

3. Build golden + comparação
- Comandos:
```powershell
.\.venv\Scripts\python.exe scripts\build_dataset.py --input dataset\out\audit_golden_input --schema schemas\dataset_chunk.schema.json --out dataset\out\audit_golden_chunks.jsonl --report dataset\out\audit_golden_report.json
.\.venv\Scripts\python.exe -c "<comparação com fixtures/expected/golden_expected.json>"
```
- Resultado: `golden_match=True`, `actual=6 expected=6`.

4. Build completo do corpus
- Comando:
```powershell
.\.venv\Scripts\python.exe scripts\build_dataset.py --input md_norm --schema schemas\dataset_chunk.schema.json --out dataset\chunks.jsonl --report dataset\build_report.json
```
- Resultado: `[OK] docs=513 chunks=57220`.

5. Validação com gate crítico
- Comando:
```powershell
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe src\uptowes\validate.py --jsonl dataset\chunks.jsonl --schema schemas\dataset_chunk.schema.json
```
- Resultado: `[OK] dataset.jsonl válido no schema.`

6. Prova do `NO_GO_TABLE_CRITICAL` (caso degradado)
- Comando:
```powershell
$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe src\uptowes\validate.py --jsonl dataset\out\audit_t2t3_degraded.jsonl --schema schemas\dataset_chunk.schema.json
```
- Resultado: falha com `[NO_GO_TABLE_CRITICAL] ...` e `Total NO_GO_TABLE_CRITICAL errors: 3`.

7. Sanity retrieval local
- Comando:
```powershell
.\.venv\Scripts\python.exe scripts\query_lex.py "apendicite alvarado escala" --dataset dataset\chunks.jsonl --lexicon src\uptowes\lexicon\ptbr_surgery_v1.py --top 5
```
- Resultado: `retrieval_mode=STRICT_GROUPS`, top hits com `chunk_id/path/loc`.

8. Benchmark oficial
- Comando:
```powershell
$env:UPTOWES_LEXICON='src\uptowes\lexicon\ptbr_surgery_v1.py'; .\.venv\Scripts\python.exe scripts\run_queries_custom.py --lex-only
```
- Resultado: **OK**.
  - `PASS total: mismatches=0/15`
  - relatório atualizado em `dataset/out/reports/queries_custom.md`

9. Infra de DB (Compose/Docker)
- Comando:
```powershell
docker compose ps
docker compose up -d db
docker compose logs --tail 120 db
docker compose exec db sh -lc "env | grep POSTGRES"
docker compose exec db sh -lc "psql -U $POSTGRES_USER -d $POSTGRES_DB -c 'select version();'"
```
- Resultado: falha de acesso ao pipe `dockerDesktopLinuxEngine` (`Access is denied`).

---

## 3) Drift do `docs/STATE_OF_BUILD.md` (antes da atualização)

| Claim | Status | Evidência |
| --- | --- | --- |
| “falta `NO_GO_TABLE_CRITICAL`” | **DESATUALIZADO** | `src/uptowes/validate.py:133` (`validate_no_go_table_critical`) + `src/uptowes/validate.py:157` |
| “pytest com erro de ACL” | **DESATUALIZADO** | `pytest -q` => 6 pass; `pytest.ini:3` (`-p no:tmpdir`) + `tests/conftest.py:18` (`local_tmp_path`) |
| “README vazio” | **DESATUALIZADO** | README atualizado com `UPTOWES_DB_DSN` e `UPTOWES_LEXICON` |
| “`qa_report.py` não existe” | **CONFIRMADO** | ausência em `scripts/` (não encontrado) |
| “run_queries_custom disponível mas depende DB” | **CONFIRMADO** | execução OK: `PASS total: mismatches=0/15` |

---

## 4) Matriz (Feature -> Evidência -> Risco -> Ação)

| Feature | Evidência | Risco atual | Ação |
| --- | --- | --- | --- |
| Build dataset | `scripts/build_dataset.py`; comando de build completo OK (`docs=513`, `chunks=57220`) | baixo | manter golden e validação no pipeline |
| Schema validation | `src/uptowes/validate.py`; comando validate OK no dataset atual | baixo | manter no runbook |
| Gate `NO_GO_TABLE_CRITICAL` | `src/uptowes/validate.py:133`; teste `tests/test_validate_no_go_table_critical.py` | baixo-médio (heurística por `row_key` T2/T3 + flags) | evoluir para marcador explícito de criticidade no contrato (P1) |
| Golden fixtures | `tests/test_golden_fixtures.py`; comparação `golden_match=True` | baixo | adicionar mais fixtures críticas |
| Retrieval lexical sanity | `scripts/query_lex.py` com output `STRICT_GROUPS` | médio (sanity não substitui benchmark oficial) | manter benchmark oficial como gate de release |
| Benchmark oficial custom queries | `scripts/run_queries_custom.py`; execução OK (`mismatches=0/15`) | baixo | manter benchmark no runbook |
| Devex de testes (Windows) | `pytest.ini`, `tests/conftest.py`; `pytest -q` verde | baixo | manter configuração fixa no repo |

---

## 5) P0 blockers (máx. 3)

## P0-1) Compose do DB bloqueado por permissão local no Docker pipe

- Como reproduzir:
```powershell
docker compose ps
docker compose up -d db
docker compose logs --tail 120 db
docker compose exec db sh -lc "env | grep POSTGRES"
docker compose exec db sh -lc "psql -U $POSTGRES_USER -d $POSTGRES_DB -c 'select version();'"
```
- Falha observada: `Access is denied` no `//./pipe/dockerDesktopLinuxEngine`.
- Correção:
1. Garantir Docker Desktop iniciado com o mesmo usuário do terminal.
2. Reexecutar os comandos Compose acima.
3. Confirmar variáveis e `select version()` dentro do container.

## P0-2) Sem blocker adicional no benchmark oficial

- Evidência fresh já coletada nesta sessão:
```powershell
$env:UPTOWES_LEXICON='src\uptowes\lexicon\ptbr_surgery_v1.py'
.\.venv\Scripts\python.exe scripts\run_queries_custom.py --lex-only
```
- Resultado: `PASS total: mismatches=0/15`.

---

## 6) P1 itens + plano mínimo

1. `scripts/qa_report.py` (triagem humana)
- Plano mínimo:
1. Ler `dataset/chunks.jsonl`.
2. Agrupar `quality_flags` por doc/chunk.
3. Gerar `dataset/out/reports/qa.md` com `chunk_id | path | loc | flag | snippet`.

2. Criticidade de tabela explícita no contrato
- Plano mínimo:
1. Introduzir campo/flag de criticidade no dataset (ex.: `table_critical_tier`).
2. Fazer gate usar marcador explícito + fallback T2/T3.
3. Adicionar fixture para “equivalente” não-TNM.

3. README operacional
- Plano mínimo:
1. Quickstart: setup, testes, build, validate, retrieval.
2. Seção de troubleshooting (DB/Docker/UTF-8/PowerShell).

---

## 7) Mudanças aplicadas nesta auditoria (diff funcional)

- `src/uptowes/validate.py`
  - Adicionado gate `NO_GO_TABLE_CRITICAL`.
  - Adicionado output seguro `_safe_print` para evitar crash de encoding no Windows.
- `tests/test_validate_no_go_table_critical.py`
  - Novo teste dedicado (caso válido, degradado e não-crítico).
- `tests/conftest.py`
  - Fixture `local_tmp_path` repo-local para evitar ACL/tmpdir do Windows.
- `tests/test_golden_fixtures.py`
  - Migrado de `tmp_path` para `local_tmp_path`.
- `pytest.ini`
  - Configuração para `pytest -q` verde no Windows (`-p no:tmpdir`, `testpaths=tests`).
- `docs/STATE_OF_BUILD.md`
  - Atualizado para estado real com checkboxes e runbook funcional PowerShell.
