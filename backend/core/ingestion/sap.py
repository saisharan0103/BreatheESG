"""
SAP MM/FI flat-file CSV ingestion.

We accept the kind of CSV a finance/procurement team produces from
SE16/SE16N or an ALV "Export to spreadsheet" of EKKO+EKPO+MSEG joined
to MARA/MAKT. The expected columns (English or German headers) are:

  EBELN/Einkaufsbeleg  -- PO number
  EBELP/Position       -- PO line item
  LIFNR/Lieferant      -- Vendor
  WERKS/Werk           -- Plant
  MATNR/Material       -- Material
  MAKTX/Materialkurztext -- Material description
  MATKL/Warengruppe    -- Material group  (drives activity_type)
  MENGE/Menge          -- Quantity
  MEINS/BME            -- Base unit of measure
  NETPR/Nettopreis     -- Unit price
  NETWR/Nettowert      -- Net order value
  WAERS/Waehrung       -- Currency
  BUDAT/Buchungsdatum  -- Posting date
  BWART/Bewegungsart   -- Movement type (101 = goods receipt; we accept that)

Delimiter is auto-detected (`,` or `;`). Encoding falls back from
UTF-8 to CP1252 because older SAP GUI downloads are ANSI-encoded.

Realistic gotchas this parser handles:
  - German `1.234,56` numbers vs US `1,234.56`
  - SAP internal `YYYYMMDD` dates vs `DD.MM.YYYY` locale dates
  - `MATNR` arrives zero-padded (`000000000000300077`); we keep it as-is
  - Empty BWART or BWART != '101' is ignored as not-a-receipt
  - MATKL → activity_type mapping uses a short controlled vocabulary;
    unknown groups are flagged for analyst review
"""
from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Iterator, Optional

from .common import normalize_quantity, parse_date, parse_decimal


# Header aliases: lower-cased lookup → canonical field name.
HEADER_ALIASES: dict[str, str] = {
    # EBELN
    "ebeln": "po_number",
    "einkaufsbeleg": "po_number",
    "bestellnummer": "po_number",
    "purchase order": "po_number",
    # EBELP
    "ebelp": "po_line",
    "position": "po_line",
    "item": "po_line",
    # LIFNR
    "lifnr": "vendor",
    "lieferant": "vendor",
    "kreditor": "vendor",
    "vendor": "vendor",
    # WERKS
    "werks": "plant",
    "werk": "plant",
    "plant": "plant",
    # MATNR
    "matnr": "material",
    "material": "material",
    "materialnummer": "material",
    # MAKTX
    "maktx": "material_text",
    "materialkurztext": "material_text",
    "bezeichnung": "material_text",
    "material description": "material_text",
    # MATKL
    "matkl": "material_group",
    "warengruppe": "material_group",
    "material group": "material_group",
    # MENGE
    "menge": "quantity",
    "quantity": "quantity",
    "qty": "quantity",
    # MEINS / BSTME
    "meins": "unit",
    "bme": "unit",
    "basismengeneinheit": "unit",
    "uom": "unit",
    "unit": "unit",
    "base unit": "unit",
    "bstme": "unit",
    "bestellme": "unit",
    "order unit": "unit",
    # NETPR
    "netpr": "unit_price",
    "nettopreis": "unit_price",
    "net price": "unit_price",
    # NETWR
    "netwr": "net_value",
    "nettowert": "net_value",
    "nettobestellwert": "net_value",
    "net value": "net_value",
    # WAERS
    "waers": "currency",
    "währung": "currency",
    "waehrung": "currency",
    "currency": "currency",
    # BUDAT
    "budat": "posting_date",
    "buchungsdatum": "posting_date",
    "posting date": "posting_date",
    # BLDAT
    "bldat": "document_date",
    "belegdatum": "document_date",
    "document date": "document_date",
    # BWART
    "bwart": "movement_type",
    "bewegungsart": "movement_type",
    "movement type": "movement_type",
    # KOSTL
    "kostl": "cost_center",
    "kostenstelle": "cost_center",
    "cost center": "cost_center",
}


