from typing import Any

from modernizer.graph.state import PipelineState
from modernizer.parsing.parser import parse_procedure


def parse_node(state: PipelineState) -> dict[str, Any]:
    report = dict(state.get("report", {}))
    try:
        parsed = parse_procedure(state["source_code"])
    except Exception as error:  # noqa: BLE001 - parser failures are execution outcomes
        message = str(error)
        report["parsing"] = {"status": "falha", "error": message}
        return {"error": message, "status": "falha", "report": report}

    report["parsing"] = {
        "status": "sucesso",
        "routine": parsed["name"],
        "kind": parsed["kind"],
        "features": parsed["features"],
    }
    return {"parsed": parsed, "report": report}
