import ast
import json
import subprocess
import sys
from typing import Any

RUFF_BASE = [
    sys.executable,
    "-m",
    "ruff",
    "check",
    "--isolated",
    "--select",
    "E,F,I,S110",
    "--stdin-filename",
    "generated.py",
]


def _ruff(extra_args: list[str], code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [*RUFF_BASE, *extra_args, "-"],
        input=code,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def validate_python(source_code: str) -> dict[str, Any]:
    issues: list[str] = []
    try:
        ast.parse(source_code)
    except SyntaxError as error:
        return {
            "valid": False,
            "issues": [f"Python syntax error at line {error.lineno}: {error.msg}"],
            "normalized_code": source_code,
        }

    try:
        fixed = _ruff(["--fix", "--exit-zero"], source_code)
        normalized_code = fixed.stdout if fixed.returncode == 0 and fixed.stdout else source_code
    except Exception as error:  # noqa: BLE001
        issues.append(f"Ruff autofix execution failed: {error}")
        normalized_code = source_code

    try:
        check = _ruff(["--output-format=json"], normalized_code)
    except Exception as error:  # noqa: BLE001
        issues.append(f"Ruff validation execution failed: {error}")
    else:
        issues += [
            f"{i['code']} line {i['location']['row']}: {i['message']}"
            for i in json.loads(check.stdout or "[]")
        ]

    return {"valid": not issues, "issues": issues, "normalized_code": normalized_code}
