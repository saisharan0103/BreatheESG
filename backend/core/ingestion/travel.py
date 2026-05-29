"""
Corporate travel export ingestion.

Targets the per-segment CSV/JSON export a Concur / Navan / TravelPerk
admin produces from a "Travel Allocation Report" or "Itinerary Segments"
report. One row per segment (air / hotel / car / rail), linked by Trip ID.

Recognised columns:

  Trip ID, Itinerary Locator, Record Locator
  Employee ID
  Segment Type           -- Air / Hotel / Car / Rail
  Start Date, End Date
  Departure Airport Code, Arrival Airport Code  (IATA)
  Cabin Class            -- Y/J/F or Economy/Business/First
  Distance in Miles      -- often blank for Concur, populated for Navan
  Hotel Name, Number of Nights, Country (for hotels)
  Car Class              -- ACRISS codes
  Pickup Location, Dropoff Location
  Total Amount, Currency Code

For air segments missing `Distance in Miles`, we reconstruct great-circle
distance from the IATA pair (see airports.py). Hotels become room-nights.
Car rentals become vehicle-km — but most exports don't carry odometer
readings, so they're frequently flagged.
"""
from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from .airports import haul_category, pair_distance_km
from .common import parse_date, parse_decimal


HEADER_ALIASES: dict[str, str] = {
    "trip id": "trip_id",
    "trip_id": "trip_id",
    "itinerary locator": "trip_id",
    "record locator": "pnr",
    "pnr": "pnr",
    "employee id": "employee_id",
    "employee_id": "employee_id",
    "traveler email": "employee_id",
    "traveler": "employee_id",
    "segment type": "segment_type",
    "segment_type": "segment_type",
    "type": "segment_type",
    "start date": "start_date",
    "start_date": "start_date",
    "start date/time": "start_date",
    "departure date": "start_date",
    "end date": "end_date",
    "end_date": "end_date",
    "end date/time": "end_date",
    "return date": "end_date",
    "departure airport code": "origin_iata",
    "departure airport": "origin_iata",
    "origin": "origin_iata",
    "origin iata": "origin_iata",
    "from": "origin_iata",
    "arrival airport code": "destination_iata",
    "arrival airport": "destination_iata",
    "destination": "destination_iata",
    "destination iata": "destination_iata",
    "to": "destination_iata",
    "cabin class": "cabin_class",
    "class of service": "cabin_class",
    "class": "cabin_class",
    "distance in miles": "distance_miles",
    "distance (miles)": "distance_miles",
    "distance_miles": "distance_miles",
    "distance": "distance_miles",
    "hotel name": "hotel_name",
    "hotel": "hotel_name",
    "number of nights": "nights",
    "nights": "nights",
    "country": "country",
    "city": "city",
    "car class": "car_class",
    "car vendor": "car_vendor",
    "pickup location": "pickup_location",
    "drop-off location": "dropoff_location",
    "dropoff location": "dropoff_location",
    "total amount": "amount",
    "amount": "amount",
    "currency code": "currency",
    "currency": "currency",
}


# Cabin class normalization. Concur ships single-letter booking classes
# but the report layer may also produce free-text. We collapse to three.
CABIN_NORMALISE: dict[str, str] = {
    "Y": "economy", "M": "economy", "B": "economy", "H": "economy",
    "K": "economy", "L": "economy", "V": "economy", "S": "economy",
    "ECONOMY": "economy", "COACH": "economy",
    "W": "premium_economy", "PREMIUM ECONOMY": "premium_economy",
    "P": "premium_economy", "T": "premium_economy",
    "J": "business", "C": "business", "D": "business", "I": "business",
    "BUSINESS": "business",
    "F": "first", "A": "first", "FIRST": "first",
}


def _normalise_cabin(value: str) -> str:
    v = (value or "").strip().upper()
    return CABIN_NORMALISE.get(v, "economy" if not v else "economy")


@dataclass
class ParsedTravelRow:
    raw: dict
    source_record_id: str
    employee_id: str
    segment_type: str  # 'air' / 'hotel' / 'car' / 'rail'
    start_date: date
    end_date: Optional[date]
    activity_type: str
    quantity: Decimal
    unit: str
    description: str
    cost_amount: Optional[Decimal]
    cost_currency: str
    parse_warnings: list[str]


def _canonical_headers(raw_headers: list[str]) -> list[str]:
    return [
        HEADER_ALIASES.get(h.strip().lower(), h.strip().lower())
        for h in raw_headers
    ]


