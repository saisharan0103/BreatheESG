# Data Model

> Why each table exists, what it stores, and how multi-tenancy, scope categorisation, source-of-truth, unit normalisation, and audit trail are handled.
>
> Code: [backend/core/models.py](backend/core/models.py).

## Shape at a glance

```
Tenant ────────────────────────────────────┐
   │                                        │
   ├── User (analyst | admin)               │
   │                                        │
   ├── ReportingPeriod  (audit lock unit)   │
   │                                        │
   └── IngestionBatch ──┐                   │
                        │                   │
EmissionFactor ◀────────┼─── ActivityRecord ┘
                        │       │
                        │       ├── ActivityRecordRevision (append-only edit log)
                        │       └── ReviewAction (append-only state-change log)
                        │
                        └── (reverse FK)
```

`ActivityRecord` is the spine. Every fuel purchase, kWh of electricity, flight leg, or hotel night becomes one row in this table — regardless of which source system produced it. The model splits each row's fields into five clusters:

- **provenance** — where this row came from, how to cite it.
- **activity** — what physically happened (type, when, how much).
- **emissions** — which factor we applied and the resulting CO₂e.
- **review state** — pending / approved / rejected / flagged / locked.
- **flags** — list of suspicious-shape codes the flagger emitted.

That five-cluster split is intentional: it lets the analyst UI render a row in two panels side by side ("as ingested" vs "normalized"), and it makes the audit story — "given this raw payload + this factor, this number is what we sent to the auditor" — trivially reconstructable.

## Each model and why

