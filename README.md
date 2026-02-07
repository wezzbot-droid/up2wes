# UpToWes

Runbook interno (Windows/PowerShell) para QA/triagem evidence-first.

## Quickstart

1. Criar/usar venv e instalar dependências:
```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt -r requirements-dev.txt
```

2. Rodar testes:
```powershell
pytest -q
```

3. Build do dataset:
```powershell
.\.venv\Scripts\python.exe scripts\build_dataset.py --input md_norm --schema schemas\dataset_chunk.schema.json --out dataset\chunks.jsonl --report dataset\build_report.json
```

4. Validação (schema + gate crítico):
```powershell
$env:PYTHONPATH="src"
.\.venv\Scripts\python.exe src\uptowes\validate.py --jsonl dataset\chunks.jsonl --schema schemas\dataset_chunk.schema.json
```

5. Sanity lexical:
```powershell
.\.venv\Scripts\python.exe scripts\query_lex.py "apendicite alvarado escala" --dataset dataset\chunks.jsonl --lexicon src\uptowes\lexicon\ptbr_surgery_v1.py --top 5
```

6. Benchmark oficial (`LEX_ONLY`):
```powershell
$env:UPTOWES_LEXICON="src\uptowes\lexicon\ptbr_surgery_v1.py"
.\.venv\Scripts\python.exe scripts\run_queries_custom.py --lex-only
```

7. QA report de flags:
```powershell
.\.venv\Scripts\python.exe scripts\qa_report.py --dataset dataset\chunks.jsonl --out dataset\out\reports\qa.md
```

## Variáveis de ambiente

- `UPTOWES_DB_DSN`
  - lida em `src/uptowes/db.py`.
  - default: `postgresql://uptowes:uptowes@localhost:5432/uptowes`
- `UPTOWES_LEXICON`
  - lida por `scripts/run_queries_custom.py` e retrieval.
  - recomendado: `src\uptowes\lexicon\ptbr_surgery_v1.py`

Exemplo:
```powershell
$env:UPTOWES_DB_DSN="postgresql://uptowes:uptowes@localhost:5432/uptowes"
$env:UPTOWES_LEXICON="src\uptowes\lexicon\ptbr_surgery_v1.py"
```

## Troubleshooting (Windows)

### 1) `Access is denied` em `//./pipe/dockerDesktopLinuxEngine`

Checklist objetivo:
1. Verificar Docker:
```powershell
docker info
```
2. Garantir que seu usuário está no grupo `docker-users`:
```powershell
net localgroup docker-users
```
3. Reiniciar backend WSL/Docker:
```powershell
wsl --shutdown
```
4. Reabrir Docker Desktop e validar Compose:
```powershell
docker compose ps
```

### 2) `No such container: db`

Causa comum: confusão entre nome de serviço Compose e container.

Use o serviço Compose (`db`), não nome ad-hoc de container:
```powershell
docker compose ps
docker compose logs --tail 120 db
docker compose exec db sh -lc "env | grep POSTGRES"
docker compose exec db sh -lc "psql -U $POSTGRES_USER -d $POSTGRES_DB -c 'select version();'"
```

### 3) `rg` não reconhecido

Instalar ripgrep:
```powershell
winget install BurntSushi.ripgrep.MSVC
```

