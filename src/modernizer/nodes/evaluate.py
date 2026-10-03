from typing import Any

from modernizer.evaluation.metrics import compute_scores
from modernizer.graph.state import PipelineState


def evaluate_node(state: PipelineState) -> dict[str, Any]:
    scores = compute_scores(state)
    report = dict(state.get("report", {}))
    report["evaluation"] = scores
    return {"evaluation": scores, "report": report}
