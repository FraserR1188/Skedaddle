# rota/forms.py
from django import forms
from .models import StaffMember


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = [
            "first_name",
            "last_name",
            "email",
            "mobile_number",
            "role",
            "crew",
            "is_active",
        ]
