import importlib
import os
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

api_module = importlib.import_module("modernizer.api.app")


def test_pkg_loads_dotenv_on_import(monkeypatch) -> None:
    import modernizer

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.setattr(
        "dotenv.load_dotenv",
        lambda *args, **kwargs: os.environ.__setitem__("LANGFUSE_PUBLIC_KEY", "pk-test"),
    )

    importlib.reload(modernizer)

    assert os.getenv("LANGFUSE_PUBLIC_KEY") == "pk-test"


def test_modernize_omits_schema_context_when_request_does_not_provide_it(
    monkeypatch,
) -> None:
    captured_state = {}

    async def fake_ainvoke(state, config=None):
        captured_state.update(state)
        return {"generated_code": "def generated(): pass", "report": state["report"], "status": "sucesso", "history_id": "history-id"}

    monkeypatch.setattr(api_module, "graph", SimpleNamespace(ainvoke=fake_ainvoke))
    monkeypatch.setattr(api_module, "create_langfuse_handler", lambda: None)

    response = TestClient(api_module.app).post(
        "/modernize", json={"source_code": "SELECT 1"}
    )

    assert response.status_code == 200
    assert captured_state["schema_sql"] is None
    assert captured_state["schema_source"] == "omitted"
    assert response.json()["report"]["context"]["schema_included"] is False


def test_modernize_passes_schema_when_request_provides_it(monkeypatch) -> None:
    captured_state = {}

    async def fake_ainvoke(state, config=None):
        captured_state.update(state)
        return {"generated_code": "", "report": state["report"], "status": "falha", "history_id": None}

    monkeypatch.setattr(api_module, "graph", SimpleNamespace(ainvoke=fake_ainvoke))
    monkeypatch.setattr(api_module, "create_langfuse_handler", lambda: None)

    response = TestClient(api_module.app).post(
        "/modernize",
        json={
            "source_code": "SELECT 1",
            "schema_sql": "CREATE TABLE request_schema (id INTEGER);",
        },
    )

    assert response.status_code == 200
    assert captured_state["schema_sql"] == "CREATE TABLE request_schema (id INTEGER);"
    assert captured_state["schema_source"] == "request"


def test_unexpected_graph_failure_is_persisted(monkeypatch) -> None:
    saved = {}

    async def failing_ainvoke(state, config=None):
        raise RuntimeError("unexpected analysis error")

    def fake_save_execution(**execution):
        saved.update(execution)
        return uuid4()

    monkeypatch.setattr(
        api_module, "graph", SimpleNamespace(ainvoke=failing_ainvoke)
    )
    monkeypatch.setattr(api_module, "create_langfuse_handler", lambda: None)
    monkeypatch.setattr(api_module, "save_execution", fake_save_execution)

    response = TestClient(api_module.app).post(
        "/modernize", json={"source_code": "SELECT 1"}
    )

    assert response.status_code == 200
    assert response.json()["status"] == "falha"
    assert response.json()["history_id"]
    assert saved["status"] == "falha"
    assert saved["report"]["pipeline"]["error"] == "unexpected analysis error"


def test_langfuse_callback_is_passed_and_flushed(monkeypatch) -> None:
    handler = SimpleNamespace(last_trace_id="langfuse-trace-id")
    captured_config = {}
    flush_calls = []

    async def fake_ainvoke(state, config=None):
        captured_config.update(config or {})
        return {
            "generated_code": "def generated(): pass",
            "report": state["report"],
            "status": "sucesso",
            "history_id": "history-id",
        }

    monkeypatch.setattr(api_module, "create_langfuse_handler", lambda: handler)
    monkeypatch.setattr(
        api_module, "flush_langfuse", lambda: flush_calls.append(True)
    )
    monkeypatch.setattr(api_module, "graph", SimpleNamespace(ainvoke=fake_ainvoke))

    response = TestClient(api_module.app).post(
        "/modernize", json={"source_code": "SELECT 1"}
    )

    assert response.status_code == 200
    assert captured_config["callbacks"] == [handler]
    assert captured_config["metadata"]["langfuse_tags"] == ["sql-modernization"]
    assert captured_config["run_name"] == "plpgsql-to-python"
    assert response.json()["trace_id"] == "langfuse-trace-id"
    assert response.json()["report"]["observability"]["status"] == "ativo"
    assert flush_calls == [True]


def test_zero_trace_id_is_normalized_to_none(monkeypatch) -> None:
    handler = SimpleNamespace(last_trace_id="0" * 32)

    async def fake_ainvoke(state, config=None):
        return {
            "generated_code": "",
            "report": state["report"],
            "status": "falha",
            "history_id": "history-id",
        }

    monkeypatch.setattr(api_module, "create_langfuse_handler", lambda: handler)
    monkeypatch.setattr(api_module, "flush_langfuse", lambda: None)
    monkeypatch.setattr(api_module, "graph", SimpleNamespace(ainvoke=fake_ainvoke))

    response = TestClient(api_module.app).post(
        "/modernize", json={"source_code": "SELECT 1"}
    )

    assert response.status_code == 200
    assert response.json()["trace_id"] is None


def test_artifacts_are_written_to_results_directory(monkeypatch, tmp_path) -> None:
    import json

    from modernizer import artifacts

    monkeypatch.setattr(artifacts, "RESULTS_DIR", tmp_path)

    output = artifacts.export_execution_artifacts(
        source_code="CREATE OR REPLACE FUNCTION fn_demo() RETURNS INT AS $$ BEGIN RETURN 1; END; $$;",
        generated_code="print('ok')",
        report={"status": "sucesso"},
        status="sucesso",
        history_id="history-123",
        trace_id="abc123",
    )

    assert output.name == "fn_demo"
    assert (tmp_path / "fn_demo" / "generated.py").read_text(encoding="utf-8") == "print('ok')"
    payload = json.loads((tmp_path / "summary.json").read_text(encoding="utf-8"))
    assert payload[-1]["trace_id"] == "abc123"