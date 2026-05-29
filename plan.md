# Breathe ESG Prototype — Plan & Questions

> Source: [work.md](work.md) — assignment brief.
> This file captures my understanding of the assignment and the open questions I need answered before I can lock the goal. Write your answers inline under each question.

---

## 1. What the project actually is

Breathe ESG is a carbon/ESG data platform. The hard problem is **not** computing carbon — it's that every client's source data lives in a different system, shape, and quality. We're building a **prototype** that:

1. **Ingests** data from three kinds of sources:
   - **SAP** — fuel and procurement (Scope 1 + Scope 3 upstream goods/services)
   - **Utility portal** — electricity (Scope 2)
   - **Corporate travel platform** — flights, hotels, ground transport (Scope 3 business travel)
2. **Normalizes** it into one canonical schema (units, dates, categories, emission factors).
3. **Surfaces a review dashboard** where an analyst can:
   - See what was ingested, what failed, what looks suspicious.
   - Approve / reject / edit rows.
   - Lock rows so they're frozen for auditors.
4. **Tracks audit trail** — who changed what, when, from which source, original vs edited value.

**Stack:** Django REST Framework backend, React frontend. **Timeline:** 4 days. **Deployment is mandatory** (Render / Railway / Fly).

### What we're graded on
- Judgment, not feature count. They explicitly say "submit less, but work you understand and can defend."
- The **data model** carries significant weight — multi-tenancy, Scope 1/2/3, source-of-truth, unit normalization, audit trail must all be in it.
- We must defend every decision. "The AI suggested it" is a fail.

### Deliverables
1. Working deployed app (live URL).
2. `MODEL.md` — data model + rationale.
3. `DECISIONS.md` — every ambiguity, what we chose, why, what we'd ask the PM.
4. `TRADEOFFS.md` — 3 things deliberately NOT built and why.
5. `SOURCES.md` — for each source: real format researched, what we learned, sample data justification, what would break in prod.

---

## 2. My current understanding of the hard parts

### 2.1 Data model spine (the thing that matters most)
A single canonical `EmissionRecord` (or `ActivityRecord`) table that all three sources flow into, with:
- `tenant_id` (multi-tenancy)
- `scope` (1 / 2 / 3) and `category` (stationary combustion, purchased electricity, business travel, etc. — GHG Protocol categories)
- `activity_type` (diesel, jet fuel, kWh, passenger-km, room-night, …)
- `quantity` + `unit` (raw) and `quantity_normalized` + `unit_normalized` (canonical, e.g. kWh, kg, km)
- `emission_factor_id` (FK to a factor table; factor has region, year, source like DEFRA/EPA/IEA)
- `co2e_kg` (computed)
- `period_start` / `period_end` (activity period — NOT ingestion date; utility bills span weird periods)
- **Source provenance**: `source_system` (sap / utility / travel), `source_record_id`, `ingested_at`, `raw_payload` (JSON blob of original row), `ingestion_batch_id`
- **Edit tracking**: `is_edited`, `edited_by`, `edited_at`, plus a separate `EmissionRecordRevision` table for full history
- **Review state**: `status` (pending / approved / rejected / flagged / locked), `reviewed_by`, `reviewed_at`, `review_notes`
- **Data quality**: `confidence` or `flags` (e.g. missing_unit, unit_inferred, date_inferred, factor_assumed)

### 2.2 Per-source realistic shape
- **SAP**: I'm leaning toward **flat-file CSV exports from a BAPI/SE16 dump** — that's what facilities/finance teams actually email. IDoc parsing is too deep for 4 days. Realistic pains: material codes (`MATNR`), plant codes (`WERKS`), unit-of-measure column (`MEINS`) in SAP-specific codes (L, KG, ST, KWH), German headers in some configs, dates as `YYYYMMDD` or `DD.MM.YYYY`, commas vs dots for decimals.
- **Utility**: I'm leaning toward **portal CSV export** for electricity (one row per meter per billing period, with `kwh_consumed`, `period_start`, `period_end`, `meter_id`, `tariff`, sometimes peak/off-peak split). PDF parsing is a rabbit hole; API access is rare. Realistic pains: billing periods that span calendar-month boundaries, demand charges (kW) mixed with energy (kWh), estimated vs actual reads.
- **Travel**: I'm leaning toward **Concur-style JSON API pull** (we'll mock the endpoint). Realistic pains: flight legs given as airport-code pairs (no distance), hotel as room-nights with no energy intensity, ground transport as miles OR fare amount only.

