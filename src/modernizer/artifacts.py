from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RESULTS_DIR = PROJECT_ROOT / "results"


def infer_sample_name(source_code: str) -> str:
    match = re.search(
        r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+([A-Za-z0-9_]+)",
        source_code,
        flags=re.IGNORECASE,
    )
    if match:
        return match.group(1).strip()
    if source_code.strip():
        cleaned = re.sub(r"[^A-Za-z0-9_]", "_", source_code.strip()[:30])
        return cleaned.strip("_") or "execution"
    return "execution"


def export_execution_artifacts(
    *,
    source_code: str,
    generated_code: str | None,
    report: dict[str, Any],
    status: str,
    history_id: str | None,
    trace_id: str | None,
) -> Path:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    sample_name = infer_sample_name(source_code)
    sample_dir = RESULTS_DIR / sample_name
    sample_dir.mkdir(parents=True, exist_ok=True)

    generated_path = sample_dir / "generated.py"
    report_path = sample_dir / "report.json"

    if generated_code is not None:
        generated_path.write_text(generated_code, encoding="utf-8")
    else:
        generated_path.write_text("", encoding="utf-8")

    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = RESULTS_DIR / "summary.json"
    summary_entries: list[dict[str, Any]] = []
    if summary_path.exists():
        try:
            existing = json.loads(summary_path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                summary_entries = existing
        except json.JSONDecodeError:
            summary_entries = []

    entry = {
        "sample": sample_name,
        "status": status,
        "history_id": history_id,
        "trace_id": trace_id,
    }

    merged = [item for item in summary_entries if item.get("sample") != sample_name]
    merged.append(entry)
    summary_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")

    return sample_dir
