import logging
from decimal import Decimal
from typing import Any, Optional
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def sp_transferir_entre_contas(
    conn: Any,
    audit_connection: Optional[Any],
    p_conta_origem: int,
    p_conta_destino: int,
    p_valor: Decimal,
) -> None:
    quant = Decimal("0.01")
    v_valor = Decimal(p_valor).quantize(quant) if p_valor is not None else None

    try:
        if v_valor is None or v_valor <= Decimal("0.00"):
            raise ValueError(f"Valor invalido para transferencia: {v_valor}")

        if p_conta_origem == p_conta_destino:
            raise ValueError("Conta de origem e destino nao podem ser iguais")

        origem_row = conn.execute(
            text(
                "SELECT saldo, status FROM contas WHERE id = :conta_id FOR UPDATE"
            ),
            {"conta_id": p_conta_origem},
        ).fetchone()

        destino_row = conn.execute(
            text("SELECT status FROM contas WHERE id = :conta_id FOR UPDATE"),
            {"conta_id": p_conta_destino},
        ).fetchone()

        v_saldo_origem: Optional[Decimal] = None
        v_status_origem: Optional[str] = None
        if origem_row is not None:
            v_saldo_origem = (
                Decimal(str(origem_row[0])).quantize(quant)
                if origem_row[0] is not None
                else None
            )
            v_status_origem = str(origem_row[1]) if origem_row[1] is not None else None

        v_status_destino: Optional[str] = None
        if destino_row is not None:
            v_status_destino = str(destino_row[0]) if destino_row[0] is not None else None

        if v_saldo_origem is None or v_status_origem is None:
            raise ValueError(f"Conta de origem {p_conta_origem} nao encontrada")

        if v_status_origem != "ATIVA" or v_status_destino != "ATIVA":
            raise ValueError("Ambas as contas precisam estar ATIVAS")

        if v_saldo_origem < v_valor:
            raise ValueError(f"Saldo insuficiente: saldo={v_saldo_origem} valor={v_valor}")

        conn.execute(
            text(
                "UPDATE contas SET saldo = saldo - :valor WHERE id = :conta_id"
            ),
            {"valor": v_valor, "conta_id": p_conta_origem},
        )

        conn.execute(
            text(
                "UPDATE contas SET saldo = saldo + :valor WHERE id = :conta_id"
            ),
            {"valor": v_valor, "conta_id": p_conta_destino},
        )

        conn.execute(
            text(
                """
                INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor)
                VALUES (:origem, :destino, 'TRANSFERENCIA', :valor)
                """
            ),
            {
                "origem": p_conta_origem,
                "destino": p_conta_destino,
                "valor": v_valor,
            },
        )

        conn.execute(
            text(
                """
                INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                VALUES (
                    'transacoes',
                    NULL,
                    'TRANSFERENCIA_OK',
                    jsonb_build_object(
                        'origem', CAST(:origem AS BIGINT),
                        'destino', CAST(:destino AS BIGINT),
                        'valor', CAST(:valor AS NUMERIC)
                    )
                )
                """
            ),
            {
                "origem": p_conta_origem,
                "destino": p_conta_destino,
                "valor": v_valor,
            },
        )

    except Exception as e:
        if audit_connection is not None:
            try:
                audit_connection.execute(
                    text(
                        """
                        INSERT INTO log_auditoria (entidade, acao, detalhes)
                        VALUES (
                            'transacoes',
                            'TRANSFERENCIA_ERRO',
                            jsonb_build_object(
                                'origem', CAST(:origem AS BIGINT),
                                'destino', CAST(:destino AS BIGINT),
                                'valor', CAST(:valor AS NUMERIC),
                                'erro', CAST(:erro AS TEXT)
                            )
                        )
                        """
                    ),
                    {
                        "origem": p_conta_origem,
                        "destino": p_conta_destino,
                        "valor": v_valor if v_valor is not None else Decimal("0.00"),
                        "erro": str(e),
                    },
                )
                audit_connection.commit()
            except SQLAlchemyError:
                logger.exception("Failed to write error audit log")
        raise