import ast
import subprocess


def validate_python(source_code: str) -> dict[str, object]:
    issues = []
    try:
        ast.parse(source_code)
    except SyntaxError as error:
        return {
            "valid": False,
            "issues": [f"Python syntax error at line {error.lineno}: {error.msg}"],
            "normalized_code": source_code,
        }

    autofix = subprocess.run(
        ["ruff", "check", "--fix", "--stdin-filename", "generated.py", "-"],
        input=source_code,
        capture_output=True,
        text=True,
        check=False,
    )
    normalized_code = autofix.stdout or source_code
    result = subprocess.run(
        ["ruff", "check", "--stdin-filename", "generated.py", "-"],
        input=normalized_code,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        issues.extend(line for line in result.stdout.splitlines() if line.strip())
        issues.extend(line for line in result.stderr.splitlines() if line.strip())

    return {
        "valid": not issues,
        "issues": issues,
        "normalized_code": normalized_code,
    }