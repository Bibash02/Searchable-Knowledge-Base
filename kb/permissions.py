from rest_framework.permissions import SAFE_METHODS, BasePermission

from accounts.models import Role


def _authed(user):
    return bool(user and user.is_authenticated)


def can_see_internal(user):
    return _authed(user) and (user.is_superuser or user.role in {Role.STAFF, Role.EDITOR, Role.ADMIN})


def is_editor(user):
    return _authed(user) and (user.is_superuser or user.role in {Role.EDITOR, Role.ADMIN})


def is_admin(user):
    return _authed(user) and (user.is_superuser or user.role == Role.ADMIN)


class EditorWritesOnly(BasePermission):
    """Anyone may read (what they can see is decided by selectors); only editors write."""

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return is_editor(request.user)
