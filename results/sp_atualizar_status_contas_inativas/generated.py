import logging

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

def sp_atualizar_status_contas_inativas(conn: Connection, p_dias: int) -> int:
    if p_dias is None or p_dias <= 0:
        raise ValueError(f"Parametro p_dias deve ser positivo, recebido: {p_dias}")

    update_stmt = text("""
        UPDATE contas c
        SET status = 'INATIVA'
        WHERE c.status = 'ATIVA'
        AND NOT EXISTS (
            SELECT 1
            FROM transacoes t
            WHERE (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
            AND t.data_transacao >= NOW() - (:p_dias || ' days')::INTERVAL
        )
    """)
    result = conn.execute(update_stmt, {"p_dias": p_dias})
    p_afetadas = result.rowcount

    audit_stmt = text("""
        INSERT INTO log_auditoria (entidade, acao, detalhes)
        VALUES (
            'contas',
            'INATIVACAO_LOTE',
            jsonb_build_object('dias', CAST(:p_dias AS INTEGER), 'afetadas', CAST(:p_afetadas AS INTEGER))
        )
    """)
    conn.execute(audit_stmt, {"p_dias": p_dias, "p_afetadas": p_afetadas})

    return p_afetadas