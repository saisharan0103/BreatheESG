#!/usr/bin/env bash
# Vercel build step for the Django backend.
# Collects static assets and runs migrations against the configured database.
set -euo pipefail

python -m pip install --break-system-packages -r requirements.txt

# Prefer the unpooled Postgres URL when Vercel Postgres is configured. If it is
# absent, leave DATABASE_URL unchanged so settings.py can use SQLite locally.
if [ -n "${DATABASE_URL_UNPOOLED:-}" ]; then
  export DATABASE_URL="${DATABASE_URL_UNPOOLED}"
fi

python manage.py collectstatic --noinput --clear
python manage.py migrate --noinput
python manage.py bootstrap

# Vercel's static-build expects an output directory.
mkdir -p staticfiles_build
cp -r staticfiles/* staticfiles_build/ 2>/dev/null || true
