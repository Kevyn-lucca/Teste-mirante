from typing import Any

from modernizer.analysis.semantic import analyze_procedure
from modernizer.graph.state import PipelineState


def analyze_node(state: PipelineState) -> dict[str, Any]:
    analysis = analyze_procedure(state["parsed"])
    report = dict(state.get("report", {}))
    report["analysis"] = {
        "status": "sucesso",
        "routine": analysis["routine"],
        "kind": analysis["kind"],
        "parameters": analysis["parameters"],
        "constructs": analysis["constructs"],
        "risk_count": analysis["risk_count"],
        "risks": analysis["risks"],
    }
    return {"analysis": analysis, "report": report}
