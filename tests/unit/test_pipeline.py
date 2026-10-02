from pathlib import Path
from uuid import uuid4

from modernizer.graph.graphbuilder import graph

SAMPLE_SOURCE = (Path("samples") / "01_fn_saldo_cliente.sql").read_text(
    encoding="utf-8"
)
VALID_PYTHON = "def fn_saldo_cliente(connection, p_cliente_id):\n    return 0\n"


def test_graph_persists_successful_generation(monkeypatch) -> None:
    saved_executions = []
    history_id = uuid4()

    monkeypatch.setattr(
        "modernizer.nodes.generate.generate_python", lambda prompt: VALID_PYTHON
    )
    monkeypatch.setattr(
        "modernizer.nodes.persist.save_execution",
        lambda **execution: saved_executions.append(execution) or history_id,
    )

    result = graph.invoke({"source_code": SAMPLE_SOURCE})

    assert result["status"] == "sucesso"
    assert result["generated_code"] == VALID_PYTHON
    assert result["history_id"] == str(history_id)
    assert saved_executions[0]["status"] == "sucesso"
    assert saved_executions[0]["report"]["validation"]["status"] == "sucesso"


def test_graph_retries_invalid_generated_code(monkeypatch) -> None:
    generated = iter(["def broken(", VALID_PYTHON])
    save_calls = []

    monkeypatch.setattr(
        "modernizer.nodes.generate.generate_python", lambda prompt: next(generated)
    )
    monkeypatch.setattr(
        "modernizer.nodes.persist.save_execution",
        lambda **execution: save_calls.append(execution) or uuid4(),
    )

    result = graph.invoke({"source_code": SAMPLE_SOURCE})

    assert result["status"] == "sucesso"
    assert result["generation_attempts"] == 2
    assert result["report"]["validation"]["attempt"] == 2
    assert len(save_calls) == 1


def test_graph_routes_parse_failure_to_persistence(monkeypatch) -> None:
    saved_executions = []
    monkeypatch.setattr(
        "modernizer.nodes.persist.save_execution",
        lambda **execution: saved_executions.append(execution) or uuid4(),
    )

    result = graph.invoke({"source_code": ""})

    assert result["status"] == "falha"
    assert result["report"]["parsing"]["status"] == "falha"
    assert len(saved_executions) == 1
    assert saved_executions[0]["generated_code"] is None