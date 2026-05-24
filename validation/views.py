# validation/views.py
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from rota.models import StaffMember
from .forms import OperatorValidationForm
from .models import IsolatorSection, OperatorValidation
from .services import aps_target_sections_from, isolator_base_label


EXPIRING_SOON_DAYS = 30
EXPIRING_URGENT_DAYS = 7

STATUS_META = {
    OperatorValidation.Status.VALID: {
        "class": "valid",
        "glyph": "V",
        "short": "Valid",
    },
    OperatorValidation.Status.IN_TRAINING: {
        "class": "in-training",
        "glyph": "T",
        "short": "Training",
    },
    OperatorValidation.Status.RESTRICTED: {
        "class": "restricted",
        "glyph": "R",
        "short": "Restricted",
    },
    OperatorValidation.Status.SUSPENDED: {
        "class": "suspended",
        "glyph": "S",
        "short": "Suspended",
    },
    "NONE": {
        "class": "none",
        "glyph": ".",
        "short": "None",
    },
}


def _staff_initials(person: StaffMember) -> str:
    initials = f"{person.first_name[:1]}{person.last_name[:1]}".upper()
    return initials or "?"


def _expiry_band(ov: OperatorValidation | None, today: date) -> str:
    if not ov or ov.status != OperatorValidation.Status.VALID or not ov.expires_on:
        return ""

    days = (ov.expires_on - today).days
    if days < 0:
        return "expired"
    if days <= EXPIRING_URGENT_DAYS:
        return "urgent"
    if days <= EXPIRING_SOON_DAYS:
        return "soon"
    return ""


def _status_detail(ov: OperatorValidation | None, today: date) -> str:
    if not ov:
        return "No APS validation record found."

    if ov.status != OperatorValidation.Status.VALID:
        return f"APS status is {ov.get_status_display()}."

    if today < ov.valid_from:
        return f"APS not effective until {ov.valid_from.isoformat()}."

    if ov.expires_on and today > ov.expires_on:
        return f"APS expired on {ov.expires_on.isoformat()}."

    return "Cleared for assignment to this section."


def _normalise_matrix_filters(request):
    q = (request.GET.get("q") or "").strip()
    active_only = request.GET.get("active") == "1"

    role_filter = (request.GET.get("role") or "ALL").strip().upper()
    if role_filter not in {"ALL", "OPERATIVE", "SUPERVISOR"}:
        role_filter = "ALL"

    sort = (request.GET.get("sort") or "name").strip().lower()
    if sort not in {"name", "crew", "coverage", "expiring"}:
        sort = "name"

    return q, active_only, role_filter, sort


