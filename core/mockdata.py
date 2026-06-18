"""Deterministic synthetic dataset generation for local pipeline/model testing.

Data and ML engineers need standardized dummy datasets to exercise pipelines and feature/serving
code without touching production data. These pure helpers turn a simple column schema into a
deterministic dataset (seeded), rendered as CSV / JSON / JSONL. Deterministic so a fixture is
reproducible across runs; bounded so an agent cannot generate an enormous file.
"""
from __future__ import annotations

import csv
import io
import json
import random
from datetime import UTC, datetime, timedelta

MAX_ROWS = 1000
_EPOCH = datetime(2024, 1, 1, tzinfo=UTC)


def _gen_value(rng: random.Random, col: dict):
    """Generate one deterministic value for a column spec ``{type, ...}``."""
    col_type = str(col.get("type", "string")).lower()
    if col_type == "int":
        lo, hi = int(col.get("min", 0)), int(col.get("max", 100))
        return rng.randint(lo, max(lo, hi))
    if col_type == "float":
        lo, hi = float(col.get("min", 0.0)), float(col.get("max", 1.0))
        precision = int(col.get("precision", 3))
        return round(rng.uniform(lo, max(lo, hi)), precision)
    if col_type == "bool":
        return rng.choice([True, False])
    if col_type == "timestamp":
        # Step within a year from a fixed epoch — deterministic ISO-8601 timestamps.
        return (_EPOCH + timedelta(seconds=rng.randint(0, 31_536_000))).isoformat()
    if col_type == "category":
        values = list(col.get("values") or ["A", "B", "C"])
        return rng.choice(values) if values else ""
    # "id" is handled positionally in generate_rows (sequential, unique); fall through to string.
    prefix = str(col.get("prefix", col.get("name", "val")))
    return f"{prefix}_{rng.randint(0, 9999)}"


def generate_rows(columns: list[dict], rows: int, *, seed: int = 0) -> list[dict]:
    """Build ``rows`` deterministic records from a column schema.

    Each column is ``{"name": str, "type": one of int|float|bool|timestamp|category|id|string, ...}``
    with optional ``min``/``max`` (numeric), ``values`` (category), and ``precision`` (float). ``id``
    columns are sequential (1-based, unique). ``rows`` is clamped to ``[0, MAX_ROWS]``. Columns
    without a ``name`` are skipped.
    """
    rng = random.Random(seed)
    n = max(0, min(int(rows), MAX_ROWS))
    named = [c for c in columns if isinstance(c, dict) and str(c.get("name", "")).strip()]
    out: list[dict] = []
    for i in range(n):
        record: dict = {}
        for col in named:
            name = str(col["name"]).strip()
            if str(col.get("type", "")).lower() == "id":
                record[name] = i + 1
            else:
                record[name] = _gen_value(rng, col)
        out.append(record)
    return out


def render(rows: list[dict], fmt: str = "csv", columns: list[dict] | None = None) -> str:
    """Render generated rows as CSV (default), JSON, or JSONL. Column order follows ``columns``."""
    fmt = (fmt or "csv").lower()
    if fmt == "json":
        return json.dumps(rows, indent=2, default=str)
    if fmt == "jsonl":
        return "\n".join(json.dumps(r, default=str) for r in rows)

    fieldnames = [str(c["name"]).strip() for c in (columns or []) if c.get("name")]
    if not fieldnames:
        fieldnames = list(rows[0].keys()) if rows else []
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames)
    writer.writeheader()
    for r in rows:
        writer.writerow({k: r.get(k, "") for k in fieldnames})
    return buf.getvalue()


def build_dataset(columns: list[dict], rows: int, *, fmt: str = "csv", seed: int = 0) -> str:
    """Convenience: generate rows then render in one call."""
    return render(generate_rows(columns, rows, seed=seed), fmt, columns)
