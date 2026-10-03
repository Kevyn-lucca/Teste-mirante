from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from modernizer.graph.graphbuilder import graph

SAMPLE_SOURCE = (Path("samples") / "01_fn_saldo_cliente.sql").read_text(
    encoding="utf-8"
)
VALID_PYTHON = "def fn_saldo_cliente(connection, p_cliente_id):\n    return 0\n"


def test_graph_persists_successful_generation(monkeypatch) -> None:
    saved_executions: list[dict[str, Any]] = []
    history_id = uuid4()

    def fake_save(**execution: Any) -> UUID:
        saved_executions.append(execution)
        return history_id

    monkeypatch.setattr(
        "modernizer.nodes.generate.generate_python", lambda prompt: VALID_PYTHON
    )
    monkeypatch.setattr("modernizer.nodes.persist.save_execution", fake_save)

    result = graph.invoke({"source_code": SAMPLE_SOURCE})

    assert result["status"] == "sucesso"
    assert result["generated_code"] == VALID_PYTHON
    assert result["history_id"] == str(history_id)
    assert saved_executions[0]["status"] == "sucesso"
    assert saved_executions[0]["report"]["validation"]["status"] == "sucesso"


def test_graph_retries_invalid_generated_code(monkeypatch) -> None:
    generated = iter(["def broken(", VALID_PYTHON])
    save_calls: list[dict[str, Any]] = []

    def fake_save(**execution: Any) -> UUID:
        save_calls.append(execution)
        return uuid4()

    monkeypatch.setattr(
        "modernizer.nodes.generate.generate_python", lambda prompt: next(generated)
    )
    monkeypatch.setattr("modernizer.nodes.persist.save_execution", fake_save)

    result = graph.invoke({"source_code": SAMPLE_SOURCE})

    assert result["status"] == "sucesso"
    assert result["generation_attempts"] == 2
    assert result["report"]["validation"]["attempt"] == 2
    assert len(save_calls) == 1


def test_graph_routes_parse_failure_to_persistence(monkeypatch) -> None:
    saved_executions: list[dict[str, Any]] = []

    def fake_save(**execution: Any) -> UUID:
        saved_executions.append(execution)
        return uuid4()

    monkeypatch.setattr("modernizer.nodes.persist.save_execution", fake_save)

    result = graph.invoke({"source_code": ""})

    assert result["status"] == "falha"
    assert result["history_id"]
    assert saved_executions[0]["status"] == "falha"
    assert saved_executions[0]["report"]["parsing"]["status"] == "falha"
