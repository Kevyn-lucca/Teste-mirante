import logging
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


def sp_transferir_entre_contas(
    conn,
    audit_conn,
    p_conta_origem: int,
    p_conta_destino: int,
    p_valor: Decimal,
) -> None:
    q_valor = Decimal(p_valor).quantize(Decimal("0.01"))
    try:
        if q_valor is None or q_valor <= 0:
            raise ValueError(f"Valor invalido para transferencia: {q_valor}")
        if p_conta_origem == p_conta_destino:
            raise ValueError("Conta de origem e destino nao podem ser iguais")

        origem_row = conn.execute(
            text(
                "SELECT saldo, status FROM contas "
                "WHERE id = :p_conta_origem FOR UPDATE"
            ),
            {"p_conta_origem": p_conta_origem},
        ).first()

        v_saldo_origem = (
            Decimal(origem_row[0]).quantize(Decimal("0.01"))
            if origem_row and origem_row[0] is not None
            else None
        )
        v_status_origem = origem_row[1] if origem_row else None

        destino_row = conn.execute(
            text(
                "SELECT status FROM contas "
                "WHERE id = :p_conta_destino FOR UPDATE"
            ),
            {"p_conta_destino": p_conta_destino},
        ).first()

        v_status_destino = destino_row[0] if destino_row else None

        if v_saldo_origem is None:
            raise ValueError(f"Conta de origem {p_conta_origem} nao encontrada")

        if v_status_origem != "ATIVA" or v_status_destino != "ATIVA":
            raise ValueError("Ambas as contas precisam estar ATIVAS")

        if v_saldo_origem < q_valor:
            raise ValueError(
                f"Saldo insuficiente: saldo={v_saldo_origem} valor={q_valor}"
            )

        conn.execute(
            text(
                "UPDATE contas SET saldo = saldo - :p_valor "
                "WHERE id = :p_conta_origem"
            ),
            {"p_valor": q_valor, "p_conta_origem": p_conta_origem},
        )
        conn.execute(
            text(
                "UPDATE contas SET saldo = saldo + :p_valor "
                "WHERE id = :p_conta_destino"
            ),
            {"p_valor": q_valor, "p_conta_destino": p_conta_destino},
        )
        conn.execute(
            text(
                "INSERT INTO transacoes "
                "(conta_origem_id, conta_destino_id, tipo, valor) "
                "VALUES (:p_conta_origem, :p_conta_destino, "
                "'TRANSFERENCIA', :p_valor)"
            ),
            {
                "p_conta_origem": p_conta_origem,
                "p_conta_destino": p_conta_destino,
                "p_valor": q_valor,
            },
        )
        conn.execute(
            text(
                "INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes) "
                "VALUES ("
                "'transacoes', "
                "NULL, "
                "'TRANSFERENCIA_OK', "
                "jsonb_build_object("
                "'origem', CAST(:p_conta_origem AS BIGINT), "
                "'destino', CAST(:p_conta_destino AS BIGINT), "
                "'valor', CAST(:p_valor AS NUMERIC)"
                ")"
                ")"
            ),
            {
                "p_conta_origem": p_conta_origem,
                "p_conta_destino": p_conta_destino,
                "p_valor": q_valor,
            },
        )
    except Exception as e:
        try:
            audit_conn.execute(
                text(
                    "INSERT INTO log_auditoria (entidade, acao, detalhes) "
                    "VALUES ("
                    "'transacoes', "
                    "'TRANSFERENCIA_ERRO', "
                    "jsonb_build_object("
                    "'origem', CAST(:p_conta_origem AS BIGINT), "
                    "'destino', CAST(:p_conta_destino AS BIGINT), "
                    "'valor', CAST(:p_valor AS NUMERIC), "
                    "'erro', CAST(:p_erro AS TEXT)"
                    ")"
                    ")"
                ),
                {
                    "p_conta_origem": p_conta_origem,
                    "p_conta_destino": p_conta_destino,
                    "p_valor": q_valor,
                    "p_erro": str(e),
                },
            )
            audit_conn.commit()
        except SQLAlchemyError:
            logger.exception("Failed to write error audit log")
        raise