# Map material group codes / patterns to canonical activity_type.
# Real SAP shops customise MATKL freely so we cover the common groups
# our seed factor table supports; anything else falls through and the
# row is flagged factor_missing.
MATERIAL_GROUP_TO_ACTIVITY: dict[str, str] = {
    "FUEL01": "diesel",
    "FUEL_DIESEL": "diesel",
    "DIESEL": "diesel",
    "FUEL02": "adblue",        # urea-water, near-zero GHG; skipped at factor level
    "FUEL03": "petrol",
    "PETROL": "petrol",
    "GASOLINE": "petrol",
    "FUEL04": "natural_gas",
    "GAS": "natural_gas",
    "NATGAS": "natural_gas",
    "LPG": "lpg",
    "PROPANE": "lpg",
    "HEATING_OIL": "heating_oil",
    "KEROSENE": "heating_oil",
}


# Material short text fallback — if MATKL doesn't map, sniff the description.
DESCRIPTION_PATTERNS: list[tuple[str, str]] = [
    ("diesel", "diesel"),
    ("petrol", "petrol"),
    ("gasoline", "petrol"),
    ("natural gas", "natural_gas"),
    ("erdgas", "natural_gas"),
    ("lpg", "lpg"),
    ("propan", "lpg"),
    ("heating oil", "heating_oil"),
    ("heizöl", "heating_oil"),
    ("heizoel", "heating_oil"),
    ("kerosene", "heating_oil"),
    ("adblue", "adblue"),
]


@dataclass
class ParsedSapRow:
    raw: dict
    source_record_id: str  # EBELN + EBELP
    posting_date: Optional[date]
    activity_type: Optional[str]
    description: str
    quantity_raw: Decimal
    unit_raw: str
    quantity_canonical: Decimal
    unit_canonical: str
    unit_inferred: bool
    cost_amount: Optional[Decimal]
    cost_currency: str
    vendor: str
    plant: str
    cost_center: str
    movement_type: str
    parse_warnings: list[str]


def _detect_delimiter(sample: str) -> str:
    """Semicolon if the file looks German (more `;` than `,` in the first line)."""
    first_line = sample.splitlines()[0] if sample else ""
    return ";" if first_line.count(";") > first_line.count(",") else ","


def _detect_locale(headers: list[str]) -> str:
    """If we see German captions in the header, return 'de'.

    Markers are German LABEL words that don't collide with SAP's
    technical English codes (MENGE/WAERS are technical codes that
    happen to be German abbreviations — they would false-positive).
    """
    german_markers = {
        "werk",            # tech is WERKS
        "lieferant",       # tech is LIFNR
        "buchungsdatum",   # tech is BUDAT
        "belegdatum",      # tech is BLDAT
        "nettopreis",      # tech is NETPR
        "nettowert",       # tech is NETWR
        "bestellnummer",   # tech is EBELN
        "kostenstelle",    # tech is KOSTL
        "währung",         # tech is WAERS
        "warengruppe",     # tech is MATKL
        "bewegungsart",    # tech is BWART
        "materialkurztext", # tech is MAKTX
        "lagerort",        # tech is LGORT
    }
    lowered = {h.strip().lower() for h in headers}
    return "de" if lowered & german_markers else "us"


def _classify_activity(material_group: str, description: str) -> Optional[str]:
    mg = (material_group or "").strip().upper()
    if mg in MATERIAL_GROUP_TO_ACTIVITY:
        return MATERIAL_GROUP_TO_ACTIVITY[mg]
    desc = (description or "").lower()
    for needle, activity in DESCRIPTION_PATTERNS:
        if needle in desc:
            return activity
    return None


_HEADER_PUNCT_RE = re.compile(r"[\s_\-./()]+")


def _normalise_header(raw: str) -> str:
    return _HEADER_PUNCT_RE.sub("", raw.strip().lower())


_NORMALISED_ALIASES: dict[str, str] = {
    _normalise_header(k): v for k, v in HEADER_ALIASES.items()
}


