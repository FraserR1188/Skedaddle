from django.contrib import admin

from .models import (
    Assignment,
    CleanRoom,
    Crew,
    Isolator,
    RotaDay,
    ShiftTemplate,
    StaffMember,
    WorkArea,
)


@admin.register(CleanRoom)
class CleanRoomAdmin(admin.ModelAdmin):
    list_display = ("number", "name")
    search_fields = ("name",)
    ordering = ("number",)


@admin.register(Isolator)
class IsolatorAdmin(admin.ModelAdmin):
    list_display = ("name", "clean_room", "order")
    list_filter = ("clean_room",)
    search_fields = ("name", "clean_room__name")
    ordering = ("clean_room__number", "order", "name")


@admin.register(Crew)
class CrewAdmin(admin.ModelAdmin):
    list_display = ("name", "sort_order")
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "role", "crew", "is_active")
    search_fields = ("first_name", "last_name", "email")
    list_filter = ("role", "crew", "is_active")
    ordering = ("crew__sort_order", "crew__name", "first_name", "last_name")


@admin.register(ShiftTemplate)
class ShiftTemplateAdmin(admin.ModelAdmin):
    list_display = ("name", "start_time", "end_time")
    search_fields = ("name",)
    ordering = ("start_time", "name")


@admin.register(WorkArea)
class WorkAreaAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "area_type",
        "required_staff_am",
        "required_staff_pm",
        "requires_supervisor",
        "requires_validation",
        "is_active",
        "sort_order",
    )
    list_filter = (
        "area_type",
        "is_active",
        "requires_supervisor",
        "requires_validation",
    )
    search_fields = ("name",)
    ordering = ("sort_order", "name")


@admin.register(RotaDay)
class RotaDayAdmin(admin.ModelAdmin):
    list_display = (
        "date",
        "status",
        "publish_version",
        "published_at",
        "published_by",
    )
    list_filter = ("status",)
    search_fields = ("date",)
    ordering = ("-date",)


@admin.register(Assignment)
class AssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "rotaday",
        "shift_block",
        "staff",
        "location_type",
        "clean_room",
        "isolator",
        "isolator_section",
        "work_area",
        "is_room_supervisor",
    )
    list_filter = (
        "location_type",
        "shift_block",
        "clean_room",
        "isolator",
        "work_area",
        "is_room_supervisor",
    )
    search_fields = (
        "staff__first_name",
        "staff__last_name",
        "clean_room__name",
        "isolator__name",
        "work_area__name",
    )
    ordering = (
        "-rotaday__date",
        "shift_block",
        "clean_room__number",
        "isolator__order",
        "work_area__sort_order",
        "staff__first_name",
        "staff__last_name",
    )