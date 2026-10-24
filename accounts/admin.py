from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

# Register your models here.
@admin.register(User)
class KBUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (("Knowledge base", {"fields": ("role",)}),)
    list_display = ("username", "email", "role", "is_active")
    list_filter = UserAdmin.list_filter + ("role",)
