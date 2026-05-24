from __future__ import annotations

from dataclasses import dataclass
from datetime import date as date_type
import re
from typing import Optional

from django.db import models
from django.utils import timezone

from rota.models import StaffMember
from .models import OperatorValidation, IsolatorSection


ISOLATOR_SIDE_SUFFIX_RE = re.compile(r"(?:^|[\s_-])([LR])$", re.IGNORECASE)
ISOLATOR_NUMBER_RE = re.compile(r"\b(?:iso|isolator)\s*(\d+)\b", re.IGNORECASE)


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: str
    validation: Optional[OperatorValidation] = None


def _as_date(d: Optional[date_type]) -> date_type:
    return d or timezone.localdate()


def isolator_declared_side(isolator) -> Optional[str]:
    """
    Some live isolator rows are already side-specific, e.g. "Isolator 1 R".
    For those rows the APS target is the matching side only, not both L and R.
    Generic rows such as "Isolator 1" still expose both sections.
    """
    match = ISOLATOR_SIDE_SUFFIX_RE.search(isolator.name.strip())
    if not match:
        return None
    return match.group(1).upper()


def isolator_base_label(isolator) -> str:
    """
    Returns the logical isolator label for APS display, without a trailing side.
    """
    name = ISOLATOR_SIDE_SUFFIX_RE.sub("", isolator.name.strip()).strip(" -_")
    number_match = ISOLATOR_NUMBER_RE.search(name)
    if number_match:
        return f"Iso {number_match.group(1)}"
    return name or isolator.name


def _isolator_sort_number(isolator) -> int:
    match = ISOLATOR_NUMBER_RE.search(isolator.name)
    if not match:
        return 9999
    return int(match.group(1))


def is_aps_target_section(section: IsolatorSection) -> bool:
    """
    True when a section should appear as an APS validation target.

    This prevents side-named isolator rows from doubling the matrix:
    "Isolator 1 L" contributes L only and "Isolator 1 R" contributes R only.
    """
    declared_side = isolator_declared_side(section.isolator)
    return declared_side is None or section.section == declared_side


def aps_section_sort_key(section: IsolatorSection) -> tuple:
    side_order = {
        IsolatorSection.SectionType.LEFT: 0,
        IsolatorSection.SectionType.RIGHT: 1,
    }
    return (
        _isolator_sort_number(section.isolator),
        side_order.get(section.section, 99),
        section.isolator.clean_room.number,
        section.isolator.order,
        section.id,
    )


def aps_target_sections_from(sections) -> list[IsolatorSection]:
    return sorted(
        [section for section in sections if section.is_active and is_aps_target_section(section)],
        key=aps_section_sort_key,
    )


def aps_target_sections_for_isolator(isolator) -> list[IsolatorSection]:
    return aps_target_sections_from(isolator.sections.all())


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

def upsert_operator_validation(
    *,
    operator,
    isolator_section,
    status,
    valid_from=None,
    expires_on=None,
    assessed_by="",
    evidence_ref="",
    notes="",
):
    """
    Create or update the OperatorValidation for (operator, isolator_section).
    """
    if valid_from is None:
        valid_from = timezone.localdate()

    obj, _created = OperatorValidation.objects.update_or_create(
        operator=operator,
        isolator_section=isolator_section,
        defaults={
            "status": status,
            "valid_from": valid_from,
            "expires_on": expires_on,
            "assessed_by": assessed_by,
            "evidence_ref": evidence_ref,
            "notes": notes,
        },
    )
    return obj
