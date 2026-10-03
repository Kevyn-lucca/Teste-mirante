from typing import Any, TypedDict

class InputState(TypedDict,total=False):
    source_code:str
    schema_source:str


class PipelineState(TypedDict, total=False):
    source_code: str
    schema_sql: str | None
    schema_source: str

    parsed: dict[str, Any]
    analysis: dict[str, Any]
    report: dict[str, Any]
    generated_code: str
    validation: dict[str, Any]
    evaluation: dict[str, float]
    generation_attempts: int
    generation_error: str | None
    status: str
    error: str
    history_id: str
    observability: dict[str, Any]