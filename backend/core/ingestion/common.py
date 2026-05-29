"""
Shared helpers for ingestion: locale-aware decimals, multi-format dates,
unit conversion to canonical units, and factor lookup.

The unit map is intentionally narrow: we convert source units into the
units that EmissionFactor rows are stored in. We do NOT try to be a full
units library — this is a prototype, and broadening the converter is one
of the things deliberately deferred to TRADEOFFS.md.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

from dateutil import parser as dateparser


# ---------------------------------------------------------------------------
# Decimal parsing (handles US `1,234.56`, German `1.234,56`, plain `1234.56`)
# ---------------------------------------------------------------------------


_DECIMAL_DE = re.compile(r"^-?\d{1,3}(\.\d{3})*(,\d+)?$|^-?\d+,\d+$")
_DECIMAL_US = re.compile(r"^-?\d{1,3}(,\d{3})*(\.\d+)?$|^-?\d+\.\d+$|^-?\d+$")


def parse_decimal(
    value: str | float | int | Decimal | None,
    locale_hint: str = "auto",
) -> Optional[Decimal]:
    """
    Parse a decimal string, sniffing US-vs-German conventions.

    German SAP exports default to `1.234,56` (dot = thousands, comma = decimal).
    US/UK SAP exports default to `1,234.56`. When both separators appear,
    the rightmost is the decimal. When only one appears, behaviour depends
    on `locale_hint`:
      - 'de': comma always = decimal point (handles SAP 4-decimal prices
              like `1,4250`)
      - 'us'/'uk': comma always = thousands
      - 'auto': heuristic — a single comma with 1-3 trailing digits is
                treated as decimal, otherwise as thousands.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    s = str(value).strip().replace(" ", "").replace("\xa0", "")
    if not s:
        return None

    has_dot = "." in s
    has_comma = "," in s

    if has_dot and has_comma:
        # The rightmost is the decimal separator.
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif has_comma:
        if locale_hint == "de":
            s = s.replace(",", ".")
        elif locale_hint in {"us", "uk"}:
            s = s.replace(",", "")
        else:
            parts = s.split(",")
            if len(parts) == 2 and 1 <= len(parts[1]) <= 3 and len(parts[0]) <= 6:
                s = s.replace(",", ".")
            else:
                s = s.replace(",", "")
    # has_dot only or neither: leave it alone

    try:
        return Decimal(s)
    except InvalidOperation:
        return None


# ---------------------------------------------------------------------------
# Date parsing (SAP YYYYMMDD, German DD.MM.YYYY, ISO, US slash)
# ---------------------------------------------------------------------------


_SAP_INTERNAL_DATE = re.compile(r"^\d{8}$")


def parse_date(value: str | date | None, locale_hint: str = "us") -> Optional[date]:
    """
    Parse a date from the messy formats sources actually use.

    SAP's internal `YYYYMMDD` is recognised first. After that we trust
    dateutil with `dayfirst` set from the locale_hint ('de' implies dayfirst).
    """
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    if not s:
        return None
    if _SAP_INTERNAL_DATE.match(s):
        return date(int(s[:4]), int(s[4:6]), int(s[6:8]))
    dayfirst = locale_hint.lower().startswith("de") or locale_hint.lower() == "uk"
    try:
        return dateparser.parse(s, dayfirst=dayfirst).date()
    except (ValueError, TypeError, dateparser.ParserError):
        return None


# ---------------------------------------------------------------------------
# Unit conversion to canonical units used by EmissionFactor rows.
#
# Canonical units we support:
#   - volume: litre  (factor unit for liquid fuels)
#   - mass:   kg     (factor unit for refrigerants)
#   - energy: kWh    (factor unit for electricity, natural gas)
#   - distance: km   (factor unit for travel)
# ---------------------------------------------------------------------------


