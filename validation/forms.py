from django import forms
from django.utils import timezone

from .models import OperatorValidation


class OperatorValidationForm(forms.ModelForm):
    class Meta:
        model = OperatorValidation
        fields = [
            "operator",
            "isolator_section",
            "status",
            "valid_from",
            "expires_on",
            "assessed_by",
            "evidence_ref",
            "notes",
        ]
        widgets = {
            "valid_from": forms.DateInput(attrs={"type": "date"}),
            "expires_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean(self):
        cleaned = super().clean()
        valid_from = cleaned.get("valid_from") or timezone.localdate()
        expires_on = cleaned.get("expires_on")

        if expires_on and expires_on < valid_from:
            self.add_error("expires_on", "Expiry date cannot be before valid_from.")

        return cleaned
