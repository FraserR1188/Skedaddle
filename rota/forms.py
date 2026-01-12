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
            "role",
            "crew",
            "is_active",
        ]
        labels = {
            "first_name": "First name",
            "last_name": "Last name",
            "mobile_number": "Mobile number",
            "is_active": "Active",
        }
        widgets = {
            "first_name": forms.TextInput(attrs={"placeholder": "e.g. Robbie"}),
            "last_name": forms.TextInput(attrs={"placeholder": "e.g. Fraser"}),
            "email": forms.EmailInput(attrs={"placeholder": "name@nhs.net"}),
            "mobile_number": forms.TextInput(attrs={"placeholder": "Optional"}),
        }

    def clean_first_name(self):
        return self.cleaned_data["first_name"].strip()

    def clean_last_name(self):
        return self.cleaned_data["last_name"].strip()