### 2.3 Review dashboard
Minimum viable analyst experience:
- List view filtered by tenant / source / status / period.
- Row detail showing raw payload side-by-side with normalized values.
- Approve / reject / edit / lock actions.
- Flag panel showing what's suspicious (missing unit, factor assumed, period overlap, > 3σ from prior period).
- Bulk approve.

### 2.4 What I'd deliberately cut (preliminary TRADEOFFS picks)
- Real PDF OCR for utility bills.
- Real SAP IDoc / OData connector — we'll do CSV upload only.
- Full GHG Protocol category coverage — pick a handful per scope.

---

## 3. Open questions I need answered before locking the goal

> Write your answer on the line below each question. If you don't care, write "your call."

### Q1. Scope of the prototype — depth vs breadth
Do you want me to go **narrow and deep** (one source done really well, the other two as thinner happy-path implementations) or **even coverage** across all three (all three sources work end-to-end but none is polished)?
**My recommendation:** even coverage — the assignment explicitly grades all three sources and asks `SOURCES.md` for each. Narrow-and-deep risks failing the "handles three sources" gate.
**Your answer:** ✅ Even coverage across all three.

### Q2. SAP ingestion mechanism
I'd pick **CSV flat-file upload** (analyst drag-drops the SAP export). Alternatives: mock OData endpoint, IDoc XML upload. Which?
**My recommendation:** CSV upload. Justifiable (it's what actually happens in practice when SAP teams won't grant API access), and lets me focus the difficulty on the *messy column shape* rather than the *transport*.
**Your answer:** CSV flat-file upload — research the real SAP export shape via web search / browser, don't invent it.
**My interpretation:** I'll use WebSearch to study real SAP IDoc / flat-file dump structure (MATNR, WERKS, MEINS columns, German headers, date formats) and build the upload + parser to match. The *transport* is CSV upload (analyst-driven), the *shape* is what real SAP MM/FI exports look like.

### Q3. Utility ingestion mechanism
**CSV portal export**, **PDF bill upload (with parsing)**, or **mock utility API**?
**My recommendation:** CSV portal export. PDF parsing eats a full day for a prototype and the value is in the normalization logic, not the OCR. I'll mention PDF as a `SOURCES.md` "what would break in prod" item.
**Your answer:** ✅ Both — CSV portal export **and** PDF bill upload with parsing. PDF parsing doesn't need to be 100% accurate; 2–3 extraction attempts is fine.
**My interpretation:** I'll support two upload paths for utility: (a) CSV from portal exports, (b) PDF bill upload with `pdfplumber` (text-layer) + regex fallback. I'll target the common bill fields (kWh consumed, billing period start/end, supply address, tariff). If extraction fails, the row lands in `flagged` status with the raw PDF text attached so an analyst can fix it manually.

### Q4. Travel ingestion mechanism
**Mock Concur-style REST API** (we run a tiny fake server / fixture endpoint and pull), or **JSON file upload**?
**My recommendation:** mock API pull — it's more realistic and showcases scheduled-sync thinking. The "API" can be a local JSON file served behind a DRF endpoint or a fixture.
**Your answer:** No mocks anywhere — ask if I need something.
**⚠️ Conflict to resolve (see "Blockers" below):** real Concur / Navan API access requires an enterprise partner agreement that we don't have, and their sandboxes aren't open. The realistic pattern most ESG teams actually use is a **JSON / CSV export file** from the travel platform's admin console — that *is* the real shape, not a mock. I'd like to call that the "real" path and document the Concur API as a `SOURCES.md` "what would break in prod" item (rate limits, OAuth refresh, pagination). Confirm in the blocker question at the end.

### Q5. Multi-tenancy model
Three options: (a) **row-level** `tenant_id` on every table with DRF permission filtering, (b) **schema-per-tenant** (django-tenants), (c) **database-per-tenant**.
**My recommendation:** row-level. Schema-per-tenant is overkill for a prototype, and the assignment says "must handle multi-tenancy" — they want to see it modeled, not productionized. I'll defend this as the right call for a prototype while noting it's the wrong call at scale for an audit-sensitive product.
**Your answer:** ✅ My choice — row-level tenancy.

### Q6. Auth / user roles
Minimum: `analyst` (review + approve) and `admin` (everything + lock). Do you also want `viewer` (read-only) or `ingestion-bot` (service account)?
**My recommendation:** just `analyst` and `admin`, with a simple Django user + role field. JWT auth via `djangorestframework-simplejwt`. No SSO, no OAuth.
**Your answer:** ✅ Minimum auth — no auth server, very simple authorization.
**My interpretation:** Django's built-in user model + DRF TokenAuthentication (simpler than JWT, no refresh logic). Two roles via a `role` char field: `analyst` and `admin`. Permissions enforced in DRF viewsets.

