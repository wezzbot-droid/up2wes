# STATE_OF_BUILD_AUDIT — UpToWes

**Data:** 2026-02-07
**Escopo da auditoria:** gate de retrieval DB-backed, ingest piloto em Postgres, embeddings/backfill piloto.

## 1) Resumo executivo

- **Retrieval crítico (DB-backed): GO PARCIAL.** O caminho com lexicon prioriza `STRICT_GROUPS` com gates de âncora/cobertura e registra `lex_mode`; não há evidência de fallback RELAX silencioso no benchmark oficial.
- **Ingest DB (piloto): GO.** Ingestão de 10 docs executou com sucesso (`inserted_total=357`) e integridade canônica ficou sem nulos inesperados.
- **Embeddings/backfill (piloto): GO.** Backfill limitado (`limit 50`) funcionou em `chunks_text` e `table_rows`, com atualização confirmada no DB.
- **Infra Docker Compose local: NO-GO operacional.** `docker compose ps/up/logs/exec` falhou por permissão no pipe (`dockerDesktopLinuxEngine`), então validações via `compose exec` não puderam ser reproduzidas neste host.
- **Decisão prática:** avançar para próxima etapa técnica é seguro em modo controlado (DSN local + piloto); não declarar pronto para operação full sem corrigir acesso Docker Compose.

## 2) Evidence Log (comandos executados)

### A) Pré-check ambiente

```powershell
docker compose ps
```
Resultado: `Access is denied` em `//./pipe/dockerDesktopLinuxEngine`.

```powershell
Test-NetConnection localhost -Port 5432
```
Resultado: `TcpTestSucceeded : True`.

```powershell
.\.venv\Scripts\python.exe -c "import sys; print(sys.executable)"
```
Resultado: `C:\Users\wesle\Desktop\uptowes_v2\.venv\Scripts\python.exe`.

```powershell
Write-Output "UPTOWES_DB_DSN=$env:UPTOWES_DB_DSN"
Write-Output "UPTOWES_LEXICON=$env:UPTOWES_LEXICON"
```
Resultado: ambas variáveis vazias no shell atual.

Evidência de DSN padrão no código: `src/uptowes/db.py:11` e `src/uptowes/db.py:20`.

### B) Gate principal do retrieval (anti-regressão RELAX legacy)

```powershell
$env:UPTOWES_LEXICON='src\uptowes\lexicon\ptbr_surgery_v1.py'
.\.venv\Scripts\python.exe scripts\run_queries_custom.py --lex-only
```
Resultado:
- `PASS total: mismatches=0/15`
- relatório escrito em `dataset/out/reports/queries_custom.md`.

```powershell
Get-Content dataset\out\reports\queries_custom.md | Select-String -Pattern "lex_mode:|PASS total"
```
Resultado:
- Queries bucket A com `lex_mode: STRICT_GROUPS`
- `PASS total: mismatches=0/15`

### C) Ingest DB (piloto)

Descoberta do entrypoint:
```powershell
Get-ChildItem -Recurse -File -Include *.py -Path scripts,src | Select-String -Pattern "ingest_pilot|COPY|INSERT INTO documents|chunks_text|table_rows" -CaseSensitive:$false | Select-Object -First 200
```
Resultado: `scripts/ingest_pilot.py` identificado com `INSERT INTO documents/chunks_text/table_rows`.

Help:
```powershell
.\.venv\Scripts\python.exe scripts\ingest_pilot.py -h
```
Resultado: opções de piloto (`--limit-docs`, `--max-chunks`, `--embed`, etc.).

Execução piloto:
```powershell
.\.venv\Scripts\python.exe scripts\ingest_pilot.py --chunks dataset\chunks.jsonl --limit-docs 10
```
Resultado:
- `[OK] Pilot doc_ids selected: 10`
- `[OK] inserted_total=357 text=334 table_rows=23`

Validação pedida via Compose (executada e falhando por permissão):
```powershell
docker compose up -d db
docker compose logs --tail 120 db
docker compose exec db sh -lc "env | grep POSTGRES"
docker compose exec db sh -lc "psql -U $POSTGRES_USER -d $POSTGRES_DB -c 'select version();'"
```
Resultado: todos falham com `Access is denied` no pipe do Docker.

