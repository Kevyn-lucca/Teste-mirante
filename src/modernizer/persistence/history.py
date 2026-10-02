from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Jsonb

from modernizer.config import settings


def save_execution(
    source_code: str,
    generated_code: str | None,
    report: dict[str, Any],
    status: str,
) -> UUID:
    database_url = settings.database_url
    if not database_url:
        raise RuntimeError("DATABASE_URL is not configured")

    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            INSERT INTO modernization_history (source_code, generated_code, report, status)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            (source_code, generated_code, Jsonb(report), status),
        ).fetchone()
    return row[0]