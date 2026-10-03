import logging
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

class RelatorioMensalClienteRow(NamedTuple):
    mes_referencia: date
    total_creditos: Decimal
    total_debitos: Decimal
    saldo_consolidado: Decimal
    qtd_transacoes: int

def fn_saldo_cliente(connection: Connection, p_cliente_id: int) -> Decimal:
    query = text("SELECT fn_saldo_cliente(:p_cliente_id)")
    result = connection.execute(query, {"p_cliente_id": p_cliente_id}).scalar()
    if result is None:
        return Decimal("0.00")
    return Decimal(str(result)).quantize(Decimal("0.01"))

def sp_relatorio_mensal_cliente(
    connection: Connection,
    p_cliente_id: int,
    p_data_inicio: date,
    p_data_fim: date,
    audit_connection: Connection | None = None
) -> list[RelatorioMensalClienteRow]:
    v_saldo_atual = Decimal("0.00")
    try:
        if p_data_inicio > p_data_fim:
            raise ValueError(f"Periodo invalido: inicio {p_data_inicio} > fim {p_data_fim}")

        v_saldo_atual = fn_saldo_cliente(connection, p_cliente_id)
        logger.info("Saldo atual do cliente %s: %s", p_cliente_id, v_saldo_atual)

        query = text("""
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
                  AND t.data_transacao >= :p_data_inicio
                  AND t.data_transacao < CAST(:p_data_fim AS DATE) + INTERVAL '1 day'
                  AND (
                      t.conta_origem_id IN (SELECT id FROM contas WHERE cliente_id = :p_cliente_id)
                      OR t.conta_destino_id IN (SELECT id FROM contas WHERE cliente_id = :p_cliente_id)
                  )
                GROUP BY 1
            )
            SELECT
                m.mes AS mes_referencia,
                COALESCE(mv.creditos, 0) AS total_creditos,
                COALESCE(mv.debitos, 0) AS total_debitos,
                CAST(:v_saldo_atual AS NUMERIC(18,2)) + COALESCE(mv.creditos, 0)
                - COALESCE(mv.debitos, 0) AS saldo_consolidado,
                COALESCE(mv.qtd, 0)::INT AS qtd_transacoes
            FROM meses m
            LEFT JOIN movimento mv ON mv.mes = m.mes
            ORDER BY m.mes;
        """)

        result = connection.execute(
            query,
            {
                "p_cliente_id": p_cliente_id,
                "p_data_inicio": p_data_inicio,
                "p_data_fim": p_data_fim,
                "v_saldo_atual": v_saldo_atual,
            },
        )

        rows = []
        for row in result:
            mes_ref = row.mes_referencia
            if isinstance(mes_ref, datetime):
                mes_ref = mes_ref.date()
            
            creditos = Decimal(str(row.total_creditos or 0)).quantize(Decimal("0.01"))
            debitos = Decimal(str(row.total_debitos or 0)).quantize(Decimal("0.01"))
            saldo_cons = Decimal(str(row.saldo_consolidado or 0)).quantize(Decimal("0.01"))
            qtd = int(row.qtd_transacoes or 0)

            rows.append(
                RelatorioMensalClienteRow(
                    mes_referencia=mes_ref,
                    total_creditos=creditos,
                    total_debitos=debitos,
                    saldo_consolidado=saldo_cons,
                    qtd_transacoes=qtd,
                )
            )
        return rows

    except Exception as exc:
        if audit_connection is not None:
            try:
                audit_query = text(
                    "INSERT INTO auditoria_erros (rotina, mensagem, dados) VALUES (:rotina, :mensagem, :dados)"
                )
                audit_connection.execute(
                    audit_query,
                    {
                        "rotina": "sp_relatorio_mensal_cliente",
                        "mensagem": str(exc),
                        "dados": f"cliente_id={p_cliente_id}, inicio={p_data_inicio}, fim={p_data_fim}",
                    },
                )
                audit_connection.commit()
            except SQLAlchemyError:
                logger.exception("Failed to write error audit record")

        logger.warning("Falha ao gerar relatorio: %s. Retornando linha de fallback.", exc)
        
        fallback_mes = p_data_inicio.replace(day=1)
        fallback_creditos = Decimal("0.00").quantize(Decimal("0.01"))
        fallback_debitos = Decimal("0.00").quantize(Decimal("0.01"))
        fallback_saldo = v_saldo_atual.quantize(Decimal("0.01"))
        fallback_qtd = 0

        return [
            RelatorioMensalClienteRow(
                mes_referencia=fallback_mes,
                total_creditos=fallback_creditos,
                total_debitos=fallback_debitos,
                saldo_consolidado=fallback_saldo,
                qtd_transacoes=fallback_qtd,
            )
        ]