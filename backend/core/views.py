from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.db import transaction
from django.db.models import Count, Sum
from django.utils import timezone
from rest_framework import generics, serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .flagging import flag_record_at_ingest, status_for_flags
from .ingestion.common import find_emission_factor
from .ingestion.sap import parse_sap_csv
from .ingestion.travel import parse_travel_csv, parse_travel_json
from .ingestion.utility_csv import parse_utility_csv
from .ingestion.utility_pdf import parse_utility_pdf
from .models import (
    ActivityRecord,
    ActivityRecordRevision,
    EmissionFactor,
    IngestionBatch,
    ReportingPeriod,
    ReviewAction,
    Tenant,
)
from .permissions import IsTenantAdmin, IsTenantMember
from .serializers import (
    ActivityRecordDetailSerializer,
    ActivityRecordEditSerializer,
    ActivityRecordListSerializer,
    EmissionFactorSerializer,
    IngestionBatchSerializer,
    ReportingPeriodSerializer,
    TenantSerializer,
    UserSerializer,
)


# ---------------------------------------------------------------------------
# Auth & meta
# ---------------------------------------------------------------------------


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def whoami(request):
    return Response(UserSerializer(request.user).data)


class TenantListView(generics.ListAPIView):
    serializer_class = TenantSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        u = self.request.user
        if u.is_superuser:
            return Tenant.objects.all()
        if u.tenant_id is None:
            return Tenant.objects.none()
        return Tenant.objects.filter(pk=u.tenant_id)


class EmissionFactorListView(generics.ListAPIView):
    serializer_class = EmissionFactorSerializer
    permission_classes = [IsAuthenticated]
    queryset = EmissionFactor.objects.all()


# ---------------------------------------------------------------------------
# Activity records
# ---------------------------------------------------------------------------


def _tenant_filter(user):
    if user.is_superuser:
        return {}
    return {"tenant_id": user.tenant_id}


class ActivityRecordListView(generics.ListAPIView):
    serializer_class = ActivityRecordListSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        qs = ActivityRecord.objects.filter(**_tenant_filter(self.request.user))
        params = self.request.query_params
        if scope := params.get("scope"):
            qs = qs.filter(scope=scope)
        if s := params.get("status"):
            qs = qs.filter(status=s)
        if src := params.get("source"):
            qs = qs.filter(source_system=src)
        if start := params.get("from"):
            qs = qs.filter(period_end__gte=start)
        if end := params.get("to"):
            qs = qs.filter(period_start__lte=end)
        if has_flags := params.get("flagged"):
            if has_flags == "1":
                qs = qs.exclude(flags=[])
        return qs.select_related("emission_factor")


class ActivityRecordDetailView(generics.RetrieveAPIView):
    serializer_class = ActivityRecordDetailSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        return ActivityRecord.objects.filter(
            **_tenant_filter(self.request.user)
        ).select_related("emission_factor", "batch")


def _check_writeable(record: ActivityRecord) -> Optional[Response]:
    if record.is_locked:
        return Response(
            {"detail": "Record is locked (audit). Unlock the reporting period to edit."},
            status=status.HTTP_409_CONFLICT,
        )
    return None


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantMember])
def record_approve(request, pk):
    record = generics.get_object_or_404(
        ActivityRecord.objects.filter(**_tenant_filter(request.user)), pk=pk
    )
    if (blocked := _check_writeable(record)) is not None:
        return blocked
    note = (request.data.get("note") or "").strip()
    record.status = ActivityRecord.Status.APPROVED
    record.reviewed_by = request.user
    record.reviewed_at = timezone.now()
    if note:
        record.review_note = note
    record.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    ReviewAction.objects.create(
        record=record, actor=request.user, action=ReviewAction.Action.APPROVE, note=note
    )
    return Response(ActivityRecordDetailSerializer(record).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantMember])
