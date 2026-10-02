from pathlib import Path

import pytest

from modernizer.analysis.semantic import analyze_procedure
from modernizer.generation.generator import _extract_code, build_generation_prompt
from modernizer.parsing.parser import parse_procedure

SAMPLE_FILES = sorted(Path("samples").glob("0[1-5]_*.sql"))


@pytest.mark.parametrize("sample_path", SAMPLE_FILES, ids=lambda path: path.stem)
def test_parse_sample_procedure(sample_path: Path) -> None:
    parsed = parse_procedure(sample_path.read_text(encoding="utf-8"))

    assert parsed["name"] == sample_path.stem.split("_", maxsplit=1)[1]
    assert parsed["kind"] in {"function", "procedure"}
    assert parsed["sql_statement_types"] == ["CreateFunctionStmt"]
    assert parsed["plpgsql_ast"]


def test_parser_extracts_signature_and_risk_features() -> None:
    source_code = (Path("samples") / "03_sp_transferir_entre_contas.sql").read_text(
        encoding="utf-8"
    )

    parsed = parse_procedure(source_code)

    assert parsed["name"] == "sp_transferir_entre_contas"
    assert [parameter["name"] for parameter in parsed["parameters"]] == [
        "p_conta_origem",
        "p_conta_destino",
        "p_valor",
    ]
    assert "for_update" in parsed["features"]
    assert "raise" in parsed["features"]
    assert "exception_block" in parsed["features"]


def test_analyzer_preserves_out_parameter_direction() -> None:
    source_code = (Path("samples") / "02_sp_atualizar_status_contas_inativas.sql").read_text(
        encoding="utf-8"
    )

    analysis = analyze_procedure(parse_procedure(source_code))

    assert [parameter["direction"] for parameter in analysis["parameters"]] == [
        "IN",
        "OUT",
    ]
    assert "get_diagnostics" in analysis["constructs"]


def test_generation_prompt_uses_analysis_schema_and_validation_feedback() -> None:
    source_code = (Path("samples") / "01_fn_saldo_cliente.sql").read_text(
        encoding="utf-8"
    )
    parsed = parse_procedure(source_code)
    state = {
        "source_code": source_code,
        "schema_sql": "CREATE TABLE contas (saldo NUMERIC(18,2));",
        "parsed": parsed,
        "analysis": analyze_procedure(parsed),
        "validation": {"issues": ["invalid syntax"]},
    }

    prompt = build_generation_prompt(state)

    assert "Structured parse and semantic analysis" in prompt
    assert "NUMERIC(18,2)" in prompt
    assert "invalid syntax" in prompt
    assert "CREATE TABLE contas" in prompt


def test_generation_prompt_without_schema_marks_it_as_not_provided() -> None:
    source_code = (Path("samples") / "01_fn_saldo_cliente.sql").read_text(
        encoding="utf-8"
    )
    parsed = parse_procedure(source_code)
    state = {
        "source_code": source_code,
        "parsed": parsed,
        "analysis": analyze_procedure(parsed),
        "schema_source": "omitted",
    }

    prompt = build_generation_prompt(state)

    assert "Optional legacy schema (source: omitted):\nNot provided." in prompt


def test_exception_analysis_requires_separate_audit_transaction() -> None:
    source_code = (Path("samples") / "03_sp_transferir_entre_contas.sql").read_text(
        encoding="utf-8"
    )
    parsed = parse_procedure(source_code)
    state = {
        "source_code": source_code,
        "parsed": parsed,
        "analysis": analyze_procedure(parsed),
    }

    prompt = build_generation_prompt(state)

    assert "separate audit_connection" in prompt
    assert "Never use except/pass or swallow errors" in prompt
    assert "catch only SQLAlchemyError" in prompt
    assert "bare `raise`, never `raise error`" in prompt
    assert "Do not add an except block that only re-raises" in prompt


def test_cursor_and_jsonb_analysis_avoids_n_plus_one() -> None:
    source_code = (Path("samples") / "04_sp_processar_lote_taxas.sql").read_text(
        encoding="utf-8"
    )
    parsed = parse_procedure(source_code)
    state = {
        "source_code": source_code,
        "parsed": parsed,
        "analysis": analyze_procedure(parsed),
    }

    prompt = build_generation_prompt(state)

    assert "sem N+1" in prompt
    assert "jsonb_build_object" in prompt
    assert "cast every bind to its concrete PostgreSQL" in prompt
    assert "Never pass a Python dict or list directly" in prompt
    assert "LEFT JOIN LATERAL" in prompt
    assert "must not execute SELECT statements" in prompt
    assert "logger.exception(...) on that instance" in prompt
    assert "Do not leave unused variables or SQL statements" in prompt


def test_nested_function_and_exception_scope_risks() -> None:
    source_code = (Path("samples") / "05_sp_relatorio_mensal_cliente.sql").read_text(
        encoding="utf-8"
    )
    parsed = parse_procedure(source_code)
    analysis = analyze_procedure(parsed)
    prompt = build_generation_prompt(
        {"source_code": source_code, "parsed": parsed, "analysis": analysis}
    )

    assert "nested_function_call" in parsed["features"]
    assert "status = 'ATIVA'" in prompt
    assert "same Python try scope" in prompt


def test_extract_code_removes_python_fence() -> None:
    assert _extract_code("```python\ndef run():\n    return 1\n```") == "def run():\n    return 1"