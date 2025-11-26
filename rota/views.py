import calendar
from datetime import date, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django import forms

from .models import (
    RotaDay,
    Assignment,
    CleanRoom,
    StaffMember,
    Isolator,
    ShiftTemplate,
)


@login_required
def home(request):
    """
    Simple landing page for the rota system.

    - If not logged in: show a 'Log in' button.
    - If logged in: show their role (Rota Manager / Rota Viewer)
      and link to the calendar.
    """
    user = request.user
    is_authenticated = user.is_authenticated
    is_manager = False

    if is_authenticated:
        # Use the custom permission defined on StaffMember.Meta
        is_manager = user.has_perm("rota.rota_manager")

    today = date.today()
    context = {
        "is_authenticated": is_authenticated,
        "is_manager": is_manager,
        "today": today,
    }
    return render(request, "rota/home.html", context)


@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def monthly_calendar(request, year, month):
    year = int(year)
    month = int(month)

    first_day = date(year, month, 1)
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    prev_month_date = (first_day - timedelta(days=1)).replace(day=1)
    next_month_date = (first_day + timedelta(days=31)).replace(day=1)

    rotadays = set(
        RotaDay.objects.filter(
            date__year=year,
            date__month=month,
        ).values_list("date", flat=True)
    )

    context = {
        "year": year,
        "month": month,
        "month_name": first_day.strftime("%B"),
        "weeks": weeks,
        "today": date.today(),
        "rotadays": rotadays,
        "prev_year": prev_month_date.year,
        "prev_month": prev_month_date.month,
        "next_year": next_month_date.year,
        "next_month": next_month_date.month,
    }
    return render(request, "rota/monthly_calendar.html", context)