Fallback de validação via conexão real do projeto (`uptowes.db.connect`):
```powershell
$env:PYTHONPATH='src'
@'
from uptowes.db import connect
queries = [
    'select count(*) from documents;',
    'select count(*) from chunks_text;',
    'select count(*) from table_rows;',
    "select count(*) from chunks_text where text_canonical is null or text_canonical='';",
    "select count(*) from table_rows where row_text_canonical is null or row_text_canonical='';",
]
with connect() as conn:
    with conn.cursor() as cur:
        for sql in queries:
            cur.execute(sql)
            print(f"{sql} => {cur.fetchone()[0]}")
'@ | .\.venv\Scripts\python.exe -
```
Resultado:
- `documents => 20`
- `chunks_text => 948`
- `table_rows => 148`
- canônicos vazios/nulos: `0` em ambas as tabelas.

### D) Embeddings/backfill (piloto)

```powershell
ollama list
```
Resultado: inclui `nomic-embed-text:latest`.

```powershell
.\.venv\Scripts\python.exe scripts\embed_backfill.py --table chunks_text --limit 50
.\.venv\Scripts\python.exe scripts\embed_backfill.py --table table_rows --limit 50
```
Resultado: `[OK] backfill completed.` nos dois casos.

Validação:
```powershell
$env:PYTHONPATH='src'
@'
from uptowes.db import connect
queries = [
    'select count(*) from chunks_text where embedding is not null;',
    'select count(*) from table_rows where embedding is not null;',
    'select count(*) from chunks_text where embedding is null;',
    'select count(*) from table_rows where embedding is null;',
]
with connect() as conn:
    with conn.cursor() as cur:
        for sql in queries:
            cur.execute(sql)
            print(f"{sql} => {cur.fetchone()[0]}")
'@ | .\.venv\Scripts\python.exe -
```
Resultado:
- `chunks_text embedding is not null => 50`
- `table_rows embedding is not null => 50`

### E) Regressão de testes

```powershell
pytest -q
```
Resultado: `7 passed`.

## 3) Code Findings (caminho crítico)

### 3.1 `hybrid_search()` usa runtime por grupos no caminho com lexicon

- `src/uptowes/retrieval.py:389` chama `lex.expand_query(q)`.
- `src/uptowes/retrieval.py:410` monta tsquery de grupos (`build_tsquery_from_groups`).
- `src/uptowes/retrieval.py:473` define estratégia `STRICT_GROUPS` com 2-pass.
- `src/uptowes/retrieval.py:477` e `src/uptowes/retrieval.py:485` executam `_lex_search_groups(...)`.

### 3.2 Onde o fallback legacy ainda existe

- `src/uptowes/retrieval.py:497` e `src/uptowes/retrieval.py:498` usam `_lex_search_strict_or_relax` apenas para `rest_text`, aceitando somente modo `STRICT` (`src/uptowes/retrieval.py:499-502`).
- `src/uptowes/retrieval.py:527-528` fallback para query pobre (`groups_query_poor`) com `lex_mode` explícito (`RELAX` ou `STRICT`).
- `src/uptowes/retrieval.py:535-540` caminho `RELAX_GROUPS` com gate de grupos.
- `src/uptowes/retrieval.py:543-546` caminho legado sem lexicon.

### 3.3 Como `lex_mode` é decidido e exposto

- Inicialização: `src/uptowes/retrieval.py:426`.
- Atribuições: `src/uptowes/retrieval.py:523`, `src/uptowes/retrieval.py:532`, `src/uptowes/retrieval.py:540`, `src/uptowes/retrieval.py:546`.
- Retorno no hit: `src/uptowes/retrieval.py:602`.
- Report registra por query: `scripts/run_queries_custom.py:304`.

### 3.4 Gates de segurança por grupos

- Hard anchor gate: `src/uptowes/retrieval.py:457-459`.
- Cobertura mínima de grupos: `src/uptowes/retrieval.py:462-463`.
- Rare-group gate: `src/uptowes/retrieval.py:466-467`.

### 3.5 Benchmark oficial realmente passa pelo DB-backed retrieval

- `scripts/run_queries_custom.py:228` abre conexão real com `connect()`.
- `scripts/run_queries_custom.py:239` e `scripts/run_queries_custom.py:253` chamam `hybrid_search(...)`.
- Portanto, `scripts/run_queries_custom.py --lex-only` exercita o caminho lexical no Postgres (sem vetor), não um mock/local-only.

## 4) GO/NO-GO final