def _process_row(record: dict, segment_index: int) -> tuple[Optional[ParsedTravelRow], Optional[str]]:
    warnings: list[str] = []

    seg_type = (record.get("segment_type") or "").strip().lower()
    if seg_type not in {"air", "flight", "hotel", "car", "rail", "train"}:
        return None, f"unsupported segment_type {seg_type!r}"
    if seg_type == "flight":
        seg_type = "air"
    if seg_type == "train":
        seg_type = "rail"

    start = parse_date(record.get("start_date"))
    end = parse_date(record.get("end_date"))
    if not start:
        return None, "missing start_date"

    trip_id = (record.get("trip_id") or "").strip()
    source_id = f"{trip_id}-{segment_index}" if trip_id else ""

    if seg_type == "air":
        origin = (record.get("origin_iata") or "").strip().upper()
        dest = (record.get("destination_iata") or "").strip().upper()
        cabin = _normalise_cabin(record.get("cabin_class", ""))

        distance_miles = parse_decimal(record.get("distance_miles"))
        if distance_miles and distance_miles > 0:
            distance_km = Decimal(str(distance_miles)) * Decimal("1.609344")
        else:
            warnings.append("distance_reconstructed_from_iata")
            km = pair_distance_km(origin, dest)
            if km is None:
                return None, f"unknown airport pair {origin}->{dest}"
            distance_km = Decimal(str(km))

        haul = haul_category(float(distance_km), origin, dest)
        # activity_type drives factor lookup; see seeded factor names.
        activity = f"flight_{haul}_{cabin}"
        description = f"{origin}→{dest} {cabin}"

        return (
            ParsedTravelRow(
                raw=record,
                source_record_id=source_id,
                employee_id=(record.get("employee_id") or "").strip(),
                segment_type="air",
                start_date=start,
                end_date=end,
                activity_type=activity,
                quantity=distance_km.quantize(Decimal("0.001")),
                unit="passenger_km",
                description=description,
                cost_amount=parse_decimal(record.get("amount")),
                cost_currency=(record.get("currency") or "").strip(),
                parse_warnings=warnings,
            ),
            None,
        )

    if seg_type == "hotel":
        nights = parse_decimal(record.get("nights"))
        if nights is None and end:
            nights = Decimal((end - start).days)
            warnings.append("nights_inferred_from_dates")
        if nights is None or nights <= 0:
            return None, "hotel missing nights"
        country = (record.get("country") or "").strip().upper()[:2] or "GB"

        return (
            ParsedTravelRow(
                raw=record,
                source_record_id=source_id,
                employee_id=(record.get("employee_id") or "").strip(),
                segment_type="hotel",
                start_date=start,
                end_date=end,
                activity_type=f"hotel_night_{country.lower()}" if country else "hotel_night",
                quantity=nights,
                unit="room_night",
                description=record.get("hotel_name", "") or "hotel",
                cost_amount=parse_decimal(record.get("amount")),
                cost_currency=(record.get("currency") or "").strip(),
                parse_warnings=warnings,
            ),
            None,
        )

    if seg_type == "car":
        # Most exports don't carry odometer readings, so this is
        # invariably flagged for analyst follow-up.
        warnings.append("car_distance_unknown")
        return (
            ParsedTravelRow(
                raw=record,
                source_record_id=source_id,
                employee_id=(record.get("employee_id") or "").strip(),
                segment_type="car",
                start_date=start,
                end_date=end,
                activity_type="car_rental_average",
                quantity=Decimal("0"),
                unit="km",
                description=record.get("car_class", "") or "rental car",
                cost_amount=parse_decimal(record.get("amount")),
                cost_currency=(record.get("currency") or "").strip(),
                parse_warnings=warnings,
            ),
            None,
        )

    if seg_type == "rail":
        distance_miles = parse_decimal(record.get("distance_miles"))
        if distance_miles is None:
            warnings.append("rail_distance_unknown")
            distance_km = Decimal("0")
        else:
            distance_km = Decimal(str(distance_miles)) * Decimal("1.609344")
        return (
            ParsedTravelRow(
                raw=record,
                source_record_id=source_id,
                employee_id=(record.get("employee_id") or "").strip(),
                segment_type="rail",
                start_date=start,
                end_date=end,
                activity_type="rail_national",
                quantity=distance_km.quantize(Decimal("0.001")),
                unit="passenger_km",
                description=record.get("description", "") or "rail",
                cost_amount=parse_decimal(record.get("amount")),
                cost_currency=(record.get("currency") or "").strip(),
                parse_warnings=warnings,
            ),
            None,
        )

    return None, f"unhandled segment {seg_type}"


def parse_travel_csv(blob: bytes) -> tuple[list[ParsedTravelRow], list[str], dict]:
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

    rows: list[ParsedTravelRow] = []
    errors: list[str] = []
    for line_no, raw_row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in raw_row):
            continue
        if len(raw_row) != len(canonical):
            raw_row = (raw_row + [""] * len(canonical))[: len(canonical)]
        record = dict(zip(canonical, raw_row))
        parsed, err = _process_row(record, line_no)
        if err:
            errors.append(f"line {line_no}: {err}")
            continue
        if parsed:
            rows.append(parsed)

    return rows, errors, notes


def parse_travel_json(blob: bytes) -> tuple[list[ParsedTravelRow], list[str], dict]:
    """
    Accepts either a top-level JSON array of segment objects, or a
    Concur-itinerary-style nested doc `{"itineraries": [{"bookings": [...]}, ...]}`.
    """
    notes: dict = {"encoding": "utf-8"}
    try:
        payload = json.loads(blob.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [], [f"JSON parse failed: {exc}"], notes

    segments: list[dict] = []
    if isinstance(payload, list):
        segments = payload
        notes["shape"] = "array_of_segments"
    elif isinstance(payload, dict):
        if "itineraries" in payload:
            notes["shape"] = "concur_itinerary_v4"
            for itin in payload.get("itineraries", []):
                trip_id = itin.get("trip_id") or itin.get("itinerary_locator") or ""
                employee_id = itin.get("employee_id", "")
                for b in itin.get("bookings", []) or []:
                    seg = dict(b)
                    seg.setdefault("trip_id", trip_id)
                    seg.setdefault("employee_id", employee_id)
                    segments.append(seg)
        elif "segments" in payload:
            notes["shape"] = "segments_wrapper"
            segments = payload["segments"]
        else:
            return [], ["unrecognised JSON shape"], notes

    canonical_segments: list[dict] = []
    for seg in segments:
        # normalise keys via the same alias table
        canonical = {
            HEADER_ALIASES.get(k.strip().lower(), k.strip().lower()): v
            for k, v in seg.items()
        }
        canonical_segments.append(canonical)

    rows: list[ParsedTravelRow] = []
    errors: list[str] = []
    for i, record in enumerate(canonical_segments, start=1):
        parsed, err = _process_row(record, i)
        if err:
            errors.append(f"segment {i}: {err}")
            continue
        if parsed:
            rows.append(parsed)

    return rows, errors, notes