def record_reject(request, pk):
    record = generics.get_object_or_404(
        ActivityRecord.objects.filter(**_tenant_filter(request.user)), pk=pk
    )
    if (blocked := _check_writeable(record)) is not None:
        return blocked
    note = (request.data.get("note") or "").strip()
    record.status = ActivityRecord.Status.REJECTED
    record.reviewed_by = request.user
    record.reviewed_at = timezone.now()
    if note:
        record.review_note = note
    record.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note"])
    ReviewAction.objects.create(
        record=record, actor=request.user, action=ReviewAction.Action.REJECT, note=note
    )
    return Response(ActivityRecordDetailSerializer(record).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantMember])
def record_edit(request, pk):
    record = generics.get_object_or_404(
        ActivityRecord.objects.filter(**_tenant_filter(request.user)), pk=pk
    )
    if (blocked := _check_writeable(record)) is not None:
        return blocked

    ser = ActivityRecordEditSerializer(data=request.data)
    ser.is_valid(raise_exception=True)
    data = ser.validated_data
    reason = data.pop("reason", "") or ""

    changes = []
    with transaction.atomic():
        for field, new_value in data.items():
            old_value = getattr(record, field)
            if str(old_value) == str(new_value):
                continue
            ActivityRecordRevision.objects.create(
                record=record,
                edited_by=request.user,
                field_name=field,
                old_value=str(old_value),
                new_value=str(new_value),
                reason=reason,
            )
            setattr(record, field, new_value)
            changes.append(field)

        if changes:
            record.is_edited = True
            # If activity_type or unit changed, recompute factor + co2e
            if "activity_type" in changes or "unit_normalized" in changes:
                ef = find_emission_factor(
                    record.activity_type,
                    record.tenant.country_code,
                    record.period_start.year,
                )
                record.emission_factor = ef
            if record.emission_factor:
                record.co2e_kg = (
                    Decimal(record.quantity_normalized)
                    * record.emission_factor.kg_co2e_per_unit
                )
            else:
                record.co2e_kg = None
            record.save()

    return Response(ActivityRecordDetailSerializer(record).data)


# ---------------------------------------------------------------------------
# Ingestion endpoints
# ---------------------------------------------------------------------------


