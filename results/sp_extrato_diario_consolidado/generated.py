import datetime
import logging
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def sp_extrato_diario_consolidado(
    conn: Connection,
    audit_connection: Connection,
    p_cliente_id: int,
    p_data_inicio: datetime.date,
    p_data_fim: datetime.date,
) -> list[tuple[datetime.date, Decimal, Decimal, Decimal, Decimal, Decimal, int]]:
    if p_data_inicio > p_data_fim:
        raise ValueError(
            f"Intervalo invalido: data_inicio ({p_data_inicio}) "
            f"posterior a data_fim ({p_data_fim})"
        )

    v_saldo_inicial = Decimal("0.00")

    try:
        try:
            res_cliente = conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM clientes
                        WHERE id = :cliente_id AND status = 'ATIVO'
                    )
                    """
                ),
                {"cliente_id": p_cliente_id},
            )
            v_cliente_existe = res_cliente.scalar()

            if not v_cliente_existe:
                raise ValueError(
                    f"Cliente {p_cliente_id} nao encontrado ou inativo"
                )

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
                    LEFT JOIN transacoes t ON (
                        t.conta_origem_id = c.id OR t.conta_destino_id = c.id
                    )
                    AND t.status = 'EFETIVADA'
                    AND t.data_transacao < :data_inicio
                    WHERE c.cliente_id = :cliente_id
                      AND c.status = 'ATIVA'
                    """
                ),
                {"cliente_id": p_cliente_id, "data_inicio": p_data_inicio},
            )
            raw_saldo = res_saldo.scalar()
            v_saldo_inicial = Decimal(
                str(raw_saldo if raw_saldo is not None else 0)
            ).quantize(Decimal("0.01"))

        except Exception as inner_err:
            logger.warning(
                "Falha na inicializacao dos saldos para o cliente %s: %s",
                p_cliente_id,
                inner_err,
            )
            v_saldo_inicial = Decimal("0.00").quantize(Decimal("0.01"))

        try:
            audit_connection.execute(
                text(
                    """
                    INSERT INTO log_auditoria (
                        entidade, entidade_id, acao, detalhes
                    )
                    VALUES (
                        CAST(:entidade AS TEXT),
                        CAST(:entidade_id AS BIGINT),
                        CAST(:acao AS TEXT),
                        jsonb_build_object(
                            'inicio', CAST(:inicio AS DATE),
                            'fim', CAST(:fim AS DATE),
                            'saldo_base_calculado',
                            CAST(:saldo_base AS NUMERIC(18,2))
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
            audit_connection.commit()
        except SQLAlchemyError as audit_err:
            logger.exception(
                "Falha ao gravar auditoria para cliente %s: %s",
                p_cliente_id,
                audit_err,
            )

        query = text(
            """
            WITH RECURSIVE calendario AS (
                SELECT CAST(:p_data_inicio AS DATE) AS dia
                UNION ALL
                SELECT (dia + INTERVAL '1 day')::DATE
                FROM calendario
                WHERE dia < CAST(:p_data_fim AS DATE)
            ),
            contas_cliente AS (
                SELECT id FROM contas WHERE cliente_id = :p_cliente_id
            ),
            movimento_diario AS (
                SELECT
                    t.data_transacao::DATE AS dia,
                    SUM(
                        CASE
                            WHEN t.conta_destino_id IN (
                                SELECT id FROM contas_cliente
                            ) THEN t.valor
                            ELSE 0
                        END
                    ) AS creditos,
                    SUM(
                        CASE
                            WHEN t.conta_origem_id IN (
                                SELECT id FROM contas_cliente
                            ) THEN t.valor
                            ELSE 0
                        END
                    ) AS debitos,
                    MAX(
                        CASE
                            WHEN t.conta_origem_id IN (
                                SELECT id FROM contas_cliente
                            ) THEN t.valor
                            ELSE 0
                        END
                    ) AS maior_debito,
                    COUNT(t.id) AS qtd
                FROM transacoes t
                WHERE t.status = 'EFETIVADA'
                  AND t.data_transacao >= CAST(:p_data_inicio AS DATE)
                  AND t.data_transacao < (
                      CAST(:p_data_fim AS DATE) + INTERVAL '1 day'
                  )
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
                    (
                        COALESCE(m.creditos, 0) - COALESCE(m.debitos, 0)
                    ) AS liquido,
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
                CAST(:v_saldo_inicial AS NUMERIC(18,2)) + SUM(b.liquido) OVER (
                    ORDER BY b.dia
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS saldo_final_dia,
                b.maior_saida,
                b.qtd AS qtd_operacoes
            FROM balanco_diario b
            ORDER BY b.dia
            """
        )

        result = conn.execute(
            query,
            {
                "p_data_inicio": p_data_inicio,
                "p_data_fim": p_data_fim,
                "p_cliente_id": p_cliente_id,
                "v_saldo_inicial": v_saldo_inicial,
            },
        )

        rows: list[
            tuple[
                datetime.date,
                Decimal,
                Decimal,
                Decimal,
                Decimal,
                Decimal,
                int,
            ]
        ] = []
        for row in result:
            r_dia: datetime.date = row.data_posicao
            r_creditos = Decimal(str(row.creditos_dia)).quantize(
                Decimal("0.01")
            )
            r_debitos = Decimal(str(row.debitos_dia)).quantize(
                Decimal("0.01")
            )
            r_liquido = Decimal(str(row.fluxo_liquido)).quantize(
                Decimal("0.01")
            )
            r_saldo_final = Decimal(str(row.saldo_final_dia)).quantize(
                Decimal("0.01")
            )
            r_maior_saida = Decimal(str(row.maior_saida)).quantize(
                Decimal("0.01")
            )
            r_qtd = int(row.qtd_operacoes)
            rows.append(
                (
                    r_dia,
                    r_creditos,
                    r_debitos,
                    r_liquido,
                    r_saldo_final,
                    r_maior_saida,
                    r_qtd,
                )
            )
        return rows

    except Exception as exc:
        logger.warning(
            "Erro critico na geracao do extrato diario do cliente %s: %s. "
            "Retornando linha de fallback.",
            p_cliente_id,
            exc,
        )
        safe_saldo = (
            v_saldo_inicial
            if v_saldo_inicial is not None
            else Decimal("0.00")
        ).quantize(Decimal("0.01"))
        zero_val = Decimal("0.00").quantize(Decimal("0.01"))
        return [
            (
                p_data_inicio,
                zero_val,
                zero_val,
                zero_val,
                safe_saldo,
                zero_val,
                0,
            )
        ]