from datetime import date
from decimal import Decimal, ROUND_HALF_UP
import logging
from typing import Any
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

TWO_PLACES = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def _quantize_money(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.00").quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _quantize_percent(value: Any) -> Decimal:
    if value is None:
        return Decimal("0.0000").quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)
    return Decimal(str(value)).quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


def sp_processar_lote_taxas(
    conn: Connection,
    audit_connection: Connection,
    p_data_referencia: date,
) -> None:
    v_total_taxas = _quantize_money(0)
    v_count = 0

    query = text(
        """
        SELECT 
            t.id, 
            t.conta_origem_id, 
            t.tipo, 
            t.valor,
            tx.percentual,
            tx.valor_minimo
        FROM transacoes t
        LEFT JOIN LATERAL (
            SELECT percentual, valor_minimo
            FROM taxas
            WHERE tipo_operacao = t.tipo
              AND vigente_de <= :p_data_referencia
              AND (vigente_ate IS NULL OR vigente_ate >= :p_data_referencia)
            ORDER BY vigente_de DESC
            LIMIT 1
        ) tx ON TRUE
        WHERE DATE(t.data_transacao) = :p_data_referencia
          AND t.status = 'EFETIVADA'
          AND t.tipo <> 'TARIFA'
        """
    )

    try:
        result = conn.execute(query, {"p_data_referencia": p_data_referencia})
        rows = result.fetchall()

        for row in rows:
            v_id = row.id
            v_origem = row.conta_origem_id
            v_tipo = row.tipo
            v_valor = _quantize_money(row.valor)
            v_percentual_raw = row.percentual
            v_minimo_raw = row.valor_minimo

            if v_percentual_raw is None:
                continue

            v_percentual = _quantize_percent(v_percentual_raw)
            v_minimo = _quantize_money(v_minimo_raw)

            calc_taxa = v_valor * v_percentual / Decimal("100.0")
            v_taxa = _quantize_money(max(calc_taxa, v_minimo))

            if v_tipo == "TRANSFERENCIA":
                v_taxa = _quantize_money(v_taxa)
            elif v_tipo == "SAQUE":
                v_taxa = _quantize_money(v_taxa * Decimal("1.10"))
            else:
                v_taxa = _quantize_money(v_taxa * Decimal("0.90"))

            if v_origem is not None:
                conn.execute(
                    text(
                        """
                        UPDATE contas 
                        SET saldo = saldo - CAST(:v_taxa AS NUMERIC) 
                        WHERE id = CAST(:v_origem AS BIGINT)
                        """
                    ),
                    {"v_taxa": v_taxa, "v_origem": v_origem},
                )

                conn.execute(
                    text(
                        """
                        INSERT INTO transacoes (conta_origem_id, tipo, valor, status)
                        VALUES (CAST(:v_origem AS BIGINT), 'TARIFA', CAST(:v_taxa AS NUMERIC), 'EFETIVADA')
                        """
                    ),
                    {"v_origem": v_origem, "v_taxa": v_taxa},
                )

                conn.execute(
                    text(
                        """
                        INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                        VALUES (
                            'transacoes',
                            CAST(:v_id AS BIGINT),
                            'TARIFA_APLICADA',
                            jsonb_build_object(
                                'transacao_origem', CAST(:v_id AS BIGINT),
                                'tipo_origem', CAST(:v_tipo AS TEXT),
                                'valor_origem', CAST(:v_valor AS NUMERIC),
                                'percentual', CAST(:v_percentual AS NUMERIC),
                                'taxa_aplicada', CAST(:v_taxa AS NUMERIC)
                            )
                        )
                        """
                    ),
                    {
                        "v_id": v_id,
                        "v_tipo": v_tipo,
                        "v_valor": v_valor,
                        "v_percentual": v_percentual,
                        "v_taxa": v_taxa,
                    },
                )

                v_total_taxas = _quantize_money(v_total_taxas + v_taxa)
                v_count += 1

        conn.execute(
            text(
                """
                INSERT INTO log_auditoria (entidade, acao, detalhes)
                VALUES (
                    'lote_taxas',
                    'LOTE_PROCESSADO',
                    jsonb_build_object(
                        'data_referencia', CAST(:p_data_referencia AS DATE),
                        'transacoes', CAST(:v_count AS INTEGER),
                        'total_taxas', CAST(:v_total_taxas AS NUMERIC)
                    )
                )
                """
            ),
            {
                "p_data_referencia": p_data_referencia,
                "v_count": v_count,
                "v_total_taxas": v_total_taxas,
            },
        )

    except Exception as e:
        try:
            audit_connection.execute(
                text(
                    """
                    INSERT INTO log_auditoria (entidade, acao, detalhes)
                    VALUES (
                        'lote_taxas',
                        'ERRO_PROCESSAMENTO',
                        jsonb_build_object(
                            'data_referencia', CAST(:p_data_referencia AS DATE),
                            'erro', CAST(:err_msg AS TEXT)
                        )
                    )
                    """
                ),
                {
                    "p_data_referencia": p_data_referencia,
                    "err_msg": str(e),
                },
            )
            audit_connection.commit()
        except SQLAlchemyError as audit_err:
            logger.exception("Failed to write error audit log: %s", audit_err)
        raise