def _canonical_headers(raw_headers: list[str]) -> list[str]:
    return [
        _NORMALISED_ALIASES.get(_normalise_header(h), _normalise_header(h))
        for h in raw_headers
    ]


def parse_sap_csv(blob: bytes) -> tuple[list[ParsedSapRow], list[str], dict]:
    """
    Returns (rows, errors, parser_notes).

    `parser_notes` records what we detected (encoding, delimiter, locale)
    so the analyst can see in the dashboard exactly how the file was read.
    """
    notes: dict = {}
    text: str = ""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            text = blob.decode(enc)
            notes["encoding"] = enc
            break
        except UnicodeDecodeError:
            continue
    if not text:
        return [], ["could not decode file as UTF-8, CP1252, or Latin-1"], notes

    delimiter = _detect_delimiter(text)
    notes["delimiter"] = delimiter

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        raw_headers = next(reader)
    except StopIteration:
        return [], ["empty file"], notes

    locale_hint = _detect_locale(raw_headers)
    notes["locale_hint"] = locale_hint
    canonical = _canonical_headers(raw_headers)
    notes["header_mapping"] = dict(zip(raw_headers, canonical))

    rows: list[ParsedSapRow] = []
    errors: list[str] = []

    for line_no, raw_row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw_row):
            continue
        if len(raw_row) != len(canonical):
            # Re-pad with empties; CSV writers sometimes drop trailing empties
            raw_row = raw_row + [""] * (len(canonical) - len(raw_row))
            raw_row = raw_row[: len(canonical)]
        record = dict(zip(canonical, raw_row))

        bwart = (record.get("movement_type") or "").strip()
        if bwart and bwart not in {"101", ""}:
            # 101 = goods receipt against PO; everything else is a movement
            # we don't want as an emissions activity (transfers, reversals).
            continue

        warnings: list[str] = []

        quantity_raw = parse_decimal(
            record.get("quantity"), locale_hint=locale_hint
        )
        if quantity_raw is None:
            errors.append(f"line {line_no}: unparseable quantity {record.get('quantity')!r}")
            continue
        unit_raw = (record.get("unit") or "").strip()
        if not unit_raw:
            warnings.append("unit_missing")
        normalized = normalize_quantity(
            quantity_raw, unit_raw, default_canonical_unit=None
        )
        if normalized is None:
            errors.append(
                f"line {line_no}: cannot map unit {unit_raw!r} for material "
                f"{record.get('material', '?')}"
            )
            continue

        activity = _classify_activity(
            record.get("material_group", ""), record.get("material_text", "")
        )
        if not activity:
            warnings.append("activity_unknown")

        posting_date = parse_date(record.get("posting_date"), locale_hint=locale_hint)
        document_date = parse_date(record.get("document_date"), locale_hint=locale_hint)
        effective_date = posting_date or document_date
        if not effective_date:
            errors.append(f"line {line_no}: missing or unparseable posting/document date")
            continue

        cost_amount = parse_decimal(record.get("net_value"), locale_hint=locale_hint)
        currency = (record.get("currency") or "").strip()

        po_number = (record.get("po_number") or "").strip()
        po_line = (record.get("po_line") or "").strip()
        source_id = f"{po_number}-{po_line}" if po_number else ""

        rows.append(
            ParsedSapRow(
                raw=record,
                source_record_id=source_id,
                posting_date=effective_date,
                activity_type=activity,
                description=record.get("material_text", "") or "",
                quantity_raw=quantity_raw,
                unit_raw=unit_raw,
                quantity_canonical=normalized.quantity,
                unit_canonical=normalized.unit,
                unit_inferred=normalized.inferred,
                cost_amount=cost_amount,
                cost_currency=currency,
                vendor=record.get("vendor", "") or "",
                plant=record.get("plant", "") or "",
                cost_center=record.get("cost_center", "") or "",
                movement_type=bwart,
                parse_warnings=warnings,
            )
        )

    return rows, errors, notes
