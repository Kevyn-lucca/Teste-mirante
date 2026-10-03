from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any, Generator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

def _q182(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00").quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

def sp_extrato_diario_consolidado(
    conn: Any,
    audit_connection: Any,
    p_cliente_id: int,
    p_data_inicio: date,
    p_data_fim: date
) -> Generator[dict[str, Any], None, None]:
    v_saldo_inicial = Decimal("0.00")
    v_cliente_existe = False

    try:
        if p_data_inicio > p_data_fim:
            raise ValueError(f"Intervalo invalido: data_inicio ({p_data_inicio}) posterior a data_fim ({p_data_fim})")

        try:
            res_cliente = conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM clientes WHERE id = :cliente_id AND status = 'ATIVO'
                    )
                    """
                ),
                {"cliente_id": p_cliente_id}
            ).scalar()
            v_cliente_existe = bool(res_cliente)

            if not v_cliente_existe:
                raise ValueError(f"Cliente {p_cliente_id} nao encontrado ou inativo")

            res_saldo = conn.execute(
                text(
                    """
                    SELECT COALESCE(SUM(
                        CASE 
                            WHEN t.conta_destino_id = c.id THEN t.valor 
                            WHEN t.conta_origem_id = c.id THEN -t.valor 
                            ELSE 0 
                        END
                    ), 0)
                    FROM contas c
                    LEFT JOIN transacoes t ON (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
                        AND t.status = 'EFETIVADA'
                        AND t.data_transacao < :data_inicio
                    WHERE c.cliente_id = :cliente_id
                      AND c.status = 'ATIVA'
                    """
                ),
                {"cliente_id": p_cliente_id, "data_inicio": p_data_inicio}
            ).scalar()
            v_saldo_inicial = _q182(res_saldo)

        except Exception as inner_err:
            logger.warning("Falha na inicializacao dos saldos para o cliente %s: %s", p_cliente_id, inner_err)
            v_saldo_inicial = Decimal("0.00")

        audit_stmt = text(
            """
            INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
            VALUES (
                CAST(:entidade AS VARCHAR),
                CAST(:entidade_id AS BIGINT),
                CAST(:acao AS VARCHAR),
                CAST(:detalhes AS JSONB)
            )
            """
        )
        try:
            audit_connection.execute(
                audit_stmt,
                {
                    "entidade": "clientes",
                    "entidade_id": p_cliente_id,
                    "acao": "GERAR_EXTRATO_DIARIO",
                    "detalhes": f'{{"inicio": "{p_data_inicio}", "fim": "{p_data_fim}", "saldo_base_calculado": {v_saldo_inicial}}}'
                }
            )
            audit_connection.commit()
        except SQLAlchemyError as audit_err:
            logger.exception("Failed to write error audit: %s", audit_err)

        query = text(
            """
            WITH RECURSIVE calendario AS (
                SELECT CAST(:data_inicio AS DATE) AS dia
                UNION ALL
                SELECT (dia + INTERVAL '1 day')::DATE
                FROM calendario
                WHERE dia < CAST(:data_fim AS DATE)
            ),
            contas_cliente AS (
                SELECT id FROM contas WHERE cliente_id = CAST(:cliente_id AS BIGINT)
            ),
            movimento_diario AS (
                SELECT
                    t.data_transacao::DATE AS dia,
                    SUM(CASE WHEN t.conta_destino_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS creditos,
                    SUM(CASE WHEN t.conta_origem_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS debitos,
                    MAX(CASE WHEN t.conta_origem_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS maior_debito,
                    COUNT(t.id) AS qtd
                FROM transacoes t
                WHERE t.status = 'EFETIVADA'
                  AND t.data_transacao >= CAST(:data_inicio AS DATE)
                  AND t.data_transacao < (CAST(:data_fim AS DATE) + INTERVAL '1 day')
                  AND (
                      t.conta_origem_id IN (SELECT id FROM contas_cliente)
                      OR t.conta_destino_id IN (SELECT id FROM contas_cliente)
                  )
                GROUP BY 1
            ),
            balanco_diario AS (
                SELECT
                    c.dia,
                    COALESCE(m.creditos, 0) AS creditos,
                    COALESCE(m.debitos, 0) AS debitos,
                    (COALESCE(m.creditos, 0) - COALESCE(m.debitos, 0)) AS liquido,
                    COALESCE(m.maior_debito, 0) AS maior_saida,
                    COALESCE(m.qtd, 0)::INT AS qtd
                FROM calendario c
                LEFT JOIN movimento_diario m ON m.dia = c.dia
            )
            SELECT
                b.dia AS data_posicao,
                b.creditos AS creditos_dia,
                b.debitos AS debitos_dia,
                b.liquido AS fluxo_liquido,
                CAST(:saldo_inicial AS NUMERIC(18,2)) + SUM(b.liquido) OVER (
                    ORDER BY b.dia 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS saldo_final_dia,
                b.maior_saida,
                b.qtd AS qtd_operacoes
            FROM balanco_diario b
            ORDER BY b.dia;
            """
        )

        rows = conn.execute(
            query,
            {
                "data_inicio": p_data_inicio,
                "data_fim": p_data_fim,
                "cliente_id": p_cliente_id,
                "saldo_inicial": v_saldo_inicial
            }
        ).fetchall()

        for row in rows:
            yield {
                "data_posicao": row.data_posicao,
                "creditos_dia": _q182(row.creditos_dia),
                "debitos_dia": _q182(row.debitos_dia),
                "fluxo_liquido": _q182(row.fluxo_liquido),
                "saldo_final_dia": _q182(row.saldo_final_dia),
                "maior_saida": _q182(row.maior_saida),
                "qtd_operacoes": int(row.qtd_operacoes or 0),
            }

    except Exception as err:
        logger.warning("Erro critico na geracao do extrato diario do cliente %s: %s. Retornando linha de fallback.", p_cliente_id, err)
        yield {
            "data_posicao": p_data_inicio,
            "creditos_dia": _q182("0"),
            "debitos_dia": _q182("0"),
            "fluxo_liquido": _q182("0"),
            "saldo_final_dia": _q182(v_saldo_inicial),
            "maior_saida": _q182("0"),
            "qtd_operacoes": 0,
        }