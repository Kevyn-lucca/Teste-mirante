import datetime
import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

CENT = Decimal("0.01")
FOUR_PLACES = Decimal("0.0001")


def sp_processar_lote_taxas(conn: Connection, p_data_referencia: datetime.date) -> None:
    sql = text("""
        SELECT
            t.id,
            t.conta_origem_id,
            t.tipo,
            t.valor,
            tax.percentual,
            tax.valor_minimo
        FROM transacoes t
        LEFT JOIN LATERAL (
            SELECT percentual, valor_minimo
            FROM taxas
            WHERE tipo_operacao = t.tipo
              AND vigente_de <= CAST(:p_data_ref AS DATE)
              AND (vigente_ate IS NULL OR vigente_ate >= CAST(:p_data_ref AS DATE))
            ORDER BY vigente_de DESC
            LIMIT 1
        ) tax ON TRUE
        WHERE DATE(t.data_transacao) = CAST(:p_data_ref AS DATE)
          AND t.status = 'EFETIVADA'
          AND t.tipo <> 'TARIFA'
        ORDER BY t.id
    """)

    try:
        result = conn.execute(sql, {"p_data_ref": p_data_referencia})
        rows = result.fetchall()

        v_total_taxas = Decimal("0.00").quantize(CENT, rounding=ROUND_HALF_UP)
        v_count = 0

        for row in rows:
            v_id = row[0]
            v_origem = row[1]
            v_tipo = row[2]
            v_valor = Decimal(str(row[3])).quantize(CENT, rounding=ROUND_HALF_UP)
            v_percentual_raw = row[4]
            v_minimo_raw = row[5]

            if v_percentual_raw is None:
                continue

            v_percentual = Decimal(str(v_percentual_raw)).quantize(
                FOUR_PLACES, rounding=ROUND_HALF_UP
            )
            v_minimo = Decimal(str(v_minimo_raw)).quantize(
                CENT, rounding=ROUND_HALF_UP
            )

            calc_base = (v_valor * v_percentual / Decimal("100.0")).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
            v_taxa = max(calc_base, v_minimo).quantize(CENT, rounding=ROUND_HALF_UP)

            if v_tipo == "TRANSFERENCIA":
                v_taxa = v_taxa.quantize(CENT, rounding=ROUND_HALF_UP)
            elif v_tipo == "SAQUE":
                v_taxa = (v_taxa * Decimal("1.10")).quantize(
                    CENT, rounding=ROUND_HALF_UP
                )
            else:
                v_taxa = (v_taxa * Decimal("0.90")).quantize(
                    CENT, rounding=ROUND_HALF_UP
                )

            if v_origem is not None:
                update_conta_sql = text("""
                    UPDATE contas
                    SET saldo = saldo - CAST(:v_taxa AS NUMERIC(18, 2))
                    WHERE id = CAST(:v_origem AS BIGINT)
                """)
                conn.execute(
                    update_conta_sql, {"v_taxa": v_taxa, "v_origem": v_origem}
                )

                insert_trans_sql = text("""
                    INSERT INTO transacoes (conta_origem_id, tipo, valor, status)
                    VALUES (
                        CAST(:v_origem AS BIGINT),
                        'TARIFA',
                        CAST(:v_taxa AS NUMERIC(18, 2)),
                        'EFETIVADA'
                    )
                """)
                conn.execute(
                    insert_trans_sql, {"v_origem": v_origem, "v_taxa": v_taxa}
                )

                audit_sql = text("""
                    INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                    VALUES (
                        'transacoes',
                        CAST(:v_id AS BIGINT),
                        'TARIFA_APLICADA',
                        jsonb_build_object(
                            'transacao_origem', CAST(:v_id AS BIGINT),
                            'tipo_origem', CAST(:v_tipo AS TEXT),
                            'valor_origem', CAST(:v_valor AS NUMERIC(18, 2)),
                            'percentual', CAST(:v_percentual AS NUMERIC(7, 4)),
                            'taxa_aplicada', CAST(:v_taxa AS NUMERIC(18, 2))
                        )
                    )
                """)
                conn.execute(
                    audit_sql,
                    {
                        "v_id": v_id,
                        "v_tipo": v_tipo,
                        "v_valor": v_valor,
                        "v_percentual": v_percentual,
                        "v_taxa": v_taxa,
                    },
                )

                v_total_taxas = (v_total_taxas + v_taxa).quantize(
                    CENT, rounding=ROUND_HALF_UP
                )
                v_count += 1

        final_audit_sql = text("""
            INSERT INTO log_auditoria (entidade, acao, detalhes)
            VALUES (
                'lote_taxas',
                'LOTE_PROCESSADO',
                jsonb_build_object(
                    'data_referencia', CAST(:p_data_ref AS DATE),
                    'transacoes', CAST(:v_count AS INTEGER),
                    'total_taxas', CAST(:v_total_taxas AS NUMERIC(18, 2))
                )
            )
        """)
        conn.execute(
            final_audit_sql,
            {
                "p_data_ref": p_data_referencia,
                "v_count": v_count,
                "v_total_taxas": v_total_taxas,
            },
        )

    except Exception:
        logger.exception("Error processing rate batch for date %s", p_data_referencia)
        raise