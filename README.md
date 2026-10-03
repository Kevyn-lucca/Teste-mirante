# Modernizer: Migração Automatizada de PL/pgSQL para Python

![Python Version](https://img.shields.io/badge/python-%3E%3D3.14-blue)
![FastAPI](https://img.shields.io/badge/FastAPI-%3E%3D0.142.2-009688)
![LangGraph](https://img.shields.io/badge/LangGraph-%3E%3D1.2.12-orange)

> **Projeto desenvolvido como parte de entrevista técnica.**
> Sistema de conversão automatizada de stored procedures PostgreSQL (PL/pgSQL) para código Python pronto para produção, usando agentes LLM com validação estática, retry automático e observabilidade completa.

## Sobre o Projeto

Este sistema demonstra a aplicação prática de **arquitetura multi-agente baseada em grafos** para resolver um problema real de engenharia: migrar lógica de negócio legada do banco de dados para código Python testável e escalável.

## Índice

- [Sobre o Projeto](#sobre-o-projeto)
- [Arquitetura do Sistema](#arquitetura-do-sistema)
- [Instalação Rápida](#instalação-rápida)
- [Acesso ao Banco de Dados](#acesso-ao-banco-de-dados)
- [Testes Unitários](#testes-unitários)
- [Funcionalidades](#funcionalidades)
- [API Endpoints](#api-endpoints)
- [Métricas de Avaliação](#métricas-de-avaliação)
- [Observabilidade com Langfuse](#observabilidade-com-langfuse)
- [Estrutura de Pastas](#estrutura-de-pastas)

---

## Arquitetura do Sistema

### Visão Geral: Multi-Agent Graph Architecture

O sistema utiliza **LangGraph** para orquestrar um pipeline de 6 agentes especializados com retry condicional:

<!-- GRAPH:START -->

```mermaid
---
config:
  flowchart:
    curve: linear
---
graph TD;
	__start__([<p>__start__</p>]):::first
	parse(parse)
	analyze(analyze)
	generate(generate)
	validate(validate)
	persist(persist)
	evaluate(evaluate)
	__end__([<p>__end__</p>]):::last
	__start__ --> parse;
	analyze --> generate;
	generate --> validate;
	parse -.-> analyze;
	parse -.-> persist;
	persist --> evaluate;
	validate -.-> generate;
	validate -.-> persist;
	evaluate --> __end__;
	classDef default fill:#f2f0ff,line-height:1.2
	classDef first fill-opacity:0
	classDef last fill:#bfb6fc

```

<!-- GRAPH:END -->

### Fluxo de Execução

```mermaid
sequenceDiagram
    participant Client
    participant API
    participant Parse
    participant Analyze
    participant Generate
    participant Validate
    participant Persist
    participant Langfuse

    Client->>API: POST /modernize
    API->>Parse: source_code + schema
    Parse->>Analyze: AST + features
    Analyze->>Generate: semantic risks
    Generate->>Validate: Python code

    alt Validation Failed (< 3 attempts)
        Validate-->>Generate: error feedback
        Generate->>Validate: retry with fixes
    else Validation Success
        Validate->>Persist: store results
    end

    Persist->>Langfuse: traces + metrics
    Persist->>API: response
    API->>Client: generated code + report
```

### Componentes e Responsabilidades

| Nó           | Entrada         | Saída          | Tecnologia          | Propósito                                               |
| ------------ | --------------- | -------------- | ------------------- | ------------------------------------------------------- |
| **Parse**    | SQL bruto       | AST + features | `pglast`            | Extrai estrutura e identifica construções críticas      |
| **Analyze**  | AST estruturada | Risk mapping   | LLM (Gemini)        | Mapeia riscos semânticos e gera diretrizes de conversão |
| **Generate** | Risks + schema  | Python code    | LLM (Gemini)        | Gera código Python com SQLAlchemy parametrizado         |
| **Validate** | Python code     | Issues list    | `ast.parse` + Ruff  | Valida sintaxe e aplica linter                          |
| **Persist**  | Full state      | history_id     | PostgreSQL          | Armazena histórico e artefatos                          |
| **Evaluate** | Full state      | Metrics        | Algoritmo ponderado | Calcula quality score                                   |

## Instalação Rápida

### Pré-requisitos

- Python 3.14+
- [uv](https://github.com/astral-sh/uv) (gerenciador de dependências)
- Docker
- Chave de API do Google Gemini, especificamente gemini-3.5-flash-lite ([obter aqui](https://aistudio.google.com/app/apikey))

### Setup Completo

**1. Clone e instale as dependências**

```bash
git clone https://github.com/Kevyn-lucca/Teste-mirante.git
cd Teste-mirante
uv sync
```

**2. Configure as variáveis de ambiente**

```bash
cp .env.example .env
# Edite o .env e adicione sua GOOGLE_API_KEY
```

Variáveis necessárias:

```ini
GOOGLE_API_KEY=sua-chave-gemini-aqui
MODEL_NAME=google_genai:gemini-3.5-flash-lite
DATABASE_URL=postgresql://modernizer:modernizer@localhost:5432/modernizer
LANGFUSE_PUBLIC_KEY=pk-lf-local
LANGFUSE_SECRET_KEY=sk-lf-local
LANGFUSE_BASE_URL=http://localhost:3000
```

Os valores de `LANGFUSE_PUBLIC_KEY` e `LANGFUSE_SECRET_KEY` acima são os padrões do `docker-compose.yml` e servem apenas para uso local. Em qualquer outro ambiente, defina chaves próprias no `.env`. Dentro dos containers, o compose sobrescreve `DATABASE_URL` e `LANGFUSE_BASE_URL` para apontar para os serviços internos, então esses dois valores do `.env` só importam quando você roda o código fora do Docker.

**3. Inicie a infraestrutura**

```bash
docker compose up -d --build
# Aguarde cerca de 30s para a inicialização completa
```

Este comando sobe todos os serviços:

| Serviço        | Endereço local        | Função                       |
| -------------- | --------------------- | ---------------------------- |
| `langgraph`    | http://localhost:8123 | API do Modernizer            |
| `postgres`     | localhost:5432        | Banco de dados do Modernizer |
| `langfuse-web` | http://localhost:3000 | Interface do Langfuse        |

Os demais serviços (`langfuse-worker`, `langfuse-postgres`, `langfuse-clickhouse` e `langfuse-redis`) são internos e não expõem porta.

O Langfuse é inicializado automaticamente no primeiro start, com organização, projeto e chaves já criados. Para ver os traces, acesse http://localhost:3000 e entre com o usuário local:

- E-mail: `admin@local.test`
- Senha: `admin-local-123`

Essas credenciais e as chaves padrão são apenas para demonstração local e devem ser trocadas fora desse contexto.

**4. Teste com exemplos**

```bash
# Em outro terminal
uv run python testes.py --samples 01 02 03
```

### Verificação Rápida

```bash
# Health check
curl http://localhost:8123/health

# Modernizar uma procedure
curl -X POST http://localhost:8123/modernize \
  -H "Content-Type: application/json" \
  -d '{
    "source_code": "CREATE FUNCTION fn_teste() RETURNS INT AS $$ BEGIN RETURN 42; END; $$ LANGUAGE plpgsql;",
    "schema_sql": null
  }'
```

### CLI de teste ponta a ponta

Ferramenta para executar múltiplas amostras contra o servidor:

```bash
# Executar todas as samples
uv run python testes.py

# Executar apenas as selecionadas
uv run python testes.py --samples 01 03 05

# Executar em paralelo
uv run python testes.py --concurrency 3

# Usar servidor customizado
uv run python testes.py --url http://production-server:8000/modernize
```

---

## Acesso ao Banco de Dados

O histórico das modernizações fica no PostgreSQL do serviço `postgres`, definido no `docker-compose.yml`. A porta é publicada apenas em `127.0.0.1`, então o banco só é acessível pela própria máquina.

### Dados de conexão

| Parâmetro | Valor                                     |
| --------- | ----------------------------------------- |
| Host      | `localhost`                               |
| Porta     | `5432` (configurável com `POSTGRES_PORT`) |
| Banco     | `modernizer`                              |
| Usuário   | `modernizer`                              |
| Senha     | `modernizer`                              |

String de conexão completa:

```
postgresql://modernizer:modernizer@localhost:5432/modernizer
```

Se a porta 5432 já estiver ocupada por outro PostgreSQL na sua máquina, defina outra porta no `.env` e suba o compose novamente:

```ini
POSTGRES_PORT=5433
```

Em clientes gráficos como DBeaver, pgAdmin ou DataGrip, crie uma conexão PostgreSQL com os dados da tabela acima.

O Langfuse usa um PostgreSQL separado (`langfuse-postgres`), que não é exposto para fora do Docker e não precisa ser acessado.

---

## Testes Unitários

Os testes unitários utilizam `pytest` e cobrem API, parsing de AST, pipeline em grafo e validação do código gerado:

```bash
# Executar todos os testes
uv run pytest

# Executar com cobertura
uv run pytest --cov=src/modernizer
```

Para checagem de tipos estáticos com MyPy e linter com Ruff:

```bash
uv run mypy src
uv run ruff check src
```

## Funcionalidades

### Parsing de PL/pgSQL

Analisa o código fonte SQL com `pglast.parse_sql` e `pglast.parse_plpgsql`, extraindo nome da rotina, tipo (function ou procedure), parâmetros e tipos de retorno, e identificando recursos sintáticos críticos como cursores, blocos EXCEPTION e CTE recursivo.

### Análise Semântica e Mapeamento de Riscos

Examina os recursos identificados na AST e gera um relatório estruturado com diretrizes de tradução para cada padrão procedural encontrado, como conversão de cursores em lote para evitar consultas N+1 e isolamento de conexão em auditoria de exceções.

### Geração de Código Python com LLM

Constrói um prompt contextualizado com as regras gerais de migração, o esquema da tabela, a assinatura e os riscos mapeados, instruindo o modelo a gerar código Python 3.14 com SQLAlchemy parametrizado e manipulação monetária com Decimal.

### Validação Estática e Autocorreção

Verifica o código gerado em duas etapas: validação de sintaxe via `ast.parse` e análise de conformidade com `ruff check` (regras E, F, I, S110). Aplica autocorreção segura de importações não utilizadas e ordenação antes de reportar problemas.

### Persistência de Histórico de Modernização

Armazena o código fonte original, o código Python resultante, o status da execução e o relatório detalhado em formato JSONB na tabela `modernization_history` do PostgreSQL.

### Exportação de Artefatos de Execução

Salva em disco, na pasta `results/<nome_rotina>/`, os arquivos `generated.py` e `report.json` correspondentes, além de manter consolidado o arquivo `results/summary.json` com o status de todas as execuções.

### Avaliação de Qualidade e Métricas

Calcula métricas compostas de conclusão, conformidade sintática, conformidade de linter e eficiência por tentativa, enviando as pontuações diretamente para o Langfuse quando configurado.

### Observabilidade e Rastreamento com Langfuse

Integra tracing assíncrono com LangChain CallbackHandler para registrar a árvore de execução dos nós, as chamadas a LLMs, os tempos de resposta e os scores vinculados a cada sessão de modernização.

## API Endpoints

### `GET /health`

Verifica a disponibilidade do serviço.

Resposta:

```json
{
  "status": "ok"
}
```

### `POST /modernize`

Processa a conversão de uma rotina PL/pgSQL para Python.

Requisição:

```json
{
  "source_code": "CREATE OR REPLACE FUNCTION fn_saldo_cliente(p_cliente_id INT) RETURNS NUMERIC AS $$ ... $$ LANGUAGE plpgsql;",
  "schema_sql": "CREATE TABLE contas (id INT, cliente_id INT, saldo NUMERIC(15,2));"
}
```

Resposta:

```json
{
  "generated_code": "from decimal import Decimal\nfrom sqlalchemy import text\n\ndef fn_saldo_cliente(connection, p_cliente_id: int) -> Decimal:\n    ...",
  "report": {
    "parsing": {
      "status": "sucesso",
      "routine": "fn_saldo_cliente",
      "kind": "function"
    },
    "analysis": { "status": "sucesso", "risk_count": 0, "risks": [] },
    "generation": { "status": "sucesso", "attempt": 1 },
    "validation": {
      "status": "sucesso",
      "issues": [],
      "autofixes_applied": false
    },
    "persistence": {
      "status": "sucesso",
      "history_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
    },
    "evaluation": {
      "quality_score": 1.0,
      "status_success": 1.0,
      "ast_parse_ok": 1.0,
      "lint_clean": 1.0,
      "first_attempt_pass": 1.0,
      "attempts": 1.0
    }
  },
  "status": "sucesso",
  "history_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "evaluation": {
    "quality_score": 1.0,
    "status_success": 1.0,
    "ast_parse_ok": 1.0,
    "lint_clean": 1.0,
    "first_attempt_pass": 1.0,
    "attempts": 1.0
  },
  "trace_id": "018f3a2b-c4d5-7e8f-9012-3456789abcde"
}
```

### `GET /evaluation/run`

Observa a última bateria de testes e retorna o resumo estatístico de desempenho.

Resposta:

```json
{
  "summary": {
    "procedures": 5,
    "avg_quality_score": 1.0,
    "completion_rate": 1.0,
    "ast_parse_rate": 1.0,
    "lint_clean_rate": 1.0,
    "first_attempt_rate": 1.0,
    "avg_attempts": 1.0
  },
  "results": [
    {
      "name": "01_fn_saldo_cliente",
      "status": "sucesso",
      "attempts": 1.0,
      "quality_score": 1.0
    }
  ]
}
```

## Métricas de Avaliação

Cada execução recebe uma nota de qualidade (`quality_score`) entre 0 e 1, calculada a partir de três critérios com pesos diferentes:

| Critério                  | Peso | O que mede                                                                                                                                     |
| ------------------------- | ---- | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| Status do pipeline        | 25%  | Vale 1 quando o pipeline termina com sucesso e 0 caso contrário.                                                                               |
| Lint                      | 35%  | Vale 1 quando o código gerado passa na validação estática sem erros (`lint_clean`) e 0 caso contrário.                                         |
| Eficiência por tentativas | 40%  | Premia quem acerta nas primeiras tentativas. Uma tentativa vale 1, e cada retry reduz a nota até chegar a 0 na última tentativa permitida (3). |

Na prática, um código que passa de primeira, sem erros de lint, recebe 1.0. Um código que precisa de retry perde parte dos 40% da eficiência, mesmo que depois seja aprovado.

Além da nota final, cada execução registra métricas individuais, que também são enviadas ao Langfuse:

| Métrica                   | Significado                                      |
| ------------------------- | ------------------------------------------------ |
| `completed_without_error` | O pipeline terminou sem exceções.                |
| `status_success`          | O status final da modernização foi sucesso.      |
| `ast_parse_ok`            | O código Python gerado tem sintaxe válida.       |
| `lint_clean`              | O código gerado passou no Ruff sem apontamentos. |
| `first_attempt_pass`      | O código foi aprovado na primeira tentativa.     |
| `attempts`                | Número de tentativas executadas, de 1 a 3.       |
| `quality_score`           | Nota final ponderada, entre 0 e 1.               |

A rota `GET /evaluation/run` calcula a média dessas métricas sobre todas as procedures avaliadas.

## Observabilidade com Langfuse

Cada execução do pipeline gera um trace no Langfuse, acessível em http://localhost:3000 após subir o `docker compose`. Os prints abaixo mostram o que é registrado.

### Visão geral de uma execução completa

![Visão geral de uma execução completa no Langfuse](docs/screenshots/fulluse.png)

### Tracing dos nós do pipeline

Mostra cada nó do grafo (parse, analyze, generate, validate, persist, evaluate), as chamadas ao LLM e o tempo de cada etapa.

![Tracing dos nós do pipeline](docs/screenshots/tracing.png)

### Scores de qualidade

Métricas enviadas pelo nó evaluate: quality_score, lint_clean, ast_parse_ok e first_attempt_pass.

![Scores de qualidade no Langfuse](docs/screenshots/scores.png)

## Estrutura de Pastas

```
Teste-mirante/
|-- db/
|   `-- init/
|       `-- 001_historia.sql       # Script de inicialização da tabela de histórico
|-- docs/
|   |-- graph.mmd                  # Definição Mermaid do grafo compilado
|   `-- screenshots/               # Imagens de telas e observabilidade
|-- results/                       # Artefatos exportados por rotina gerada
|   `-- summary.json               # Consolidado de execuções
|-- samples/                       # Stored procedures e funções PL/pgSQL de teste
|   |-- 00_schema.sql              # Estrutura das tabelas bancárias de exemplo
|   |-- 01_fn_saldo_cliente.sql
|   |-- 02_sp_atualizar_status_contas_inativas.sql
|   |-- 03_sp_transferir_entre_contas.sql
|   |-- 04_sp_processar_lote_taxas.sql
|   |-- 05_sp_relatorio_mensal_cliente.sql
|   `-- 06_fn_algumacoisa.sql
|-- src/
|   `-- modernizer/
|       |-- analysis/              # Análise semântica e detecção de riscos
|       |-- api/                   # Aplicação FastAPI e endpoints
|       |-- evaluation/            # Cálculo de notas e envio de métricas
|       |-- generation/            # Prompts e chamada ao modelo de linguagem
|       |-- graph/                 # StateGraph e definições de estado
|       |-- nodes/                 # Nós de execução do pipeline LangGraph
|       |-- observability/         # Integração de tracing com Langfuse
|       |-- parsing/               # Análise sintática com pglast
|       |-- persistence/           # Conexão PostgreSQL e gravação de histórico
|       |-- validation/            # Checagem com AST e linter Ruff
|       |-- artifacts.py           # Gravação de arquivos de saída em results/
|       `-- config.py              # Configurações via Pydantic Settings
|-- tests/
|   `-- unit/                      # Testes unitários do sistema
|-- docker-compose.yml             # Serviços PostgreSQL, Redis, MinIO, ClickHouse e Langfuse
|-- Dockerfile                     # Imagem de produção do Modernizer
|-- exporta_graph.py               # Script para sincronizar o grafo Mermaid no README
|-- langgraph.json                 # Configuração do servidor LangGraph
|-- pyproject.toml                 # Manifesto de dependências do projeto
`-- testes.py                      # Script CLI para teste das rotinas de exemplo
```
