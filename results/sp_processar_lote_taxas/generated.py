import datetime
import logging
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)


def sp_processar_lote_taxas(conn: Connection, p_data_referencia: datetime.date) -> None:
    try:
        query = text(
            """
            SELECT
                t.id,
                t.conta_origem_id,
                t.tipo,
                t.valor,
                tax.percentual,
                tax.valor_minimo
            FROM transacoes t
            LEFT JOIN LATERAL (
                th.percentual,
                th.valor_minimo
            ) AS tax ON TRUE
            LEFT JOIN LATERAL (
                SELECT percentual, valor_minimo
                FROM taxas
                WHERE tipo_operacao = t.tipo
                  AND vigente_de <= :p_data_referencia
                  AND (vigente_ate IS NULL OR vigente_ate >= :p_data_referencia)
                ORDER BY vigente_de DESC
                LIMIT 1
            ) th ON TRUE
            WHERE DATE(t.data_transacao) = :p_data_referencia
              AND t.status = 'EFETIVADA'
              AND t.tipo <> 'TARIFA'
            """
        )

        result = conn.execute(query, {"p_data_referencia": p_data_referencia})
        rows = result.fetchall()

        v_total_taxas = Decimal("0.00")
        v_count = 0

        for row in rows:
            v_id: int = row[0]
            v_origem: int | None = row[1]
            v_tipo: str = row[2]
            v_valor: Decimal = Decimal(str(row[3])).quantize(Decimal("0.01"))
            v_percentual: Decimal | None = row[4]
            v_minimo: Decimal | None = row[5]

            if v_percentual is None:
                continue

            v_percentual = Decimal(str(v_percentual)).quantize(Decimal("0.0001"))
            v_minimo = Decimal(str(v_minimo or "0.00")).quantize(Decimal("0.01"))

            v_taxa = v_valor * v_percentual / Decimal("100.0")
            if v_taxa < v_minimo:
                v_taxa = v_minimo
            v_taxa = v_taxa.quantize(Decimal("0.01"))

            if v_tipo == "TRANSFERENCIA":
                pass
            elif v_tipo == "SAQUE":
                v_taxa = (v_taxa * Decimal("1.10")).quantize(Decimal("0.01"))
            else:
                v_taxa = (v_taxa * Decimal("0.90")).quantize(Decimal("0.01"))

            if v_origem is not None:
                conn.execute(
                    text(
                        """
                        UPDATE contas
                        SET saldo = saldo - CAST(:v_taxa AS NUMERIC(18,2))
                        WHERE id = CAST(:v_origem AS BIGINT)
                        """
                    ),
                    {"v_taxa": v_taxa, "v_origem": v_origem},
                )

                conn.execute(
                    text(
                        """
                        INSERT INTO transacoes (conta_origem_id, tipo, valor, status)
                        VALUES (
                            CAST(:v_origem AS BIGINT),
                            CAST(:v_tipo AS VARCHAR(20)),
                            CAST(:v_taxa AS NUMERIC(18,2)),
                            CAST(:v_status AS VARCHAR(20))
                        )
                        """
                    ),
                    {
                        "v_origem": v_origem,
                        "v_tipo": "TARIFA",
                        "v_taxa": v_taxa,
                        "v_status": "EFETIVADA",
                    },
                )

                conn.execute(
                    text(
                        """
                        INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                        VALUES (
                            CAST(:entidade AS TEXT),
                            CAST(:entidade_id AS BIGINT),
                            CAST(:acao AS TEXT),
                            jsonb_build_object(
                                'transacao_origem', CAST(:transacao_origem AS BIGINT),
                                'tipo_origem', CAST(:tipo_origem AS TEXT),
                                'valor_origem', CAST(:valor_origem AS NUMERIC(18,2)),
                                'percentual', CAST(:percentual AS NUMERIC(7,4)),
                                'taxa_aplicada', CAST(:taxa_aplicada AS NUMERIC(18,2))
                            )
                        )
                        """
                    ),
                    {
                        "entidade": "transacoes",
                        "entidade_id": v_id,
                        "acao": "TARIFA_APLICADA",
                        "transacao_origem": v_id,
                        "tipo_origem": v_tipo,
                        "valor_origem": v_valor,
                        "percentual": v_percentual,
                        "taxa_aplicada": v_taxa,
                    },
                )

                v_total_taxas = (v_total_taxas + v_taxa).quantize(Decimal("0.01"))
                v_count += 1

        conn.execute(
            text(
                """
                INSERT INTO log_auditoria (entidade, acao, detalhes)
                VALUES (
                    CAST(:entidade AS TEXT),
                    CAST(:acao AS TEXT),
                    jsonb_build_object(
                        'data_referencia', CAST(:data_referencia AS DATE),
                        'transacoes', CAST(:transacoes AS INTEGER),
                        'total_taxas', CAST(:total_taxas AS NUMERIC(18,2))
                    )
                )
                """
            ),
            {
                "entidade": "lote_taxas",
                "acao": "LOTE_PROCESSADO",
                "data_referencia": p_data_referencia,
                "transacoes": v_count,
                "total_taxas": v_total_taxas,
            },
        )
    except Exception:
        logger.exception("Error processing batch fees for date %s", p_data_referencia)
        raise