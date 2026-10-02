from typing import Any

_RISK_GUIDANCE = {
    "cursor": (
        "Carregar as linhas em lote; combine lookups por registro com JOIN/LATERAL ou outra consulta "
        "set-based, sem N+1; preservar a ordem do cursor e não deixar SQL preparado sem uso."
    ),
    "for_update": (
        "Preservar o bloqueio de linha e executar leituras e escritas na mesma transacao do banco."
    ),
    "jsonb": (
        "Preservar a construcao JSONB no PostgreSQL ou validar explicitamente a equivalencia do JSON Python."
    ),
    "recursive_cte": (
        "Preservar o limite e a inclusao de meses da recursao; testar periodos de um e varios meses."
    ),
    "raise": (
        "Distinguir erros de negocio de mensagens NOTICE/WARNING e manter a propagacao definida pela origem."
    ),
    "exception_block": (
        "Preserve the exact protected exception scope: Python validation must remain inside the same "
        "try boundary as the source block, including invalid-period checks. Keep fallback values and "
        "audit behavior identical for errors caught by that block."
    ),
    "nested_function_call": (
        "Preserve nested function behavior and all its filters. fn_saldo_cliente only sums contas "
        "whose status is 'ATIVA'; reuse that function or apply the identical predicate when inlining."
    ),
    "return_query": (
        "Representar o resultado set-returning como uma colecao tipada e preservar a ordenacao."
    ),
    "get_diagnostics": (
        "Capturar rowcount imediatamente apos o UPDATE correspondente."
    ),
}


def analyze_procedure(parsed: dict[str, Any]) -> dict[str, Any]:
    features = parsed["features"]
    risks = [
        {"feature": feature, "severity": "high", "guidance": _RISK_GUIDANCE[feature]}
        for feature in features
        if feature in _RISK_GUIDANCE
    ]
    parameters = [
        {
            **parameter,
            "direction": {
                "d": "IN",
                "i": "IN",
                "o": "OUT",
                "b": "INOUT",
                "v": "VARIADIC",
            }.get(parameter["mode"], "UNKNOWN"),
        }
        for parameter in parsed["parameters"]
    ]

    return {
        "routine": parsed["name"],
        "kind": parsed["kind"],
        "parameters": parameters,
        "variables": parsed["declarations"],
        "constructs": features,
        "risk_count": len(risks),
        "risks": risks,
        "translation_strategy": {
            "procedural_logic": "Translate PL/pgSQL control flow into Python.",
            "database_operations": "Keep data operations as parameterized PostgreSQL SQL.",
            "monetary_values": "Use Decimal and quantize to the source NUMERIC scale.",
            "exception_auditing": (
                "When an exception handler writes an audit record and re-raises, accept a separate "
                "audit_connection and commit that audit in its own transaction so rollback of the "
                "business transaction does not erase it. Never swallow the original exception."
                if "exception_block" in features
                else "Preserve source exception behavior and re-raise failures."
            ),
            "jsonb": (
                "Preserve JSONB value types, especially numeric fields; prefer PostgreSQL "
                "jsonb_build_object with bound parameters instead of stringifying Decimal values. "
                "Because jsonb_build_object is polymorphic, cast every bind to its concrete PostgreSQL "
                "type (for example BIGINT, TEXT, DATE, INTEGER, or NUMERIC)."
                if "jsonb" in features
                else "No JSONB translation required."
            ),
            "bulk_lookup": (
                "For a cursor over transactions with a per-row rate lookup, use one SELECT with "
                "LEFT JOIN LATERAL selecting the latest applicable rate for each transaction. "
                "The Python result loop must not execute SELECT statements."
                if "cursor" in features
                else "No cursor-based lookup to batch."
            ),
        },
    }