### `Tenant` ([models.py:21](backend/core/models.py))
A client company. UUID PK so tenant IDs are non-enumerable in URLs and analytics. `country_code` drives the default emission-factor region (a GB tenant gets DEFRA factors; US gets EPA). Multi-tenancy is **row-level**: every business-data table carries `tenant_id` and DRF permissions enforce isolation. Defended in [DECISIONS.md](DECISIONS.md#multi-tenancy).

### `User` ([models.py:35](backend/core/models.py))
Custom user extending `AbstractUser`. Two role-based responsibilities matter:

- `analyst` — review, approve, reject, edit rows.
- `admin` — everything `analyst` can do, plus lock and unlock reporting periods.

Auth is DRF `TokenAuthentication`. JWT would have been over-engineered for a prototype with two roles; tokens never expire on the server side, but the assignment specifies a "very simple authorisation system."

### `EmissionFactor` ([models.py:69](backend/core/models.py))
Reference data only. **Versioned per `(activity_type, region, year, source)`**. The unique constraint is the load-bearing thing — we never `UPDATE` an existing factor row when DEFRA publishes a correction; we insert a new one and let the lookup function (`find_emission_factor`) pick the most appropriate. That's the only honest way to support audit: a 2024 record approved in March was tied to the factor row that existed in March; a later DEFRA correction creates a NEW factor row, and old records keep pointing at the old one.

Every row carries:
- `citation_url` — direct link to the workbook the factor came from.
- `citation_sheet` — sheet + row reference inside the workbook.

So `SOURCES.md` can be regenerated from the database and auditors can verify each number against the original.

Seeded from the real DEFRA 2024 condensed workbook (v1.1) and EPA 2024 Emission Factors Hub via [migration 0002_seed_emission_factors.py](backend/core/migrations/0002_seed_emission_factors.py).

### `ReportingPeriod` ([models.py:140](backend/core/models.py))
The **audit lock unit**. Locking is per reporting period (CY2024, FY24-Q1, etc.), not per row. That matches how audits actually work in practice — sign-off is on the period, and a record is locked iff its `period_end` falls in a locked period. See [DECISIONS.md → audit lock semantics](DECISIONS.md#audit-lock-semantics).

A lock cascades:
- approved records → `LOCKED`
- pending / flagged records → **block the lock attempt** (you can't lock a period with un-reviewed data).
- rejected records → left in `REJECTED` (the analyst declined them).

Unlocking reverses the cascade for `LOCKED` rows back to `APPROVED`, so re-opening a period doesn't lose review decisions.

### `IngestionBatch` ([models.py:170](backend/core/models.py))
Every upload or pull becomes one batch. A batch is the unit of "undo" — if you fat-fingered the wrong SAP file you delete one row and 200 ActivityRecord rows go with it.

`file_sha256` is what we keep instead of the file itself. Vercel's serverless filesystem is ephemeral, and the audit story doesn't actually need the file: it needs the parsed values + a hash of the bytes that produced them. A real auditor would ask for the file separately (from your S3 / SharePoint / wherever); the hash proves it's the same file. Defended in [TRADEOFFS.md](TRADEOFFS.md).

`parser_notes` is a JSON blob the analyst can inspect — what encoding we detected, what delimiter, what locale, what each raw header mapped to. That transparency matters when you're explaining "why did the SAP team's file produce 200 rows instead of 250."

### `ActivityRecord` ([models.py:230](backend/core/models.py))
The spine. Worth calling out specific design choices:

- **Two quantity/unit pairs (raw + normalized).** `quantity_raw / unit_raw` preserves what the source actually said (15000 L, 100 GAL, 1.5 MWh, 5 nights). `quantity_normalized / unit_normalized` is in the unit the linked `EmissionFactor` expects. We keep both so an analyst can audit the conversion ("100 GAL → 378.541 L, factor is per litre, so co2e is …").
- **`raw_payload` JSON column.** Every parser drops the original parsed row into this column, preserving fields we *don't* use for emissions math. Cost centre, vendor, German material text — all retained. When something is wrong, the analyst sees the raw context, not a stripped-down extract.
- **`source_record_id` + unique constraint.** A partial unique on `(tenant, source_system, source_record_id)` blocks silent re-ingestion of the same SAP PO line or the same utility (meter, period) pair. Re-ingestions raise an error that the analyst sees in `IngestionBatch.error_summary`. Travel exports get an index-suffixed id (`<TripID>-<segment_index>`).
- **`is_edited` boolean + `ActivityRecordRevision` log.** When an analyst edits a normalized field, we *don't* mutate `raw_payload` — the original is preserved. The before/after pair goes into a revision row, append-only. So the timeline reads: "ingested as 15000 L → analyst-edited to 15500 L (reason: supplier rebill, dated …) → approved."
- **`flags: JSONField` (list of codes).** Soft flags. Codes like `unit_inferred`, `factor_year_drift`, `period_overlap`, `drift_vs_prior`. The flagger ([core/flagging.py](backend/core/flagging.py)) computes them from rules. Whether a flag is blocking is a separate decision (`status_for_flags`); soft flags leave the row PENDING for review, hard flags move it to FLAGGED.

### `ActivityRecordRevision` ([models.py:325](backend/core/models.py))
Append-only edit log. Every `record_edit` view-call writes one row per *changed field*. We never `UPDATE` this table; rebuilding the value at audit time means walking the revisions back.

### `ReviewAction` ([models.py:360](backend/core/models.py))
Separate append-only log for status transitions (approve / reject / flag / lock / unlock). Independent of `ActivityRecordRevision` so the audit log can show "who approved this row" without confusing it with "who edited a number." The actor and timestamp are on the row.

## Multi-tenancy

Row-level, with three guarantees:

1. Every business-data table (`User`, `EmissionFactor` if tenant-specific, `ReportingPeriod`, `IngestionBatch`, `ActivityRecord`, ...) carries `tenant` as a FK.
2. DRF view querysets always filter by `request.user.tenant` (`_tenant_filter` helper at [views.py:73](backend/core/views.py)). There is no path to read another tenant's data via the API.
3. The `IsTenantMember` permission ([permissions.py](backend/core/permissions.py)) enforces this at object level too — `has_object_permission` checks `obj.tenant_id == request.user.tenant_id` before any object-level action (approve, edit, lock).

Superusers can pass `?tenant=<slug>` to act across tenants (useful for the Django admin / data fixes).

`EmissionFactor` is intentionally NOT tenant-scoped — they're reference data published by DEFRA/EPA, shared across all tenants. Different from "per-tenant factor overrides" which a real product would add (and we explicitly ship without — see [TRADEOFFS.md](TRADEOFFS.md)).

## Scope 1/2/3 categorisation

Stored on `ActivityRecord.scope` (IntegerChoices: 1, 2, 3) and `EmissionFactor.scope`. Categorisation happens at the **parser** level, not the model layer:

- SAP fuel + procurement → Scope 1 (stationary + mobile combustion).
- Utility electricity → Scope 2 (or Scope 1 if supply_type=gas).
- Travel → Scope 3 (business travel category).

Per-row scope is set at ingest time in [views.py `_activity_record_from_parsed`](backend/core/views.py). The factor's scope and the record's scope should agree but are stored independently; a mismatch would be a parser bug worth catching.

GHG Protocol category-15 granularity (which Scope 3 sub-category) is intentionally out of scope — see [TRADEOFFS.md](TRADEOFFS.md).

## Source-of-truth tracking

For every record we record:

1. `source_system` — `sap` / `utility_csv` / `utility_pdf` / `travel`
2. `source_record_id` — the native identifier (SAP `EBELN+EBELP`, MPAN+period for utility, Concur TripID+segment for travel)
3. `batch` (FK to `IngestionBatch`) — which upload produced it, when, by whom, with what file hash
4. `raw_payload` — JSON dict of the original parsed row, every field preserved
5. `is_edited` — set the first time an analyst modifies a normalized field
6. `revisions` — full edit history; original ingested values are never overwritten
7. `review_actions` — full status-change history

The combination of `batch.file_sha256` + `raw_payload` + `revisions` means: given a row, you can produce (a) the exact bytes uploaded, (b) the exact field values that came out of the parser, (c) every change since, with timestamps and reasons.

## Unit normalisation

Two layers:

1. **At parser time** — [`normalize_quantity`](backend/core/ingestion/common.py) accepts a `(quantity, unit)` pair and converts to the canonical unit family (litre / kg / kWh / km / passenger_km / room_night). The conversion table is deliberately narrow — only units we actually expect to see in the three sources. If a unit is missing or unrecognised, the row is flagged `unit_inferred` for analyst review, not silently dropped.
2. **At factor lookup time** — `EmissionFactor.unit` must match `ActivityRecord.unit_normalized`. The factor row "diesel litre" cannot be applied to a "kg" record. That's enforced by activity_type pairing: parsers produce records whose `(activity_type, unit_normalized)` line up with the seeded factor table.

Locale-aware decimal parsing ([`parse_decimal`](backend/core/ingestion/common.py)) handles `1,234.56` (US), `1.234,56` (German), and SAP's 4-decimal-place German prices like `1,4250` via a `locale_hint` parameter the SAP parser threads through from the file's detected language.

## Audit trail

Three append-only tables together form the trail:

| Table | What it records | Mutability |
|---|---|---|
| `IngestionBatch` | Each upload — who, when, file hash, parser notes, row counts | Counts updated at end of parsing; nothing else changes |
| `ActivityRecordRevision` | Each field-level edit to a record | Append-only |
| `ReviewAction` | Each status transition (approve/reject/lock/unlock) | Append-only |

The `ReportingPeriod.locked_at` + `locked_by` finalise the chain — after that timestamp, no record whose `period_end` is in this period can be edited (server-side enforced in `_check_writeable` at [views.py:114](backend/core/views.py)).
