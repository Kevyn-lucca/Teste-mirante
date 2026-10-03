import json
import re
from collections.abc import Mapping
from typing import Any

from langchain.chat_models import init_chat_model

from modernizer.config import settings

# Regras gerais
_GENERAL_RULES = [
    "Return only Python 3.14 source code for one complete module, without Markdown fences.",
    (
        "Translate procedural control flow into Python and keep database operations as "
        "parameterized PostgreSQL SQL using SQLAlchemy text() and a caller-provided connection."
    ),
    "Use Decimal for monetary values and quantize at each assignment matching the NUMERIC scale.",
    (
        "Preserve the transaction, locking, exception, row-count, ordering and fallback "
        "semantics identified in the analysis below."
    ),
    (
        "Do not invent schema fields; use only columns present in the supplied schema or "
        "in the original source."
    ),
    (
        "The complete module must pass Ruff, including import sorting and type-hint checks. "
        "Do not leave unused variables, imports or SQL statements."
    ),
    (
        "Never use except/pass or swallow errors. Re-raise the original error with a bare "
        "`raise`, never `raise error`, to preserve its traceback. Do not add an except block "
        "that only re-raises without logging or translating the exception."
    ),
    (
        "When logging, define `logger = logging.getLogger(__name__)` once and call "
        "logger.exception(...) on that instance, never logging.getLogger(...) at the call site."
    ),
    "Fix every issue listed under the previous attempt's validation issues.",
]

# Regras condicionais
_CONSTRUCT_RULES: dict[str, list[str]] = {
    "exception_block": [
        (
            "For an exception handler that audits and re-raises, use the separate "
            "audit_connection contract from the analysis; never write that audit through a "
            "failed business transaction. If writing the error audit fails, catch only "
            "SQLAlchemyError, log it with logger.exception(), then bare-raise the original "
            "business exception."
        ),
        (
            "Keep validation inside the same Python try scope as the source PL/pgSQL "
            "exception block when that block catches the validation failure, and return the "
            "source fallback row."
        ),
    ],
    "jsonb": [
        (
            "Preserve JSONB numeric types; do not stringify Decimal values in JSON logs. "
            "When binding parameters to jsonb_build_object, explicitly CAST every value to "
            "its PostgreSQL type, because the function is polymorphic."
        ),
        (
            "Never pass a Python dict or list directly as a SQLAlchemy text() bind value; use "
            "jsonb_build_object or json.dumps(...) with CAST(:details AS JSONB)."
        ),
    ],
    "cursor": [
        (
            "For cursor/loop processing, avoid per-record queries: fetch the rows and any "
            "per-row lookup in one set-based statement (for example a JOIN or LEFT JOIN "
            "LATERAL), with no SELECT inside the Python loop."
        ),
    ],
    "nested_function_call": [
        (
            "Preserve the called function's behavior and predicates exactly: reuse the "
            "function, or replicate the identical filters when inlining."
        ),
    ],
}


def _build_rules(constructs: list[str]) -> str:
    rules = list(_GENERAL_RULES)
    for construct in dict.fromkeys(constructs):
        rules.extend(_CONSTRUCT_RULES.get(construct, []))
    return "\n".join(f"{index}. {rule}" for index, rule in enumerate(rules, start=1))


def build_generation_prompt(state: Mapping[str, Any]) -> str:
    parsed = state["parsed"]
    analysis = state["analysis"]
    context = {
        "routine": {
            "name": parsed["name"],
            "kind": parsed["kind"],
            "parameters": analysis["parameters"],
            "return_type": parsed["return_type"],
            "variables": analysis["variables"],
            "constructs": analysis["constructs"],
        },
        "translation_strategy": analysis["translation_strategy"],
        "risks": analysis["risks"],
    }
    repair_feedback = (state.get("validation") or {}).get("issues", [])

    return "\n\n".join(
        [
            "Generate a Python 3.14 module equivalent to the supplied PL/pgSQL routine.",
            "Rules:\n" + _build_rules(analysis["constructs"]),
            "Structured parse and semantic analysis:\n"
            + json.dumps(context, ensure_ascii=False, indent=2),
            "Optional legacy schema (source: "
            + state.get("schema_source", "unspecified")
            + "):\n"
            + (state.get("schema_sql") or "Not provided."),
            "Original source for implementation details:\n" + state["source_code"],
            "Validation issues from the previous attempt:\n"
            + ("\n".join(repair_feedback) if repair_feedback else "None."),
        ]
    )


def _extract_code(content: Any) -> str:
    if isinstance(content, list):
        content = "\n".join(
            block.get("text", "") for block in content if isinstance(block, dict)
        )
    if not isinstance(content, str):
        raise TypeError("LLM response did not contain text")

    code = content.strip()
    fenced = re.fullmatch(r"```(?:python)?\s*\n?(.*?)\n?```", code, re.DOTALL)
    return fenced.group(1).strip() if fenced else code


def generate_python(prompt: str) -> str:
    model_name = settings.model_name
    if not model_name:
        raise RuntimeError("MODEL_NAME is not configured")
    model = init_chat_model(model_name, temperature=0)
    return _extract_code(model.invoke(prompt).content)