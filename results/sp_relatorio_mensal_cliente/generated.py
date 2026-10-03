from datetime import date
from decimal import Decimal
import logging
from typing import Any, Sequence
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def fn_saldo_cliente(conn: Connection, cliente_id: int) -> Decimal:
    query = text(
        """
        SELECT COALESCE(SUM(saldo), 0) AS saldo
        FROM contas
        WHERE cliente_id = :cliente_id
          AND status = 'ATIVA'
    """
    )
    result = conn.execute(query, {"cliente_id": cliente_id}).scalar()
    return Decimal(str(result if result is not None else 0)).quantize(
        Decimal("0.01")
    )


def sp_relatorio_mensal_cliente(
    conn: Connection,
    audit_connection: Connection,
    p_cliente_id: int,
    p_data_inicio: date,
    p_data_fim: date,
) -> Sequence[dict[str, Any]]:
    v_saldo_atual = Decimal("0.00")
    try:
        if p_data_inicio > p_data_fim:
            raise ValueError(
                f"Periodo invalido: inicio {p_data_inicio} > fim {p_data_fim}"
            )

        v_saldo_atual = fn_saldo_cliente(conn, p_cliente_id)
        logger.info("Saldo atual do cliente %s: %s", p_cliente_id, v_saldo_atual)

        query = text(
            """
            WITH RECURSIVE meses AS (
                SELECT DATE_TRUNC('month', CAST(:p_data_inicio AS DATE))::DATE AS mes
                UNION ALL
                SELECT (mes + INTERVAL '1 month')::DATE
                FROM meses
                WHERE mes < DATE_TRUNC('month', CAST(:p_data_fim AS DATE))
            ),
            movimento AS (
                SELECT
                    DATE_TRUNC('month', t.data_transacao)::DATE AS mes,
                    SUM(CASE WHEN t.conta_destino_id IN (
                        SELECT id FROM contas WHERE cliente_id = :p_cliente_id
                    ) THEN t.valor ELSE 0 END) AS creditos,
                    SUM(CASE WHEN t.conta_origem_id IN (
                        SELECT id FROM contas WHERE cliente_id = :p_cliente_id
                    ) THEN t.valor ELSE 0 END) AS debitos,
                    COUNT(*) AS qtd
                FROM transacoes t
                WHERE t.status = 'EFETIVADA'
                  AND t.data_transacao >= CAST(:p_data_inicio AS DATE)
                  AND t.data_transacao < CAST(:p_data_fim AS DATE) + INTERVAL '1 day'
                  AND (
                      t.conta_origem_id IN (SELECT id FROM contas WHERE cliente_id = :p_cliente_id)
                      OR t.conta_destino_id IN (SELECT id FROM contas WHERE cliente_id = :p_cliente_id)
                  )
                GROUP BY 1
            )
            SELECT
                m.mes AS mes_referencia,
                COALESCE(mv.creditos, 0)::NUMERIC(18,2) AS total_creditos,
                COALESCE(mv.debitos, 0)::NUMERIC(18,2) AS total_debitos,
                (CAST(:v_saldo_atual AS NUMERIC(18,2)) + COALESCE(mv.creditos, 0)
                 - COALESCE(mv.debitos, 0))::NUMERIC(18,2) AS saldo_consolidado,
                COALESCE(mv.qtd, 0)::INT AS qtd_transacoes
            FROM meses m
            LEFT JOIN movimento mv ON mv.mes = m.mes
            ORDER BY m.mes
        """
        )

        rows = conn.execute(
            query,
            {
                "p_cliente_id": p_cliente_id,
                "p_data_inicio": p_data_inicio,
                "p_data_fim": p_data_fim,
                "v_saldo_atual": v_saldo_atual,
            },
        ).fetchall()

        result = []
        for row in rows:
            result.append(
                {
                    "mes_referencia": row.mes_referencia,
                    "total_creditos": Decimal(str(row.total_creditos)).quantize(
                        Decimal("0.01")
                    ),
                    "total_debitos": Decimal(str(row.total_debitos)).quantize(
                        Decimal("0.01")
                    ),
                    "saldo_consolidado": Decimal(
                        str(row.saldo_consolidado)
                    ).quantize(Decimal("0.01")),
                    "qtd_transacoes": int(row.qtd_transacoes),
                }
            )
        return result

    except Exception as e:
        logger.warning(
            "Falha ao gerar relatorio: %s. Retornando linha de fallback.", e
        )
        try:
            audit_query = text(
                """
                INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                VALUES (
                    CAST(:entidade AS VARCHAR(50)),
                    CAST(:entidade_id AS BIGINT),
                    CAST(:acao AS VARCHAR(50)),
                    jsonb_build_object(
                        CAST('erro' AS TEXT), CAST(:erro AS TEXT)
                    )
                )
            """
            )
            audit_connection.execute(
                audit_query,
                {
                    "entidade": "clientes",
                    "entidade_id": p_cliente_id,
                    "acao": "SP_RELATORIO_MENSAL_CLIENTE_ERRO",
                    "erro": str(e),
                },
            )
            audit_connection.commit()
        except SQLAlchemyError:
            logger.exception("Failed to audit exception in log_auditoria")

        fallback_mes = p_data_inicio.replace(day=1)
        zero_val = Decimal("0.00").quantize(Decimal("0.01"))
        fallback_saldo = v_saldo_atual.quantize(Decimal("0.01"))

        return [
            {
                "mes_referencia": fallback_mes,
                "total_creditos": zero_val,
                "total_debitos": zero_val,
                "saldo_consolidado": fallback_saldo,
                "qtd_transacoes": 0,
            }
        ]