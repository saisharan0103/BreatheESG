# Sources

> For each of the three ingestion sources: what real-world format we researched, what we learned, what the sample data looks like and why, and what would break in a real deployment.
>
> Plus a section for the emission-factor reference data, since those are also "sources" that the data model cites by URL.

---

## 1. SAP — fuel & procurement

### Real-world format researched
SAP procurement and goods-movement data is stored across multiple tables:

- **EKKO** (Purchasing Document Header), **EKPO** (PO Item)
- **MKPF** / **MSEG** (Material Document Header / Segment — goods receipts)
- **BKPF** / **BSEG** (Accounting Document Header / Segment)
- **MARA** / **MAKT** / **MARC** (Material Master, descriptions, plant data)

In practice, a finance/procurement team produces an emissions-ready export by joining EKKO+EKPO+MSEG+MARA+MAKT and downloading via SAP GUI's "Export to spreadsheet" or transaction SE16/SE16N. The result is a flat CSV with one row per PO line item.

### What we learned
The real-world shape we built against:

- **Technical field names are language-independent** (`MATNR`, `WERKS`, `MEINS`, `MENGE`, `BUDAT`, `BWART`, `NETPR`, `NETWR`, `WAERS`). They look like German abbreviations because SAP was developed by SAP SE, but in an English-locale download they appear unchanged.
- **German-locale exports use field LABELS** (`Werk`, `Materialkurztext`, `BME`, `Menge`, `Buchungsdatum`, `Bewegungsart`, `Nettopreis`). These come from the German translations of the data-element labels.
- **Date formats** — SAP internal is `YYYYMMDD`; ALV downloads honour user-profile locale → US gets `MM/DD/YYYY`, German gets `DD.MM.YYYY`.
- **Decimal/thousand separators** — when the SAP user's profile (transaction SU3) is set to German format, `1.234.567,89` is the export convention. US format is `1,234,567.89`.
- **Delimiter** — German Excel uses `;` because `,` is reserved for decimals; US Excel uses `,`.
- **Encoding** — older SAP GUI versions default to CP1252 / ANSI; newer versions are UTF-8. Mojibake on `ä ö ü ß` is the classic symptom of misread encoding.
- **`MEINS`** — the base unit of measure is a 3-character code: `L` (litre), `KG`, `ST` (each / piece), `KWH`, `GAL` (US gallon), `M3`, etc. Maintained in SAP table `T006`.
- **`MATKL`** — material group; freely customised per-customer but commonly `FUEL01` for diesel, `FUEL03` for petrol, etc. The parser does substring-match the description (`MAKTX`) as a fallback when `MATKL` is unrecognised.
- **`BWART`** — movement type. `101` = goods receipt against PO (the one we want). `201` = consumption to cost centre. `122` = return delivery. `561` = receipt against inventory adjustment. Filtering on 101 keeps our dataset clean.
- **`MANDT`** (client) often arrives in column 1 but is constant per export; we ignore it.

### What our sample data looks like and why
[backend/sample_data/sap_en.csv](backend/sample_data/sap_en.csv) — 5 rows of bulk-diesel and petrol purchases at two plants over two months. The fields and shape match SAP's actual SE16 download of an EKKO+EKPO+MSEG join:

```
EBELN,EBELP,LIFNR,WERKS,LGORT,MATNR,MAKTX,MATKL,MENGE,MEINS,NETPR,PEINH,NETWR,WAERS,BUDAT,KOSTL,BWART
4500001234,00010,V100245,1000,F001,000000000000300077,Diesel EN590 bulk,FUEL01,15000.000,L,1.4250,1,21375.00,GBP,20240312,CC-DE-LOG-01,101
```

- The MATNR is zero-padded to 18 characters as SAP actually stores it.
- The MATKL `FUEL01` maps to activity_type `diesel` in our parser; `FUEL03` maps to `petrol`. `FUEL02` (AdBlue) is intentionally included so you can see how a real procurement export contains rows we *don't* have factors for — those land in `flagged` status.
- Dates use SAP internal `YYYYMMDD`.
- One AdBlue row (FUEL02 — urea-water additive, near-zero GHG, no DEFRA factor) demonstrates the `factor_missing` flag path.