def _resolve_tenant(request):
    """Resolve the tenant for an ingestion request.

    Order of resolution:
      1. explicit ?tenant=<slug> (any user)
      2. user.tenant (if set)
      3. error
    """
    user = request.user
    slug = request.query_params.get("tenant") or request.data.get("tenant")
    if slug:
        try:
            tenant = Tenant.objects.get(slug=slug)
        except Tenant.DoesNotExist:
            return None, Response(
                {"detail": f"unknown tenant {slug!r}"},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Non-superusers must match their assigned tenant.
        if not user.is_superuser and user.tenant_id != tenant.id:
            return None, Response(
                {"detail": "not a member of that tenant"},
                status=status.HTTP_403_FORBIDDEN,
            )
        return tenant, None
    if user.tenant_id is not None:
        return user.tenant, None
    return None, Response(
        {"detail": "user has no tenant assigned; pass ?tenant=<slug>"},
        status=status.HTTP_400_BAD_REQUEST,
    )


def _attach_reporting_period(tenant: Tenant, record: ActivityRecord) -> None:
    rp = (
        ReportingPeriod.objects.filter(
            tenant=tenant,
            period_start__lte=record.period_end,
            period_end__gte=record.period_end,
        )
        .order_by("-period_start")
        .first()
    )
    record.reporting_period = rp


def _create_records_for_batch(batch: IngestionBatch, tenant: Tenant, parsed_iter):
    """
    Materialise ActivityRecord rows from parser output. Returns
    (ingested, errored). Each parser hands us an iterable of objects
    with the same canonical shape (see _PARSED_ATTRS below) plus
    `raw` and `parse_warnings`.
    """
    ingested = 0
    skipped: list[str] = []

    for parsed in parsed_iter:
        record_init = _activity_record_from_parsed(batch, tenant, parsed)
        if record_init is None:
            skipped.append(f"unhandled row: {parsed!r}")
            continue
        record, parse_warnings = record_init

        # Factor lookup using the tenant's country code as region default.
        factor = find_emission_factor(
            record.activity_type, tenant.country_code, record.period_start.year
        )
        record.emission_factor = factor
        if factor:
            record.co2e_kg = (
                Decimal(record.quantity_normalized) * factor.kg_co2e_per_unit
            )

        _attach_reporting_period(tenant, record)

        # First save to get a PK so flagging rules can query siblings.
        # Exceptions must be caught OUTSIDE the atomic block (Django ORM
        # marks the transaction broken otherwise).
        try:
            with transaction.atomic():
                record.save()
        except Exception as exc:
            skipped.append(f"{record.source_record_id or '<no-id>'}: {exc}")
            continue

        with transaction.atomic():
            flags = flag_record_at_ingest(record, parse_warnings)
            record.flags = flags
            record.status = status_for_flags(flags)
            record.save(update_fields=["flags", "status"])

        ingested += 1

    return ingested, skipped


def _activity_record_from_parsed(batch: IngestionBatch, tenant: Tenant, parsed):
    """
    Build an unsaved ActivityRecord from a parser dataclass. Returns
    (record, parse_warnings) or None if the parser shape is unrecognised.

    Avoids a runtime import dependency on each parser's dataclass by
    duck-typing on attribute names. Cleaner than isinstance forks.
    """
    cls_name = type(parsed).__name__

    if cls_name == "ParsedSapRow":
        scope = ActivityRecord.Scope.SCOPE_1
        return (
            ActivityRecord(
                tenant=tenant,
                batch=batch,
                source_system=IngestionBatch.SourceSystem.SAP,
                source_record_id=parsed.source_record_id,
                raw_payload=parsed.raw,
                scope=scope,
                activity_type=parsed.activity_type or "unknown",
                description=parsed.description,
                quantity_raw=parsed.quantity_raw,
                unit_raw=parsed.unit_raw,
                quantity_normalized=parsed.quantity_canonical,
                unit_normalized=parsed.unit_canonical,
                period_start=parsed.posting_date,
                period_end=parsed.posting_date,
                cost_amount=parsed.cost_amount,
                cost_currency=parsed.cost_currency,
            ),
            parsed.parse_warnings,
        )

    if cls_name == "ParsedUtilityRow":
        scope = ActivityRecord.Scope.SCOPE_2 if parsed.supply_type == "electricity" else ActivityRecord.Scope.SCOPE_1
        activity = "grid_electricity" if parsed.supply_type == "electricity" else "natural_gas"
        return (
            ActivityRecord(
                tenant=tenant,
                batch=batch,
                source_system=IngestionBatch.SourceSystem.UTILITY_CSV,
                source_record_id=parsed.source_record_id,
                raw_payload=parsed.raw | {"meter_id": parsed.meter_id, "estimated": parsed.estimated, "tariff": parsed.tariff},
                scope=scope,
                activity_type=activity,
                description=f"{parsed.site} {parsed.tariff}".strip(),
                quantity_raw=parsed.kwh,
                unit_raw="kWh",
                quantity_normalized=parsed.kwh,
                unit_normalized="kWh",
                period_start=parsed.period_start,
                period_end=parsed.period_end,
            ),
            parsed.parse_warnings,
        )

    if cls_name == "ParsedUtilityPdf":
        # PDF parser returns a single record (one bill); validate fields here.
        if not parsed.period_start or not parsed.period_end or parsed.kwh is None:
            warnings = list(parsed.parse_warnings) + ["pdf_partial_parse"]
            # Build a placeholder so the analyst can see it; mark zero-quantity to flag it.
            return (
                ActivityRecord(
                    tenant=tenant,
                    batch=batch,
                    source_system=IngestionBatch.SourceSystem.UTILITY_PDF,
                    source_record_id=parsed.meter_id or f"pdf-{batch.id}",
                    raw_payload={
                        "meter_id": parsed.meter_id,
                        "supplier": parsed.supplier,
                        "raw_text_excerpt": parsed.raw_text[:2000],
                    },
                    scope=ActivityRecord.Scope.SCOPE_2,
                    activity_type="grid_electricity",
                    description=f"PDF bill ({parsed.supplier})",
                    quantity_raw=parsed.kwh or Decimal("0"),
                    unit_raw="kWh",
                    quantity_normalized=parsed.kwh or Decimal("0"),
                    unit_normalized="kWh",
                    period_start=parsed.period_start or timezone.now().date(),
                    period_end=parsed.period_end or timezone.now().date(),
                ),
                warnings,
            )
        return (
            ActivityRecord(
                tenant=tenant,
                batch=batch,
                source_system=IngestionBatch.SourceSystem.UTILITY_PDF,
                source_record_id=f"{parsed.meter_id}-{parsed.period_start:%Y%m%d}",
                raw_payload={
                    "meter_id": parsed.meter_id,
                    "supplier": parsed.supplier,
                    "raw_text_excerpt": parsed.raw_text[:2000],
                },
                scope=ActivityRecord.Scope.SCOPE_2,
                activity_type="grid_electricity",
                description=f"PDF bill ({parsed.supplier})",
                quantity_raw=parsed.kwh,
                unit_raw="kWh",
                quantity_normalized=parsed.kwh,
                unit_normalized="kWh",
                period_start=parsed.period_start,
                period_end=parsed.period_end,
            ),
            parsed.parse_warnings,
        )

    if cls_name == "ParsedTravelRow":
        return (
            ActivityRecord(
                tenant=tenant,
                batch=batch,
                source_system=IngestionBatch.SourceSystem.TRAVEL,
                source_record_id=parsed.source_record_id,
                raw_payload=parsed.raw | {"employee_id": parsed.employee_id, "segment_type": parsed.segment_type},
                scope=ActivityRecord.Scope.SCOPE_3,
                activity_type=parsed.activity_type,
                description=parsed.description,
                quantity_raw=parsed.quantity,
                unit_raw=parsed.unit,
                quantity_normalized=parsed.quantity,
                unit_normalized=parsed.unit,
                period_start=parsed.start_date,
                period_end=parsed.end_date or parsed.start_date,
                cost_amount=parsed.cost_amount,
                cost_currency=parsed.cost_currency,
            ),
            parsed.parse_warnings,
        )

    return None


def _do_ingest(request, parse_fn, source_system: str, expects_pdf: bool = False):
    tenant, err = _resolve_tenant(request)
    if err:
        return err
    if "file" not in request.FILES:
        return Response({"detail": "field 'file' missing"}, status=status.HTTP_400_BAD_REQUEST)
    upload = request.FILES["file"]
    blob = upload.read()

    batch = IngestionBatch.objects.create(
        tenant=tenant,
        source_system=source_system,
        uploaded_by=request.user,
        original_filename=upload.name,
        file_sha256=IngestionBatch.sha256_of(blob),
        file_size_bytes=len(blob),
        status=IngestionBatch.Status.PARSED,
    )

    if expects_pdf:
        parsed_obj = parse_fn(blob)
        parsed_iter = [parsed_obj]
        errors: list[str] = []
        notes: dict = {"pdf_parse_warnings": parsed_obj.parse_warnings}
    else:
        parsed_iter, errors, notes = parse_fn(blob)

    ingested, skipped = _create_records_for_batch(batch, tenant, parsed_iter)
    all_errs = errors + skipped

    batch.rows_ingested = ingested
    batch.rows_errored = len(all_errs)
    batch.parser_notes = notes
    if ingested == 0 and all_errs:
        batch.status = IngestionBatch.Status.FAILED
    elif all_errs:
        batch.status = IngestionBatch.Status.PARTIAL
    batch.error_summary = "\n".join(all_errs[:50])
    batch.save()

    return Response(
        IngestionBatchSerializer(batch).data, status=status.HTTP_201_CREATED
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantMember])
def ingest_sap(request):
    return _do_ingest(request, parse_sap_csv, IngestionBatch.SourceSystem.SAP)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantMember])
