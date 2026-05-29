# Decisions

> For every ambiguity in the brief, this records what was chosen, why, what would have happened differently, and what I'd ask the PM. Grouped roughly in build order.

## Stack & architecture

### Multi-tenancy
**Chosen:** row-level — `tenant_id` on every business-data table, DRF permissions enforce isolation.
**Alternatives:** schema-per-tenant (`django-tenants`), database-per-tenant.
**Why:** schema-per-tenant is overkill for a prototype and adds operational complexity (migrations have to run per-schema); database-per-tenant doesn't scale past tens of customers. Row-level is the standard for early-stage B2B SaaS and what most ESG vendors actually ship; the assignment says "must handle multi-tenancy" — they want to see it modelled, not productionised.
**What I'd ask:** at what tenant count do we need to consider physical isolation? Some auditors require it; some regulated industries (defence, finance) do too. The migration path from row-level → schema-per-tenant is doable but painful; the migration to per-DB is much harder. Worth knowing before sales pipeline forces the answer.

### Auth
**Chosen:** Django built-in `User` (extended) + DRF `TokenAuthentication`. Two roles via a `role` char field: `analyst`, `admin`.
**Alternatives:** JWT (`djangorestframework-simplejwt`), session auth + CSRF, an external auth provider (Auth0, Clerk).
**Why:** the assignment specified "very simple authorisation system." Tokens don't need a refresh dance, they survive across browser tabs, and they cost ~50 lines of code. JWT pays a complexity tax (expiry / refresh / revocation lists) that's wasted for a prototype.
**What I'd ask:** SSO is the first thing enterprise customers will demand. Pick between SAML 2.0 (most enterprise IdPs) and OIDC (Okta, Azure AD, Google Workspace) early; bolting SSO onto Django built-in auth is easy via `django-allauth` or `mozilla-django-oidc`, but the choice of IdP shapes the user-provisioning flow.

### Database
**Chosen:** PostgreSQL via Vercel Postgres (Neon-backed). Local dev falls back to SQLite when `DATABASE_URL` isn't set.
**Override of original instinct:** the user initially requested SQLite. SQLite cannot run on Vercel (filesystem is ephemeral, writes don't persist between invocations). Switching to Vercel Postgres was a blocker resolution; documented in [plan.md](plan.md#b2-deploy--resolved-).
**What I'd ask:** is connection-pooled or unpooled the default for analytics queries? Neon's pgbouncer breaks `LISTEN/NOTIFY` and some long-running migrations — fine for the prototype where everything's a short transaction.

### Deploy target
**Chosen:** Vercel for both halves of the monorepo (Python serverless function for Django + static build for React). Postgres via Vercel's integration.
**Constraint this forced:** file uploads cannot be persisted on Vercel's ephemeral filesystem. Ingestion parses uploads in-memory, stores a SHA-256 of the bytes + the parsed rows in Postgres, and discards the file. Documented in [TRADEOFFS.md](TRADEOFFS.md).
**What I'd ask:** for production we'd attach Vercel Blob or S3 for raw-file retention. Most audits don't actually need the original file (the parsed values + hash is enough), but some accounting regulations (SOX) do. Worth understanding which auditors the customer base reports to before committing.

### Ingestion mechanism per source
**SAP:** CSV flat-file upload (analyst drag-and-drops the SE16/SE16N or ALV "Export to spreadsheet" output).
**Utility:** CSV portal export upload AND PDF bill upload (two parallel endpoints).
**Travel:** CSV or JSON file upload (Concur "Standard Reports" CSV export or REST-export JSON).
**Why these and not API pulls:** real Concur / Navan / SAP API access requires enterprise partner agreements we don't have. File uploads are not a "mock" — they are genuinely how most ESG teams get this data day-to-day (SAP teams won't grant API access; Concur admins export and email). Real API integrations are documented in [SOURCES.md](SOURCES.md) as the "what would break in prod" scaling story.
**What I'd ask:** what % of customers in the target ICP actually have IT willing to grant SAP/Concur API access? If it's >30%, the API-pull path is worth building day-one with a fixture-driven sandbox. If it's <10%, ship file-upload only and lean into a great UX there (which is what most ESG vendors actually do).

### Ingestion synchronously vs queued
**Chosen:** synchronous. Upload → parse → persist → respond, all in one request.
**Why:** at prototype data volumes (hundreds to low thousands of rows per upload), parsing fits inside Vercel's 60-300s function timeout. The ingestion entry point is factored as a callable function (`_do_ingest`) that would drop into a Celery task verbatim.
**What I'd ask:** for a 10k-row SAP year-end dump the sync path will timeout. The trigger is volume per single file, not total throughput. Worth profiling on real customer data before deciding when to move to async.