Authentic fields beyond what we use for emissions math (`LIFNR`, `KOSTL`, `LGORT`, `PEINH`) are preserved into `raw_payload` so an analyst sees the full context.

The German-headers + German-numbers + semicolon-delimited variant lives in [the test fixtures](backend/core/tests.py) (`SapCsvParserTests.DE_SAMPLE`); we documented but didn't ship a separate file to avoid duplication.

### What would break in a real deployment

- **IDoc / OData / BAPI live integrations** — completely unsupported. SAP teams who refuse CSV downloads typically gate IDoc consumption behind SAP NetWeaver Gateway access, which requires production credentials and firewall changes most customers won't grant.
- **Multi-currency** — we store `cost_currency` as-is. A real product converts via daily FX rates from ECB / OANDA. Cost itself doesn't drive emissions math (only quantity does), so this is a finance-reporting concern, not an audit one.
- **Custom MATKL values** — every customer customises material groups. A real deployment ships a customer-specific mapping table; ours has a small built-in dictionary that catches common conventions, with text-description fallback.
- **`MEINS` units we don't recognise** (e.g. `EA` for each, `M2` for area) → the row is rejected with an explicit error. A real product would have a more comprehensive UOM table and a "map this unit" UI for analysts.
- **CSV that wasn't a goods-receipt extract** — financial postings (BSEG), inventory movements (MSEG with BWART != 101), invoice receipts (KR) all have different shapes. We assume the customer chose the right transaction to export. A real product would offer a guided "what kind of SAP export is this?" step.