def ingest_utility_csv(request):
    return _do_ingest(
        request, parse_utility_csv, IngestionBatch.SourceSystem.UTILITY_CSV
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantMember])
def ingest_utility_pdf(request):
    return _do_ingest(
        request,
        parse_utility_pdf,
        IngestionBatch.SourceSystem.UTILITY_PDF,
        expects_pdf=True,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantMember])
def ingest_travel(request):
    """
    Accepts CSV OR JSON. The choice is made by the uploaded file's
    extension (or `format=json|csv` query param override).
    """
    fmt = (request.query_params.get("format") or "").lower()
    if "file" in request.FILES:
        name = request.FILES["file"].name.lower()
        if not fmt:
            if name.endswith(".json"):
                fmt = "json"
            else:
                fmt = "csv"
    parser = parse_travel_json if fmt == "json" else parse_travel_csv
    return _do_ingest(request, parser, IngestionBatch.SourceSystem.TRAVEL)


# ---------------------------------------------------------------------------
# Batches & reporting periods
# ---------------------------------------------------------------------------


class IngestionBatchListView(generics.ListAPIView):
    serializer_class = IngestionBatchSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        return IngestionBatch.objects.filter(**_tenant_filter(self.request.user))


class ReportingPeriodListView(generics.ListCreateAPIView):
    serializer_class = ReportingPeriodSerializer
    permission_classes = [IsAuthenticated, IsTenantMember]

    def get_queryset(self):
        return ReportingPeriod.objects.filter(**_tenant_filter(self.request.user))

    def perform_create(self, serializer):
        tenant, err = _resolve_tenant(self.request)
        if err is not None or tenant is None:
            # _resolve_tenant returns a 4xx Response; serialize that as
            # a validation error instead so DRF's create() pipeline gets
            # a proper failure mode.
            raise serializers.ValidationError(
                {"tenant": "could not resolve tenant for this user"}
            )
        serializer.save(tenant=tenant)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantAdmin])
