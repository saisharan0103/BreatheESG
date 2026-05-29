from django.urls import path
from rest_framework.authtoken.views import obtain_auth_token

from . import views

urlpatterns = [
    path("auth/token/", obtain_auth_token, name="auth-token"),
    path("auth/whoami/", views.whoami, name="whoami"),
    path("tenants/", views.TenantListView.as_view(), name="tenant-list"),
    path("factors/", views.EmissionFactorListView.as_view(), name="factor-list"),
    path("records/", views.ActivityRecordListView.as_view(), name="record-list"),
    path(
        "records/<uuid:pk>/",
        views.ActivityRecordDetailView.as_view(),
        name="record-detail",
    ),
    path(
        "records/<uuid:pk>/approve/",
        views.record_approve,
        name="record-approve",
    ),
    path(
        "records/<uuid:pk>/reject/",
        views.record_reject,
        name="record-reject",
    ),
    path(
        "records/<uuid:pk>/edit/",
        views.record_edit,
        name="record-edit",
    ),
    path("batches/", views.IngestionBatchListView.as_view(), name="batch-list"),
    path("ingest/sap/", views.ingest_sap, name="ingest-sap"),
    path("ingest/utility-csv/", views.ingest_utility_csv, name="ingest-utility-csv"),
    path("ingest/utility-pdf/", views.ingest_utility_pdf, name="ingest-utility-pdf"),
    path("ingest/travel/", views.ingest_travel, name="ingest-travel"),
    path(
        "reporting-periods/",
        views.ReportingPeriodListView.as_view(),
        name="period-list",
    ),
    path(
        "reporting-periods/<uuid:pk>/lock/",
        views.reporting_period_lock,
        name="period-lock",
    ),
    path(
        "reporting-periods/<uuid:pk>/unlock/",
        views.reporting_period_unlock,
        name="period-unlock",
    ),
    path("summary/", views.tenant_summary, name="tenant-summary"),
]
