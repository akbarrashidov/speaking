from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import DailyQuota, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = (
        "email",
        "first_name",
        "plan",
        "last_active_at",
    )
    list_filter = ("plan", "is_staff", "is_active")
    search_fields = ("email", "first_name")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "last_active_at", "last_login")
    list_editable = ("plan",)
    actions = ("make_premium", "make_free")

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Profil", {"fields": ("first_name", "language_code")}),
        ("O'qish", {"fields": ("plan", "speaking_register")}),
        (
            "Ruxsatlar",
            {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions")},
        ),
        ("Sanalar", {"fields": ("created_at", "last_active_at", "last_login")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
    )

    @admin.action(description="Premium qilish")
    def make_premium(self, request, queryset):
        queryset.update(plan="premium")

    @admin.action(description="Free qilish")
    def make_free(self, request, queryset):
        queryset.update(plan="free")


@admin.register(DailyQuota)
class DailyQuotaAdmin(admin.ModelAdmin):
    list_display = ("user", "date", "sessions_used")
    list_filter = ("date",)
    search_fields = ("user__email", "user__first_name")
