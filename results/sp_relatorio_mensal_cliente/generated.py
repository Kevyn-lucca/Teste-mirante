import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def quantize_val(val: Any) -> Decimal:
    if val is None:
        return Decimal("0.00").quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    return Decimal(str(val)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


def fn_saldo_cliente(
    connection: Connection, p_cliente_id: int
) -> Decimal:
    query = text(
        """
        SELECT COALESCE(SUM(
            CASE 
                WHEN conta_destino_id IN (
                    SELECT id FROM contas WHERE cliente_id = :cliente_id
                ) THEN valor
                WHEN conta_origem_id IN (
                    SELECT id FROM contas WHERE cliente_id = :cliente_id
                ) THEN -valor
                ELSE 0
            END
        ), 0) AS saldo
        FROM transacoes
        WHERE status = 'EFETIVADA'
          AND (
              conta_origem_id IN (
                  SELECT id FROM contas WHERE cliente_id = :cliente_id
              )
              OR conta_destino_id IN (
                  SELECT id FROM contas WHERE cliente_id = :cliente_id
              )
          )
        """
    )
    res = connection.execute(query, {"cliente_id": p_cliente_id}).scalar()
    return quantize_val(res)


def sp_relatorio_mensal_cliente(
    connection: Connection,
    p_cliente_id: int,
    p_data_inicio: datetime.date,
    p_data_fim: datetime.date,
    audit_connection: Connection | None = None,
) -> list[dict[str, Any]]:
    v_saldo_atual: Decimal | None = None
    try:
        if p_data_inicio > p_data_fim:
            raise ValueError(
                f"Periodo invalido: inicio {p_data_inicio} > "
                f"fim {p_data_fim}"
            )

        v_saldo_atual = fn_saldo_cliente(connection, p_cliente_id)
        logger.info(
            "Saldo atual do cliente %s: %s",
            p_cliente_id,
            v_saldo_atual,
        )

        query = text(
            """
            WITH RECURSIVE meses AS (
                SELECT DATE_TRUNC('month', CAST(:p_data_inicio AS DATE))
                    ::DATE AS mes
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
                  AND t.data_transacao >= :p_data_inicio
                  AND t.data_transacao < CAST(:p_data_fim AS DATE)
                      + INTERVAL '1 day'
                  AND (
                      t.conta_origem_id IN (
                          SELECT id FROM contas
                          WHERE cliente_id = :p_cliente_id
                      )
                      OR t.conta_destino_id IN (
                          SELECT id FROM contas
                          WHERE cliente_id = :p_cliente_id
                      )
                  )
                GROUP BY 1
            )
            SELECT
                m.mes AS mes_referencia,
                COALESCE(mv.creditos, 0) AS total_creditos,
                COALESCE(mv.debitos, 0) AS total_debitos,
                CAST(:v_saldo_atual AS NUMERIC(18,2))
                    + COALESCE(mv.creditos, 0)
                    - COALESCE(mv.debitos, 0) AS saldo_consolidado,
                COALESCE(mv.qtd, 0)::INT AS qtd_transacoes
            FROM meses m
            LEFT JOIN movimento mv ON mv.mes = m.mes
            ORDER BY m.mes
            """
        )

        result = connection.execute(
            query,
            {
                "p_data_inicio": p_data_inicio,
                "p_data_fim": p_data_fim,
                "p_cliente_id": p_cliente_id,
                "v_saldo_atual": v_saldo_atual,
            },
        )

        rows = []
        for row in result:
            rows.append(
                {
                    "mes_referencia": row.mes_referencia,
                    "total_creditos": quantize_val(row.total_creditos),
                    "total_debitos": quantize_val(row.total_debitos),
                    "saldo_consolidado": quantize_val(
                        row.saldo_consolidado
                    ),
                    "qtd_transacoes": int(row.qtd_transacoes),
                }
            )
        return rows

    except Exception as e:
        if audit_connection is not None:
            try:
                audit_query = text(
                    """
                    INSERT INTO audit_log (evento, detalhes)
                    VALUES (:evento, :detalhes)
                    """
                )
                audit_connection.execute(
                    audit_query,
                    {
                        "evento": "sp_relatorio_mensal_cliente_error",
                        "detalhes": str(e),
                    },
                )
                audit_connection.commit()
            except SQLAlchemyError:
                logger.exception("Failed to write error audit log")

        logger.warning(
            "Falha ao gerar relatorio: %s. Retornando linha de fallback.",
            e,
        )

        fallback_saldo = (
            quantize_val(v_saldo_atual)
            if v_saldo_atual is not None
            else quantize_val(0)
        )

        return [
            {
                "mes_referencia": datetime.date(
                    p_data_inicio.year, p_data_inicio.month, 1
                ),
                "total_creditos": quantize_val(0),
                "total_debitos": quantize_val(0),
                "saldo_consolidado": fallback_saldo,
                "qtd_transacoes": 0,
            }
        ]