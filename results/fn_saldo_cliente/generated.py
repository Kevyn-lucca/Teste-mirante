import logging
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import Connection, text

logger = logging.getLogger(__name__)


def fn_saldo_cliente(conn: Connection, p_cliente_id: int) -> Decimal:
    try:
        stmt = text(
            """
            SELECT COALESCE(SUM(saldo), 0)
            FROM contas
            WHERE cliente_id = :cliente_id
              AND status = 'ATIVA'
            """
        )
        result: Any = conn.execute(stmt, {"cliente_id": p_cliente_id}).scalar()
        raw_val = Decimal(str(result if result is not None else 0))
        return raw_val.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    except Exception:
        logger.exception("Error executing fn_saldo_cliente for cliente_id %s", p_cliente_id)
        raise