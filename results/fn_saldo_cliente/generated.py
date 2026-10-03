import logging
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import text
from sqlalchemy.engine import Connection

logger = logging.getLogger(__name__)

_SCALE_TWO = Decimal("0.01")


def fn_saldo_cliente(conn: Connection, p_cliente_id: int) -> Decimal:
    try:
        query = text(
            """
            SELECT COALESCE(SUM(saldo), 0)
            FROM contas
            WHERE cliente_id = :cliente_id
              AND status = 'ATIVA'
            """
        )
        result = conn.execute(query, {"cliente_id": p_cliente_id}).scalar()
        raw_val = result if result is not None else Decimal("0")
        return Decimal(str(raw_val)).quantize(_SCALE_TWO, rounding=ROUND_HALF_UP)
    except Exception:
        logger.exception("Error calculating balance for client ID %s", p_cliente_id)
        raise