from __future__ import annotations

import logging

from langfuse import Langfuse, get_client
from langfuse.langchain import CallbackHandler

from modernizer.config import settings

logger = logging.getLogger(__name__)
_client: Langfuse | None = None


def init_langfuse() -> Langfuse | None:
    global _client
    if _client is not None:
        return _client

    public_key = settings.langfuse_public_key
    secret_key = settings.langfuse_secret_key
    host = settings.langfuse_base_url or "http://localhost:3000"

    if not public_key or not secret_key:
        return None

    _client = Langfuse(public_key=public_key, secret_key=secret_key, host=host)
    return _client


def create_langfuse_handler() -> CallbackHandler | None:
    client = init_langfuse()
    if client is None:
        return None
    return CallbackHandler(public_key=settings.langfuse_public_key)


def flush_langfuse() -> None:
    try:
        get_client().flush()
    except Exception as exc:  # pragma: no cover - best-effort cleanup only  # noqa: BLE001
        logger.debug("Langfuse flush skipped: %s", exc)