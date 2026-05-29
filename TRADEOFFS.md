# Tradeoffs

> Three things deliberately not built and why. (Plus a fourth and fifth because they're cheap to call out.)

## 1. Persistent raw-file storage

**Cut:** uploaded files (SAP CSV, utility CSV, utility PDF, travel exports) are parsed in-memory in the request handler and then discarded. We store the parsed rows + a SHA-256 of the uploaded bytes + the original filename + size — but not the bytes themselves.

**Why:** the deploy target is Vercel's Python serverless runtime. The filesystem is ephemeral per-invocation and `/tmp` is the only writable path (~512 MB, scoped to a single function execution). Persistent file storage requires a separate object store — Vercel Blob, AWS S3, Cloudflare R2 — and the auth/credential plumbing that goes with it. For a prototype:

- The audit story doesn't strictly require the bytes. `raw_payload` (JSON dict of the parsed row) + `file_sha256` together let us prove (a) what the parser saw, (b) that it came from the same file the customer claims. A real audit would request the original file from the customer's SharePoint / mailbox / wherever — the hash gates re-uploads of the same file.
- Adding S3 doubles the deploy complexity (more env vars, IAM roles, regional concerns) for a prototype.

**What we lose:** the ability to re-parse the original after a parser bug fix, without asking the customer to re-upload. For a real product this is non-negotiable; for the prototype it's a deliberate cut.

**Migration path:** add a `RawFile` model with `s3_key` + `bucket`, swap `_do_ingest` to push bytes to S3 before parsing, store the S3 key on `IngestionBatch`. A day's work; intentionally deferred.

## 2. Background job queue (Celery + worker)

**Cut:** ingestion is synchronous — upload → parse → persist → respond, all in one HTTP request. No queue, no worker, no status polling.

**Why:** at prototype data volumes (hundreds to a few thousand rows per upload), parsing fits inside Vercel's 60-second default function timeout (extendable to 300 s on the Pro plan). The synchronous path is simpler to reason about, simpler to deploy, and simpler to debug. The user explicitly approved this choice for the prototype.

**What we lose:** the ability to ingest very large SAP year-end dumps (~10k+ rows in a single file would timeout). Real-time progress feedback ("parsed 3000 of 10000") is also missing.

**Migration path:** the ingestion function (`_do_ingest` in [views.py](backend/core/views.py)) is structured so the entire body could be wrapped in `@shared_task` and queued. The view would create the `IngestionBatch` row, enqueue the task, and return `202 Accepted` with the batch ID. The frontend would poll. Celery + Redis is well-trodden — half a day's work — but deliberately deferred.

## 3. OCR for image-only utility bill PDFs

**Cut:** the utility PDF parser ([utility_pdf.py](backend/core/ingestion/utility_pdf.py)) extracts text via `pdfplumber`'s text-layer extraction. PDFs without an embedded text layer (scanned bills, fax-style image PDFs) produce zero text and the row lands in `flagged` status with the raw text excerpt attached and a `pdf_partial_parse` flag.

**Why:** OCR adds two large dependencies (Tesseract via `pytesseract` ≈ 80 MB system binary, or Vision API call costs). Tesseract on Vercel serverless requires bundling the system binary — fights the 50 MB Lambda layer limit. Vision APIs (Google Document AI, AWS Textract, Azure Form Recognizer) are per-call paid services that require credential plumbing.

The user explicitly accepted "2-3 extraction attempts; doesn't need to be 100% accurate." Most modern UK utility bills (EDF, British Gas, E.ON post-2018) ship with text layers; older scanned bills are the minority case.

**What we lose:** ~20-30% of older scanned utility bills will need manual data entry. We surface them clearly in the UI with the raw text and flag for follow-up; they don't silently fail.

**Migration path:** swap `pdfplumber` for a Document-AI-style API call when text extraction returns empty. Cost is per-page; ~$0.005-0.05 depending on provider. Half a day to wire; deliberately deferred.

## 4. Per-tenant emission factor overrides

**Cut:** the `EmissionFactor` table is shared across all tenants (filtered by region/year/source via the lookup function, but a row is global). There's no way for an analyst to say "for OUR specific data centre in eGRID region RFCW, override the default with our REGO-backed market-based factor of 0.04 kg CO₂e/kWh."

**Why:** market-based Scope 2 with supplier-specific factors is a real and important feature (it's how customers report renewable energy contracts), but it requires:

- A `TenantEmissionFactor` table that overrides the public one.
- A precedence order in the lookup (tenant override > tenant default > regional default > GLOBAL).
- UI for uploading REGO/GoO certificates as proof.
- A "location-based vs market-based" toggle on reports.

That's a real subproject. The prototype uses DEFRA/EPA location-based factors throughout, which is the standard default.

## 5. Full GHG Protocol Scope 3 category coverage

**Cut:** we cover Scope 3 category 6 (business travel) and category 3 (T&D losses, indirectly via the UK grid combined factor we ship). The other 13 Scope 3 categories (purchased goods & services, capital goods, upstream transportation, waste, downstream activities, etc.) are not specifically tagged.

**Why:** real Scope 3 category-15 reporting requires a richer activity ontology than three sources can produce. SAP procurement (MM module) is the obvious feeder for Scope 3.1 (purchased goods & services), but mapping a `MATKL` code to a Scope 3 sub-category requires industry-specific spend-based or supplier-specific factors that vary wildly. Doing this badly is worse than not doing it.

The prototype's seeded factors and activity_type set are deliberately narrow:

- Scope 1: diesel, petrol, natural gas, LPG, heating oil
- Scope 2: grid_electricity (location-based)
- Scope 3: flights (short/long-haul × economy/business/first), rail, hotel nights (country-specific)

That covers the three sources end-to-end and shows the model is right. Extending the activity_type vocabulary is a matter of seeding more factors + adding mapping rules — not a model change.
