# Breathe ESG — prototype

Django REST + React monorepo for ingesting fuel/procurement, electricity, and corporate travel data, normalizing it, and surfacing a review dashboard where analysts approve rows and lock reporting periods.

Built against the [4-day take-home assignment](work.md). The deliverables that carry weight in evaluation:

- [MODEL.md](MODEL.md) — the data model and why.
- [DECISIONS.md](DECISIONS.md) — every ambiguity resolved.
- [TRADEOFFS.md](TRADEOFFS.md) — three things deliberately not built.
- [SOURCES.md](SOURCES.md) — what real-world formats were researched and how the sample data was authored.
- [plan.md](plan.md) — the conversation record where scope was negotiated.

---

## Run locally

### Prerequisites
- Python 3.12+
- Node 18+
- Optional: Postgres locally; otherwise SQLite is the default for dev.

### Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
.\.venv\Scripts\python manage.py migrate
.\.venv\Scripts\python manage.py bootstrap     # creates admin / breathe-esg-admin
.\.venv\Scripts\python manage.py runserver 8000
```

The backend serves at `http://localhost:8000`. The seeded admin user has API token printed by the `bootstrap` command.

### Frontend
```powershell
cd frontend
npm install
npm run dev
```

Vite dev server runs at `http://localhost:5173` and proxies `/api/*` to `http://localhost:8000`.

Open `http://localhost:5173`, sign in with `admin` / `breathe-esg-admin`, and try the Ingest page.

### Run tests
```powershell
cd backend
.\.venv\Scripts\python manage.py test core
```

37 tests covering decimal/date/unit parsing, all four parsers, and airport-pair distance.

### Try a real-shape upload
A sample SAP CSV ships in [backend/sample_data/sap_en.csv](backend/sample_data/sap_en.csv). Upload it from the Ingest page; you'll get 5 records back, four with `pending` status (diesel + petrol have DEFRA factors) and one with `flagged` (AdBlue has no emission factor — the row is preserved with `factor_missing` for analyst review).

---

## Deploy

Two Vercel projects pointing at the same repo:

### Project 1 — backend
- **Root Directory:** `backend`
- **Integration:** add Vercel Postgres (provisions `DATABASE_URL`)
- **Environment variables:**
  - `DJANGO_SECRET_KEY` — generate one
  - `DJANGO_DEBUG=0`
  - `DJANGO_ALLOWED_HOSTS` — `.vercel.app` plus your custom domain
  - `DJANGO_CORS_ALLOWED_ORIGINS` — the frontend Vercel URL
- **After first deploy:** run `python manage.py bootstrap` via `vercel env pull && python manage.py bootstrap` against the unpooled `DATABASE_URL` to seed the admin user.

### Project 2 — frontend
- **Root Directory:** `frontend`
- **Environment variables:**
  - `VITE_API_URL` — the backend Vercel URL (e.g. `https://breathe-esg-backend.vercel.app`)

The frontend reads `VITE_API_URL` at build time and makes direct CORS-protected calls to the backend.

---

## What's where

```
backend/
  breatheesg/        # Django project (settings, urls, wsgi)
  core/              # Single app — models, views, serializers, ingestion
    ingestion/       # Per-source parsers
      sap.py
      utility_csv.py
      utility_pdf.py
      travel.py
      airports.py    # OpenFlights-derived hub subset for distance
      common.py      # locale-aware decimals, multi-format dates, unit conversion, factor lookup
    flagging.py      # rule-based suspicious-row detector
    management/commands/bootstrap.py   # idempotent tenant + admin user seeding
    migrations/0002_seed_emission_factors.py  # real DEFRA + EPA factors
    tests.py         # 37 normalization tests
  sample_data/sap_en.csv  # realistic SAP procurement CSV
  vercel.json        # Vercel backend deploy config
  build_files.sh     # collectstatic + migrate hook

frontend/
  src/
    api.ts           # fetch wrapper with token auth
    App.tsx          # router + auth shell
    pages/
      Login.tsx
      Dashboard.tsx          # by-scope + by-status summary
      Ingestion.tsx          # four uploader cards
      RecordList.tsx         # filterable table
      RecordDetail.tsx       # raw ↔ normalized side-by-side, approve/edit
      Periods.tsx            # lock + unlock reporting periods
  vercel.json
```

---

## API quick reference

Token auth — get one via:
```
POST /api/auth/token/  body: {"username","password"}  → {"token": "..."}
```
Use as `Authorization: Token <token>` for everything below.

| Verb | Path | Purpose |
|---|---|---|
| GET | `/api/auth/whoami/` | current user + tenant |
| GET | `/api/summary/` | dashboard stats by scope/status/source |
| POST | `/api/ingest/sap/` | multipart file upload — SAP CSV |
| POST | `/api/ingest/utility-csv/` | utility portal CSV |
| POST | `/api/ingest/utility-pdf/` | utility bill PDF |
| POST | `/api/ingest/travel/` | travel CSV or JSON |
| GET | `/api/records/` | list (filters: `scope`, `status`, `source`, `from`, `to`, `flagged=1`) |
| GET | `/api/records/<uuid>/` | detail incl. raw_payload + revisions + actions |
| POST | `/api/records/<uuid>/approve/` | approve, body `{"note": "..."}` |
| POST | `/api/records/<uuid>/reject/` | reject |
| POST | `/api/records/<uuid>/edit/` | edit normalized fields with reason |
| GET | `/api/reporting-periods/` | list periods |
| POST | `/api/reporting-periods/` | create period |
| POST | `/api/reporting-periods/<uuid>/lock/` | lock (admin only); blocked if any pending/flagged record in period |
| POST | `/api/reporting-periods/<uuid>/unlock/` | unlock (admin only) |
