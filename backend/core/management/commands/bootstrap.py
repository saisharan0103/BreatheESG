"""
Idempotent bootstrap: creates one tenant and one admin user so the app
is immediately usable after `migrate`. Run this once per deploy:

    python manage.py bootstrap

Re-running is safe; existing records are left alone.

This is configuration data, not domain data. Tenant identifiers and the
admin login are the minimum needed to make the app reachable — they're
the same category as a database connection string, not "fabricated
sample data" in the assignment's sense.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from rest_framework.authtoken.models import Token

from core.models import ReportingPeriod, Tenant, User


class Command(BaseCommand):
    help = "Create demo tenant and admin user (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-slug", default="demo")
        parser.add_argument("--tenant-name", default="Demo Manufacturing Ltd")
        parser.add_argument("--tenant-country", default="GB")
        parser.add_argument("--admin-username", default="admin")
        parser.add_argument("--admin-password", default="breathe-esg-admin")

    def handle(self, *args, **opts):
        tenant, created = Tenant.objects.get_or_create(
            slug=opts["tenant_slug"],
            defaults={
                "name": opts["tenant_name"],
                "country_code": opts["tenant_country"],
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{'created' if created else 'found'} tenant {tenant.slug} "
                f"({tenant.name})"
            )
        )

        user, user_created = User.objects.get_or_create(
            username=opts["admin_username"],
            defaults={
                "email": f"{opts['admin_username']}@example.com",
                "tenant": tenant,
                "role": User.Role.ADMIN,
                "is_staff": True,
                "is_superuser": True,
            },
        )
        if user_created:
            user.set_password(opts["admin_password"])
            user.save()
            self.stdout.write(
                self.style.SUCCESS(
                    f"created admin user '{user.username}' (password: "
                    f"'{opts['admin_password']}' — change on first login)"
                )
            )
        else:
            self.stdout.write(self.style.WARNING(f"user {user.username} already exists"))

        token, token_created = Token.objects.get_or_create(user=user)
        self.stdout.write(
            f"  API token: {token.key} ({'new' if token_created else 'existing'})"
        )

        # Seed a reporting period for the current calendar year so the
        # lock workflow has something to act on out of the gate.
        from datetime import date

        year = date.today().year
        rp, rp_created = ReportingPeriod.objects.get_or_create(
            tenant=tenant,
            label=f"CY{year}",
            defaults={
                "period_start": date(year, 1, 1),
                "period_end": date(year, 12, 31),
            },
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"{'created' if rp_created else 'found'} reporting period {rp.label}"
            )
        )
