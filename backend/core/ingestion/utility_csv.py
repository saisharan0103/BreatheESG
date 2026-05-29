"""
Utility CSV portal export ingestion.

Targets the kind of CSV a UK or US business electricity customer gets
when they "Download usage history" from the supplier portal (EDF Energy
Hub, British Gas Business, ConEd MyAccount). Expected shape: one row per
billing period per meter.

Recognised columns (header aliases handle common spelling differences):

  MPAN / Meter / Meter Number / Service Account
  Site / Site Name / Supply Address
  Period Start / Billing Period Start / From
  Period End / Billing Period End / To
  Units / kWh / Units Consumed / Consumption (kWh)
  Day kWh / Peak kWh
  Night kWh / Off-Peak kWh
  Estimated / Estimated Flag / Reading Type
  Tariff / Tariff Name
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from .common import normalize_quantity, parse_date, parse_decimal


HEADER_ALIASES: dict[str, str] = {
    "mpan": "meter_id",
    "meter": "meter_id",
    "meter id": "meter_id",
    "meter number": "meter_id",
    "meter serial": "meter_id",
    "service account": "meter_id",
    "premise id": "meter_id",
    "account": "meter_id",
    "site": "site",
    "site name": "site",
    "supply address": "site",
    "address": "site",
    "period start": "period_start",
    "billing period start": "period_start",
    "start date": "period_start",
    "from": "period_start",
    "from date": "period_start",
    "period end": "period_end",
    "billing period end": "period_end",
    "end date": "period_end",
    "to": "period_end",
    "to date": "period_end",
    "units": "kwh",
    "kwh": "kwh",
    "units consumed": "kwh",
    "consumption": "kwh",
    "consumption (kwh)": "kwh",
    "energy (kwh)": "kwh",
    "total kwh": "kwh",
    "unitsconsumed_kwh": "kwh",
    "day units": "kwh_day",
    "day kwh": "kwh_day",
    "peak kwh": "kwh_day",
    "dayunits_kwh": "kwh_day",
    "night units": "kwh_night",
    "night kwh": "kwh_night",
    "off-peak kwh": "kwh_night",
    "nightunits_kwh": "kwh_night",
    "estimated": "estimated",
    "estimated flag": "estimated",
    "reading type": "estimated",
    "previousreadtype": "estimated_prev",
    "currentreadtype": "estimated_curr",
    "estimatedflag": "estimated",
    "tariff": "tariff",
    "tariff name": "tariff",
    "tariffname": "tariff",
    "rate plan": "tariff",
    "rate schedule": "tariff",
    "supply type": "supply_type",
    "fuel": "supply_type",
    "currency": "currency",
}


@dataclass
class ParsedUtilityRow:
    raw: dict
    source_record_id: str
    meter_id: str
    site: str
    period_start: date
    period_end: date
    kwh: Decimal
    estimated: bool
    tariff: str
    supply_type: str  # 'electricity' or 'gas' or '' (default electricity)
    parse_warnings: list[str]


_HEADER_PUNCT_RE = re.compile(r"[\s_\-./()]+")


def _normalise_header(raw: str) -> str:
    """Collapse 'Period Start', 'period_start', 'PeriodStart', 'period.start'
    to the same lookup key 'periodstart' so one alias entry covers them all."""
    return _HEADER_PUNCT_RE.sub("", raw.strip().lower())


# Build a normalised-key view of HEADER_ALIASES so lookups are O(1)
# regardless of which separator style the source CSV uses.
_NORMALISED_ALIASES: dict[str, str] = {
    _normalise_header(k): v for k, v in HEADER_ALIASES.items()
}


def _canonical_headers(raw_headers: list[str]) -> list[str]:
    return [
        _NORMALISED_ALIASES.get(_normalise_header(h), _normalise_header(h))
        for h in raw_headers
    ]


def _is_estimated(value: str) -> bool:
    v = (value or "").strip().lower()
    return v in {"e", "est", "estimated", "true", "1", "y", "yes"}


def parse_utility_csv(blob: bytes) -> tuple[list[ParsedUtilityRow], list[str], dict]:
    notes: dict = {}
    text = ""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = blob.decode(enc)
            notes["encoding"] = enc
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return [], ["could not decode file"], notes

    first_line = text.splitlines()[0] if text else ""
    delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
    notes["delimiter"] = delimiter

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return [], ["empty file"], notes

    canonical = _canonical_headers(raw_headers)
    notes["header_mapping"] = dict(zip(raw_headers, canonical))

    rows: list[ParsedUtilityRow] = []
    errors: list[str] = []

    for line_no, raw_row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw_row):
            continue
        if len(raw_row) != len(canonical):
            raw_row = (raw_row + [""] * len(canonical))[: len(canonical)]
        record = dict(zip(canonical, raw_row))
        warnings: list[str] = []

        period_start = parse_date(record.get("period_start"))
        period_end = parse_date(record.get("period_end"))
        if not period_start or not period_end:
            errors.append(f"line {line_no}: missing period dates")
            continue
        if period_end < period_start:
            errors.append(
                f"line {line_no}: period_end before period_start "
                f"({period_start}..{period_end})"
            )
            continue

        # Sum split kWh fields if a total wasn't provided.
        kwh_total = parse_decimal(record.get("kwh"))
        if kwh_total is None:
            day = parse_decimal(record.get("kwh_day"))
            night = parse_decimal(record.get("kwh_night"))
            parts = [v for v in (day, night) if v is not None]
            if parts:
                kwh_total = sum(parts, start=Decimal("0"))
                warnings.append("kwh_summed_from_day_night")
        if kwh_total is None:
            errors.append(f"line {line_no}: missing consumption (kWh)")
            continue

        meter_id = (record.get("meter_id") or "").strip()
        if not meter_id:
            warnings.append("meter_missing")

        estimated = _is_estimated(
            record.get("estimated") or record.get("estimated_curr") or ""
        )
        if estimated:
            warnings.append("estimated_read")

        supply_type = (record.get("supply_type") or "").strip().lower()
        if supply_type and supply_type not in {"electricity", "gas"}:
            supply_type = ""

        source_id = f"{meter_id}-{period_start:%Y%m%d}-{period_end:%Y%m%d}"

        rows.append(
            ParsedUtilityRow(
                raw=record,
                source_record_id=source_id,
                meter_id=meter_id,
                site=record.get("site", "") or "",
                period_start=period_start,
                period_end=period_end,
                kwh=kwh_total,
                estimated=estimated,
                tariff=record.get("tariff", "") or "",
                supply_type=supply_type or "electricity",
                parse_warnings=warnings,
            )
        )

    return rows, errors, notes
