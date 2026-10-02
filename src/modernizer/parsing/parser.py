import re
from typing import Any

from pglast import parse_plpgsql, parse_sql
from pglast.stream import RawStream

_FEATURE_PATTERNS = {
    "cursor": r"\b(?:CURSOR|OPEN|FETCH|CLOSE)\b",
    "for_update": r"\bFOR\s+UPDATE\b",
    "jsonb": r"\bJSONB\b|\bjsonb_build_object\b",
    "recursive_cte": r"\bWITH\s+RECURSIVE\b",
    "raise": r"\bRAISE\s+(?:EXCEPTION|NOTICE|WARNING)\b",
    "exception_block": r"\bEXCEPTION\s+WHEN\b",
    "return_query": r"\bRETURN\s+QUERY\b",
    "get_diagnostics": r"\bGET\s+DIAGNOSTICS\b",
    "nested_function_call": r"\bfn_saldo_cliente\s*\(",
}


def parse_procedure(source_code: str) -> dict[str, Any]:
    """Parse one PostgreSQL routine into metadata and a pglast PL/pgSQL AST."""
    statements = parse_sql(source_code)
    routines = [
        statement.stmt
        for statement in statements
        if type(statement.stmt).__name__ == "CreateFunctionStmt"
    ]
    if len(routines) != 1:
        raise ValueError(f"Expected one CREATE FUNCTION/PROCEDURE, found {len(routines)}")

    routine = routines[0]
    plpgsql_ast = parse_plpgsql(source_code)
    if len(plpgsql_ast) != 1:
        raise ValueError(f"Expected one PL/pgSQL body, found {len(plpgsql_ast)}")

    body = plpgsql_ast[0]["PLpgSQL_function"]
    declarations = []
    for datum in body.get("datums", []):
        variable = datum.get("PLpgSQL_var")
        if variable and "lineno" in variable:
            declarations.append(
                {
                    "name": variable["refname"],
                    "type": variable.get("datatype", {})
                    .get("PLpgSQL_type", {})
                    .get("typname"),
                }
            )

    source_upper = source_code.upper()
    detected_features = [
        feature
        for feature, pattern in _FEATURE_PATTERNS.items()
        if re.search(pattern, source_upper, re.IGNORECASE)
    ]
    parameters = [
        {
            "name": parameter.name,
            "mode": parameter.mode.value,
            "type": RawStream()(parameter.argType),
        }
        for parameter in routine.parameters or ()
    ]

    return {
        "name": routine.funcname[-1].sval,
        "kind": "procedure" if routine.is_procedure else "function",
        "parameters": parameters,
        "return_type": RawStream()(routine.returnType) if routine.returnType else None,
        "declarations": declarations,
        "features": detected_features,
        "sql_statement_types": [type(statement.stmt).__name__ for statement in statements],
        "plpgsql_ast": plpgsql_ast,
    }