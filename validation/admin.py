from django.contrib import admin

from .models import IsolatorSection, OperatorValidation


# ----------------------------
# Isolator Section Admin
# ----------------------------

@admin.register(IsolatorSection)
class IsolatorSectionAdmin(admin.ModelAdmin):
    list_display = ("isolator", "section", "is_active")
    list_filter = ("isolator", "section", "is_active")
    search_fields = (
        "isolator__name",
        "isolator__clean_room__name",
    )
    ordering = ("isolator__clean_room__number", "isolator__order", "section")


# ----------------------------
# Operator Validation Admin
# ----------------------------

@admin.register(OperatorValidation)
class OperatorValidationAdmin(admin.ModelAdmin):
    list_display = (
        "operator",
        "isolator_section",
        "status",
        "valid_from",
        "expires_on",
    )
    list_filter = (
        "status",
        "isolator_section__isolator",
        "isolator_section",
    )
    search_fields = (
        "operator__first_name",
        "operator__last_name",
        "operator__email",
        "isolator_section__isolator__name",
        "isolator_section__isolator__clean_room__name",
    )
    autocomplete_fields = ("operator", "isolator_section")
    ordering = ("isolator_section__isolator__order", "isolator_section__section", "operator__last_name")
    date_hierarchy = "valid_from"
