import ast
from collections.abc import Mapping
from typing import Any

MAX_ATTEMPTS = 3  # manter igual ao MAX_ATTEMPTS do graphbuilder.py


NUMERIC_SCORES = {"attempts", "quality_score"}

WEIGHTS = {"lint": 0.35, "status": 0.25, "efficiency": 0.40}


def _ast_ok(code: str) -> bool:
    if not code.strip():
        return False
    try:
        ast.parse(code)
        return True
    except SyntaxError:
        return False


def quality_score(state: Mapping[str, Any]) -> float:
    """Nota de 1 a 10 para o código final.

    - Código vazio ou que não passa em ast.parse: 1.0 (portão).
    - Caso contrário, 1 + 9 * (média ponderada de):
        lint        = 1 / (1 + nº de issues restantes)       (gradual)
        status      = 1 se status == "sucesso", senão 0
        efficiency  = 1 na 1ª tentativa, caindo até 0 em MAX_ATTEMPTS
    """
    code = state.get("generated_code", "") or ""
    if not _ast_ok(code):
        return 1.0

    validation = state.get("validation") or {}
    issues = validation.get("issues") or []
    attempts = max(int(state.get("generation_attempts", 0) or 0), 1)

    lint = 1 / (1 + len(issues))
    status = 1.0 if state.get("status") == "sucesso" else 0.0
    efficiency = max(0.0, 1 - (attempts - 1) / (MAX_ATTEMPTS - 1))

    raw = (
        WEIGHTS["lint"] * lint
        + WEIGHTS["status"] * status
        + WEIGHTS["efficiency"] * efficiency
    )
    return round(1 + 9 * raw, 1)


def compute_scores(state: Mapping[str, Any]) -> dict[str, float]:
    code = state.get("generated_code", "") or ""
    valid = bool((state.get("validation") or {}).get("valid"))
    attempts = state.get("generation_attempts", 0)

    return {
        "quality_score": quality_score(state),
        "status_success": float(state.get("status") == "sucesso"),
        "ast_parse_ok": float(_ast_ok(code)),
        "lint_clean": float(valid),
        "first_attempt_pass": float(valid and attempts == 1),
        "attempts": float(attempts),
    }


def log_scores(
    trace_id: str | None, state: dict[str, Any], completed: bool = True
) -> dict[str, float]:
    """Calcula as notas do estado final e as envia ao trace no Langfuse."""
    scores = {"completed_without_error": float(completed), **compute_scores(state)}
    if not completed:
        scores["quality_score"] = 1.0   # pipeline quebrou: nota mínima
    if not trace_id:
        return scores

    from langfuse import (
        get_client,  
    )

    langfuse = get_client()
    for name, value in scores.items():
        langfuse.create_score(
            trace_id=trace_id,
            name=name,
            value=value,
            data_type="NUMERIC" if name in NUMERIC_SCORES else "BOOLEAN",
        )
    langfuse.flush()
    return scores