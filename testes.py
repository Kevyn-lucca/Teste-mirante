"""Envia amostras PL/pgSQL ao servidor Modernizer e resume o resultado."""

import argparse
import os
import sys
import time
from pathlib import Path

import httpx

DEFAULT_URL = os.getenv("MODERNIZE_URL", "http://127.0.0.1:8123/modernize")
SAMPLES_DIR = Path("samples")
SCHEMA_PREFIX = "00_"


def check_server(url: str) -> None:
    health_url = url.rsplit("/", 1)[0] + "/health"
    try:
        response = httpx.get(health_url, timeout=10)
    except httpx.HTTPError as error:
        raise RuntimeError(
            f"Servidor indisponivel em {health_url} ({error!r}). "
            "Rode primeiro: uv run langgraph dev --no-browser --port 8123"
        ) from error

    if response.status_code != 200:
        raise RuntimeError(
            f"Health check falhou em {health_url} (status={response.status_code})."
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "samples",
        nargs="*",
        type=Path,
        help="arquivos .sql a enviar (padrao: todos de samples/, exceto 00_)",
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--no-schema", action="store_true", help="nao envia o schema (00_*.sql)"
    )
    parser.add_argument(
        "--show-code", action="store_true", help="imprime o Python gerado"
    )
    parser.add_argument(
        "--timeout", type=float, default=300, help="timeout por amostra (s)"
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="mostra o detalhe da validacao"
    )
    args = parser.parse_args()

    try:
        check_server(args.url)
    except RuntimeError as error:
        print(f"ERRO: {error}")
        return 2

    samples = args.samples or [
        p
        for p in sorted(SAMPLES_DIR.glob("*.sql"))
        if not p.stem.startswith(SCHEMA_PREFIX)
    ]

    schema_sql = None
    if not args.no_schema:
        schema_files = sorted(SAMPLES_DIR.glob(f"{SCHEMA_PREFIX}*.sql"))
        if schema_files:
            schema_sql = schema_files[0].read_text(encoding="utf-8")
        else:
            print("AVISO: nenhum schema 00_*.sql encontrado, enviando sem schema")

    total = len(samples)
    failures = 0
    timeout = httpx.Timeout(args.timeout, connect=10)

    for index, sample in enumerate(samples, start=1):
        prefix = f"[{index}/{total}] {sample.stem}:"
        payload = {
            "source_code": sample.read_text(encoding="utf-8"),
            "schema_sql": schema_sql,
        }

        began = time.monotonic()
        try:
            response = httpx.post(args.url, json=payload, timeout=timeout)
        except httpx.TimeoutException:
            print(f"{prefix} TIMEOUT apos {args.timeout:.0f}s")
            failures += 1
            continue
        except httpx.HTTPError as error:
            print(f"{prefix} ERRO de requisicao: {error!r}")
            failures += 1
            continue
        took = time.monotonic() - began

        if response.status_code >= 400:
            print(f"{prefix} HTTP {response.status_code}: {response.text[:300]}")
            failures += 1
            continue

        try:
            data = response.json()
        except ValueError:
            print(f"{prefix} resposta nao e JSON: {response.text[:300]}")
            failures += 1
            continue

        report = data.get("report", {})
        validation = report.get("validation", {})
        attempts = validation.get("attempt") or report.get("generation", {}).get(
            "attempt"
        )
        status = data.get("status")

        print(f"{prefix} {status} | tentativas={attempts} | {took:.1f}s")

        if args.verbose and validation:
            print(f"    validacao: {validation}")
        if args.show_code:
            print(data.get("generated_code") or "(sem codigo gerado)")
            print("-" * 60)
        if status != "sucesso":
            failures += 1

    print(f"Fim: {total - failures} ok, {failures} falha(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())