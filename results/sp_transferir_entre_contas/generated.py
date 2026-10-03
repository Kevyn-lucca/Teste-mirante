import logging
from decimal import Decimal

from sqlalchemy import Connection, text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)

NUMERIC_QUANTUM = Decimal("0.01")


def sp_transferir_entre_contas(
    conn: Connection,
    audit_conn: Connection,
    p_conta_origem: int,
    p_conta_destino: int,
    p_valor: Decimal | None,
) -> None:
    quantized_valor = (
        p_valor.quantize(NUMERIC_QUANTUM) if p_valor is not None else None
    )

    try:
        if quantized_valor is None or quantized_valor <= Decimal("0.00"):
            raise ValueError(f"Valor invalido para transferencia: {quantized_valor}")

        if p_conta_origem == p_conta_destino:
            raise ValueError("Conta de origem e destino nao podem ser iguais")

        origem_row = conn.execute(
            text(
                "SELECT saldo, status FROM contas WHERE id = :p_conta_origem FOR UPDATE"
            ),
            {"p_conta_origem": p_conta_origem},
        ).first()

        destino_row = conn.execute(
            text("SELECT status FROM contas WHERE id = :p_conta_destino FOR UPDATE"),
            {"p_conta_destino": p_conta_destino},
        ).first()

        v_saldo_origem = (
            origem_row[0].quantize(NUMERIC_QUANTUM)
            if origem_row and origem_row[0] is not None
            else None
        )
        v_status_origem = origem_row[1] if origem_row else None
        v_status_destino = destino_row[0] if destino_row else None

        if v_saldo_origem is None:
            raise ValueError(f"Conta de origem {p_conta_origem} nao encontrada")

        if v_status_origem != "ATIVA" or v_status_destino != "ATIVA":
            raise ValueError("Ambas as contas precisam estar ATIVAS")

        if v_saldo_origem < quantized_valor:
            raise ValueError(
                f"Saldo insuficiente: saldo={v_saldo_origem} valor={quantized_valor}"
            )

        conn.execute(
            text(
                "UPDATE contas SET saldo = saldo - CAST(:p_valor AS NUMERIC) WHERE id = :p_conta_origem"
            ),
            {"p_valor": quantized_valor, "p_conta_origem": p_conta_origem},
        )

        conn.execute(
            text(
                "UPDATE contas SET saldo = saldo + CAST(:p_valor AS NUMERIC) WHERE id = :p_conta_destino"
            ),
            {"p_valor": quantized_valor, "p_conta_destino": p_conta_destino},
        )

        conn.execute(
            text(
                "INSERT INTO transacoes (conta_origem_id, conta_destino_id, tipo, valor) "
                "VALUES (CAST(:p_conta_origem AS BIGINT), CAST(:p_conta_destino AS BIGINT), "
                "CAST(:p_tipo AS VARCHAR), CAST(:p_valor AS NUMERIC))"
            ),
            {
                "p_conta_origem": p_conta_origem,
                "p_conta_destino": p_conta_destino,
                "p_tipo": "TRANSFERENCIA",
                "p_valor": quantized_valor,
            },
        )

        conn.execute(
            text(
                "INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes) "
                "VALUES (CAST(:p_entidade AS VARCHAR), NULL, CAST(:p_acao AS VARCHAR), "
                "jsonb_build_object('origem', CAST(:p_origem AS BIGINT), "
                "'destino', CAST(:p_destino AS BIGINT), 'valor', CAST(:p_valor AS NUMERIC)))"
            ),
            {
                "p_entidade": "transacoes",
                "p_acao": "TRANSFERENCIA_OK",
                "p_origem": p_conta_origem,
                "p_destino": p_conta_destino,
                "p_valor": quantized_valor,
            },
        )

    except Exception as e:
        try:
            audit_conn.execute(
                text(
                    "INSERT INTO log_auditoria (entidade, acao, detalhes) "
                    "VALUES (CAST(:p_entidade AS VARCHAR), CAST(:p_acao AS VARCHAR), "
                    "jsonb_build_object('origem', CAST(:p_origem AS BIGINT), "
                    "'destino', CAST(:p_destino AS BIGINT), 'valor', CAST(:p_valor AS NUMERIC), "
                    "'erro', CAST(:p_erro AS TEXT)))"
                ),
                {
                    "p_entidade": "transacoes",
                    "p_acao": "TRANSFERENCIA_ERRO",
                    "p_origem": p_conta_origem,
                    "p_destino": p_conta_destino,
                    "p_valor": quantized_valor if quantized_valor is not None else Decimal("0.00"),
                    "p_erro": str(e),
                },
            )
            audit_conn.commit()
        except SQLAlchemyError:
            logger.exception("Failed to write error audit record")

        raise