@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def daily_rota(request, year, month, day):
    """
    View + edit the rota for a single day.

    - GET: show suite layout + assignments.
    - POST: update batches + room supervisors for a single isolator.
    """
    target_date = date(year=int(year), month=int(month), day=int(day))
    rotaday, _ = RotaDay.objects.get_or_create(date=target_date)

    # For now, use the first shift template as the default shift for editing.
    # You can change this to filter by name, e.g. ShiftTemplate.objects.get(name="Core")
    day_shift = ShiftTemplate.objects.first()
    if day_shift is None:
        # Hard fail if no shifts configured yet.
        messages.error(request, "No shift templates have been configured.")
        return redirect("current_month_redirect")

    # ----- POST: update assignments for a single isolator -----
    if request.method == "POST":
        # Only rota managers (or superusers) are allowed to change assignments
        if not request.user.has_perm("rota.rota_manager") and not request.user.is_superuser:
            raise PermissionDenied("You do not have permission to edit the rota.")

        isolator_id = request.POST.get("isolator_id")
        isolator = get_object_or_404(Isolator, pk=isolator_id)

        # 1) BATCH ASSIGNMENTS (8 batches for this isolator)
        for batch in range(1, 9):
            field_name = f"batch_{batch}"
            staff_id = request.POST.get(field_name) or None

            qs = Assignment.objects.filter(
                rotaday=rotaday,
                shift=day_shift,
                isolator=isolator,
                clean_room=isolator.clean_room,
                location_type="ISOLATOR",
                batch_number=batch,
            )

            if staff_id:
                staff = get_object_or_404(StaffMember, pk=staff_id)

                if qs.exists():
                    assn = qs.first()
                    assn.staff = staff
                    assn.clean_room = isolator.clean_room
                    assn.location_type = "ISOLATOR"
                    assn.batch_number = batch
                    assn.is_room_supervisor = False
                    assn.full_clean()
                    assn.save()
                else:
                    assn = Assignment(
                        rotaday=rotaday,
                        staff=staff,
                        clean_room=isolator.clean_room,
                        isolator=isolator,
                        shift=day_shift,
                        location_type="ISOLATOR",
                        batch_number=batch,
                        is_room_supervisor=False,
                    )
                    assn.full_clean()
                    assn.save()
            else:
                # No staff selected for this batch → remove any existing row
                qs.delete()

        # 2) ROOM SUPERVISORS (up to 4 for the isolator's clean room)
        supervisor_ids = request.POST.getlist("room_supervisors")
        # Convert to ints, ignore blanks, limit to 4
        supervisor_ids = [
            int(sid) for sid in supervisor_ids if sid.strip()
        ][:4]

        # Delete supervisors that are no longer in the list
        Assignment.objects.filter(
            rotaday=rotaday,
            shift=day_shift,
            clean_room=isolator.clean_room,
            isolator__isnull=True,
            location_type="ROOM",
            is_room_supervisor=True,
        ).exclude(staff_id__in=supervisor_ids).delete()

        # Existing supervisors (to avoid duplicates)
        existing_sup_ids = set(
            Assignment.objects.filter(
                rotaday=rotaday,
                shift=day_shift,
                clean_room=isolator.clean_room,
                isolator__isnull=True,
                location_type="ROOM",
                is_room_supervisor=True,
            ).values_list("staff_id", flat=True)
        )

        for sid in supervisor_ids:
            if sid not in existing_sup_ids:
                staff = get_object_or_404(StaffMember, pk=sid)
                assn = Assignment(
                    rotaday=rotaday,
                    staff=staff,
                    clean_room=isolator.clean_room,
                    isolator=None,
                    shift=day_shift,
                    location_type="ROOM",
                    batch_number=None,
                    is_room_supervisor=True,
                )
                assn.full_clean()
                assn.save()

        messages.success(request, f"Assignments updated for {isolator.name}.")
        return redirect("daily_rota", year=target_date.year, month=target_date.month, day=target_date.day)

    # ----- GET: build display data -----
    assignments = Assignment.objects.filter(rotaday=rotaday).select_related(
        "staff", "staff__crew", "clean_room", "isolator", "shift"
    )

    cleanrooms = CleanRoom.objects.all().prefetch_related("isolators")

    rooms_grid = []
    for room in cleanrooms:
        isolators = list(room.isolators.all())
        if room.number in (1, 3):
            right_wall = isolators[0:4]
            left_wall = isolators[4:8]
        else:
            right_wall = isolators
            left_wall = []

        rooms_grid.append(
            {"room": room, "right_wall": right_wall, "left_wall": left_wall}
        )

    # Map isolator → assignments for quick access and set flags used in the template
    isolator_assignments = {}
    for a in assignments:
        if a.isolator_id:
            isolator_assignments.setdefault(a.isolator_id, []).append(a)

    for block in rooms_grid:
        for iso in list(block["right_wall"]) + list(block["left_wall"]):
            ia = isolator_assignments.get(iso.id, [])
            iso.has_assignments = bool(ia)
            iso.batch_assignments = ia  # list of Assignment objects for this isolator

    # Active staff list for dropdowns in the modal
    staff_list = StaffMember.objects.filter(is_active=True).order_by("full_name")

    context = {
        "date": target_date,
        "today": date.today(),
        "rotaday": rotaday,
        "assignments": assignments,
        "rooms_grid": rooms_grid,
        "staff_list": staff_list,
        "day_shift": day_shift,
    }
    return render(request, "rota/daily_rota.html", context)


@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def current_month_redirect(request):
    today = date.today()
    return redirect("monthly_calendar", year=today.year, month=today.month)


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = ["full_name", "email", "mobile_number", "role", "crew", "is_active"]
        # If you later add rota_role or similar, put it here too.


# Only superuser for now – later we can change this to rota_manager permission
def is_superuser(user):
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def staff_create(request):
    if request.method == "POST":
        form = StaffMemberForm(request.POST)
        if form.is_valid():
            staff = form.save()
            messages.success(request, f"Staff member '{staff.full_name}' created.")
            return redirect("staff_list")
    else:
        form = StaffMemberForm()

    context = {
        "form": form,
        "today": date.today(),
    }
    return render(request, "rota/staff_create.html", context)


@login_required
@user_passes_test(is_superuser)
def staff_list(request):
    staff = StaffMember.objects.order_by("full_name")
    context = {
        "staff": staff,
        "today": date.today(),
    }
    return render(request, "rota/staff_list.html", context)
