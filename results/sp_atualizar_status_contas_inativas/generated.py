import logging
from sqlalchemy import text

logger = logging.getLogger(__name__)


def sp_atualizar_status_contas_inativas(
    connection, p_dias: int
) -> int:
    try:
        if p_dias is None or p_dias <= 0:
            raise ValueError(
                f"Parametro p_dias deve ser positivo, recebido: {p_dias}"
            )

        update_sql = text(
            """
            UPDATE contas c
            SET status = 'INATIVA'
            WHERE c.status = 'ATIVA'
            AND NOT EXISTS (
                SELECT 1
                FROM transacoes t
                WHERE (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
                AND t.data_transacao >= NOW() - (CAST(:p_dias AS TEXT) || ' days')::INTERVAL
            )
            """
        )
        result = connection.execute(update_sql, {"p_dias": p_dias})
        p_afetadas = result.rowcount

        audit_sql = text(
            """
            INSERT INTO log_auditoria (entidade, acao, detalhes)
            VALUES (
                CAST(:entidade AS VARCHAR),
                CAST(:acao AS VARCHAR),
                jsonb_build_object(
                    'dias', CAST(:dias AS INTEGER),
                    'afetadas', CAST(:afetadas AS INTEGER)
                )
            )
            """
        )
        connection.execute(
            audit_sql,
            {
                "entidade": "contas",
                "acao": "INATIVACAO_LOTE",
                "dias": p_dias,
                "afetadas": p_afetadas,
            },
        )
        return p_afetadas
    except Exception:
        raise