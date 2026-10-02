from typing import Any

from modernizer.validation.validator import validate_python


def validate_node(state: dict[str, Any]) -> dict[str, Any]:
    if state.get("generation_error"):
        validation = {"valid": False, "issues": [state["generation_error"]]}
    else:
        validation = validate_python(state.get("generated_code", ""))

    report = dict(state.get("report", {}))
    report["validation"] = {
        "status": "sucesso" if validation["valid"] else "falha",
        "attempt": state.get("generation_attempts", 0),
        "issues": validation["issues"],
        "autofixes_applied": validation.get("normalized_code")
        != state.get("generated_code", ""),
    }
    status = (
        "sucesso"
        if validation["valid"]
        else "parcial"
        if state.get("generated_code")
        else "falha"
    )
    return {
        "validation": validation,
        "report": report,
        "status": status,
        "generated_code": validation.get(
            "normalized_code", state.get("generated_code", "")
        ),
    }