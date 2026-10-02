from typing import Any

from modernizer.generation.generator import build_generation_prompt, generate_python


def generate_node(state: dict[str, Any]) -> dict[str, Any]:
    attempt = state.get("generation_attempts", 0) + 1
    report = dict(state.get("report", {}))
    try:
        prompt = build_generation_prompt(state)
        generated_code = generate_python(prompt)
        report["generation"] = {"status": "sucesso", "attempt": attempt}
        return {
            "generated_code": generated_code,
            "generation_attempts": attempt,
            "generation_error": None,
            "report": report,
        }
    except Exception as error:  # noqa: BLE001 - provider exceptions must enter the execution report
        message = str(error)
        report["generation"] = {
            "status": "falha",
            "attempt": attempt,
            "error": message,
        }
        return {
            "generated_code": "",
            "generation_attempts": attempt,
            "generation_error": message,
            "report": report,
        }