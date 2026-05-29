"""
Utility bill PDF parsing.

Targets UK commercial electricity bills (EDF Business, British Gas
Business, E.ON Next style). We use pdfplumber to pull the text layer
and then run regex passes for the five fields we actually need:

  - MPAN (or US account number)
  - Billing period start
  - Billing period end
  - Total kWh consumed
  - Supplier / supply address (best-effort)

Extraction is intentionally lenient. If we can't find a field, the row
lands in `flagged` status with the raw text attached so an analyst can
fix it manually — that is the explicit deal the user signed off on
(`Q3: PDF parsing doesn't need to be 100% accurate; 2-3 extraction
attempts is fine`).

OCR (scanned bills) is out of scope. We rely on the embedded text layer
that PDF generators produce; image-only PDFs will return empty text and
fail loudly.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

import pdfplumber

from .common import parse_date, parse_decimal


# ----- Regex patterns -----
# UK MPAN: 13-digit core, sometimes shown as profile-class (2) + MTC (3) +
# LLF (3) + Distributor (2) + UniqueID (10) + Check (1). The clean 13-core
# is what most bills print.
MPAN_PATTERN = re.compile(r"\b(\d{2}\s?\d{3}\s?\d{3}\s?\d{2}\s?\d{10}\s?\d{1}|\d{13})\b")
US_ACCOUNT_PATTERN = re.compile(
    r"(?:account|service)\s*(?:number|no\.?|#)\s*[:\-]?\s*([0-9\-]{6,20})",
    re.IGNORECASE,
)

# Billing period: "Billing Period: 01 Jan 2024 to 31 Jan 2024", or
# "From 01/01/2024 To 31/01/2024", etc.
PERIOD_PATTERNS = [
    re.compile(
        r"(?:billing\s+period|period\s+from|service\s+period|invoice\s+period)\s*[:\-]?\s*"
        r"(\d{1,2}[\s/.\-][A-Za-z]{3,9}[\s/.\-]\d{2,4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})"
        r"\s*(?:to|-|–|until|–\s)\s*"
        r"(\d{1,2}[\s/.\-][A-Za-z]{3,9}[\s/.\-]\d{2,4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
        re.IGNORECASE,
    ),
    re.compile(
        r"(?:from)\s+"
        r"(\d{1,2}[\s/.\-][A-Za-z]{3,9}[\s/.\-]\d{2,4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})"
        r"\s+(?:to|until)\s+"
        r"(\d{1,2}[\s/.\-][A-Za-z]{3,9}[\s/.\-]\d{2,4}|\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4})",
        re.IGNORECASE,
    ),
]

# Total kWh used: try "Total Units 12,345 kWh", "Energy used 12345 kWh", etc.
KWH_PATTERNS = [
    re.compile(
        r"(?:total\s+(?:units|energy|consumption|kwh)|units\s+used|energy\s+used|consumption)\s*"
        r"[:\-]?\s*([0-9.,]+)\s*kwh",
        re.IGNORECASE,
    ),
    re.compile(r"([0-9.,]+)\s*kwh\s+(?:consumed|used|of\s+electricity)", re.IGNORECASE),
    re.compile(r"^([0-9.,]+)\s*kwh\s*$", re.IGNORECASE | re.MULTILINE),
]

SUPPLIER_HINTS = [
    "British Gas",
    "EDF",
    "E.ON",
    "Octopus",
    "SSE",
    "Scottish Power",
    "Drax",
    "ConEd",
    "PG&E",
    "Duke Energy",
]


@dataclass
class ParsedUtilityPdf:
    meter_id: str
    supplier: str
    period_start: Optional[date]
    period_end: Optional[date]
    kwh: Optional[Decimal]
    raw_text: str
    parse_warnings: list[str]


def _first_match(patterns: list[re.Pattern], text: str) -> Optional[re.Match]:
    for pat in patterns:
        m = pat.search(text)
        if m:
            return m
    return None


def parse_utility_pdf(blob: bytes) -> ParsedUtilityPdf:
    warnings: list[str] = []
    text = ""
    try:
        with pdfplumber.open(io.BytesIO(blob)) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text() or ""
                if page_text:
                    text += page_text + "\n"
    except Exception as exc:  # pdfplumber wraps various I/O / parse errors
        warnings.append(f"pdf_open_failed:{type(exc).__name__}")
        return ParsedUtilityPdf(
            meter_id="",
            supplier="",
            period_start=None,
            period_end=None,
            kwh=None,
            raw_text="",
            parse_warnings=warnings,
        )

    if not text.strip():
        warnings.append("empty_text_layer")  # likely a scanned/image-only PDF

    # --- MPAN / account ---
    meter_id = ""
    mpan_m = MPAN_PATTERN.search(text)
    if mpan_m:
        meter_id = re.sub(r"\s+", "", mpan_m.group(1))
    else:
        acct_m = US_ACCOUNT_PATTERN.search(text)
        if acct_m:
            meter_id = acct_m.group(1)
        else:
            warnings.append("meter_id_not_found")

    # --- Billing period ---
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    p_match = _first_match(PERIOD_PATTERNS, text)
    if p_match:
        period_start = parse_date(p_match.group(1), locale_hint="uk")
        period_end = parse_date(p_match.group(2), locale_hint="uk")
    if not period_start or not period_end:
        warnings.append("period_not_found")

    # --- kWh total ---
    kwh: Optional[Decimal] = None
    k_match = _first_match(KWH_PATTERNS, text)
    if k_match:
        kwh = parse_decimal(k_match.group(1))
    if kwh is None:
        warnings.append("kwh_not_found")

    # --- Supplier hint (best-effort label only) ---
    supplier = ""
    lower = text.lower()
    for s in SUPPLIER_HINTS:
        if s.lower() in lower:
            supplier = s
            break

    return ParsedUtilityPdf(
        meter_id=meter_id,
        supplier=supplier,
        period_start=period_start,
        period_end=period_end,
        kwh=kwh,
        raw_text=text[:10000],  # cap stored text so JSONB stays sane
        parse_warnings=warnings,
    )
