from rest_framework import permissions


class IsTenantMember(permissions.BasePermission):
    """User must belong to the same tenant as the record."""

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        if request.user.tenant_id is None:
            return False
        return getattr(obj, "tenant_id", None) == request.user.tenant_id


class IsTenantAdmin(permissions.BasePermission):
    """Admin role required (used for the period-lock action)."""

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.is_superuser or u.role == "admin"))

    def has_object_permission(self, request, view, obj):
        u = request.user
        if u.is_superuser:
            return True
        if getattr(obj, "tenant_id", None) != u.tenant_id:
            return False
        return u.role == "admin"