def _build_validation_matrix_context(request):
    q, active_only, role_filter, sort = _normalise_matrix_filters(request)
    today = timezone.localdate()

    staff_qs = StaffMember.objects.all().select_related("crew")
    if active_only:
        staff_qs = staff_qs.filter(is_active=True)
    if role_filter != "ALL":
        staff_qs = staff_qs.filter(role=role_filter)
    if q:
        staff_qs = staff_qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(crew__name__icontains=q)
        )

    staff = list(
        staff_qs.order_by("crew__sort_order", "crew__name", "first_name", "last_name")
    )
    staff_ids = [p.id for p in staff]

    sections = aps_target_sections_from(
        IsolatorSection.objects.filter(is_active=True)
        .select_related("isolator", "isolator__clean_room")
        .order_by("isolator__clean_room__number", "isolator__order", "section", "id")
    )
    section_ids = [s.id for s in sections]

    vmap: dict[int, dict[int, OperatorValidation]] = {pid: {} for pid in staff_ids}
    ovs = (
        OperatorValidation.objects.filter(
            operator_id__in=staff_ids,
            isolator_section_id__in=section_ids,
        )
        .select_related("operator", "isolator_section", "isolator_section__isolator")
    )
    for ov in ovs:
        vmap.setdefault(ov.operator_id, {})[ov.isolator_section_id] = ov

    section_stats = {
        section.id: {"valid": 0, "training": 0, "blocked": 0, "expiring": 0}
        for section in sections
    }
    total_sections = len(sections)
    totals = {
        "cells": len(staff) * total_sections,
        "valid": 0,
        "training": 0,
        "restricted": 0,
        "suspended": 0,
        "none": 0,
        "expiring": 0,
        "expired": 0,
    }

    staff_rows = []
    for person in staff:
        validation_row = vmap.get(person.id, {})
        cells = []
        valid_count = 0
        training_count = 0
        blocked_count = 0
        expiring_count = 0
        expired_count = 0

        for section in sections:
            ov = validation_row.get(section.id)
            status_key = ov.status if ov else "NONE"
            meta = STATUS_META.get(status_key, STATUS_META["NONE"])
            expiry_band = _expiry_band(ov, today)
            can_work = bool(ov and ov.is_effective_on(today))

            if can_work:
                valid_count += 1
                totals["valid"] += 1
                section_stats[section.id]["valid"] += 1
            elif status_key == OperatorValidation.Status.VALID:
                blocked_count += 1
                section_stats[section.id]["blocked"] += 1
            elif status_key == OperatorValidation.Status.IN_TRAINING:
                training_count += 1
                totals["training"] += 1
                section_stats[section.id]["training"] += 1
            elif status_key == OperatorValidation.Status.RESTRICTED:
                blocked_count += 1
                totals["restricted"] += 1
                section_stats[section.id]["blocked"] += 1
            elif status_key == OperatorValidation.Status.SUSPENDED:
                blocked_count += 1
                totals["suspended"] += 1
                section_stats[section.id]["blocked"] += 1
            else:
                blocked_count += 1
                totals["none"] += 1
                section_stats[section.id]["blocked"] += 1

            if expiry_band in {"soon", "urgent"}:
                expiring_count += 1
                totals["expiring"] += 1
                section_stats[section.id]["expiring"] += 1
            elif expiry_band == "expired":
                expired_count += 1
                totals["expired"] += 1
                section_stats[section.id]["expiring"] += 1

            cells.append(
                {
                    "section": section,
                    "ov": ov,
                    "status_key": status_key,
                    "status_label": ov.get_status_display() if ov else "Not validated",
                    "status_class": meta["class"],
                    "status_short": meta["short"],
                    "glyph": meta["glyph"],
                    "expiry_band": expiry_band,
                    "can_work": can_work,
                    "detail": _status_detail(ov, today),
                    "section_label": f"{isolator_base_label(section.isolator)} {section.get_section_display()}",
                }
            )

        valid_percent = int(round((valid_count / total_sections) * 100)) if total_sections else 0
        training_percent = (
            int(round((training_count / total_sections) * 100)) if total_sections else 0
        )

        staff_rows.append(
            {
                "person": person,
                "initials": _staff_initials(person),
                "cells": cells,
                "valid_count": valid_count,
                "training_count": training_count,
                "blocked_count": blocked_count,
                "expiring_count": expiring_count,
                "expired_count": expired_count,
                "valid_percent": valid_percent,
                "training_percent": training_percent,
            }
        )

    if sort == "coverage":
        staff_rows.sort(key=lambda r: (-r["valid_count"], r["person"].full_name.lower()))
    elif sort == "crew":
        staff_rows.sort(
            key=lambda r: (
                r["person"].crew.sort_order if r["person"].crew else 9999,
                r["person"].crew.name if r["person"].crew else "",
                r["person"].full_name.lower(),
            )
        )
    elif sort == "expiring":
        staff_rows.sort(
            key=lambda r: (
                -(r["expired_count"] * 5 + r["expiring_count"]),
                r["person"].full_name.lower(),
            )
        )
    else:
        staff_rows.sort(key=lambda r: r["person"].full_name.lower())

    columns = [
        {
            "section": section,
            "stats": section_stats[section.id],
            "iso_label": isolator_base_label(section.isolator),
            "room_label": f"CR{section.isolator.clean_room.number}",
            "side_label": section.section,
        }
        for section in sections
    ]

    role_counts = {
        "ALL": StaffMember.objects.count(),
        "OPERATIVE": StaffMember.objects.filter(role="OPERATIVE").count(),
        "SUPERVISOR": StaffMember.objects.filter(role="SUPERVISOR").count(),
    }
    sort_choices = [
        ("name", "A-Z"),
        ("crew", "Crew"),
        ("coverage", "Coverage"),
        ("expiring", "Expiring"),
    ]
    status_options = [
        {
            "value": OperatorValidation.Status.VALID,
            "label": "Mark as Valid",
            "sub": "Allows isolator assignment while in date.",
            **STATUS_META[OperatorValidation.Status.VALID],
        },
        {
            "value": OperatorValidation.Status.IN_TRAINING,
            "label": "Start training",
            "sub": "Not assignable without a valid APS record.",
            **STATUS_META[OperatorValidation.Status.IN_TRAINING],
        },
        {
            "value": OperatorValidation.Status.RESTRICTED,
            "label": "Restrict",
            "sub": "Blocks assignment to this section.",
            **STATUS_META[OperatorValidation.Status.RESTRICTED],
        },
        {
            "value": OperatorValidation.Status.SUSPENDED,
            "label": "Suspend",
            "sub": "Blocks assignment pending review.",
            **STATUS_META[OperatorValidation.Status.SUSPENDED],
        },
        {
            "value": "NONE",
            "label": "Clear status",
            "sub": "Removes the validation record.",
            **STATUS_META["NONE"],
        },
    ]

    totals["blocked"] = max(totals["cells"] - totals["valid"], 0)
    totals["valid_percent"] = (
        int(round((totals["valid"] / totals["cells"]) * 100)) if totals["cells"] else 0
    )

    return {
        "staff": staff,
        "sections": sections,
        "columns": columns,
        "staff_rows": staff_rows,
        "vmap": vmap,
        "totals": totals,
        "total_sides": total_sections,
        "total_staff": role_counts["ALL"],
        "q": q,
        "active_only": active_only,
        "role_filter": role_filter,
        "role_counts": role_counts,
        "sort": sort,
        "sort_choices": sort_choices,
        "status_choices": OperatorValidation.Status.choices,
        "status_options": status_options,
        "status_valid_value": OperatorValidation.Status.VALID,
        "default_expiry": today + timedelta(days=183),
        "today": today,
    }


