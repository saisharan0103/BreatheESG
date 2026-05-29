from rest_framework import serializers

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


class TenantSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = ["id", "name", "slug", "country_code", "created_at"]


class UserSerializer(serializers.ModelSerializer):
    tenant = TenantSerializer(read_only=True)

    class Meta:
        model = User
        fields = ["id", "username", "email", "role", "tenant"]


class EmissionFactorSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmissionFactor
        fields = [
            "id",
            "activity_type",
            "scope",
            "region",
            "year",
            "source",
            "unit",
            "kg_co2e_per_unit",
            "citation_url",
            "citation_sheet",
            "notes",
        ]


class ReportingPeriodSerializer(serializers.ModelSerializer):
    locked_by_username = serializers.CharField(
        source="locked_by.username", read_only=True, default=None
    )
    records_in_period = serializers.SerializerMethodField()

    class Meta:
        model = ReportingPeriod
        fields = [
            "id",
            "tenant",
            "label",
            "period_start",
            "period_end",
            "status",
            "locked_by",
            "locked_by_username",
            "locked_at",
            "records_in_period",
        ]
        read_only_fields = ["tenant", "locked_by", "locked_at", "status"]

    def get_records_in_period(self, obj):
        return obj.activity_records.count()


class IngestionBatchSerializer(serializers.ModelSerializer):
    uploaded_by_username = serializers.CharField(
        source="uploaded_by.username", read_only=True, default=None
    )

    class Meta:
        model = IngestionBatch
        fields = [
            "id",
            "tenant",
            "source_system",
            "uploaded_by_username",
            "uploaded_at",
            "original_filename",
            "file_sha256",
            "file_size_bytes",
            "rows_ingested",
            "rows_errored",
            "status",
            "error_summary",
            "parser_notes",
        ]


class ActivityRecordRevisionSerializer(serializers.ModelSerializer):
    edited_by_username = serializers.CharField(
        source="edited_by.username", read_only=True, default=None
    )

    class Meta:
        model = ActivityRecordRevision
        fields = [
            "id",
            "field_name",
            "old_value",
            "new_value",
            "reason",
            "edited_by_username",
            "edited_at",
        ]


class ReviewActionSerializer(serializers.ModelSerializer):
    actor_username = serializers.CharField(
        source="actor.username", read_only=True, default=None
    )

    class Meta:
        model = ReviewAction
        fields = ["id", "action", "actor_username", "at", "note"]


class ActivityRecordListSerializer(serializers.ModelSerializer):
    factor_activity = serializers.CharField(
        source="emission_factor.activity_type", read_only=True, default=None
    )
    factor_region = serializers.CharField(
        source="emission_factor.region", read_only=True, default=None
    )
    factor_year = serializers.IntegerField(
        source="emission_factor.year", read_only=True, default=None
    )

    class Meta:
        model = ActivityRecord
        fields = [
            "id",
            "tenant",
            "scope",
            "activity_type",
            "description",
            "quantity_raw",
            "unit_raw",
            "quantity_normalized",
            "unit_normalized",
            "period_start",
            "period_end",
            "co2e_kg",
            "cost_amount",
            "cost_currency",
            "status",
            "flags",
            "source_system",
            "is_edited",
            "factor_activity",
            "factor_region",
            "factor_year",
        ]


class ActivityRecordDetailSerializer(serializers.ModelSerializer):
    emission_factor = EmissionFactorSerializer(read_only=True)
    revisions = ActivityRecordRevisionSerializer(many=True, read_only=True)
    review_actions = ReviewActionSerializer(many=True, read_only=True)
    batch_info = IngestionBatchSerializer(source="batch", read_only=True)

    class Meta:
        model = ActivityRecord
        fields = [
            "id",
            "tenant",
            "scope",
            "activity_type",
            "description",
            "quantity_raw",
            "unit_raw",
            "quantity_normalized",
            "unit_normalized",
            "period_start",
            "period_end",
            "co2e_kg",
            "cost_amount",
            "cost_currency",
            "status",
            "flags",
            "source_system",
            "source_record_id",
            "raw_payload",
            "is_edited",
            "emission_factor",
            "reporting_period",
            "ingested_at",
            "reviewed_at",
            "review_note",
            "revisions",
            "review_actions",
            "batch_info",
        ]


class ActivityRecordEditSerializer(serializers.Serializer):
    """
    Edit payload. Analysts can change the normalized quantity, the
    unit, the activity_type (to fix a misclassification), or the dates.
    Every change goes through ActivityRecordRevision.
    """

    quantity_normalized = serializers.DecimalField(
        max_digits=18, decimal_places=6, required=False
    )
    unit_normalized = serializers.CharField(required=False, max_length=24)
    activity_type = serializers.CharField(required=False, max_length=80)
    period_start = serializers.DateField(required=False)
    period_end = serializers.DateField(required=False)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=300)
