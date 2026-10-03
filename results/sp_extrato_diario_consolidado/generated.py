import logging
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterator

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import SQLAlchemyError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExtratoDiarioConsolidadoRow:
    data_posicao: date
    creditos_dia: Decimal
    debitos_dia: Decimal
    fluxo_liquido: Decimal
    saldo_final_dia: Decimal
    maior_saida: Decimal
    qtd_operacoes: int


def sp_extrato_diario_consolidado(
    connection: Connection,
    audit_connection: Connection,
    p_cliente_id: int,
    p_data_inicio: date,
    p_data_fim: date,
) -> Iterator[ExtratoDiarioConsolidadoRow]:
    two_places = Decimal("0.01")
    v_saldo_inicial = Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP)

    try:
        if p_data_inicio > p_data_fim:
            raise ValueError(
                f"Intervalo invalido: data_inicio ({p_data_inicio}) posterior a data_fim ({p_data_fim})"
            )

        try:
            cliente_existe_stmt = text(
                "SELECT EXISTS (SELECT 1 FROM clientes WHERE id = :cliente_id AND status = 'ATIVO')"
            )
            v_cliente_existe = connection.scalar(
                cliente_existe_stmt, {"cliente_id": p_cliente_id}
            )

            if not v_cliente_existe:
                raise ValueError(f"Cliente {p_cliente_id} nao encontrado ou inativo")

            saldo_inicial_stmt = text(
                """
                SELECT COALESCE(SUM(
                    CASE 
                        WHEN t.conta_destino_id = c.id THEN t.valor 
                        WHEN t.conta_origem_id = c.id THEN -t.valor 
                        ELSE 0 
                    END
                ), 0)
                FROM contas c
                LEFT JOIN transacoes t ON (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
                    AND t.status = 'EFETIVADA'
                    AND t.data_transacao < :data_inicio
                WHERE c.cliente_id = :cliente_id
                  AND c.status = 'ATIVA'
                """
            )
            raw_saldo = connection.scalar(
                saldo_inicial_stmt,
                {"cliente_id": p_cliente_id, "data_inicio": p_data_inicio},
            )
            v_saldo_inicial = Decimal(str(raw_saldo if raw_saldo is not None else 0)).quantize(
                two_places, rounding=ROUND_HALF_UP
            )
        except Exception as inner_err:
            logger.warning(
                "Falha na inicializacao dos saldos para o cliente %s: %s",
                p_cliente_id,
                inner_err,
            )
            v_saldo_inicial = Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP)

        audit_stmt = text(
            """
            INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
            VALUES (
                'clientes',
                CAST(:entidade_id AS BIGINT),
                'GERAR_EXTRATO_DIARIO',
                jsonb_build_object(
                    'inicio', CAST(:inicio AS DATE),
                    'fim', CAST(:fim AS DATE),
                    'saldo_base_calculado', CAST(:saldo_base_calculado AS NUMERIC)
                )
            )
            """
        )
        audit_connection.execute(
            audit_stmt,
            {
                "entidade_id": p_cliente_id,
                "inicio": p_data_inicio,
                "fim": p_data_fim,
                "saldo_base_calculado": v_saldo_inicial,
            },
        )
        audit_connection.commit()

        query = text(
            """
            WITH RECURSIVE calendario AS (
                SELECT CAST(:p_data_inicio AS DATE) AS dia
                UNION ALL
                SELECT (dia + INTERVAL '1 day')::DATE
                FROM calendario
                WHERE dia < CAST(:p_data_fim AS DATE)
            ),
            contas_cliente AS (
                SELECT id FROM contas WHERE cliente_id = :p_cliente_id
            ),
            movimento_diario AS (
                SELECT
                    t.data_transacao::DATE AS dia,
                    SUM(CASE WHEN t.conta_destino_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS creditos,
                    SUM(CASE WHEN t.conta_origem_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS debitos,
                    MAX(CASE WHEN t.conta_origem_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS maior_debito,
                    COUNT(t.id) AS qtd
                FROM transacoes t
                WHERE t.status = 'EFETIVADA'
                  AND t.data_transacao >= CAST(:p_data_inicio AS DATE)
                  AND t.data_transacao < (CAST(:p_data_fim AS DATE) + INTERVAL '1 day')
                  AND (
                      t.conta_origem_id IN (SELECT id FROM contas_cliente)
                      OR t.conta_destino_id IN (SELECT id FROM contas_cliente)
                  )
                GROUP BY 1
            ),
            balanco_diario AS (
                SELECT
                    c.dia,
                    COALESCE(m.creditos, 0) AS creditos,
                    COALESCE(m.debitos, 0) AS debitos,
                    (COALESCE(m.creditos, 0) - COALESCE(m.debitos, 0)) AS liquido,
                    COALESCE(m.maior_debito, 0) AS maior_saida,
                    COALESCE(m.qtd, 0)::INT AS qtd
                FROM calendario c
                LEFT JOIN movimento_diario m ON m.dia = c.dia
            )
            SELECT
                b.dia AS data_posicao,
                b.creditos AS creditos_dia,
                b.debitos AS debitos_dia,
                b.liquido AS fluxo_liquido,
                CAST(:v_saldo_inicial AS NUMERIC(18,2)) + SUM(b.liquido) OVER (
                    ORDER BY b.dia 
                    ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
                ) AS saldo_final_dia,
                b.maior_saida,
                b.qtd AS qtd_operacoes
            FROM balanco_diario b
            ORDER BY b.dia
            """
        )

        result = connection.execute(
            query,
            {
                "p_cliente_id": p_cliente_id,
                "p_data_inicio": p_data_inicio,
                "p_data_fim": p_data_fim,
                "v_saldo_inicial": v_saldo_inicial,
            },
        )

        rows_found = False
        for row in result:
            rows_found = True
            yield ExtratoDiarioConsolidadoRow(
                data_posicao=row.data_posicao,
                creditos_dia=Decimal(str(row.creditos_dia)).quantize(two_places, rounding=ROUND_HALF_UP),
                debitos_dia=Decimal(str(row.debitos_dia)).quantize(two_places, rounding=ROUND_HALF_UP),
                fluxo_liquido=Decimal(str(row.fluxo_liquido)).quantize(two_places, rounding=ROUND_HALF_UP),
                saldo_final_dia=Decimal(str(row.saldo_final_dia)).quantize(two_places, rounding=ROUND_HALF_UP),
                maior_saida=Decimal(str(row.maior_saida)).quantize(two_places, rounding=ROUND_HALF_UP),
                qtd_operacoes=int(row.qtd_operacoes),
            )

        if not rows_found:
            yield ExtratoDiarioConsolidadoRow(
                data_posicao=p_data_inicio,
                creditos_dia=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
                debitos_dia=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
                fluxo_liquido=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
                saldo_final_dia=v_saldo_inicial.quantize(two_places, rounding=ROUND_HALF_UP),
                maior_saida=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
                qtd_operacoes=0,
            )

    except Exception as err:
        logger.warning(
            "Erro critico na geracao do extrato diario do cliente %s: %s. Retornando linha de fallback.",
            p_cliente_id,
            err,
        )
        try:
            fallback_audit = text(
                """
                INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
                VALUES (
                    'clientes',
                    CAST(:entidade_id AS BIGINT),
                    'ERRO_EXTRATO_DIARIO',
                    jsonb_build_object(
                        'inicio', CAST(:inicio AS DATE),
                        'fim', CAST(:fim AS DATE),
                        'erro', CAST(:erro AS TEXT)
                    )
                )
                """
            )
            audit_connection.execute(
                fallback_audit,
                {
                    "entidade_id": p_cliente_id,
                    "inicio": p_data_inicio,
                    "fim": p_data_fim,
                    "erro": str(err),
                },
            )
            audit_connection.commit()
        except SQLAlchemyError as audit_err:
            logger.exception("Falha ao registrar auditoria de erro: %s", audit_err)

        yield ExtratoDiarioConsolidadoRow(
            data_posicao=p_data_inicio,
            creditos_dia=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
            debitos_dia=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
            fluxo_liquido=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
            saldo_final_dia=v_saldo_inicial.quantize(two_places, rounding=ROUND_HALF_UP),
            maior_saida=Decimal("0.00").quantize(two_places, rounding=ROUND_HALF_UP),
            qtd_operacoes=0,
        )