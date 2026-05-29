"""
Rule-based "looks suspicious" flag engine.

The brief asks the dashboard to surface "what looks suspicious." We
chose rules over stats because the interesting judgment is in WHICH
rules apply, not in coefficient tuning (defended in DECISIONS.md).

A flag is a short snake_case code. Rules read existing data — they
don't mutate it; the ingestion code persists the resulting list onto
ActivityRecord.flags.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from django.db.models import Q

from .models import ActivityRecord


# Threshold for the "drift vs prior period" rule. 3x is loose enough to
# avoid noise but tight enough to catch obvious meter mis-reads.
DRIFT_MULTIPLIER = Decimal("3.0")


def flag_record_at_ingest(record: ActivityRecord, parse_warnings: Iterable[str]) -> list[str]:
    """
    Run all flag rules for a record being newly ingested. Returns the
    list to store on `record.flags`. Caller is responsible for setting
    status to FLAGGED if the list is non-empty AND the row is otherwise
    unactionable (vs the user being able to approve anyway).
    """
    flags: list[str] = list(parse_warnings or [])

    if record.emission_factor is None:
        flags.append("factor_missing")
    elif _factor_year_drift(record):
        flags.append("factor_year_drift")

    if not record.unit_raw:
        if "unit_missing" not in flags:
            flags.append("unit_missing")
    elif record.unit_normalized != record.unit_raw.lower() and record.unit_raw.upper() not in {
        record.unit_normalized.upper()
    }:
        # unit was converted (not just lowercased) — useful breadcrumb
        flags.append("unit_converted")

    if record.period_end < record.period_start:
        flags.append("period_invalid")
    if record.period_start.year < 2015 or record.period_end.year > 2035:
        flags.append("period_out_of_range")

    if _overlaps_prior_period(record):
        flags.append("period_overlap")

    if _drifts_from_prior(record):
        flags.append("drift_vs_prior")

    if record.quantity_normalized <= 0:
        flags.append("zero_quantity")

    # dedupe preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for f in flags:
        if f not in seen:
            seen.add(f)
            deduped.append(f)
    return deduped


def status_for_flags(flags: list[str]) -> str:
    """
    Pick an initial review status from the flags.

    Rules that block emissions math (factor_missing, period_invalid,
    zero_quantity) land the row in FLAGGED. Soft warnings (unit_inferred,
    estimated_read) leave it in PENDING so analysts can bulk-approve.
    """
    blocking = {"factor_missing", "period_invalid", "zero_quantity"}
    if any(f in blocking for f in flags):
        return ActivityRecord.Status.FLAGGED
    return ActivityRecord.Status.PENDING


# ---------------------------------------------------------------------------
# Rule implementations
# ---------------------------------------------------------------------------


def _factor_year_drift(record: ActivityRecord) -> bool:
    """Factor year is more than 2 years away from the activity period."""
    if record.emission_factor is None:
        return False
    return abs(record.emission_factor.year - record.period_start.year) > 2


def _overlaps_prior_period(record: ActivityRecord) -> bool:
    """
    Any other record for the same tenant + activity_type + (meter/site
    identifier from raw_payload) whose period overlaps this one. We
    approximate the identifier with `source_record_id`'s prefix for
    utility (everything before the date suffix); for SAP/travel this
    rule is largely about catching utility re-bills, so an absent
    identifier just means the rule no-ops.
    """
    if record.source_system != "utility_csv" and record.source_system != "utility_pdf":
        return False
    meter = record.raw_payload.get("meter_id") if isinstance(record.raw_payload, dict) else ""
    if not meter:
        return False
    qs = (
        ActivityRecord.objects.filter(
            tenant=record.tenant,
            source_system__in=["utility_csv", "utility_pdf"],
            activity_type=record.activity_type,
        )
        .exclude(pk=record.pk)
        .filter(
            Q(period_start__lte=record.period_end)
            & Q(period_end__gte=record.period_start)
        )
    )
    return any(
        (r.raw_payload or {}).get("meter_id") == meter for r in qs
    )


def _drifts_from_prior(record: ActivityRecord) -> bool:
    """Quantity > DRIFT_MULTIPLIER x the most recent prior period for same activity."""
    prior = (
        ActivityRecord.objects.filter(
            tenant=record.tenant,
            activity_type=record.activity_type,
            period_end__lt=record.period_start,
        )
        .exclude(pk=record.pk)
        .order_by("-period_end")
        .first()
    )
    if not prior or prior.quantity_normalized == 0:
        return False
    ratio = record.quantity_normalized / prior.quantity_normalized
    return ratio > DRIFT_MULTIPLIER or ratio < (Decimal("1") / DRIFT_MULTIPLIER)
