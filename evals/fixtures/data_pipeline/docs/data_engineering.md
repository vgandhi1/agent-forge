# Data Engineering Design — CNC Press-Line Telemetry

Fixture artifact for the `data_pipeline` eval scenario. Represents a passing Data Engineer
deliverable: a design doc that declares sources, contracts, the pipeline DAG, the storage
model, and data-quality rules for factory telemetry feeding predictive maintenance.

## Sources

| Source | Mode | Protocol | Cadence |
|--------|------|----------|---------|
| Press-line PLC sensors (spindle load, vibration, temperature) | streaming | OPC-UA | 10 Hz |
| MES production orders & part records | batch | CSV export | hourly |
| Maintenance work-order log | batch | DB extract | daily |

## Data Contracts

Explicit schema per source — name, type, unit, valid range, nullability, keys.

| Field | Type | Unit | Range | Null? | Key |
|-------|------|------|-------|-------|-----|
| `asset_id` | string | — | known assets | no | partition |
| `ts` | timestamp(UTC) | — | ≤ now | no | sort |
| `spindle_load` | float | % | 0–120 | no | — |
| `vibration_rms` | float | mm/s | 0–50 | no | — |
| `temperature` | float | °C | -20–200 | no | — |

Rows violating the contract are **quarantined**, never silently dropped or coerced.

## Pipeline

Idempotent, restartable DAG — a re-run must not double-load.

```
extract (OPC-UA / CSV) → validate (contract + range + unit) → transform (resample, derive)
  → load (partitioned table)   [quarantine → reject table; watermark per asset/run]
```

## Storage Model

Lakehouse table `telemetry_clean`, partitioned by `asset_id` / event date, 400-day retention.
Reject table `telemetry_rejects` keeps the raw row plus the failed rule for audit.

## Data Quality

- Schema + type + range + unit checks at the boundary.
- Freshness: alert if an asset's latest watermark lags > 5 min.
- Deduplication on (`asset_id`, `ts`); late arrivals merged within a 1-hour window.
- Per-run metrics recorded: rows in, rows loaded, rows quarantined, watermark/lag.
