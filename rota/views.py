import calendar
from datetime import date, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django import forms

from .models import (
    RotaDay,
    Assignment,
    CleanRoom,
    StaffMember,
    Isolator,
    ShiftTemplate,
)


# ------------------------------------------------------------
# HOME
# ------------------------------------------------------------
@login_required
def home(request):
    user = request.user
    is_authenticated = user.is_authenticated

    is_manager = False
    if is_authenticated:
        is_manager = user.has_perm("rota.rota_manager")

    today = date.today()
    context = {
        "is_authenticated": is_authenticated,
        "is_manager": is_manager,
        "today": today,
    }
    return render(request, "rota/home.html", context)


# ------------------------------------------------------------
# MONTHLY CALENDAR
# ------------------------------------------------------------
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


# ------------------------------------------------------------
# DAILY ROTA (GET + POST)
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def daily_rota(request, year, month, day):
    target_date = date(year=int(year), month=int(month), day=int(day))
    rotaday, _ = RotaDay.objects.get_or_create(date=target_date)

    day_shift = ShiftTemplate.objects.first()
    if day_shift is None:
        messages.error(request, "No shift templates have been configured.")
        return redirect("current_month_redirect")

    # --------------------------------------------------------
    # POST — update assignments
    # --------------------------------------------------------
    if request.method == "POST":

        if not request.user.has_perm("rota.rota_manager") and not request.user.is_superuser:
            raise PermissionDenied("You do not have permission to edit the rota.")

        isolator_id = request.POST.get("isolator_id")
        isolator = get_object_or_404(Isolator, pk=isolator_id)

        # ----------------------------------------------------
        # 1) BATCH ASSIGNMENTS (ISOLATOR)
        # ----------------------------------------------------
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

                try:
                    assn.full_clean()
                    assn.save()
                except ValidationError as e:
                    messages.error(request, e.messages[0])
                    return redirect(request.path)

            else:
                # No staff selected → delete any existing assignment for this batch
                qs.delete()

        # ----------------------------------------------------
        # 2) ROOM SUPERVISORS (max 4, only SUPERVISOR role)
        # ----------------------------------------------------
        supervisor_ids = request.POST.getlist("room_supervisors")
        supervisor_ids = [int(sid) for sid in supervisor_ids if sid.strip()][:4]

        # Remove supervisors no longer selected
        Assignment.objects.filter(
            rotaday=rotaday,
            shift=day_shift,
            clean_room=isolator.clean_room,
            isolator__isnull=True,
            location_type="ROOM",
            is_room_supervisor=True,
        ).exclude(staff_id__in=supervisor_ids).delete()

        # Existing supervisors for this clean room
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

        # Add any new supervisors
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
                try:
                    assn.full_clean()
                    assn.save()
                except ValidationError as e:
                    messages.error(request, e.messages[0])
                    return redirect(request.path)

        messages.success(request, f"Assignments updated for {isolator.name}.")
        return redirect("daily_rota", year=target_date.year, month=target_date.month, day=target_date.day)

    # --------------------------------------------------------
    # GET — build display data
    # --------------------------------------------------------
    assignments = Assignment.objects.filter(rotaday=rotaday).select_related(
        "staff", "staff__crew", "clean_room", "isolator", "shift"
    )

    cleanrooms = CleanRoom.objects.all().prefetch_related("isolators")

    # Maps for quick lookup
    isolator_assignments = {}
    room_supervisor_ids_by_room = {}

    for a in assignments:
        # Isolator duties
        if a.isolator_id:
            isolator_assignments.setdefault(a.isolator_id, []).append(a)

        # Room supervisors (for that clean room)
        if a.location_type == "ROOM" and a.is_room_supervisor:
            room_supervisor_ids_by_room.setdefault(a.clean_room_id, set()).add(a.staff_id)

    rooms_grid = []
    for room in cleanrooms:
        isolators = list(room.isolators.all())
        if room.number in (1, 3):
            right_wall = isolators[0:4]
            left_wall = isolators[4:8]
        else:
            right_wall = isolators
            left_wall = []

        # Attach supervisor IDs for this room
        room.room_supervisor_ids = list(room_supervisor_ids_by_room.get(room.id, set()))

        # Attach per-isolator data
        for iso in right_wall + left_wall:
            ia = isolator_assignments.get(iso.id, [])
            iso.has_assignments = bool(ia)
            iso.batch_assignments = ia
            # use the room's supervisor IDs (same for all isolators in that room)
            iso.room_supervisor_ids = room.room_supervisor_ids

        rooms_grid.append(
            {"room": room, "right_wall": right_wall, "left_wall": left_wall}
        )

    # All active staff (for batches)
    staff_list = StaffMember.objects.filter(is_active=True).order_by("full_name")

    # Only supervisors (for room supervisors selector)
    supervisors = StaffMember.objects.filter(
        is_active=True,
        role="SUPERVISOR",
    ).order_by("full_name")

    context = {
        "date": target_date,
        "today": date.today(),
        "rotaday": rotaday,
        "assignments": assignments,
        "rooms_grid": rooms_grid,
        "staff_list": staff_list,
        "supervisors": supervisors,
        "day_shift": day_shift,
    }
    return render(request, "rota/daily_rota.html", context)

# ------------------------------------------------------------
# Helpers / Staff Management
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def current_month_redirect(request):
    today = date.today()
    return redirect("monthly_calendar", year=today.year, month=today.month)


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = ["full_name", "email", "mobile_number", "role", "crew", "is_active"]


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

    return render(
        request,
        "rota/staff_create.html",
        {"form": form, "today": date.today()},
    )


@login_required
@user_passes_test(is_superuser)
def staff_list(request):
    staff = StaffMember.objects.order_by("full_name")
    return render(
        request,
        "rota/staff_list.html",
        {"staff": staff, "today": date.today()},
    )
