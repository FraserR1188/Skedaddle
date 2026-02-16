# validation/views.py
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from rota.models import StaffMember
from .forms import OperatorValidationForm
from .models import IsolatorSection, OperatorValidation


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
# Cards page
# Template: validation/validation_cards.html
#
# IMPORTANT: In your data model, the "side" is already encoded
# in the isolator naming (e.g., "Isolator 1 R" vs "Isolator 1 L"),
# so we treat EACH active IsolatorSection as ONE "side target".
# That means the UI is one Validate button per section row.
# ---------------------------------------------------------

@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_cards(request):
    q = (request.GET.get("q") or "").strip()
    active_only = request.GET.get("active") == "1"

    staff_qs = StaffMember.objects.all().select_related("crew")
    if active_only:
        staff_qs = staff_qs.filter(is_active=True)
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

    # One "side" per active section (your isolator naming already includes L/R)
    sections = list(
        IsolatorSection.objects.filter(is_active=True)
        .select_related("isolator", "isolator__clean_room")
        .order_by("isolator__clean_room__number", "isolator__order", "section", "id")
    )
    section_ids = [s.id for s in sections]

    # Map validations for fast template access:
    # vmap[operator_id][isolator_section_id] = OperatorValidation
    vmap: dict[int, dict[int, OperatorValidation]] = {pid: {} for pid in staff_ids}

    ovs = (
        OperatorValidation.objects.filter(
            operator_id__in=staff_ids,
            isolator_section_id__in=section_ids,
        )
        .select_related("isolator_section", "isolator_section__isolator")
    )
    for ov in ovs:
        vmap.setdefault(ov.operator_id, {})[ov.isolator_section_id] = ov

    # Denominator: total possible "sides" == number of active sections
    total_sides = len(sections)

    # Per-person validated count (VALID only)
    valid_counts: dict[int, int] = {}
    for person in staff:
        row = vmap.get(person.id, {})
        valid_counts[person.id] = sum(
            1
            for s in sections
            if (row.get(s.id) and row.get(s.id).status == OperatorValidation.Status.VALID)
        )

    default_expiry = timezone.localdate() + timedelta(days=183)

    context = {
        "staff": staff,
        "sections": sections,
        "vmap": vmap,
        "valid_counts": valid_counts,
        "total_sides": total_sides,
        "q": q,
        "active_only": active_only,
        "status_choices": OperatorValidation.Status.choices,
        "status_valid_value": OperatorValidation.Status.VALID,
        "default_expiry": default_expiry,
    }
    return render(request, "validation/validation_cards.html", context)


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
    expires_on_raw = (request.POST.get("expires_on") or "").strip() or None

    if not operator_id or not section_id:
        if wants_json:
            return JsonResponse(
                {"ok": False, "error": "Missing operator_id/section_id"}, status=400
            )
        messages.error(request, "Missing operator/section.")
        return redirect("validation:validation_cards")

    # Validate foreign keys exist
    get_object_or_404(StaffMember, pk=operator_id)
    get_object_or_404(IsolatorSection, pk=section_id)

    expires_on = None
    if expires_on_raw:
        try:
            expires_on = date.fromisoformat(expires_on_raw)
        except ValueError:
            expires_on = None
            if wants_json:
                return JsonResponse({"ok": False, "error": "Invalid expires_on"}, status=400)
            messages.warning(request, "Expiry date was invalid; saved without expiry.")

    if action == "remove":
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

    # validate (default)
    ov, _created = OperatorValidation.objects.get_or_create(
        operator_id=operator_id,
        isolator_section_id=section_id,
        defaults={
            "status": OperatorValidation.Status.VALID,
            "valid_from": timezone.localdate(),
        },
    )
    ov.status = OperatorValidation.Status.VALID
    ov.valid_from = timezone.localdate()
    ov.expires_on = expires_on
    ov.full_clean()
    ov.save()

    if wants_json:
        return JsonResponse(
            {
                "ok": True,
                "action": "validate",
                "status": ov.get_status_display(),
                "expires_on": ov.expires_on.isoformat() if ov.expires_on else None,
            }
        )

    messages.success(request, "Validation set to VALID.")
    return redirect(request.META.get("HTTP_REFERER") or "validation:validation_cards")


# ---------------------------------------------------------
# Matrix view (kept)
# ---------------------------------------------------------

@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_matrix(request):
    q = (request.GET.get("q") or "").strip()
    active_only = request.GET.get("active") == "1"

    staff_qs = StaffMember.objects.all().select_related("crew")
    if active_only:
        staff_qs = staff_qs.filter(is_active=True)
    if q:
        staff_qs = staff_qs.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(crew__name__icontains=q)
        )

    staff = list(
        staff_qs.order_by("crew__sort_order", "crew__name", "first_name", "last_name")
    )

    sections = list(
        IsolatorSection.objects.filter(is_active=True)
        .select_related("isolator", "isolator__clean_room")
        .order_by("isolator__clean_room__number", "isolator__order", "section")
    )

    if request.method == "POST":
        operator_id = int(request.POST["operator_id"])
        section_id = int(request.POST["section_id"])
        status = request.POST.get("status") or OperatorValidation.Status.VALID
        expires_on_raw = (request.POST.get("expires_on") or "").strip() or None

        expires_on = None
        if expires_on_raw:
            try:
                expires_on = date.fromisoformat(expires_on_raw)
            except ValueError:
                expires_on = None

        ov, _created = OperatorValidation.objects.get_or_create(
            operator_id=operator_id,
            isolator_section_id=section_id,
            defaults={"status": status, "valid_from": timezone.localdate()},
        )
        ov.status = status
        ov.expires_on = expires_on
        ov.full_clean()
        ov.save()

        return redirect(
            request.path
            + (
                "?" + request.META.get("QUERY_STRING", "")
                if request.META.get("QUERY_STRING")
                else ""
            )
        )

    vmap = {}
    ovs = OperatorValidation.objects.filter(
        operator_id__in=[p.id for p in staff],
        isolator_section_id__in=[s.id for s in sections],
    )
    for ov in ovs:
        vmap.setdefault(ov.operator_id, {})[ov.isolator_section_id] = ov

    context = {
        "staff": staff,
        "sections": sections,
        "vmap": vmap,
        "q": q,
        "active_only": active_only,
        "status_choices": OperatorValidation.Status.choices,
    }
    return render(request, "validation/validation_matrix.html", context)
