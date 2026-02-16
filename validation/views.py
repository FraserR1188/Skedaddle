from django.contrib.auth.decorators import login_required, permission_required
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import OperatorValidationForm
from .models import OperatorValidation


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