- **Ingest DB (pgvector): GO PARCIAL**
  - **GO (piloto):** ingest e integridade canônica comprovados.
  - **NO-GO (full rollout):** enquanto `docker compose` permanecer inacessível por permissão local, operação e troubleshooting ficam frágeis.

- **Embeddings/backfill (Ollama nomic-embed-text): GO PARCIAL**
  - **GO (piloto):** backfill limitado funcionou em ambas as tabelas com atualização confirmada.
  - **NO-GO (full backfill):** falta validação operacional via Compose neste host e não há evidência de teste de carga longo nesta sessão.

## 5) What can break

1. Queda de engine Docker/pipe sem acesso ao Compose impede observabilidade e `exec` no container.
2. Query sem âncora útil pode cair em fallback controlado (`STRICT/RELAX`), reduzindo precisão se não houver gate de benchmark.
3. Backfill massivo pode falhar no meio (rede/Ollama), exigindo retomada por lotes.

## 6) Rollback

1. Rollback do piloto de ingest (doc_ids ingeridos nesta sessão):
```sql
BEGIN;
DELETE FROM table_rows WHERE doc_id IN (
  'CIRURGIA_ABDOMEAGUDO_ABSCESSOHEPATICO',
  'CIRURGIA_ABDOMEAGUDO_APENDICITEAGUDA',
  'CIRURGIA_ABDOMEAGUDO_COLANGITE',
  'CIRURGIA_ABDOMEAGUDO_COLECISTITE',
  'CIRURGIA_ABDOMEAGUDO_COLEDOCOLITIASE',
  'CIRURGIA_ABDOMEAGUDO_COLELITIASE',
  'CIRURGIA_ABDOMEAGUDO_COMPLICACOES',
  'CIRURGIA_ABDOMEAGUDO_DIVERTICULITE',
  'CIRURGIA_ABDOMEAGUDO_HEMORRAGICO',
  'CIRURGIA_ABDOMEAGUDO_INTRODUCAO'
);
DELETE FROM chunks_text WHERE doc_id IN (
  'CIRURGIA_ABDOMEAGUDO_ABSCESSOHEPATICO',
  'CIRURGIA_ABDOMEAGUDO_APENDICITEAGUDA',
  'CIRURGIA_ABDOMEAGUDO_COLANGITE',
  'CIRURGIA_ABDOMEAGUDO_COLECISTITE',
  'CIRURGIA_ABDOMEAGUDO_COLEDOCOLITIASE',
  'CIRURGIA_ABDOMEAGUDO_COLELITIASE',
  'CIRURGIA_ABDOMEAGUDO_COMPLICACOES',
  'CIRURGIA_ABDOMEAGUDO_DIVERTICULITE',
  'CIRURGIA_ABDOMEAGUDO_HEMORRAGICO',
  'CIRURGIA_ABDOMEAGUDO_INTRODUCAO'
);
DELETE FROM documents WHERE doc_id IN (
  'CIRURGIA_ABDOMEAGUDO_ABSCESSOHEPATICO',
  'CIRURGIA_ABDOMEAGUDO_APENDICITEAGUDA',
  'CIRURGIA_ABDOMEAGUDO_COLANGITE',
  'CIRURGIA_ABDOMEAGUDO_COLECISTITE',
  'CIRURGIA_ABDOMEAGUDO_COLEDOCOLITIASE',
  'CIRURGIA_ABDOMEAGUDO_COLELITIASE',
  'CIRURGIA_ABDOMEAGUDO_COMPLICACOES',
  'CIRURGIA_ABDOMEAGUDO_DIVERTICULITE',
  'CIRURGIA_ABDOMEAGUDO_HEMORRAGICO',
  'CIRURGIA_ABDOMEAGUDO_INTRODUCAO'
);
COMMIT;
```

2. Rollback de embeddings do piloto:
```sql
UPDATE chunks_text SET embedding = NULL WHERE embedding IS NOT NULL;
UPDATE table_rows SET embedding = NULL WHERE embedding IS NOT NULL;
```
Use somente em ambiente de teste/piloto.

## 7) Next 3 steps (highest EV)

1. Corrigir acesso Docker Compose neste host (pipe/permissões) e repetir `compose ps/logs/exec` para fechar evidência operacional de produção.
2. Rodar ingest ampliado (ex.: 100 docs) e validar contagens + nulidade + benchmark `run_queries_custom.py --lex-only` sem regressão.
3. Executar backfill incremental com checkpoints (`--limit` por lotes) até cobertura alvo e registrar throughput/erros por lote.
