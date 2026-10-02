from typing import Any

from modernizer.analysis.semantic import analyze_procedure


def analyze_node(state: dict[str, Any]) -> dict[str, Any]:
    analysis = analyze_procedure(state["parsed"])
    report = dict(state.get("report", {}))
    report["analysis"] = {
        "status": "sucesso",
        "routine": analysis["routine"],
        "risk_count": analysis["risk_count"],
        "risks": analysis["risks"],
    }
    return {"analysis": analysis, "report": report}