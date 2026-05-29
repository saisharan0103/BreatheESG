"""
Data model for the Breathe ESG ingestion + review prototype.

The spine is `ActivityRecord` — every fuel purchase, kWh of electricity,
flight leg, or hotel night becomes one row here, regardless of which
source system produced it. Sources hand off their messy raw data and
this table stores the canonical, normalized, auditable view.

Conventions:

- `tenant` is on every business-data table; row-level multi-tenancy.
- Provenance lives on each row: which source, which batch, raw payload,
  content hash. We never persist the uploaded file (Vercel filesystem
  is ephemeral and audit only needs the parsed values + a hash).
- Edits go through `ActivityRecordRevision`, never destructive in place.
- Reporting-period lock is the audit gate; row-level approval feeds it.
"""
from __future__ import annotations

import hashlib
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Tenant(models.Model):
    """A client company whose emissions we ingest."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200, unique=True)
    slug = models.SlugField(max_length=80, unique=True)
    country_code = models.CharField(
        max_length=2,
        help_text="ISO 3166-1 alpha-2; drives default factor region (e.g. GB, US).",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class User(AbstractUser):
    """Custom user with a role field and tenant scoping."""

    class Role(models.TextChoices):
        ANALYST = "analyst", "Analyst"
        ADMIN = "admin", "Admin"

    tenant = models.ForeignKey(
        Tenant,
        on_delete=models.CASCADE,
        related_name="users",
        null=True,
        blank=True,
        help_text="Tenant this user reviews data for. Superusers can be tenant-less.",
    )
    role = models.CharField(
        max_length=16,
        choices=Role.choices,
        default=Role.ANALYST,
    )

    @property
    def is_period_locker(self) -> bool:
        return self.role == self.Role.ADMIN or self.is_superuser


# ---------------------------------------------------------------------------
# Reference data — emission factors
# ---------------------------------------------------------------------------


class EmissionFactor(models.Model):
    """
    A single emission factor row.

    Factors are versioned per (activity_type, region, year, source). We
    never overwrite a factor; we add a new row when the publishing body
    releases an update. Activity records link to a specific factor row,
    so re-running emission math after a factor update is a deliberate
    re-tagging, not a silent number change. That matters for audit.

    Sources we seed:
    - DEFRA / UK DESNZ 2024 GHG conversion factors workbook (v1.1).
    - US EPA Emission Factors Hub 2024.
    """

    class Scope(models.IntegerChoices):
        SCOPE_1 = 1, "Scope 1"
        SCOPE_2 = 2, "Scope 2"
        SCOPE_3 = 3, "Scope 3"

    class Source(models.TextChoices):
        DEFRA = "defra", "DEFRA / UK DESNZ"
        EPA = "epa", "US EPA"

    activity_type = models.CharField(
        max_length=80,
        help_text="Canonical key, e.g. diesel, natural_gas, grid_electricity, "
        "flight_short_haul_economy, hotel_night, rail.",
    )
    scope = models.IntegerField(choices=Scope.choices)
    region = models.CharField(
        max_length=8,
        help_text="ISO country code, eGRID subregion, or 'GLOBAL'.",
    )
    year = models.IntegerField()
    source = models.CharField(max_length=16, choices=Source.choices)

    # Factor body
    unit = models.CharField(
        max_length=24,
        help_text="Activity unit the factor applies to, e.g. litre, kWh, "
        "passenger_km, room_night, kg.",
    )
    kg_co2e_per_unit = models.DecimalField(max_digits=14, decimal_places=8)

    # Provenance & traceability — never invent a factor; always cite.
    citation_url = models.URLField(
        help_text="Direct URL to the source workbook / PDF this row was extracted from.",
    )
    citation_sheet = models.CharField(
        max_length=200,
        blank=True,
        help_text="Sheet name and/or row reference inside the workbook.",
    )
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["activity_type", "region", "year", "source"],
                name="emission_factor_unique_per_dimension",
            ),
        ]
        indexes = [
            models.Index(fields=["activity_type", "region", "year"]),
        ]
        ordering = ["activity_type", "region", "-year"]

    def __str__(self) -> str:
        return f"{self.activity_type} {self.region} {self.year} ({self.source})"


# ---------------------------------------------------------------------------
# Reporting periods (the audit lock unit)
# ---------------------------------------------------------------------------


class ReportingPeriod(models.Model):
    """
    A reporting period for a tenant (calendar year, quarter, custom).

    The audit lock attaches here, not on individual rows. Once locked,
    no record whose `period_end` falls inside this period can be edited.
    """

    class Status(models.TextChoices):
        OPEN = "open", "Open"
        LOCKED = "locked", "Locked"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="reporting_periods"
    )
    label = models.CharField(
        max_length=80,
        help_text="Human label, e.g. 'FY2024 Q1' or 'CY2024'.",
    )
    period_start = models.DateField()
    period_end = models.DateField()
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.OPEN
    )
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="periods_locked",
    )
    locked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["tenant", "label"], name="reporting_period_unique_label"
            ),
        ]
        ordering = ["-period_end"]

    def __str__(self) -> str:
        return f"{self.tenant.slug} {self.label}"

    @property
    def is_locked(self) -> bool:
        return self.status == self.Status.LOCKED


# ---------------------------------------------------------------------------
# Ingestion provenance
# ---------------------------------------------------------------------------


class IngestionBatch(models.Model):
    """One upload / pull. A batch is the unit of 'undo'."""

    class SourceSystem(models.TextChoices):
        SAP = "sap", "SAP (procurement / fuel)"
        UTILITY_CSV = "utility_csv", "Utility portal CSV"
        UTILITY_PDF = "utility_pdf", "Utility bill PDF"
        TRAVEL = "travel", "Corporate travel export"

    class Status(models.TextChoices):
        PARSED = "parsed", "Parsed"
        PARTIAL = "partial", "Partial (some rows errored)"
        FAILED = "failed", "Failed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="ingestion_batches"
    )
    source_system = models.CharField(max_length=24, choices=SourceSystem.choices)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="batches_uploaded",
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    original_filename = models.CharField(max_length=512, blank=True)
    file_sha256 = models.CharField(
        max_length=64,
        blank=True,
        help_text="Content hash of the uploaded bytes. We don't keep the file "
        "(Vercel filesystem is ephemeral and the parsed rows + hash are "
        "what auditors need).",
    )
    file_size_bytes = models.PositiveIntegerField(default=0)

    rows_ingested = models.PositiveIntegerField(default=0)
    rows_errored = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PARSED
    )
    error_summary = models.TextField(
        blank=True,
        help_text="Human-readable summary of why rows failed (parser errors, "
        "missing required fields).",
    )
    parser_notes = models.JSONField(
        default=dict, blank=True, help_text="Locale detected, header language, etc."
    )

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self) -> str:
        return f"{self.source_system} batch {self.id} ({self.rows_ingested} rows)"

    @staticmethod
    def sha256_of(blob: bytes) -> str:
        return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# The spine: ActivityRecord
# ---------------------------------------------------------------------------


class ActivityRecord(models.Model):
    """
    One unit of activity, normalized.

    All three sources collapse into rows of this table. Fields are split
    into:
      - **provenance** (where did this come from, how do we cite it),
      - **activity** (what happened: what type, when, how much),
      - **emissions** (what factor did we apply, what's the CO2e),
      - **review state** (approval, lock, edit tracking),
      - **flags** (rules that fired during ingestion / review).
    """

    class Scope(models.IntegerChoices):
        SCOPE_1 = 1, "Scope 1"
        SCOPE_2 = 2, "Scope 2"
        SCOPE_3 = 3, "Scope 3"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending review"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        FLAGGED = "flagged", "Flagged for follow-up"
        LOCKED = "locked", "Locked (audit)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tenant = models.ForeignKey(
        Tenant, on_delete=models.CASCADE, related_name="activity_records"
    )

    # --- Provenance ---
    batch = models.ForeignKey(
        IngestionBatch,
        on_delete=models.CASCADE,
        related_name="records",
    )
    source_system = models.CharField(
        max_length=24, choices=IngestionBatch.SourceSystem.choices
    )
    source_record_id = models.CharField(
        max_length=200,
        blank=True,
        help_text="Native identifier from the source: SAP EBELN+EBELP, MPAN+period, "
        "Concur Trip ID + segment index, etc. Used to dedupe re-ingestions.",
    )
    raw_payload = models.JSONField(
        default=dict,
        help_text="The original parsed row as a JSON dict. Preserves every "
        "field we received even if we don't use it for emissions math.",
    )
    ingested_at = models.DateTimeField(auto_now_add=True)

    # --- Activity ---
    scope = models.IntegerField(choices=Scope.choices)
    activity_type = models.CharField(
        max_length=80,
        help_text="Canonical key matching EmissionFactor.activity_type "
        "(e.g. diesel, grid_electricity, flight_short_haul_economy).",
    )
    description = models.CharField(max_length=300, blank=True)

    quantity_raw = models.DecimalField(max_digits=18, decimal_places=6)
    unit_raw = models.CharField(max_length=24)
    quantity_normalized = models.DecimalField(
        max_digits=18,
        decimal_places=6,
        help_text="Converted into the unit the matched EmissionFactor expects.",
    )
    unit_normalized = models.CharField(max_length=24)

    period_start = models.DateField(
        help_text="Activity period start. NOT ingestion date. Utility bills span "
        "weird periods that don't align with calendar months — we store what "
        "the source said happened."
    )
    period_end = models.DateField()

    cost_amount = models.DecimalField(
        max_digits=14, decimal_places=2, null=True, blank=True
    )
    cost_currency = models.CharField(max_length=3, blank=True)

    # --- Emissions ---
    emission_factor = models.ForeignKey(
        EmissionFactor,
        on_delete=models.PROTECT,
        related_name="activity_records",
        null=True,
        blank=True,
        help_text="Null when no factor matched (row will be flagged "
        "factor_missing).",
    )
    co2e_kg = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        null=True,
        blank=True,
        help_text="quantity_normalized * emission_factor.kg_co2e_per_unit.",
    )

    # --- Review state ---
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="records_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.TextField(blank=True)

    reporting_period = models.ForeignKey(
        ReportingPeriod,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_records",
        help_text="Set when the record's period_end falls inside a known "
        "reporting period for the tenant. Lock state flows from here.",
    )

    is_edited = models.BooleanField(
        default=False,
        help_text="True if a user has edited any normalized field since "
        "ingestion. Original ingested values live in raw_payload.",
    )

    # --- Flags ---
    flags = models.JSONField(
        default=list,
        blank=True,
        help_text="List of flag codes the flagging engine emitted, "
        "e.g. ['unit_inferred', 'factor_assumed', 'period_overlap'].",
    )

    class Meta:
        constraints = [
            # Same source identifier within a tenant should not be re-ingested
            # silently. We allow re-ingestion via a fresh batch but dedupe
            # at the source-record level.
            models.UniqueConstraint(
                fields=["tenant", "source_system", "source_record_id"],
                condition=models.Q(source_record_id__gt=""),
                name="activity_record_unique_source_id_per_tenant",
            ),
        ]
        indexes = [
            models.Index(fields=["tenant", "status"]),
            models.Index(fields=["tenant", "scope", "period_start"]),
            models.Index(fields=["tenant", "activity_type", "period_start"]),
            models.Index(fields=["batch"]),
        ]
        ordering = ["-period_end", "-ingested_at"]

    def __str__(self) -> str:
        return f"{self.activity_type} {self.quantity_normalized} {self.unit_normalized} ({self.period_start}..{self.period_end})"

    @property
    def is_locked(self) -> bool:
        return self.status == self.Status.LOCKED or (
            self.reporting_period and self.reporting_period.is_locked
        )


class ActivityRecordRevision(models.Model):
    """
    Append-only edit history for ActivityRecord.

    Every time an analyst edits a field, we snapshot the old value here
    along with who/when/why. Reconstructing the value at audit time means
    walking this table back. We never UPDATE these rows.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(
        ActivityRecord, on_delete=models.CASCADE, related_name="revisions"
    )
    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="record_edits",
    )
    edited_at = models.DateTimeField(default=timezone.now)
    field_name = models.CharField(max_length=80)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    reason = models.CharField(
        max_length=300,
        blank=True,
        help_text="Why the analyst changed it (e.g. 'meter reading corrected after "
        "supplier rebill', 'unit was L not GAL').",
    )

    class Meta:
        ordering = ["-edited_at"]
        indexes = [models.Index(fields=["record", "edited_at"])]

    def __str__(self) -> str:
        return f"{self.record_id} {self.field_name} @ {self.edited_at}"


class ReviewAction(models.Model):
    """
    Every status transition on an ActivityRecord (approve, reject, flag,
    lock, unlock). Separate from RecordRevision so the audit log can
    show 'who approved' independently from 'who edited a number'.
    """

    class Action(models.TextChoices):
        APPROVE = "approve", "Approve"
        REJECT = "reject", "Reject"
        FLAG = "flag", "Flag"
        UNFLAG = "unflag", "Clear flag"
        LOCK = "lock", "Lock"
        UNLOCK = "unlock", "Unlock"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    record = models.ForeignKey(
        ActivityRecord, on_delete=models.CASCADE, related_name="review_actions"
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    action = models.CharField(max_length=16, choices=Action.choices)
    at = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-at"]