### Citations
- LeanX — [EKPO table reference](https://leanx.eu/en/sap/table/ekpo.html), [BSEG reference](https://leanx.eu/en/sap/table/bseg.html), [BKPF reference](https://www.leanx.eu/en/sap/table/bkpf.html)
- SAP4TECH — [SAP Goods Movement Tables](https://sap4tech.net/sap-goods-movement-tables/)
- SAP Learning (DE) — [Klassische Bestandslisten](https://learning.sap.com/courses/inventory-management-and-physical-inventory-in-sap-s-4hana-de/using-classic-stock-lists-and-document-lists) (for the German caption set)
- SAP Community — [field labels EN/DE thread](https://community.sap.com/t5/application-development-and-automation-discussions/how-to-change-the-field-labels-from-english-to-german-language/td-p/10478991)

---

## 2. Utility — electricity (CSV + PDF)

### Real-world format researched
UK commercial electricity bills (and their CSV portal exports) from suppliers like EDF Business, British Gas Business, E.ON Next, SSE Business, Drax. The structure on a typical UK bill:

- **MPAN** (Meter Point Administration Number) — 21-digit identifier. The 13-digit "core" is what most exports include.
- **Billing Period Start / End** — service period, in days, typically 30-32 days but can overlap when suppliers switch.
- **Previous Read / Current Read** — each flagged `Actual` / `Customer` / `Estimated`.
- **Day kWh / Night kWh** for multi-rate meters (Economy 7).
- **Standing charge**, **CCL (Climate Change Levy)**, **VAT**.
- **Tariff name** — free-text.

US bills carry a `Service Account Number`, an `eGRID subregion` (often derivable from zip code), `Demand (kW)` charges, and time-of-use rates.

### What we learned
- **Estimated reads are the single biggest data-quality problem.** When the meter wasn't physically read, the supplier estimates consumption based on historical profile. The next period's "actual" read absorbs the estimation error. Back-bills (corrections within 12 months per Ofgem rules) require deduplicating on `(meter, period)` and preferring the most recent.
- **Period overlaps** happen on supplier switches — outgoing supplier's "final bill" + incoming supplier's "opening bill" can share a day.
- **kWh vs MWh** — half-hourly meter exports often switch units in the totals row.
- **CSV portal exports** are usually one row per (meter, period) — much simpler shape than the bill PDF itself.

### What our sample data looks like and why

For CSV — typical shape:
```
MPAN,SiteName,PeriodStart,PeriodEnd,UnitsConsumed_kWh,Tariff,EstimatedFlag
2000012345678,London HQ,2024-01-01,2024-01-31,52400,Fixed 24 Business,A
2000012345678,London HQ,2024-02-01,2024-02-29,48900,Fixed 24 Business,A
2000012345679,Manchester DC,2024-01-01,2024-01-31,128300,HH Variable,E
```

Three rows representing two meters. The third row has an `E` flag → ingested as `estimated_read` flag. The MPAN format is the 13-digit "core" UK shape. SiteName is fabricated; MPANs are syntactically valid but not assigned to a real customer.

For PDF — we tested against real publicly-available sample bills (linked in citations below). The parser recognises:

- `MPAN: <13-digit>` or unspaced MPAN in the body text.
- `Billing Period: <start> to <end>` plus a half-dozen common phrasings (`From X to Y`, `Service Period X – Y`, …).
- `Total Units 12,345 kWh` or `12,345 kWh consumed/used`.

The PDF parser is intentionally lenient. If extraction is partial (some field missing), the row lands in `flagged` status with the raw text excerpt stored in `raw_payload` so an analyst can fix it manually. This is the explicit tradeoff the user signed off on ("PDF parsing doesn't need to be 100% accurate; 2-3 extraction attempts is fine").

### What would break in a real deployment

- **Half-hourly settlement (HH) data** — post-MHHS rollout (UK, 2025-26) all meters move to HH and the kWh/period model becomes antiquated. A real product would ingest 17,520 settlement-period rows per meter per year and apply hourly grid carbon-intensity from National Grid ESO API.
- **OCR for scanned PDFs** — see [TRADEOFFS.md](TRADEOFFS.md). Scanned bills produce empty text from `pdfplumber` and land as flagged rows with `pdf_partial_parse`.
- **Multi-fuel mixed bills** — some suppliers bundle gas + electric in one PDF. Our parser only looks for electricity totals; gas would be missed.
- **Demand charges (US bills)** — the kW peak-demand portion of US commercial bills isn't an emissions input but customers expect it visible. Not modelled.
- **Re-bills** — Ofgem allows back-bills for up to 12 months. Real product needs to detect a re-bill (same `(meter, period)` re-submitted) and prefer the latest; the unique constraint we ship would reject it as a duplicate. Need a more sophisticated dedupe.
- **Embedded vs separate gas** — UK suppliers bill gas in kWh on **gross** calorific value basis; if a customer provides net-CV data we'd apply a ~1.108x correction. Not currently handled.

### Citations
- Wikipedia — [Electricity billing in the United Kingdom](https://en.wikipedia.org/wiki/Electricity_billing_in_the_UK)
- Business Energy Deals — [Business electricity bill breakdown](https://www.businessenergydeals.co.uk/blog/business-electricity-bill/)
- CEB Consultants — [Understanding your electricity bill](https://www.cebconsultants.co.uk/understanding-your-electricity-bill)
- British Gas Business — [How to read my bill](https://www.britishgas.co.uk/business/help-and-support/billing-and-payments/how-to-read-my-bill)
- Ofgem — [Understand your electricity and gas bills](https://www.ofgem.gov.uk/understand-your-electricity-and-gas-bills)
- Real example bills tested against:
  - British Gas — [Example Bill (Scribd)](https://www.scribd.com/document/424987637/British-Gas-Example-Bill)
  - Greencity Utilities — [How to understand your energy bills (PDF)](https://greencityutilities.co.uk/site/wp-content/uploads/2018/06/How-to-understand-your-energy-bills-v3-.pdf)

---

## 3. Corporate travel — Concur / Navan / TravelPerk

### Real-world format researched
Two surfaces from Concur (which is by far the largest enterprise travel platform; Navan and TravelPerk follow very similar shapes for interoperability):

- **Standard Reports / Cognos Analysis Studio** — BI reports out as CSV/XLSX. The "Travel - Itinerary Segments" subject area is what most ESG teams pull.
- **Itinerary API v4 / Extract files** — JSON, requires OAuth + partner-app credentials. We model the JSON shape but the file-upload path is the practical one.

### What we learned

- **Per-segment, not per-trip.** A 4-leg international business trip with one hotel and one car becomes 6 rows: 4 `Air`, 1 `Hotel`, 1 `Car`. All linked by `Trip ID`.
- **Field naming** in Standard Reports uses spaces, capitalisation, and varies by report variant (`Departure Airport Code`, `Itinerary Locator`, `Cabin Class`, `Class of Service`, `Total Amount`). Our parser collapses headers via punctuation-stripping normalisation so `Departure Airport Code`, `departure_airport_code`, and `DepartureAirportCode` all match the same alias.
- **Flights from Concur rarely include `Distance in Miles`** — the GDS hands Concur the airport pair + flight number but not km. ESG ingestion has to reconstruct distance via great-circle calculation from IATA coordinates.
- **Cabin class** is sometimes a single booking class letter (`Y` economy, `J` business, `F` first) and sometimes free text. We normalise.
- **Hotels** never carry energy intensity — always factor-based (room-nights × country factor). Country code is the discriminator (`Country: US`, `GB`, etc.).
- **Car rentals** carry an ACRISS class code (`ECAR`, `CCAR`, `ICAR`) but rarely odometer mileage. They are almost always flagged for analyst follow-up.

### What our sample data looks like and why

Example matches the per-segment shape Concur Standard Reports produces:
```
Trip ID,Employee ID,Segment Type,Start Date,End Date,Departure Airport Code,Arrival Airport Code,Cabin Class,Distance in Miles,Hotel Name,Number of Nights,Country,Total Amount,Currency Code
T-4471290,E10245,Air,2024-04-08,2024-04-08,LHR,JFK,J,,,,,,4280.50,USD
T-4471290,E10245,Hotel,2024-04-08,2024-04-12,,,,,Hilton Midtown,4,US,1156.00,USD
T-4471291,E10245,Air,2024-04-15,2024-04-15,LHR,CDG,Y,,,,,,245.00,EUR
```

Three segments, two trips:
- LHR→JFK business — distance NOT in source, reconstructed to 5540 km, classified `flight_long_haul_business`.
- 4-night Hilton Midtown in the US — `hotel_night_us` activity, 4 room-nights.
- LHR→CDG economy — 347 km, but cross-border → `flight_short_haul_economy` (NOT domestic, despite the short distance).

Trip and employee IDs follow Concur's `T-<7 digits>` and `E<5 digits>` conventions but are not assigned to a real person.

### What would break in a real deployment

- **OAuth + Reporting API live pull** — requires Concur partner agreement, OAuth refresh-token handling, pagination on result sets, and rate-limit backoff. Documented but not built; the file-upload path is what 80%+ of ESG teams actually use.
- **Hotel energy intensity overrides** — large hotel chains publish per-property energy data (Hilton's LightStay, Marriott's Serve360) but it's not in Concur. A real product would optionally cross-reference.
- **Car rental vehicle-km** — most exports don't have it; some customers also feed odometer data from a separate fuel-card / mileage-claim system. Not in scope here.
- **Train segments** — Concur captures rail (UK rail, Eurostar) but the export shape is irregular. We parse rail with the same activity_type `rail_national` regardless of carrier, which is a simplification.
- **Cancelled segments** — Concur exports both `Confirmed` and `Cancelled` segments in the same file. We don't currently filter on `Trip Status`; a real product would exclude cancelled rows.

### Citations
- CSU Sacramento — [Concur Travel Reference Guide (PDF)](https://www.csus.edu/administration-business-affairs/internal/concur-travel/_internal/_documents/concur-rg-travel.pdf)
- SAP Concur — [Itinerary API resource](https://developer.concur.com/api-reference/travel/itinerary/booking/booking-resource.html)
- SAP Concur — [Itinerary v4 specification](https://github.com/SAP-docs/preview.developer.concur.com/blob/main/src/api-reference/travel/itinerary-v4/v4.itinerary.md)
- Airport coordinates — [OpenFlights airports.dat](https://openflights.org/data.html) (Open Database License)

---

## Emission factors

### Sources
**DEFRA / UK DESNZ 2024 GHG conversion factors** (condensed workbook v1.1, October 2024 correction):
- [Publication landing page (GOV.UK)](https://www.gov.uk/government/publications/greenhouse-gas-reporting-conversion-factors-2024)
- [Condensed XLSX direct download (v1.1)](https://assets.publishing.service.gov.uk/media/6722566a3758e4604742aa1e/ghg-conversion-factors-2024-condensed_set__for_most_users__v1_1.xlsx)
- [2024 methodology PDF](https://assets.publishing.service.gov.uk/media/66a9fe4ca3c2a28abb50da4a/2024-greenhouse-gas-conversion-factors-methodology.pdf)

**US EPA Emission Factors Hub 2024** (uses eGRID 2022 data):
- [Hub landing page](https://www.epa.gov/climateleadership/ghg-emission-factors-hub)
- [2024 PDF](https://www.epa.gov/system/files/documents/2024-02/ghg-emission-factors-hub-2024.pdf)
- [2024 XLSX](https://www.epa.gov/system/files/documents/2024-02/ghg-emission-factors-hub-2024.xlsx)

### What we seeded
See [migration 0002_seed_emission_factors.py](backend/core/migrations/0002_seed_emission_factors.py) for the exact values. Each row in the migration carries the workbook URL + sheet name as `citation_url` / `citation_sheet`, so an auditor can verify each factor against the original.

The shipped factor set is intentionally narrow — only the activity_types our three parsers produce. Adding more is a matter of extending the seed migration; no model change needed.

### What we learned

- **DEFRA workbook is pivot-style.** The same fuel-activity combination appears in multiple rows: one row per gas (`Total kg CO2e`, `kg CO2`, `kg CH4`, `kg N2O`). The `Column Text` field discriminates. For ingestion we use the `Total kg CO2e` row.
- **UK grid factor — generation vs combined.** DEFRA publishes Scope 2 "generation only" (location-based) at 0.20705 kg/kWh, separate from T&D losses at 0.01830 kg/kWh (which is Scope 3 cat 3). Customers reporting under GHG Protocol need to know which they're using; we ship the generation-only number and document the T&D as a future addition.
- **Gas factors are gross-CV.** UK suppliers bill gas in kWh on gross calorific value basis; DEFRA's factor is on the same basis. A naïve cross-source comparison with EPA (which uses HHV) would need conversion.
- **Hotel-night factors are country-specific.** DEFRA publishes per-country kg CO₂e per room per night (GB, US, DE, FR, …). We seed the three most common destinations and fall back to a GLOBAL average for unknowns.
- **EPA factors are imperial.** Per-US-gallon for fuels, per-mmBtu for stationary combustion, per-passenger-mile for travel. We convert to canonical SI units at seed time and store the converted value with the math documented in the citation field.

### What would break in a real deployment

- **Market-based Scope 2** — see [TRADEOFFS.md](TRADEOFFS.md). Real customers reporting renewable energy contracts (REGOs, GoOs, contracted EFs) need per-tenant factor overrides; the prototype is location-based only.
- **Factor updates** — DEFRA publishes annually (June, with a correction round in October usually). We currently re-seed on each migration deploy; a real product would have a "factor library sync" command that pulls the latest workbook automatically.
- **Other regions** — France's ADEME / Base Empreinte, Germany's UBA, Australia's NGA factors, ISO 14064-2 sector factors — none seeded. Adding region by region is straightforward extension.
- **Embodied carbon factors** — Scope 3 cat 1 (purchased goods & services) requires either spend-based (£ → kg CO₂e via input-output tables) or supplier-specific factors. The prototype carries neither. See [TRADEOFFS.md](TRADEOFFS.md) item 5.