def reporting_period_lock(request, pk):
    period = generics.get_object_or_404(
        ReportingPeriod.objects.filter(**_tenant_filter(request.user)), pk=pk
    )
    pending = period.activity_records.exclude(
        status__in=[ActivityRecord.Status.APPROVED, ActivityRecord.Status.REJECTED]
    ).count()
    if pending > 0:
        return Response(
            {
                "detail": (
                    f"Cannot lock: {pending} record(s) still pending/flagged. "
                    "Resolve them first."
                )
            },
            status=status.HTTP_409_CONFLICT,
        )
    period.status = ReportingPeriod.Status.LOCKED
    period.locked_by = request.user
    period.locked_at = timezone.now()
    period.save()
    # cascade lock to approved records (rejected rows are left as-is)
    period.activity_records.filter(status=ActivityRecord.Status.APPROVED).update(
        status=ActivityRecord.Status.LOCKED
    )
    return Response(ReportingPeriodSerializer(period).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated, IsTenantAdmin])
def reporting_period_unlock(request, pk):
    period = generics.get_object_or_404(
        ReportingPeriod.objects.filter(**_tenant_filter(request.user)), pk=pk
    )
    period.status = ReportingPeriod.Status.OPEN
    period.locked_by = None
    period.locked_at = None
    period.save()
    period.activity_records.filter(status=ActivityRecord.Status.LOCKED).update(
        status=ActivityRecord.Status.APPROVED
    )
    return Response(ReportingPeriodSerializer(period).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated, IsTenantMember])
def tenant_summary(request):
    """Aggregate stats for the dashboard landing page."""
    qs = ActivityRecord.objects.filter(**_tenant_filter(request.user))
    by_scope = list(
        qs.values("scope")
        .annotate(co2e_kg=Sum("co2e_kg"), count=Count("id"))
        .order_by("scope")
    )
    by_status = list(
        qs.values("status").annotate(count=Count("id")).order_by("status")
    )
    by_source = list(
        qs.values("source_system").annotate(count=Count("id")).order_by("source_system")
    )
    return Response(
        {
            "total_records": qs.count(),
            "total_co2e_kg": qs.aggregate(Sum("co2e_kg"))["co2e_kg__sum"] or 0,
            "by_scope": by_scope,
            "by_status": by_status,
            "by_source": by_source,
        }
    )
