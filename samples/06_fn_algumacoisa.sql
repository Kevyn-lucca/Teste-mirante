-- =============================================================
-- Anexo G: sp_extrato_diario_consolidado
-- Complexidade: Muito Alta
-- Recompõe o saldo diário histórico encadeado e métricas de risco.
-- Usa CTE recursiva temporal, Window Functions, Savepoints para
-- resiliência transacional e registra execução em log_auditoria.
-- =============================================================
CREATE OR REPLACE FUNCTION sp_extrato_diario_consolidado(
    p_cliente_id BIGINT,
    p_data_inicio DATE,
    p_data_fim DATE
)
RETURNS TABLE (
    data_posicao DATE,
    creditos_dia NUMERIC(18,2),
    debitos_dia NUMERIC(18,2),
    fluxo_liquido NUMERIC(18,2),
    saldo_final_dia NUMERIC(18,2),
    maior_saida NUMERIC(18,2),
    qtd_operacoes INT
)
LANGUAGE plpgsql
AS $$
DECLARE
    v_saldo_inicial NUMERIC(18,2);
    v_cliente_existe BOOLEAN;
BEGIN
    -- Validacao basica de parametros de intervalo
    IF p_data_inicio > p_data_fim THEN
        RAISE EXCEPTION 'Intervalo invalido: data_inicio (%) posterior a data_fim (%)', 
            p_data_inicio, p_data_fim;
    END IF;

    -- Bloco isolado para checagem de existencia e calculo do saldo base
    BEGIN
        SELECT EXISTS (
            SELECT 1 FROM clientes WHERE id = p_cliente_id AND status = 'ATIVO'
        ) INTO v_cliente_existe;

        IF NOT v_cliente_existe THEN
            RAISE EXCEPTION 'Cliente % nao encontrado ou inativo', p_cliente_id;
        END IF;

        -- Calcula o saldo acumulado antes do periodo solicitado (saldo inicial base)
        SELECT COALESCE(SUM(
            CASE 
                WHEN t.conta_destino_id = c.id THEN t.valor 
                WHEN t.conta_origem_id = c.id THEN -t.valor 
                ELSE 0 
            END
        ), 0)
        INTO v_saldo_inicial
        FROM contas c
        LEFT JOIN transacoes t ON (t.conta_origem_id = c.id OR t.conta_destino_id = c.id)
            AND t.status = 'EFETIVADA'
            AND t.data_transacao < p_data_inicio
        WHERE c.cliente_id = p_cliente_id
          AND c.status = 'ATIVA';

    EXCEPTION
        WHEN OTHERS THEN
            RAISE WARNING 'Falha na inicializacao dos saldos para o cliente %: %', p_cliente_id, SQLERRM;
            v_saldo_inicial := 0.00;
    END;

    -- Registra execucao do relatorio na tabela de auditoria
    INSERT INTO log_auditoria (entidade, entidade_id, acao, detalhes)
    VALUES (
        'clientes',
        p_cliente_id,
        'GERAR_EXTRATO_DIARIO',
        jsonb_build_object(
            'inicio', p_data_inicio,
            'fim', p_data_fim,
            'saldo_base_calculado', v_saldo_inicial
        )
    );

    -- Executa a consulta com CTE recursiva e Window Function
    RETURN QUERY
    WITH RECURSIVE calendario AS (
        -- Gerador de datas continuas para o periodo
        SELECT p_data_inicio AS dia
        UNION ALL
        SELECT (dia + INTERVAL '1 day')::DATE
        FROM calendario
        WHERE dia < p_data_fim
    ),
    contas_cliente AS (
        SELECT id FROM contas WHERE cliente_id = p_cliente_id
    ),
    movimento_diario AS (
        -- Agrupamento do fluxo diario de transacoes
        SELECT
            t.data_transacao::DATE AS dia,
            SUM(CASE WHEN t.conta_destino_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS creditos,
            SUM(CASE WHEN t.conta_origem_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS debitos,
            MAX(CASE WHEN t.conta_origem_id IN (SELECT id FROM contas_cliente) THEN t.valor ELSE 0 END) AS maior_debito,
            COUNT(t.id) AS qtd
        FROM transacoes t
        WHERE t.status = 'EFETIVADA'
          AND t.data_transacao >= p_data_inicio
          AND t.data_transacao < (p_data_fim + INTERVAL '1 day')
          AND (
              t.conta_origem_id IN (SELECT id FROM contas_cliente)
              OR t.conta_destino_id IN (SELECT id FROM contas_cliente)
          )
        GROUP BY 1
    ),
    balanco_diario AS (
        -- Consolida os dias sem movimento (LEFT JOIN) e calcula o fluxo liquido
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
        -- Window function com soma acumulada a partir do saldo inicial
        v_saldo_inicial + SUM(b.liquido) OVER (
            ORDER BY b.dia 
            ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS saldo_final_dia,
        b.maior_saida,
        b.qtd AS qtd_operacoes
    FROM balanco_diario b
    ORDER BY b.dia;

EXCEPTION
    WHEN OTHERS THEN
        RAISE WARNING 'Erro critico na geracao do extrato diario do cliente %: %. Retornando linha de fallback.', 
            p_cliente_id, SQLERRM;
        RETURN QUERY
        SELECT
            p_data_inicio,
            0::NUMERIC(18,2),
            0::NUMERIC(18,2),
            0::NUMERIC(18,2),
            COALESCE(v_saldo_inicial, 0),
            0::NUMERIC(18,2),
            0::INT;
END;
$$;