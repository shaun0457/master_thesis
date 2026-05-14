import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path


class _DummyToolExec:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def ok(self, value):
        return None


class _DummyLogger:
    def tool_exec(self, **kwargs):
        return _DummyToolExec()

    def error_event(self, **kwargs):
        return None


def test_sql_db_query_rejects_non_select_and_allows_select(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")

    import de_tools
    monkeypatch.setattr(de_tools, "get_run_logger", lambda: _DummyLogger())
    executed = []

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": 1, "value": "alpha"}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execution_options(self, **kwargs):
            assert kwargs["no_cache_on_overflow"] is True
            return self

        def exec_driver_sql(self, sql):
            executed.append(("pragma", sql))

        def execute(self, stmt):
            executed.append(("query", str(stmt)))
            return FakeResult()

    class FakeEngine:
        dialect = type("Dialect", (), {"name": "sqlite"})()

        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(de_tools, "_get_db_engine", lambda: FakeEngine())
    monkeypatch.setenv("DE_AUTOREGISTER", "0")

    for query in (
        "DELETE FROM metrics",
        "  /* leading comment */ DROP TABLE metrics",
        "-- comment only\nINSERT INTO metrics(value) VALUES ('beta')",
    ):
        payload = json.loads(de_tools.sql_db_query.invoke({"query": query}))
        assert payload["status"] == "error"
        assert "Only read-only SELECT queries are allowed." in payload["error"]

    payload = json.loads(de_tools.sql_db_query.invoke({"query": "SELECT id, value FROM metrics"}))
    assert payload["status"] == "ok"
    assert payload["rowcount"] == 1
    assert payload["rows"][0]["value"] == "alpha"
    assert ("pragma", "PRAGMA query_only = ON") in executed
    assert any(item[0] == "query" for item in executed)


def test_sql_db_query_returns_df_payload_after_autoregister(monkeypatch):
    monkeypatch.setenv("RUN_ID", "sql-df-payload")
    monkeypatch.setenv("RUNS_DIR", os.getcwd())
    monkeypatch.setenv("DE_AUTOREGISTER", "1")
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")

    import de_tools
    monkeypatch.setattr(de_tools, "get_run_logger", lambda: _DummyLogger())

    class FakeResult:
        def mappings(self):
            return self

        def all(self):
            return [{"id": 1, "value": "alpha"}]

    class FakeConnection:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def execution_options(self, **kwargs):
            return self

        def exec_driver_sql(self, sql):
            return None

        def execute(self, stmt):
            return FakeResult()

    class FakeEngine:
        dialect = type("Dialect", (), {"name": "sqlite"})()

        def connect(self):
            return FakeConnection()

    monkeypatch.setattr(de_tools, "_get_db_engine", lambda: FakeEngine())
    monkeypatch.setattr(de_tools, "bb_register_dataset_path", lambda **kwargs: {"status": "ok"})
    monkeypatch.setattr(
        de_tools.pd.DataFrame,
        "to_parquet",
        lambda self, path, index=False: Path(path).write_text("stub", encoding="utf-8"),
    )

    payload = json.loads(de_tools.sql_db_query.invoke({"query": "SELECT id, value FROM metrics"}))
    assert payload["status"] == "ok"
    assert payload["df_payload"] is not None
    assert payload["df_payload"]["run_id"] == "sql-df-payload"
    assert payload["df_payload"]["path"].endswith(".parquet")


def test_execute_python_code_does_not_forward_secret_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_API_KEY", "super-secret")

    import ds_tools
    monkeypatch.setattr(ds_tools, "get_run_logger", lambda: _DummyLogger())

    result = ds_tools._execute_python_subprocess(
        "import os; print(os.environ.get('GOOGLE_API_KEY', 'missing'))"
    )

    assert result["returncode"] == 0
    assert result["stdout"].strip() == "missing"


def test_bb_write_concurrent_writes_preserve_all_records(monkeypatch):
    monkeypatch.setenv("RUN_ID", "bb-lock")
    monkeypatch.setenv("RUNS_DIR", os.getcwd())
    monkeypatch.setenv("GOOGLE_API_KEY", "dummy-key-for-unit-test")

    import bb_tools
    monkeypatch.setattr(bb_tools, "emit_bb_write", lambda **kwargs: None)
    monkeypatch.setattr(bb_tools, "note_tool_call", lambda **kwargs: None)

    storage = {"facts": [], "datasets": [], "citations": [], "open_issues": [], "artifacts": []}

    def fake_load(run_id=None):
        time.sleep(0.01)
        return {
            "facts": list(storage["facts"]),
            "datasets": list(storage["datasets"]),
            "citations": list(storage["citations"]),
            "open_issues": list(storage["open_issues"]),
            "artifacts": list(storage["artifacts"]),
        }

    def fake_save(run_id, reg):
        time.sleep(0.01)
        storage["facts"] = list(reg["facts"])
        storage["datasets"] = list(reg["datasets"])
        storage["citations"] = list(reg["citations"])
        storage["open_issues"] = list(reg["open_issues"])
        storage["artifacts"] = list(reg["artifacts"])

    monkeypatch.setattr(bb_tools, "_load", fake_load)
    monkeypatch.setattr(bb_tools, "_save", fake_save)

    def write_one(i):
        return bb_tools.bb_write(
            run_id="bb-lock",
            topic_id="topic-1",
            section="facts",
            content_preview=f"fact-{i}",
            created_by="test",
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(write_one, range(2)))

    previews = {item["preview"] for item in storage["facts"]}
    assert previews == {"fact-0", "fact-1"}
    assert len(storage["artifacts"]) == 2
