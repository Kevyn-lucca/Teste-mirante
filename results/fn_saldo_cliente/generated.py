from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.engine import Connection


def fn_saldo_cliente(conn: Connection, p_cliente_id: int) -> Decimal:
    query = text(
        """
        SELECT COALESCE(SUM(saldo), 0)
        FROM contas
        WHERE cliente_id = :p_cliente_id
          AND status = 'ATIVA'
        """
    )
    result = conn.execute(query, {"p_cliente_id": p_cliente_id}).scalar()
    v_total = Decimal(str(result if result is not None else 0))
    return v_total.quantize(Decimal("0.01"))