## Data model

### Per-row activity table, not per-source tables
**Chosen:** one `ActivityRecord` table that all three sources flow into.
**Alternative:** `FuelPurchase`, `ElectricityUsage`, `TravelSegment` separate tables.
**Why:** the dashboard, review workflow, audit log, reporting period, and CO₂e math are all source-agnostic. Three tables means three copies of approval state, three copies of `co2e_kg`, three places to add a new flag rule. The `raw_payload` JSON column preserves source-specific fields without bloating the schema.
**What I'd ask:** at what scale does this become a performance problem? Partitioning by `tenant_id` + `period_start` would handle 100M rows easily; the activity-type / scope split as separate tables only matters above that.

### Source-of-truth tracking
**Chosen:** every record stores `source_system`, `source_record_id`, `batch_id`, `raw_payload`, `ingested_at`, `is_edited`, plus a separate revision log for edits and review-action log for status changes.
**Why:** the brief explicitly asks for "source-of-truth tracking (which source produced this row, when, was it edited)" — that's an audit requirement, and the cleanest model is **never overwrite, always append**. `raw_payload` preserves the original; `revisions` preserves diffs; combined they let you reconstruct any value at any past time.

### Audit lock semantics
**Chosen:** per-reporting-period lock (CY, FY-quarter, etc.) with per-row approval gating the lock.
**Alternative:** per-row lock (manually flip each row).
**Why:** that's how real audits work — sign-off is on the period, not on individual rows. Per-row approval is the gate ("this row is ready") that *unlocks* the period lock ("everything is ready to be frozen"). A period with even one pending row can't be locked. Cascades: approved → locked when period locks; rejected → stays rejected; pending/flagged blocks the lock.
**What I'd ask:** do auditors require re-approval after unlock? Some do. Current impl flips `LOCKED` → `APPROVED` on unlock, preserving review state. If re-approval is required we'd add an "unlocked, awaiting re-review" intermediate.

### Emission factors as versioned reference data
**Chosen:** factors are uniquely keyed by `(activity_type, region, year, source)`. We **never overwrite** — DEFRA publishing a correction means a new row, and old records keep their factor link.
**Why:** an audit doesn't care that DEFRA later corrected the diesel factor by 0.3%; it cares which factor was applied at the time the analyst signed off. Mutating factors silently changes historical CO₂e numbers; that's an audit-failure mode.
**What I'd ask:** do customers want manual "use the latest factor" buttons in the UI to re-tag old records? That's a deliberate re-tag, not a silent re-calc, so the model supports it; just need a UX.

### Flags as a JSON list, not a separate table
**Chosen:** `flags: list[str]` stored as JSON on each `ActivityRecord`.
**Alternative:** a `Flag` table FK'd to records.
**Why:** flags are derived (rules → list), they're read together with the record 99% of the time, and they don't carry independent metadata. A separate table is a join we'd pay for on every list query for no gain.

## Per-source choices

### SAP
**Chosen subset:** procurement (EKKO+EKPO+MSEG) joined with material master (MARA+MAKT), filtered to BWART=101 (goods receipt against PO). Both English (tech codes: MATNR, WERKS, MEINS, BUDAT) and German (labels: Material, Werk, BME, Buchungsdatum) headers.
**Subset I ignored:** IDoc XML, OData/BAPI live integrations, BSEG (financial postings without GR), inventory movements other than 101, multi-currency conversion, tax code parsing, profit-centre accounting.
**Why:** the assignment says "decide what subset of SAP reality you're handling." Real ESG teams accept CSV exports from finance/SAP teams; IDoc consumption requires SAP-NetWeaver gateway access that customers rarely grant. Filtering to BWART=101 keeps the dataset clean (no double-counting from transfers / reversals / inventory adjustments).
**What I'd ask:** does the customer want consumption-based (BWART 201/261) or purchase-based (101) data? Different teams have opinions. We chose 101 because it matches the procurement → fuel-bought-this-quarter model that auditors usually want.

