from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
from typing import Optional

from django.db import models
from django.utils import timezone

from rota.models import StaffMember
from .models import OperatorValidation, IsolatorSection


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str
    validation: Optional[OperatorValidation] = None


def _as_date(d: Optional[date_type]) -> date_type:
    return d or timezone.localdate()


def get_operator_validation(
    operator: StaffMember,
    isolator_section: IsolatorSection,
) -> Optional[OperatorValidation]:
    """
    Returns the validation row for operator + section if it exists, else None.
    """
    return (
        OperatorValidation.objects
        .select_related("operator", "isolator_section", "isolator_section__isolator")
        .filter(operator=operator, isolator_section=isolator_section)
        .first()
    )


def check_operator_valid_for_section(
    operator: StaffMember,
    isolator_section: IsolatorSection,
    on_date: Optional[date_type] = None,
) -> ValidationResult:
    """
    Core eligibility check.
    Use this everywhere (UI filtering, save-time enforcement, swaps, auto-assign).
    """
    on_date = _as_date(on_date)

    if not operator.is_active:
        return ValidationResult(False, "Staff member is inactive.")

    if not isolator_section.is_active:
        return ValidationResult(False, "Isolator section is inactive.")

    # Optional: if isolator has no 'is_active' field in rota, skip this.
    # If you later add rota.Isolator.is_active, you can enforce here.

    v = get_operator_validation(operator, isolator_section)
    if not v:
        return ValidationResult(False, "No APS validation record found.")

    if v.status != OperatorValidation.Status.VALID:
        return ValidationResult(False, f"APS status is '{v.get_status_display()}'.", v)

    if on_date < v.valid_from:
        return ValidationResult(False, f"APS not yet effective until {v.valid_from.isoformat()}.", v)

    if v.expires_on and on_date > v.expires_on:
        return ValidationResult(False, f"APS expired on {v.expires_on.isoformat()}.", v)

    return ValidationResult(True, "OK", v)


def is_operator_valid_for_section(
    operator: StaffMember,
    isolator_section: IsolatorSection,
    on_date: Optional[date_type] = None,
) -> tuple[bool, str]:
    """
    Backwards-friendly helper returning (ok, reason).
    """
    r = check_operator_valid_for_section(operator, isolator_section, on_date)
    return r.ok, r.reason


def get_valid_operators_for_section(
    isolator_section: IsolatorSection,
    on_date: Optional[date_type] = None,
) -> models.QuerySet[StaffMember]:
    """
    Query helper for dropdown filtering / candidate pools.
    """
    on_date = _as_date(on_date)

    return (
        StaffMember.objects
        .filter(
            is_active=True,
            isolator_validations__isolator_section=isolator_section,
            isolator_validations__status=OperatorValidation.Status.VALID,
            isolator_validations__valid_from__lte=on_date,
        )
        .filter(
            models.Q(isolator_validations__expires_on__isnull=True) |
            models.Q(isolator_validations__expires_on__gte=on_date)
        )
        .distinct()
        .order_by("crew__sort_order", "crew__name", "last_name", "first_name")
    )
