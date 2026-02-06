from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

import psycopg
from pgvector.psycopg import register_vector


DEFAULT_DSN = "postgresql://uptowes:uptowes@localhost:5432/uptowes"


@dataclass(frozen=True)
class DBConfig:
    dsn: str


def get_db_config() -> DBConfig:
    dsn = os.environ.get("UPTOWES_DB_DSN", DEFAULT_DSN)
    return DBConfig(dsn=dsn)


def connect(dsn: Optional[str] = None) -> psycopg.Connection:
    """
    Conecta no Postgres e tenta registrar o tipo VECTOR (pgvector).

    Importante:
    - Na primeira execução (antes de rodar migrations), o tipo 'vector' pode não existir ainda.
      Nesse caso, seguimos sem registrar (db_migrate não precisa do tipo).
    - Depois que a migration criar a extensão, o register_vector passa a funcionar normalmente.
    """
    cfg = get_db_config()
    conn = psycopg.connect(dsn or cfg.dsn, autocommit=False)

    try:
        register_vector(conn)
    except psycopg.ProgrammingError as e:
        # Caso clássico: DB recém-criado, extensão ainda não aplicada
        msg = str(e).lower()
        if "vector type not found" in msg:
            # OK para fase de migrate; scripts que precisarem de embedding rodarão depois da extensão existir
            pass
        else:
            raise

    return conn
