from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.contrib import messages
from django.utils import timezone
from rota.models import StaffMember
from .models import IsolatorSection, OperatorValidation
from .forms import OperatorValidationForm


@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_list(request):
    """
    List + search/filter validations.
    """
    qs = OperatorValidation.objects.select_related(
        "operator",
        "isolator_section",
        "isolator_section__isolator",
        "isolator_section__isolator__clean_room",
    ).order_by(
        "operator__last_name",
        "operator__first_name",
        "isolator_section__isolator__order",
        "isolator_section__section",
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
            return redirect("validation:list")
    else:
        form = OperatorValidationForm()

    return render(request, "validation/validation_form.html", {"form": form, "mode": "create"})


@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_update(request, pk: int):
    obj = get_object_or_404(OperatorValidation, pk=pk)

    if request.method == "POST":
        form = OperatorValidationForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
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
        return redirect("validation:list")

    return render(request, "validation/validation_confirm_delete.html", {"obj": obj})

@login_required
@permission_required("rota.rota_manager", raise_exception=True)
def validation_matrix(request):
    # --- Filters ---
    q = (request.GET.get("q") or "").strip()
    active_only = request.GET.get("active") == "1"

    staff_qs = StaffMember.objects.all().select_related("crew")
    if active_only:
        staff_qs = staff_qs.filter(is_active=True)
    if q:
        staff_qs = staff_qs.filter(
            Q(first_name__icontains=q) |
            Q(last_name__icontains=q) |
            Q(crew__name__icontains=q)
        )

    staff = list(staff_qs.order_by("crew__sort_order", "crew__name", "first_name", "last_name"))

    # --- Sections (these become your columns) ---
    sections = list(
        IsolatorSection.objects
        .filter(is_active=True)
        .select_related("isolator", "isolator__clean_room")
        .order_by("isolator__clean_room__number", "isolator__order", "section")
    )

    # --- Handle save (cell update) ---
    if request.method == "POST":
        operator_id = int(request.POST["operator_id"])
        section_id = int(request.POST["section_id"])
        status = request.POST.get("status") or OperatorValidation.Status.VALID
        expires_on = request.POST.get("expires_on") or None

        ov, _created = OperatorValidation.objects.get_or_create(
            operator_id=operator_id,
            isolator_section_id=section_id,
            defaults={"status": status, "valid_from": timezone.localdate()},
        )
        ov.status = status
        ov.expires_on = expires_on or None
        ov.full_clean()
        ov.save()

        # PRG pattern (prevents resubmits)
        return redirect(request.path + ("?" + request.META.get("QUERY_STRING", "") if request.META.get("QUERY_STRING") else ""))

    # --- Build vmap the way your template expects: vmap[operator_id][section_id] = ov ---
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