from __future__ import annotations

from typing import Any, Dict, List, Tuple

import pytest

from uptowes import retrieval


def _row(chunk_id: str, text: str, score_lex: float = 1.0) -> Dict[str, Any]:
    return {
        "source_table": "chunks_text",
        "chunk_id": chunk_id,
        "doc_id": "DOC_1",
        "source_path": "md_norm/example.md",
        "locator": "L1",
        "title": "Title",
        "chunk_type": "text",
        "text": text,
        "score_lex": score_lex,
    }


def test_hybrid_search_calls_expand_query_when_require_lexicon(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLex:
        def __init__(self) -> None:
            self.groups = {}
            self.calls = 0

        def expand_query(self, _query: str) -> Tuple[str, List[set[str]], set[str], set[str]]:
            self.calls += 1
            return ("apendicite", [{"apendicite"}, {"alvarado"}], set(), set())

    fake_lex = FakeLex()
    monkeypatch.setenv("UPTOWES_LEXICON", "fixtures/lexicon_ok.py")
    monkeypatch.setattr(retrieval, "load_lexicon", lambda _path: fake_lex)
    monkeypatch.setattr(retrieval, "_has_unaccent", lambda _conn: True)
    monkeypatch.setattr(retrieval, "_has_column", lambda _conn, _table, _column: True)
    monkeypatch.setattr(
        retrieval,
        "_lex_search_groups",
        lambda *_args, **_kwargs: [_row("c1", "apendicite alvarado")],
    )
    monkeypatch.setattr(
        retrieval,
        "_lex_search_strict_or_relax",
        lambda *_args, **_kwargs: ([], "NONE"),
    )

    hits = retrieval.hybrid_search(
        conn=object(),  # type: ignore[arg-type]
        query="apendicite alvarado",
        top=3,
        enable_vector=False,
        require_lexicon=True,
    )

    assert fake_lex.calls == 1
    assert hits
    assert hits[0].lex_mode == "STRICT_GROUPS"


def test_hybrid_search_uses_groups_query_poor_mode_with_require_lexicon(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeLex:
        groups: Dict[str, Dict[str, Any]] = {}

        def expand_query(self, _query: str) -> Tuple[str, List[set[str]], set[str], set[str]]:
            return ("sindrome", [{"sindrome"}], set(), set())

    monkeypatch.setenv("UPTOWES_LEXICON", "fixtures/lexicon_ok.py")
    monkeypatch.setattr(retrieval, "load_lexicon", lambda _path: FakeLex())
    monkeypatch.setattr(retrieval, "_has_unaccent", lambda _conn: True)
    monkeypatch.setattr(retrieval, "_has_column", lambda _conn, _table, _column: True)
    monkeypatch.setattr(retrieval, "_lex_search_groups", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(
        retrieval,
        "_lex_search_strict_or_relax",
        lambda *_args, **_kwargs: ([_row("c2", "sindrome de resposta")], "STRICT"),
    )

    hits = retrieval.hybrid_search(
        conn=object(),  # type: ignore[arg-type]
        query="sindrome",
        top=3,
        enable_vector=False,
        require_lexicon=True,
    )

    assert hits
    assert hits[0].lex_mode == "GROUPS_QUERY_POOR"


def test_hybrid_search_fails_without_lexicon_when_required(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("UPTOWES_LEXICON", raising=False)
    with pytest.raises(RuntimeError, match="UPTOWES_LEXICON"):
        retrieval.hybrid_search(
            conn=object(),  # type: ignore[arg-type]
            query="apendicite",
            enable_vector=False,
            require_lexicon=True,
        )


def test_hybrid_search_fails_when_expand_query_crashes(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenLex:
        groups: Dict[str, Dict[str, Any]] = {}

        def expand_query(self, _query: str) -> Tuple[str, List[set[str]], set[str], set[str]]:
            raise ValueError("boom")

    monkeypatch.setenv("UPTOWES_LEXICON", "fixtures/lexicon_ok.py")
    monkeypatch.setattr(retrieval, "load_lexicon", lambda _path: BrokenLex())

    with pytest.raises(RuntimeError, match="Failed to load lexicon"):
        retrieval.hybrid_search(
            conn=object(),  # type: ignore[arg-type]
            query="apendicite",
            enable_vector=False,
            require_lexicon=True,
        )


def test_hybrid_search_fails_when_expand_query_returns_empty_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    class EmptyGroupsLex:
        groups: Dict[str, Dict[str, Any]] = {}

        def expand_query(self, _query: str) -> Tuple[str, List[set[str]], set[str], set[str]]:
            return ("apendicite", [], set(), set())

    monkeypatch.setenv("UPTOWES_LEXICON", "fixtures/lexicon_ok.py")
    monkeypatch.setattr(retrieval, "load_lexicon", lambda _path: EmptyGroupsLex())

    with pytest.raises(RuntimeError, match="empty must_groups"):
        retrieval.hybrid_search(
            conn=object(),  # type: ignore[arg-type]
            query="apendicite",
            enable_vector=False,
            require_lexicon=True,
        )


def test_vector_search_casts_parameter_to_vector_and_accepts_list() -> None:
    class _Col:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeCursor:
        def __init__(self) -> None:
            self.executed_sql = ""
            self.executed_params: tuple[Any, ...] | None = None
            self.description = [_Col("source_table"), _Col("chunk_id"), _Col("score_vec")]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql: str, params: tuple[Any, ...]) -> None:
            self.executed_sql = sql
            self.executed_params = params

        def fetchall(self) -> List[tuple[str, str, float]]:
            return [("chunks_text", "c1", 0.9)]

    class FakeConn:
        def __init__(self) -> None:
            self.last_cursor = FakeCursor()

        def cursor(self) -> FakeCursor:
            self.last_cursor = FakeCursor()
            return self.last_cursor

    conn = FakeConn()
    rows = retrieval._vector_search(conn=conn, table="chunks_text", query_vec=[0.1, 0.2], limit=1)  # type: ignore[arg-type]

    assert rows and rows[0]["chunk_id"] == "c1"
    assert "::vector" in conn.last_cursor.executed_sql
    assert "source_path LIKE" not in conn.last_cursor.executed_sql
    assert conn.last_cursor.executed_params is not None
    first_param = conn.last_cursor.executed_params[0]
    assert isinstance(first_param, str)
    assert first_param.startswith("[") and first_param.endswith("]")


def test_vector_search_applies_source_prefix_like_with_first_param() -> None:
    class _Col:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeCursor:
        def __init__(self) -> None:
            self.executed_sql = ""
            self.executed_params: tuple[Any, ...] | None = None
            self.description = [_Col("source_table"), _Col("chunk_id"), _Col("score_vec")]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execute(self, sql: str, params: tuple[Any, ...]) -> None:
            self.executed_sql = sql
            self.executed_params = params

        def fetchall(self) -> List[tuple[str, str, float]]:
            return [("chunks_text", "c1", 0.9)]

    class FakeConn:
        def __init__(self) -> None:
            self.last_cursor = FakeCursor()

        def cursor(self) -> FakeCursor:
            self.last_cursor = FakeCursor()
            return self.last_cursor

    conn = FakeConn()
    rows = retrieval._vector_search(
        conn=conn,  # type: ignore[arg-type]
        table="chunks_text",
        query_vec=[0.1, 0.2],
        limit=1,
        source_prefix="cirurgia/",
    )

    assert rows and rows[0]["chunk_id"] == "c1"
    assert "source_path LIKE" in conn.last_cursor.executed_sql
    assert conn.last_cursor.executed_params is not None
    assert conn.last_cursor.executed_params[0] == "cirurgia/%"


def test_lex_search_strict_or_relax_toggles_source_prefix_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Col:
        def __init__(self, name: str) -> None:
            self.name = name

    class FakeConn:
        def __init__(self) -> None:
            self.calls: List[tuple[str, tuple[Any, ...]]] = []
            self.description = [
                _Col("source_table"),
                _Col("chunk_id"),
                _Col("doc_id"),
                _Col("source_path"),
                _Col("locator"),
                _Col("title"),
                _Col("chunk_type"),
                _Col("text"),
                _Col("score_lex"),
            ]
            self._fetch_plan: List[List[tuple[Any, ...]]] = []

        def queue_fetch(self, rows: List[tuple[Any, ...]]) -> None:
            self._fetch_plan.append(rows)

        def cursor(self):  # noqa: ANN001
            conn = self

            class FakeCursor:
                description = conn.description

                def __enter__(self):
                    return self

                def __exit__(self, exc_type, exc, tb):
                    return False

                def execute(self, sql: str, params: tuple[Any, ...]) -> None:
                    conn.calls.append((sql, params))

                def fetchall(self) -> List[tuple[Any, ...]]:
                    if conn._fetch_plan:
                        return conn._fetch_plan.pop(0)
                    return []

            return FakeCursor()

    monkeypatch.setattr(retrieval, "_has_unaccent", lambda _conn: False)
    monkeypatch.setattr(retrieval, "_has_column", lambda _conn, _table, _column: False)

    conn_with_prefix = FakeConn()
    conn_with_prefix.queue_fetch(
        [("chunks_text", "c1", "DOC_1", "cirurgia/x.md", "L1", "T", "text", "abc", 1.0)]
    )
    retrieval._lex_search_strict_or_relax(
        conn_with_prefix,  # type: ignore[arg-type]
        "chunks_text",
        "apendicite",
        5,
        source_prefix="cirurgia/",
    )
    sql_with_prefix, params_with_prefix = conn_with_prefix.calls[0]
    assert "source_path LIKE" in sql_with_prefix
    assert params_with_prefix[0] == "cirurgia/%"

    conn_without_prefix = FakeConn()
    conn_without_prefix.queue_fetch(
        [("chunks_text", "c1", "DOC_1", "cirurgia/x.md", "L1", "T", "text", "abc", 1.0)]
    )
    retrieval._lex_search_strict_or_relax(
        conn_without_prefix,  # type: ignore[arg-type]
        "chunks_text",
        "apendicite",
        5,
        source_prefix=None,
    )
    sql_without_prefix, _ = conn_without_prefix.calls[0]
    assert "source_path LIKE" not in sql_without_prefix


def test_hybrid_search_propagates_source_prefix_to_lex_and_vector(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: Dict[str, List[str | None]] = {"lex": [], "vec": []}

    monkeypatch.delenv("UPTOWES_LEXICON", raising=False)
    monkeypatch.setattr(retrieval, "ollama_embed", lambda *_args, **_kwargs: [0.1, 0.2])

    def fake_lex(*_args, **kwargs):
        seen["lex"].append(kwargs.get("source_prefix"))
        return ([], "NONE")

    def fake_vec(*_args, **kwargs):
        seen["vec"].append(kwargs.get("source_prefix"))
        return []

    monkeypatch.setattr(retrieval, "_lex_search_strict_or_relax", fake_lex)
    monkeypatch.setattr(retrieval, "_vector_search", fake_vec)

    retrieval.hybrid_search(
        conn=object(),  # type: ignore[arg-type]
        query="apendicite",
        enable_vector=True,
        require_lexicon=False,
        source_prefix="cirurgia/",
    )

    assert seen["lex"] and all(v == "cirurgia/" for v in seen["lex"])
    assert seen["vec"] and all(v == "cirurgia/" for v in seen["vec"])
