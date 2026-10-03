import asyncio
import logging
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from langchain_core.runnables import RunnableConfig
from pydantic import BaseModel

from modernizer.artifacts import export_execution_artifacts
from modernizer.evaluation.metrics import log_scores
from modernizer.graph.graphbuilder import graph
from modernizer.graph.state import PipelineState
from modernizer.observability.tracing import (
    create_langfuse_handler,
    flush_langfuse,
)
from modernizer.persistence.history import save_execution

app = FastAPI()
logger = logging.getLogger(__name__)

SAMPLES_DIR = Path("samples")
EVAL_GLOB = "0[1-5]_*.sql"  # Anexos B a F
SCORE_NAMES = [
    "completed_without_error",
    "quality_score",
    "status_success",
    "ast_parse_ok",
    "lint_clean",
    "first_attempt_pass",
    "attempts",
]


def normalize_trace_id(handler: Any | None) -> str | None:
    """Extrai o last_trace_id do handler, descartando valores inválidos."""
    if handler is None:
        return None

    trace_id = getattr(handler, "last_trace_id", None)
    if trace_id is None:
        return None

    # Descarta o ID "zero" que às vezes aparece
    if isinstance(trace_id, str) and trace_id.strip() == "0" * 32:
        return None

    return str(trace_id)


async def _send_scores(
    trace_id: str | None, state: dict[str, Any], completed: bool
) -> None:
    """Registra as notas de avaliação no Langfuse sem nunca derrubar a resposta."""
    try:
        await asyncio.to_thread(log_scores, trace_id, state, completed)
    except Exception:
        logger.exception("Falha ao registrar scores de avaliação")


class ModernizeRequest(BaseModel):
    source_code: str
    schema_sql: str | None = None


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/modernize")
async def modernize(req: ModernizeRequest) -> dict:
    schema_sql = req.schema_sql if req.schema_sql and req.schema_sql.strip() else None
    schema_source = "request" if schema_sql is not None else "omitted"
    session_id = str(uuid4())

    final_trace_id = None

    langfuse_handler = None
    try:
        # to_thread: a criação do handler pode fazer I/O síncrono
        langfuse_handler = await asyncio.to_thread(create_langfuse_handler)
        observability = {
            "status": "ativo" if langfuse_handler else "desativado",
            "session_id": session_id,
        }
    except Exception as error:
        logger.exception("Não foi possível inicializar o callback do Langfuse")
        langfuse_handler = None
        observability = {
            "status": "indisponivel",
            "error": str(error),
            "session_id": session_id,
        }

    initial_report = {
        "context": {
            "schema_included": schema_sql is not None,
            "schema_source": schema_source,
        },
        "observability": observability,
    }

    invocation_config: RunnableConfig = {
        "run_name": "plpgsql-to-python",
        "tags": ["sql-modernization"],
        "metadata": {
            "langfuse_session_id": session_id,
            "langfuse_tags": ["sql-modernization"],
            "schema_source": schema_source,
        },
    }

    if langfuse_handler is not None:
        invocation_config["callbacks"] = [langfuse_handler]

    result = None
    initial_state: PipelineState = {
        "source_code": req.source_code,
        "schema_sql": schema_sql,
        "schema_source": schema_source,
        "report": initial_report,
        "observability": observability,
    }

    try:
        result = await graph.ainvoke(
            initial_state,
            config=invocation_config,
        )

        final_trace_id = normalize_trace_id(langfuse_handler)
        await _send_scores(final_trace_id, result, completed=True)

    except Exception as error:  # noqa: BLE001
        # Mesmo com o grafo quebrado, o handler já tem o trace_id da execução
        final_trace_id = normalize_trace_id(langfuse_handler)
        await _send_scores(final_trace_id, {}, completed=False)

        report: dict[str, Any] = {
            **initial_report,
            "pipeline": {"status": "falha", "error": str(error)},
        }
        history_id = None

        try:
            history_id = str(
                await asyncio.to_thread(
                    save_execution,
                    source_code=req.source_code,
                    generated_code=None,
                    report=report,
                    status="falha",
                )
            )
            report["persistence"] = {"status": "sucesso", "history_id": history_id}
        except Exception as persistence_error:  # noqa: BLE001
            report["persistence"] = {
                "status": "falha",
                "error": str(persistence_error),
            }

        await asyncio.to_thread(
            export_execution_artifacts,
            source_code=req.source_code,
            generated_code="",
            report=report,
            status="falha",
            history_id=history_id,
            trace_id=final_trace_id,
        )

        return {
            "generated_code": "",
            "report": report,
            "status": "falha",
            "history_id": history_id,
            "trace_id": final_trace_id,
        }

    finally:
        # Sempre tenta flush (mesmo em caso de erro)
        if langfuse_handler is not None:
            try:
                await asyncio.to_thread(flush_langfuse)
            except Exception:
                logger.exception("Falha ao enviar traces ao Langfuse")

    response = {
        "generated_code": result.get("generated_code", "") if result else "",
        "report": result.get("report", {}) if result else {},
        "status": result.get("status", "falha") if result else "falha",
        "history_id": result.get("history_id") if result else None,
        "trace_id": final_trace_id,
    }

    await asyncio.to_thread(
        export_execution_artifacts,
        source_code=req.source_code,
        generated_code=response["generated_code"],
        report=response["report"],
        status=response["status"],
        history_id=response["history_id"],
        trace_id=final_trace_id,
    )

    return response


def _load_eval_inputs() -> tuple[str | None, list[tuple[str, str]]]:
    """Leitura de arquivos (síncrona): rodar sempre via asyncio.to_thread."""
    schema_files = sorted(SAMPLES_DIR.glob("00_*.sql"))
    schema = schema_files[0].read_text(encoding="utf-8") if schema_files else None
    procedures = [
        (p.stem, p.read_text(encoding="utf-8"))
        for p in sorted(SAMPLES_DIR.glob(EVAL_GLOB))
    ]
    return schema, procedures


@app.post("/evaluation/run")
async def run_evaluation() -> dict:
    """Roda o conjunto dos Anexos B a F e devolve a métrica agregada."""
    schema_sql, procedures = await asyncio.to_thread(_load_eval_inputs)

    rows: list[dict[str, Any]] = []
    for name, source in procedures:
        response = await modernize(
            ModernizeRequest(source_code=source, schema_sql=schema_sql)
        )
        report = response.get("report", {})
        completed = report.get("pipeline", {}).get("status") != "falha"
        evaluation = {
            "completed_without_error": float(completed),
            **report.get("evaluation", {}),
        }
        rows.append(
            {
                "procedure": name,
                "status": response.get("status"),
                "trace_id": response.get("trace_id"),
                **{n: float(evaluation.get(n, 0.0)) for n in SCORE_NAMES},
            }
        )

    def rate(score: str) -> float:
        if not rows:
            return 0.0
        total = 0.0
        for r in rows:
            val = r.get(score)
            if isinstance(val, (int, float)):
                total += float(val)
        return round(total / len(rows), 3)

    return {
        "summary": {
            "procedures": len(rows),
            "avg_quality_score": rate("quality_score"),
            "completion_rate": rate("completed_without_error"),
            "success_rate": rate("status_success"),
            "ast_parse_rate": rate("ast_parse_ok"),
            "lint_clean_rate": rate("lint_clean"),
            "first_attempt_rate": rate("first_attempt_pass"),
            "avg_attempts": rate("attempts"),
        },
        "per_procedure": rows,
    }