# -----------------------------
# Existing list / CRUD screens
# -----------------------------

@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_list(request):
    qs = (
        OperatorValidation.objects.select_related(
            "operator",
            "isolator_section",
            "isolator_section__isolator",
            "isolator_section__isolator__clean_room",
        )
        .order_by(
            "operator__last_name",
            "operator__first_name",
            "isolator_section__isolator__order",
            "isolator_section__section",
        )
    )

    q = request.GET.get("q", "").strip()
    status = request.GET.get("status", "").strip()

    if q:
        qs = qs.filter(
            Q(operator__first_name__icontains=q)
            | Q(operator__last_name__icontains=q)
            | Q(operator__email__icontains=q)
            | Q(isolator_section__isolator__name__icontains=q)
            | Q(isolator_section__isolator__clean_room__name__icontains=q)
        )

    if status:
        qs = qs.filter(status=status)

    context = {
        "validations": qs,
        "q": q,
        "status": status,
        "status_choices": OperatorValidation.Status.choices,
    }
    return render(request, "validation/validation_list.html", context)


@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_create(request):
    if request.method == "POST":
        form = OperatorValidationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Validation created.")
            return redirect("validation:list")
    else:
        form = OperatorValidationForm()

    return render(
        request,
        "validation/validation_form.html",
        {"form": form, "mode": "create"},
    )


@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_update(request, pk: int):
    obj = get_object_or_404(OperatorValidation, pk=pk)

    if request.method == "POST":
        form = OperatorValidationForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Validation updated.")
            return redirect("validation:list")
    else:
        form = OperatorValidationForm(instance=obj)

    return render(
        request,
        "validation/validation_form.html",
        {"form": form, "mode": "update", "obj": obj},
    )


@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_delete(request, pk: int):
    obj = get_object_or_404(OperatorValidation, pk=pk)

    if request.method == "POST":
        obj.delete()
        messages.success(request, "Validation deleted.")
        return redirect("validation:list")

    return render(request, "validation/validation_confirm_delete.html", {"obj": obj})


