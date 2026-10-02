import asyncio
import logging
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel

from modernizer.artifacts import export_execution_artifacts
from modernizer.graph.graphbuilder import graph
from modernizer.observability.tracing import (
    create_langfuse_handler,
    flush_langfuse,
)
from modernizer.persistence.history import save_execution

app = FastAPI()
logger = logging.getLogger(__name__)


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

    invocation_config: dict[str, Any] = {
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

    try:
        result = await graph.ainvoke(
            {
                "source_code": req.source_code,
                "schema_sql": schema_sql,
                "schema_source": schema_source,
                "report": initial_report,
            },
            config=invocation_config,
        )

        final_trace_id = normalize_trace_id(langfuse_handler)

    except Exception as error:  # noqa: BLE001
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