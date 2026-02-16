from django.contrib import admin
from .models import CleanRoom, Isolator, StaffMember, ShiftTemplate, RotaDay, Assignment, Crew


admin.site.register(CleanRoom)
admin.site.register(Isolator)
admin.site.register(Crew)


@admin.register(StaffMember)
class StaffMemberAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "role", "crew", "is_active")
    search_fields = ("first_name", "last_name", "email")
    list_filter = ("role", "crew", "is_active")
    ordering = ("crew__sort_order", "crew__name", "first_name", "last_name")


admin.site.register(ShiftTemplate)
admin.site.register(RotaDay)
admin.site.register(Assignment)
