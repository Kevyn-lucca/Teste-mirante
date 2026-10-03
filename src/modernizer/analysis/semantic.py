from typing import Any

# Orientações de tradução por construção.
_RISK_GUIDANCE = {
    "cursor": (
        "Carregar as linhas em lote. Lookups feitos por registro devem virar JOIN/LATERAL "
        "ou outra consulta set-based, sem N+1. Preservar a ordem do cursor e não deixar "
        "SQL preparado sem uso."
    ),
    "for_update": (
        "Preservar o bloqueio de linha e executar leituras e escritas na mesma transação "
        "do banco."
    ),
    "jsonb": (
        "Preservar a construção JSONB no PostgreSQL ou validar explicitamente a "
        "equivalência do JSON gerado em Python."
    ),
    "recursive_cte": (
        "Preservar o limite e a inclusão de cada passo da recursão. Testar intervalos "
        "de um e de vários passos."
    ),
    "raise": (
        "Distinguir erros de negócio (RAISE EXCEPTION) de mensagens NOTICE/WARNING e "
        "manter a propagação definida pela origem."
    ),
    "exception_block": (
        "Preservar o escopo exato protegido pelo bloco EXCEPTION: as validações que "
        "estavam dentro do bloco devem ficar dentro do mesmo try em Python. Manter "
        "valores de fallback e auditoria idênticos para os erros capturados por ele."
    ),
    "nested_function_call": (
        "Preservar o comportamento da função chamada, incluindo todos os seus filtros e "
        "predicados. Reutilizar a função ou, ao fazer inlining, replicar exatamente os "
        "mesmos predicados."
    ),
    "return_query": (
        "Representar o resultado set-returning como uma coleção tipada e preservar a "
        "ordenação."
    ),
    "get_diagnostics": (
        "Capturar o rowcount imediatamente após o comando correspondente."
    ),
}

# Severidade por construção 
_SEVERITY = {
    "for_update": "high",
    "exception_block": "high",
    "cursor": "high",
    "recursive_cte": "high",
    "jsonb": "medium",
    "raise": "medium",
    "nested_function_call": "medium",
    "return_query": "medium",
    "get_diagnostics": "low",
}

# Modos de parâmetro do pglast/PostgreSQL (proargmodes).
_PARAM_DIRECTIONS = {
    "d": "IN",        # default
    "i": "IN",
    "o": "OUT",
    "b": "INOUT",
    "v": "VARIADIC",
    "t": "TABLE",     # colunas de RETURNS TABLE
}


def analyze_procedure(parsed: dict[str, Any]) -> dict[str, Any]:
    features = parsed["features"]
    risks = [
        {
            "feature": feature,
            "severity": _SEVERITY.get(feature, "medium"),
            "guidance": _RISK_GUIDANCE[feature],
        }
        for feature in features
        if feature in _RISK_GUIDANCE
    ]
    parameters = [
        {
            **parameter,
            "direction": _PARAM_DIRECTIONS.get(parameter["mode"], "UNKNOWN"),
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
            "procedural_logic": "Traduzir o fluxo de controle PL/pgSQL para Python.",
            "database_operations": (
                "Manter as operações de dados como SQL PostgreSQL parametrizado."
            ),
            "monetary_values": (
                "Usar Decimal e quantizar para a escala NUMERIC da origem."
            ),
            "exception_auditing": (
                "Quando o handler de exceção grava um registro de auditoria e relança, "
                "aceitar uma audit_connection separada e fazer commit da auditoria em "
                "transação própria, para que o rollback da transação de negócio não "
                "apague o registro. Nunca engolir a exceção original."
                if "exception_block" in features
                else "Preservar o comportamento de exceções da origem e relançar as falhas."
            ),
            "jsonb": (
                "Preservar os tipos dos valores JSONB, principalmente campos numéricos. "
                "Preferir jsonb_build_object do PostgreSQL com parâmetros vinculados em "
                "vez de converter Decimal para string. Como jsonb_build_object é "
                "polimórfico, fazer cast de cada parâmetro para o tipo PostgreSQL "
                "concreto (BIGINT, TEXT, DATE, INTEGER ou NUMERIC)."
                if "jsonb" in features
                else "Nenhuma tradução de JSONB necessária."
            ),
            "bulk_lookup": (
                "Para cursor com consulta auxiliar por linha, usar um único SELECT com "
                "JOIN (por exemplo LEFT JOIN LATERAL) que traga o registro aplicável de "
                "cada linha. O laço Python do resultado não deve executar SELECT."
                if "cursor" in features
                else "Nenhum lookup por cursor para agrupar em lote."
            ),
        },
    }