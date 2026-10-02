from typing import Literal

from typing_extensions import TypedDict
from langgraph.graph import END, START, StateGraph

from modernizer.graph.state import PipelineState
from modernizer.nodes.analyze import analyze_node
from modernizer.nodes.generate import generate_node
from modernizer.nodes.parse import parse_node
from modernizer.nodes.persist import persist_node
from modernizer.nodes.validate import validate_node

MAX_ATTEMPTS = 3


class InputState(TypedDict, total=False):
    source_code: str
    schema_sql: str


def _after_parse(state: PipelineState) -> Literal["analyze", "persist"]:
    return "analyze" if state.get("parsed") else "persist"


def _after_validation(state: PipelineState) -> Literal["persist", "generate"]:
    if state.get("validation", {}).get("valid"):
        return "persist"
    if state.get("generation_error") or state.get("generation_attempts", 0) >= MAX_ATTEMPTS:
        return "persist"
    return "generate"


_builder = StateGraph(PipelineState, input_schema=InputState)
_builder.add_node("parse", parse_node)
_builder.add_node("analyze", analyze_node)
_builder.add_node("generate", generate_node)
_builder.add_node("validate", validate_node)
_builder.add_node("persist", persist_node)

_builder.add_edge(START, "parse")
_builder.add_conditional_edges("parse", _after_parse)
_builder.add_edge("analyze", "generate")
_builder.add_edge("generate", "validate")
_builder.add_conditional_edges("validate", _after_validation)
_builder.add_edge("persist", END)

graph = _builder.compile()