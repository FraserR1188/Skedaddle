from django.contrib import admin
from .models import CleanRoom, Isolator, StaffMember, ShiftTemplate, RotaDay, Assignment

admin.site.register(CleanRoom)
admin.site.register(Isolator)
admin.site.register(StaffMember)
admin.site.register(ShiftTemplate)
admin.site.register(RotaDay)
admin.site.register(Assignment)