### Q7. Database
**PostgreSQL** (production-realistic, JSON fields work properly) or **SQLite** (zero-config, fine for prototype)?
**My recommendation:** PostgreSQL. Render / Railway / Fly all give it free. JSON support matters for `raw_payload`. Audit trail is more honest on Postgres.
**Your answer:** SQLite.
**⚠️ Conflict with Q8 (Vercel) — see Blockers section.** SQLite + Vercel serverless will not persist writes; Vercel's filesystem is ephemeral per-invocation. I'll honor SQLite for local dev, but we need to resolve the deploy story.

### Q8. Deployment target
**Render**, **Railway**, **Fly.io**, or other?
**My recommendation:** Render — easiest Django + Postgres + static React in one place, free tier works.
**Your answer:** Vercel (you'll handle deploy).
**⚠️ Conflict — see Blockers section.** Vercel is great for the React frontend but Django on Vercel runs as Python serverless functions with an ephemeral, mostly-read-only filesystem. SQLite writes will not persist, file uploads (the entire ingestion story for SAP CSV / utility PDF) will not persist, and cold-start latency is bad for an ingestion endpoint. I'd recommend: **React on Vercel + Django on Render/Railway/Fly**. I'll build the app so it's portable either way; you pick the backend host.

### Q9. Background jobs
Ingestion can be **synchronous** (upload → parse → return) or **async** (upload → queue → poll for status).
**My recommendation:** synchronous for the prototype, but design the ingestion as a callable function so it'd swap into Celery cleanly. I'll note this in `TRADEOFFS.md`.
**Your answer:** ✅ My choice — synchronous, but factored for an easy Celery swap. Documented in TRADEOFFS.md.

### Q10. Frontend scope
React with which UI library? Options: **Tailwind + shadcn/ui**, **Material UI**, **Chakra**, **plain CSS**.
**My recommendation:** Tailwind + shadcn/ui — fastest path to a non-embarrassing dashboard.
**Your answer:** ✅ Tailwind + shadcn/ui.

### Q11. Emission factors
Where do factors come from? Options: (a) **hardcoded constants** for the 10–15 activity types I support, (b) **seed a `EmissionFactor` table** from a small fixture (DEFRA 2024 values), (c) **fetch from an external API**.
**My recommendation:** (b) — seed an `EmissionFactor` table from a DEFRA 2024 fixture. Showcases the model (factors are versioned per region/year) without the time sink of a real lookup service.
**Your answer:** Real factors — fetch from authoritative sources per work.md, no fabrication.
**My interpretation:** I'll download the **real DEFRA 2024 (UK BEIS) GHG conversion factors workbook** and the **EPA emission factors hub** (both public, both authoritative for ESG reporting), extract the rows we need into a CSV fixture, and load them via a Django data migration. The fixture file shipped in the repo is *literally* DEFRA / EPA numbers, not values I invented. `SOURCES.md` will cite the exact workbook URLs + version year + which sheet each factor came from.

### Q12. Sample data volume
How much fake data per source? 50 rows each? 500? 5,000?
**My recommendation:** ~200 rows per source, with deliberate dirty rows (missing units, German headers in SAP, period overlap in utility, airport-code-only flights). Enough to show pagination + filtering, small enough to seed fast.
**Your answer:** No fake data — only real, authentic, fetched data.
**⚠️ Conflict with work.md — see Blockers section.** Real customer SAP exports, real utility bills with billing addresses, and real corporate travel feeds are private business records — they aren't publicly downloadable. The work.md brief explicitly says *"You can fabricate the sample data yourself once you understand what's realistic. We will ask why your sample data looks the way it does."* My interpretation of your "no fake data" rule, reconciled with the brief: I'll **harvest real publicly-available samples wherever they exist** (SAP demo/training datasets, government open-data utility consumption sets, IATA route distance tables, DEFRA factors, sample utility bills posted by regulators) and **only fabricate the row-level identifiers** (company names, meter numbers, employee names) where privacy makes real data impossible. Every fabricated field will be documented in `SOURCES.md`. Confirm in the blocker question.

### Q13. Audit lock semantics
When an analyst "locks" a row for audit, should locking be (a) **per-row**, (b) **per-reporting-period** (e.g. lock all Q1 2026 rows for tenant X), or (c) **both**?
**My recommendation:** per-reporting-period lock, with per-row approval underneath. That matches how audits actually work (you sign off on a period, not individual rows). Per-row approval gates entry into the period lock.
**Your answer:** ✅ Per-reporting-period lock with row-level approval.

### Q14. "Suspicious" detection — how much to build
The brief says the dashboard shows "what looks suspicious." Options: (a) **rule-based flags only** (missing unit, period overlap, factor assumed, > N× prior period), (b) **add a simple statistical outlier check** (z-score vs same activity for same tenant), (c) **skip entirely, just show ingestion errors**.
**My recommendation:** (a) — rule-based flags. Defensible, fast, and the *interesting* judgment is in *which rules*, not in stats.
**Your answer:** ✅ My choice — rule-based flags.

### Q15. Anything you want me to deliberately NOT do?
e.g. "don't bother with a login screen, just hard-code a user", or "don't write tests, the model design matters more"
**Your answer:** Nothing — no extra cuts beyond what I propose in TRADEOFFS.md.

### Q16. What's the actual submission deadline?
You said 4 days in the brief, but is the clock already running? When do you need this submitted?
**Your answer:** Lots of time — no rush.

---

## 4. Blockers — RESOLVED

### B1. Sample data — RESOLVED ✅
**Decision:** Real public datasets + minimal fabrication. Harvest from SAP open training data, gov utility open-data, IATA airport distances, DEFRA / EPA emission factor workbooks, regulator-published sample bill PDFs. Only fabricate row-level identifiers (company name, meter number, employee name) where privacy blocks real data. Every fabricated field cited in `SOURCES.md` with the rationale.

### B2. Deploy — RESOLVED ✅
**Decision:** Postgres on Vercel. Backend = Django as Vercel Python serverless functions, DB = Vercel Postgres (Neon-backed).
**Implication this forces on the architecture:** Vercel serverless filesystem is ephemeral, so uploaded SAP CSVs and utility PDFs cannot be persisted as files. **Ingestion will parse uploads in-memory and persist only the extracted normalized rows + a SHA-256 of the raw bytes + the raw text/JSON blob in Postgres.** This is actually *better* for the audit story — we keep a content hash + the parsed data, not the original file — and matches real prod ESG systems that move raw files to cold storage and work off the parsed rows. I'll document this trade in `TRADEOFFS.md` and `DECISIONS.md`.
**Stack lock-in:**
- Backend: Django 5 + DRF, deployed as `api/index.py` Vercel handler
- DB: Vercel Postgres (`psycopg[binary]`)
- Frontend: React + Vite + Tailwind + shadcn/ui, deployed as Vercel static build
- Both halves live in one Vercel project (monorepo), shared domain.

### B3. Travel ingestion — RESOLVED ✅
**Decision:** JSON / CSV export upload (the genuine real-world day-to-day mechanism — Concur admins export reports). Concur Reporting API documented in `SOURCES.md` as the "what would break in prod" scaling story (OAuth refresh, pagination, rate limits).

---

## 5. Goal & build order — STARTING

**Goal condition:** Deployed Vercel app (Django serverless + Vercel Postgres + React) ingesting SAP CSV + utility CSV/PDF + travel JSON/CSV from real-shape data, analyst can approve rows and lock reporting periods, plus the four markdown deliverables (MODEL.md, DECISIONS.md, TRADEOFFS.md, SOURCES.md).

**Build order:**
1. Research phase — pull real format specs for SAP MM/FI exports, utility bill structures, Concur export shape, DEFRA 2024 factor workbook (using WebSearch / WebFetch).
2. Repo scaffold — monorepo with `/backend` (Django + DRF) and `/frontend` (Vite + React + Tailwind + shadcn).
3. Data model — `Tenant`, `User`, `EmissionFactor`, `ActivityRecord`, `ActivityRecordRevision`, `IngestionBatch`, `ReportingPeriod`. Migrations.
4. Auth — Django built-in user + DRF TokenAuthentication, two roles (`analyst`, `admin`).
5. Emission factor seeding — data migration loading real DEFRA + EPA factors.
6. SAP CSV ingestion — endpoint, parser, normalizer, unit/date/decimal handling, German-header support.
7. Utility ingestion — CSV path + PDF path (`pdfplumber` + regex), period-overlap detection.
8. Travel ingestion — JSON/CSV parser, airport-code → distance lookup, category-specific factor selection.
9. Suspicious-row flagging — rule set (missing unit, period overlap, factor assumed, > 3× prior period, ingestion errors).
10. React dashboard — login, ingestion uploaders, record list with filters, record detail (raw ↔ normalized side-by-side), approve / reject / edit / flag, reporting period view + lock action.
11. Tests on normalization paths (this is the load-bearing logic).
12. Deliverables — write MODEL.md, DECISIONS.md, TRADEOFFS.md, SOURCES.md.
13. Vercel deploy config — `vercel.json`, `api/index.py` WSGI handler, build script, env-var wiring.