# Conversion factor to canonical. Keys are uppercased + stripped.
_UNIT_MAP: dict[str, tuple[str, Decimal]] = {
    # Volume → litre
    "L": ("litre", Decimal("1")),
    "LTR": ("litre", Decimal("1")),
    "LITRE": ("litre", Decimal("1")),
    "LITER": ("litre", Decimal("1")),
    "LITERS": ("litre", Decimal("1")),
    "ML": ("litre", Decimal("0.001")),
    "GAL": ("litre", Decimal("3.785411784")),  # US gallon
    "UGL": ("litre", Decimal("3.785411784")),
    "USGAL": ("litre", Decimal("3.785411784")),
    "UKGAL": ("litre", Decimal("4.54609")),
    "M3": ("litre", Decimal("1000")),
    "CBM": ("litre", Decimal("1000")),
    # Mass → kg
    "KG": ("kg", Decimal("1")),
    "KGS": ("kg", Decimal("1")),
    "G": ("kg", Decimal("0.001")),
    "T": ("kg", Decimal("1000")),
    "TO": ("kg", Decimal("1000")),
    "TONNE": ("kg", Decimal("1000")),
    "TONNES": ("kg", Decimal("1000")),
    "LB": ("kg", Decimal("0.45359237")),
    "LBS": ("kg", Decimal("0.45359237")),
    # Energy → kWh
    "KWH": ("kWh", Decimal("1")),
    "MWH": ("kWh", Decimal("1000")),
    "GWH": ("kWh", Decimal("1000000")),
    "MJ": ("kWh", Decimal("0.27777778")),
    "GJ": ("kWh", Decimal("277.77777778")),
    "THM": ("kWh", Decimal("29.3001")),
    # Distance → km
    "KM": ("km", Decimal("1")),
    "MI": ("km", Decimal("1.609344")),
    "MILE": ("km", Decimal("1.609344")),
    "MILES": ("km", Decimal("1.609344")),
    "M": ("km", Decimal("0.001")),
    # Passenger-distance (kept distinct so we don't accidentally apply
    # vehicle-mile factors to passenger-miles)
    "PKM": ("passenger_km", Decimal("1")),
    "PMI": ("passenger_km", Decimal("1.609344")),
    # Time-based (hotel)
    "NIGHT": ("room_night", Decimal("1")),
    "ROOM_NIGHT": ("room_night", Decimal("1")),
}


@dataclass
class Normalized:
    quantity: Decimal
    unit: str
    inferred: bool = False  # True if the unit was missing and we guessed


def normalize_quantity(
    quantity_raw: Decimal | float | int | str | None,
    unit_raw: str | None,
    default_canonical_unit: str | None = None,
) -> Optional[Normalized]:
    """
    Convert (quantity, unit) into canonical units.

    If unit_raw is missing or unrecognised and a `default_canonical_unit`
    is supplied, the quantity is taken as-is in that canonical unit and
    the result is marked `inferred=True` so the flagging engine can
    surface it for analyst review.
    """
    q = parse_decimal(quantity_raw)
    if q is None:
        return None
    key = (unit_raw or "").strip().upper()
    if key in _UNIT_MAP:
        canonical_unit, mult = _UNIT_MAP[key]
        return Normalized(quantity=q * mult, unit=canonical_unit)
    if default_canonical_unit:
        return Normalized(
            quantity=q, unit=default_canonical_unit, inferred=True
        )
    return None


# ---------------------------------------------------------------------------
# Factor lookup
# ---------------------------------------------------------------------------


def find_emission_factor(activity_type: str, region: str, year: int):
    """
    Look up the best emission factor row.

    Strategy:
      1. exact (activity_type, region, year) match
      2. exact (activity_type, region) with newest year <= year
      3. exact (activity_type, 'GLOBAL') with newest year <= year
      4. None
    """
    from core.models import EmissionFactor

    qs = EmissionFactor.objects.filter(activity_type=activity_type)
    exact = qs.filter(region=region, year=year).first()
    if exact:
        return exact
    closest = qs.filter(region=region, year__lte=year).order_by("-year").first()
    if closest:
        return closest
    global_closest = (
        qs.filter(region="GLOBAL", year__lte=year).order_by("-year").first()
    )
    return global_closest
