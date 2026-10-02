import json
import re
from typing import Any

from langchain.chat_models import init_chat_model

from modernizer.config import settings


def build_generation_prompt(state: dict[str, Any]) -> str:
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
    repair_feedback = state.get("validation", {}).get("issues", [])

    return "\n\n".join(
        [
            "Generate a Python 3.14 module equivalent to the supplied PL/pgSQL routine.",
            (
                "Translate procedural control flow into Python and keep database operations as "
                "parameterized PostgreSQL SQL using SQLAlchemy text() and a caller-provided connection. "
                "Use Decimal for monetary values and quantize at each assignment matching NUMERIC scale. "
                "Preserve transaction, locking, exception, row-count, cursor, ordering, and fallback "
                "semantics identified below. For an exception handler that audits and re-raises, use "
                "the separate audit_connection contract in the analysis; never write that audit through "
                "a failed business transaction. If writing the error audit fails, catch only "
                "SQLAlchemyError, log it with logging.getLogger(__name__).exception(), then bare-raise "
                "the original business exception. Never use except/pass or swallow errors. Ensure the "
                "logger variable refers to a Logger instance; call logger.exception(...) on that "
                "instance rather than calling logger.getLogger(...). Re-raise the original error with "
                "bare `raise`, never `raise error`, to preserve its traceback. Do not add an "
                "except block that only re-raises without logging or translating the exception. "
                "Preserve nested SQL function semantics and predicates exactly; for fn_saldo_cliente "
                "the balance includes only contas with status = 'ATIVA'. Keep validation inside the "
                "same Python try scope as the source PL/pgSQL exception block when that block catches "
                "the validation failure, and return the source fallback row. "
                "complete module passes Ruff, including import sorting and type-hint checks. Do not leave "
                "unused variables or SQL statements. For cursor/loop processing, avoid per-record queries "
                "by using a set-based join or batch lookup. Preserve JSONB numeric types; do not stringify "
                "Decimal values in JSON logs; cast JSON text parameters to JSONB when a text payload is "
                "used. When passing bind parameters to jsonb_build_object, explicitly CAST every value "
                "to its PostgreSQL type because the function is polymorphic. Never pass a Python dict "
                "or list directly as a SQLAlchemy text() bind value; use jsonb_build_object or "
                "json.dumps(...) with CAST(:details AS JSONB). For the transaction-rate "
                "cursor pattern, the SELECT with LEFT JOIN LATERAL must "
                "fetch each transaction and its most recent applicable rate in one round trip, with no "
                "SELECT inside the Python loop. Do not invent schema fields. Return only Python source "
                "code, without Markdown fences."
            ),
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