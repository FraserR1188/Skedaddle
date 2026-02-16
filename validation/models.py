from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class Isolator(models.Model):
    """
    Represents an isolator unit (e.g. Isolator 1).
    """

    name = models.CharField(max_length=100, unique=True)
    sort_order = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self) -> str:
        return self.name


class IsolatorSection(models.Model):
    """
    Represents a section of an isolator (e.g. Left / Right).
    APS validation is applied at this level.
    """

    class SectionType(models.TextChoices):
        LEFT = "L", "Left"
        RIGHT = "R", "Right"

    isolator = models.ForeignKey(
        Isolator,
        on_delete=models.PROTECT,
        related_name="sections",
    )

    section = models.CharField(
        max_length=1,
        choices=SectionType.choices,
    )

    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("isolator", "section")
        ordering = ["isolator__sort_order", "section"]

    def __str__(self) -> str:
        return f"{self.isolator.name} {self.get_section_display()}"
        

class OperatorValidation(models.Model):
    """
    Maps an operator to an isolator section with APS validation status.
    """

    class Status(models.TextChoices):
        VALID = "VALID", "Valid"
        IN_TRAINING = "IN_TRAINING", "In Training"
        RESTRICTED = "RESTRICTED", "Restricted"
        SUSPENDED = "SUSPENDED", "Suspended"

    # ⚠️ Change this if you use a Staff model instead of auth User
    operator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="isolator_validations",
    )

    isolator_section = models.ForeignKey(
        IsolatorSection,
        on_delete=models.PROTECT,
        related_name="operator_validations",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.VALID,
    )

    valid_from = models.DateField(default=timezone.localdate)
    expires_on = models.DateField(null=True, blank=True)

    assessed_by = models.CharField(max_length=120, blank=True)
    evidence_ref = models.CharField(max_length=120, blank=True)
    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ("operator", "isolator_section")
        ordering = ["isolator_section", "operator"]
        indexes = [
            models.Index(fields=["operator", "isolator_section"]),
            models.Index(fields=["status", "expires_on"]),
        ]

    def __str__(self) -> str:
        return f"{self.operator} → {self.isolator_section} [{self.status}]"

    def clean(self):
        if self.expires_on and self.expires_on < self.valid_from:
            raise ValidationError(
                {"expires_on": "Expiry date cannot be before valid_from."}
            )

    def is_effective_on(self, date=None) -> bool:
        """
        Returns True if validation is effective on given date.
        """
        if date is None:
            date = timezone.localdate()

        if self.status != self.Status.VALID:
            return False

        if date < self.valid_from:
            return False

        if self.expires_on and date > self.expires_on:
            return False

        return True
