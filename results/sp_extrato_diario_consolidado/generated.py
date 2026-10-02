import datetime
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

logger = logging.getLogger(__name__)


def sp_extrato_diario_consolidado(
    conn: Any,
    p_cliente_id: int,
    p_data_inicio: datetime.date,
    p_data_fim: datetime.date,
    audit_conn: Any | None = None,
) -> list[dict[str, Any]]:
    if p_data_inicio > p_data_fim:
        raise ValueError(
            f"Intervalo invalido: data_inicio ({p_data_inicio}) posterior a data_fim ({p_data_fim})"
        )

    v_saldo_inicial = Decimal("0.00")

    try:
        try:
            res_cliente = conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM clientes WHERE id = :cliente_id AND status = 'ATIVO'
                    )
                    """
                ),
                {"cliente_id": p_cliente_id},
            ).scalar()

            if not res_cliente:
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
                {"cliente_id": p_cliente_id, "data_inicio": p_data_inicio},
            ).scalar()

            v_saldo_inicial = Decimal(str(res_saldo or "0.00")).quantize(Decimal("0.01"))

        except (DBAPIError, SQLAlchemyError, ValueError) as inner_err:
            logger.warning(
                "Falha na inicializacao dos saldos para o cliente %s: %s",
                p_cliente_id,
                str(inner_err),
            )
            v_saldo_inicial = Decimal("0.00").quantize(Decimal("0.01"))

        if audit_conn is not None:
            try:
                audit_conn.execute(
                    text(
                        """
                        INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                        VALUES (
                            CAST(:entidade AS VARCHAR),
                            CAST(:entidade_id AS BIGINT),
                            CAST(:acao AS VARCHAR),
                            jsonb_build_object(
                                CAST('inicio' AS TEXT), CAST(:inicio AS DATE),
                                CAST('fim' AS TEXT), CAST(:fim AS DATE),
                                CAST('saldo_base_calculado' AS TEXT), CAST(:saldo_base AS NUMERIC)
                            )
                        )
                        """
                    ),
                    {
                        "entidade": "clientes",
                        "entidade_id": p_cliente_id,
                        "acao": "GERAR_EXTRATO_DIARIO",
                        "inicio": p_data_inicio,
                        "fim": p_data_fim,
                        "saldo_base": v_saldo_inicial,
                    },
                )
                audit_conn.commit()
            except SQLAlchemyError as audit_err:
                logger.exception("Failed to audit business transaction: %s", audit_err)

        rows = conn.execute(
            text(
                """
                WITH RECURSIVE calendario AS (
                    SELECT CAST(:p_data_inicio AS DATE) AS dia
                    UNION ALL
                    SELECT (dia + INTERVAL '1 day')::DATE
                    FROM calendario
                    WHERE dia < CAST(:p_data_fim AS DATE)
                ),
                contas_cliente AS (
                    SELECT id FROM contas WHERE cliente_id = CAST(:p_cliente_id AS BIGINT)
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
                      AND t.data_transacao >= CAST(:p_data_inicio AS DATE)
                      AND t.data_transacao < (CAST(:p_data_fim AS DATE) + INTERVAL '1 day')
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
                    CAST(:v_saldo_inicial AS NUMERIC) + SUM(b.liquido) OVER (
                        ORDER BY b.dia 
                        ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                    ) AS saldo_final_dia,
                    b.maior_saida,
                    b.qtd AS qtd_operacoes
                FROM balanco_diario b
                ORDER BY b.dia
                """
            ),
            {
                "p_cliente_id": p_cliente_id,
                "p_data_inicio": p_data_inicio,
                "p_data_fim": p_data_fim,
                "v_saldo_inicial": v_saldo_inicial,
            },
        ).mappings().all()

        result = []
        for r in rows:
            result.append(
                {
                    "data_posicao": r["data_posicao"],
                    "creditos_dia": Decimal(str(r["creditos_dia"])).quantize(Decimal("0.01")),
                    "debitos_dia": Decimal(str(r["debitos_dia"])).quantize(Decimal("0.01")),
                    "fluxo_liquido": Decimal(str(r["fluxo_liquido"])).quantize(Decimal("0.01")),
                    "saldo_final_dia": Decimal(str(r["saldo_final_dia"])).quantize(Decimal("0.01")),
                    "maior_saida": Decimal(str(r["maior_saida"])).quantize(Decimal("0.01")),
                    "qtd_operacoes": int(r["qtd_operacoes"]),
                }
            )
        return result

    except (DBAPIError, SQLAlchemyError, ValueError, TypeError) as err:
        logger.warning(
            "Erro critico na geracao do extrato diario do cliente %s: %s. Retornando linha de fallback.",
            p_cliente_id,
            str(err),
        )
        fallback_saldo = v_saldo_inicial if v_saldo_inicial is not None else Decimal("0.00")
        return [
            {
                "data_posicao": p_data_inicio,
                "creditos_dia": Decimal("0.00").quantize(Decimal("0.01")),
                "debitos_dia": Decimal("0.00").quantize(Decimal("0.01")),
                "fluxo_liquido": Decimal("0.00").quantize(Decimal("0.01")),
                "saldo_final_dia": Decimal(str(fallback_saldo)).quantize(Decimal("0.01")),
                "maior_saida": Decimal("0.00").quantize(Decimal("0.01")),
                "qtd_operacoes": 0,
            }
        ]