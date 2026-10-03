from typing import Any

from modernizer.graph.state import PipelineState
from modernizer.persistence.history import save_execution


def persist_node(state: PipelineState) -> dict[str, Any]:
    report = dict(state.get("report", {}))
    status = state.get("status", "falha")
    report["persistence"] = {"status": "sucesso"}
    try:
        history_id = save_execution(
            source_code=state["source_code"],
            generated_code=state.get("generated_code") or None,
            report=report,
            status=status,
        )
        report["persistence"]["history_id"] = str(history_id)
        return {"history_id": str(history_id), "report": report}
    except Exception as error:  # noqa: BLE001 - persistence failures belong in the response report
        report["persistence"] = {"status": "falha", "error": str(error)}
        return {"report": report}
