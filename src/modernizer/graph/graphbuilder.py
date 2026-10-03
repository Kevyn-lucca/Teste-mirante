from typing import Literal

from langgraph.graph import END, START, StateGraph

from modernizer.graph.state import PipelineState
from modernizer.nodes.analyze import analyze_node
from modernizer.nodes.evaluate import evaluate_node
from modernizer.nodes.generate import generate_node
from modernizer.nodes.parse import parse_node
from modernizer.nodes.persist import persist_node
from modernizer.nodes.validate import validate_node

MAX_ATTEMPTS = 3


def _after_parse(state: PipelineState) -> Literal["analyze", "persist"]:
    return "persist" if state.get("status") == "falha" else "analyze"


def _after_validation(state: PipelineState) -> Literal["generate", "persist"]:
    if (
        state.get("status") != "sucesso"
        and state.get("generation_attempts", 0) < MAX_ATTEMPTS
    ):
        return "generate"
    return "persist"


_builder = StateGraph(PipelineState)
_builder.add_node("parse", parse_node)
_builder.add_node("analyze", analyze_node)
_builder.add_node("generate", generate_node)
_builder.add_node("validate", validate_node)
_builder.add_node("persist", persist_node)
_builder.add_node("evaluate", evaluate_node)

_builder.add_edge(START, "parse")
_builder.add_conditional_edges("parse", _after_parse)
_builder.add_edge("analyze", "generate")
_builder.add_edge("generate", "validate")
_builder.add_conditional_edges("validate", _after_validation)
_builder.add_edge("persist", "evaluate")
_builder.add_edge("evaluate", END)

graph = _builder.compile()
