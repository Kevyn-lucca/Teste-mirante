
import argparse
import os
import sys
import threading
import time
from pathlib import Path

import httpx

DEFAULT_URL = os.getenv("MODERNIZE_URL", "http://127.0.0.1:8123/modernize")
START = time.monotonic()


def log(message: str) -> None:
    elapsed = time.monotonic() - START
    print(f"[{elapsed:7.1f}s] {message}", flush=True)


class Heartbeat:

    def __init__(self, label: str, interval: float = 10.0) -> None:
        self.label = label
        self.interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._began = time.monotonic()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            waited = time.monotonic() - self._began
            log(f"{self.label}: ainda aguardando resposta do servidor ({waited:.0f}s)...")

    def __enter__(self) -> "Heartbeat":
        self._thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self._stop.set()


def ensure_server_is_running(url: str) -> None:
    health_url = url.rsplit("/", 1)[0] + "/health"
    log(f"Verificando servidor em {health_url}")
    try:
        response = httpx.get(health_url, timeout=10)
    except httpx.HTTPError as error:
        raise RuntimeError(
            f"Servidor indisponivel em {health_url} ({error!r}). "
            "Rode primeiro: uv run langgraph dev --no-browser --port 8123"
        ) from error

    if response.status_code != 200:
        raise RuntimeError(
            f"Health check falhou em {health_url} (status={response.status_code}). "
            "Verifique se o servidor foi iniciado e se a porta 8123 esta livre."
        )
    log("Servidor OK")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "samples",
        nargs="*",
        type=Path,
        help="arquivos .sql a enviar (padrao: samples/01 a 05)",
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--no-schema", action="store_true", help="nao envia o schema do Anexo A"
    )
    parser.add_argument(
        "--show-code", action="store_true", help="imprime o Python gerado"
    )
    parser.add_argument("--timeout", type=float, default=300, help="timeout por amostra (s)")
    parser.add_argument("--verbose", "-v", action="store_true", help="mais detalhes")
    args = parser.parse_args()

    log(f"URL alvo: {args.url}")
    try:
        ensure_server_is_running(args.url)
    except RuntimeError as error:
        log(f"ERRO: {error}")
        return 2

    samples = args.samples or sorted(Path("samples").glob("0[1-6]_*.sql"))
    log(f"{len(samples)} amostra(s): {[s.name for s in samples]}")

    schema_sql = None
    if not args.no_schema:
        schema_files = sorted(Path("samples").glob("00_*.sql"))
        if schema_files:
            schema_sql = schema_files[0].read_text(encoding="utf-8")
            log(f"Schema carregado: {schema_files[0].name} ({len(schema_sql)} chars)")
        else:
            log("AVISO: nenhum samples/00_*.sql encontrado, enviando sem schema")
    else:
        log("Schema desativado (--no-schema)")

    timeout = httpx.Timeout(args.timeout, connect=10)
    failures = 0

    for index, sample in enumerate(samples, start=1):
        label = f"{sample.stem} ({index}/{len(samples)})"
        source = sample.read_text(encoding="utf-8")
        payload = {"source_code": source, "schema_sql": schema_sql}
        log(f"{label}: enviando POST ({len(source)} chars de codigo)")

        began = time.monotonic()
        try:
            with Heartbeat(label):
                response = httpx.post(args.url, json=payload, timeout=timeout)
        except httpx.TimeoutException as error:
            log(f"{label}: TIMEOUT apos {time.monotonic() - began:.0f}s ({error!r})")
            log("  -> veja o terminal do langgraph dev: LLM lento? banco/Langfuse pendurado?")
            failures += 1
            continue
        except httpx.HTTPError as error:
            log(f"{label}: ERRO de requisicao: {error!r}")
            failures += 1
            continue

        took = time.monotonic() - began
        log(f"{label}: resposta HTTP {response.status_code} em {took:.1f}s")

        if response.status_code >= 400:
            log(f"{label}: corpo do erro: {response.text[:1000]}")
            failures += 1
            continue

        try:
            data = response.json()
        except ValueError:
            log(f"{label}: resposta nao e JSON: {response.text[:500]}")
            failures += 1
            continue

        if args.verbose:
            log(f"{label}: chaves da resposta: {sorted(data.keys())}")

        status = data.get("status")
        validation = data.get("report", {}).get("validation", {})
        log(
            f"{label}: {status} | tentativas={validation.get('attempt')} "
            f"| history_id={data.get('history_id')} | trace_id={data.get('trace_id')}"
        )
        if args.verbose and validation:
            log(f"{label}: validacao: {validation}")

        if args.show_code:
            print(data.get("generated_code") or "(sem codigo gerado)", flush=True)
            print("-" * 60, flush=True)
        if status != "sucesso":
            failures += 1

    log(f"Fim: {len(samples) - failures} ok, {failures} falha(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())