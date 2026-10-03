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
    "nested_function_call": r"\b(?:PERFORM\s+[A-Za-z0-9_]+|CALL\s+[A-Za-z0-9_]+|(?:fn_|sp_)[A-Za-z0-9_]+)\s*\(",
}


def parse_procedure(source_code: str) -> dict[str, Any]:
    """Parse one PostgreSQL routine into metadata and a pglast PL/pgSQL AST."""
    statements = parse_sql(source_code)
    if not statements:
        raise ValueError("No SQL statements found in source code")

    routine = statements[0].stmt
    plpgsql_ast = parse_plpgsql(source_code)
    declarations = []

    for variable in plpgsql_ast[0]["PLpgSQL_function"]["datums"]:
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
    raw_params = getattr(routine, "parameters", None) or ()
    parameters = [
        {
            "name": parameter.name,
            "mode": parameter.mode.value,
            "type": RawStream()(parameter.argType),
        }
        for parameter in raw_params
    ]

    funcname = getattr(routine, "funcname", None)
    return_type = getattr(routine, "returnType", None)

    return {
        "name": funcname[-1].sval if funcname else "unknown",
        "kind": "procedure" if getattr(routine, "is_procedure", False) else "function",
        "return_type": RawStream()(return_type) if return_type else "void",
        "parameters": parameters,
        "declarations": declarations,
        "features": detected_features,
        "sql_statement_types": [type(statement.stmt).__name__ for statement in statements],
        "plpgsql_ast": plpgsql_ast,
    }