# ---------------------------------------------------------
# APS matrix page
#
# IMPORTANT: In this data model, the "side" is already encoded
# by IsolatorSection. The UI edits OperatorValidation records only;
# Assignment.clean() remains the backend source of truth for whether
# a person can actually work a section.
# ---------------------------------------------------------

@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_cards(request):
    return render(request, "validation/validation_matrix.html", _build_validation_matrix_context(request))


# ---------------------------------------------------------
# Modal POST handler (Validate / Remove)
# URL name MUST be: validation:validation_quick_update
# ---------------------------------------------------------

@require_POST
@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_quick_update(request):
    wants_json = (
        request.headers.get("x-requested-with") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("accept") or "")
    )

    operator_id = request.POST.get("operator_id")
    section_id = request.POST.get("section_id")
    action = (request.POST.get("action") or "validate").strip().lower()
    requested_status = (request.POST.get("status") or "").strip().upper()
    expires_on_raw = (request.POST.get("expires_on") or "").strip() or None

    if not operator_id or not section_id:
        if wants_json:
            return JsonResponse(
                {"ok": False, "error": "Missing operator_id/section_id"}, status=400
            )
        messages.error(request, "Missing operator/section.")
        return redirect("validation:validation_cards")

    # Validate foreign keys exist
    operator = get_object_or_404(StaffMember, pk=operator_id)
    section = get_object_or_404(IsolatorSection, pk=section_id)

    expires_on = None
    if expires_on_raw:
        try:
            expires_on = date.fromisoformat(expires_on_raw)
        except ValueError:
            expires_on = None
            if wants_json:
                return JsonResponse({"ok": False, "error": "Invalid expires_on"}, status=400)
            messages.warning(request, "Expiry date was invalid; saved without expiry.")

    if action in {"remove", "clear"} or requested_status == "NONE":
        deleted, _ = OperatorValidation.objects.filter(
            operator_id=operator_id,
            isolator_section_id=section_id,
        ).delete()

        if wants_json:
            return JsonResponse({"ok": True, "action": "remove", "deleted": bool(deleted)})

        if deleted:
            messages.success(request, "Validation removed.")
        else:
            messages.info(request, "No validation existed to remove.")
        return redirect(request.META.get("HTTP_REFERER") or "validation:validation_cards")

    allowed_statuses = {value for value, _label in OperatorValidation.Status.choices}
    status = requested_status or OperatorValidation.Status.VALID
    if status not in allowed_statuses:
        if wants_json:
            return JsonResponse({"ok": False, "error": "Invalid status"}, status=400)
        messages.error(request, "Invalid APS status.")
        return redirect(request.META.get("HTTP_REFERER") or "validation:validation_cards")

    if status != OperatorValidation.Status.VALID:
        expires_on = None

    ov, _created = OperatorValidation.objects.get_or_create(
        operator=operator,
        isolator_section=section,
        defaults={
            "status": status,
            "valid_from": timezone.localdate(),
        },
    )
    ov.status = status
    ov.valid_from = timezone.localdate()
    ov.expires_on = expires_on
    try:
        ov.full_clean()
    except ValidationError as exc:
        if wants_json:
            return JsonResponse({"ok": False, "error": exc.message_dict}, status=400)
        messages.error(request, "Validation could not be saved. Check the expiry date.")
        return redirect(request.META.get("HTTP_REFERER") or "validation:validation_cards")
    ov.save()

    if wants_json:
        return JsonResponse(
            {
                "ok": True,
                "action": "set_status",
                "status": ov.get_status_display(),
                "status_value": ov.status,
                "expires_on": ov.expires_on.isoformat() if ov.expires_on else None,
            }
        )

    if ov.status == OperatorValidation.Status.VALID:
        messages.success(request, "Validation set to VALID.")
    else:
        messages.success(request, f"APS status set to {ov.get_status_display()}.")
    return redirect(request.META.get("HTTP_REFERER") or "validation:validation_cards")


# ---------------------------------------------------------
# Matrix view (kept)
# ---------------------------------------------------------

@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_matrix(request):
    if request.method == "POST":
        return validation_quick_update(request)

    return render(request, "validation/validation_matrix.html", _build_validation_matrix_context(request))