### Utility — electricity
**Chosen subset:** UK MPAN-style portal CSV exports (one row per billing period per meter), plus PDF bills with text layer (not scanned images).
**Subset I ignored:** half-hourly settlement data, demand charges (kVA), peak/off-peak split as separate factors (we sum), CCL/RO/FIT pass-throughs, multi-fuel mixed gas+electric bills, image-only PDFs requiring OCR.
**Why:** half-hourly is a different (richer) ingestion shape; the prototype targets the most common analyst hand-off, which is the periodic bill. PDF OCR via Tesseract would multiply parser complexity for ~5% additional coverage; we accept that scanned bills land as flagged rows with raw text attached for manual fixup.
**What I'd ask:** post-MHHS (Market-wide Half-Hourly Settlement) rollout (2025-2026, UK), more meters expose half-hourly data. Worth knowing whether the customer base has already migrated, because the kWh/period model is becoming antiquated.

### Travel
**Chosen subset:** Concur-style Standard-Reports CSV (one row per segment; Air, Hotel, Car, Rail). JSON shape supports either a flat array or a Concur Itinerary v4 nested doc.
**Subset I ignored:** Concur Reporting API (OAuth, pagination, rate limits), live booking integrations, hotel energy-intensity overrides, vehicle-mile odometer ingestion, fuel-card data for company vehicles.
**Why:** the per-segment flat shape is what every travel platform's "export to CSV" produces and is the universal common denominator. Live API integration is documented in [SOURCES.md](SOURCES.md) as the scaling story.

### Distance reconstruction for flights
**Chosen:** when Concur doesn't include `Distance in Miles` (Concur usually doesn't; Navan sometimes does), we compute the great-circle distance from IATA codes using a small embedded subset of OpenFlights `airports.dat` (~100 hubs).
**Alternative:** require the customer to upload a fuller IATA → coordinates table; ship the full ~7000-airport file (~600 KB).
**Why:** ~100 airports cover the majority of business travel in practice; unknowns are flagged `airport_unknown` for analyst review. Shipping a 600 KB file bloats the function bundle (Vercel has a 500 MB limit but every kB counts toward cold-start latency).

### Haul-category classification
**Chosen:** uses both `(distance_km)` AND `(origin_country, dest_country)`. Same country → domestic; different country + <3700 km → short-haul; ≥3700 km → long-haul.
**Why a real correctness fix:** distance-only would classify LHR→CDG (347 km) as "domestic" because DEFRA's domestic flight factor is meant for *intra-UK* flights, not "short distance." Country comparison fixes this.

## Emission factors

### Source
**Chosen:** real DEFRA / UK DESNZ 2024 condensed workbook (v1.1, October 2024 correction) for UK tenants; real EPA 2024 Emission Factors Hub (using eGRID 2022 data) for US tenants.
**Alternative:** Climatiq API (commercial; richer, paid).
**Why:** DEFRA and EPA are authoritative for ESG reporting and are the factors most disclosure frameworks (CDP, SBTi, GRI, ISSB) expect. Their workbooks are public domain. The seeded values in [migration 0002](backend/core/migrations/0002_seed_emission_factors.py) are cited directly to the workbook URL and sheet name.

### Region resolution
**Chosen:** factor lookup tries (1) exact `(activity, region, year)`, then (2) exact `(activity, region)` newest ≤ year, then (3) `(activity, GLOBAL)` newest ≤ year, then None.
**Why:** if a 2024 record arrives but only a 2023 factor exists, we use 2023 and flag `factor_year_drift`. If a 2024 record arrives for a country we don't have a factor for (say, IT), we fall back to GLOBAL. A null result is a hard flag (`factor_missing`).

## What I'd ask the PM if I could

(Beyond the per-decision asks above.)

1. **Which audit framework is the customer reporting under?** CDP, SBTi, GHG Protocol, ISSB, EU CSRD, SEC climate disclosure. They have different methodology requirements — location-based vs market-based Scope 2 is the obvious one, but Scope 3 category-15 granularity matters for SBTi.
2. **Who is the buyer?** Sustainability lead, CFO, head of risk? Their priorities are different. CFO cares about cost data alongside emissions; sustainability lead cares about narrative; head of risk cares about audit failures.
3. **What's the SLA on data freshness?** Monthly close vs annual disclosure shapes how aggressive we are about live integrations.
4. **What does "approve" mean exactly?** Is it analyst sign-off (one person) or two-eye review (two people)? Some regulated industries require dual approval; we'd model that as a state machine extension.
5. **Re-baselining policy** — when a customer re-categorises an activity (e.g. moves a row from Scope 3.1 to Scope 3.2), should the change flow back through prior locked periods? Most ESG vendors freeze. Some compliance frameworks require restatement.
