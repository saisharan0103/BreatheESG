from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import (
    ActivityRecord,
    ActivityRecordRevision,
    EmissionFactor,
    IngestionBatch,
    ReportingPeriod,
    ReviewAction,
    Tenant,
    User,
)


@admin.register(User)
class UserAdminCustom(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Tenant / role", {"fields": ("tenant", "role")}),
    )
    list_display = ("username", "email", "tenant", "role", "is_staff")
    list_filter = ("role", "tenant", "is_staff")


@admin.register(Tenant)
class TenantAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "country_code", "created_at")
    search_fields = ("name", "slug")


@admin.register(EmissionFactor)
class EmissionFactorAdmin(admin.ModelAdmin):
    list_display = (
        "activity_type",
        "scope",
        "region",
        "year",
        "source",
        "unit",
        "kg_co2e_per_unit",
    )
    list_filter = ("scope", "source", "region", "year")
    search_fields = ("activity_type",)


@admin.register(ReportingPeriod)
class ReportingPeriodAdmin(admin.ModelAdmin):
    list_display = ("tenant", "label", "period_start", "period_end", "status")
    list_filter = ("status", "tenant")


@admin.register(IngestionBatch)
class IngestionBatchAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "source_system",
        "uploaded_at",
        "rows_ingested",
        "rows_errored",
        "status",
    )
    list_filter = ("source_system", "status", "tenant")
    readonly_fields = ("id", "uploaded_at", "file_sha256")


@admin.register(ActivityRecord)
class ActivityRecordAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "tenant",
        "scope",
        "activity_type",
        "quantity_normalized",
        "unit_normalized",
        "period_start",
        "period_end",
        "co2e_kg",
        "status",
    )
    list_filter = ("scope", "status", "source_system", "tenant")
    search_fields = ("activity_type", "description", "source_record_id")
    readonly_fields = ("id", "ingested_at", "raw_payload")


@admin.register(ActivityRecordRevision)
class ActivityRecordRevisionAdmin(admin.ModelAdmin):
    list_display = ("record", "field_name", "edited_by", "edited_at")
    readonly_fields = ("id", "edited_at")


@admin.register(ReviewAction)
class ReviewActionAdmin(admin.ModelAdmin):
    list_display = ("record", "action", "actor", "at")
    list_filter = ("action",)
