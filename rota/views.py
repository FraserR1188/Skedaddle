import calendar
from datetime import date, timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required, user_passes_test
from django.contrib import messages
from django import forms

from .models import RotaDay, Assignment, CleanRoom, StaffMember


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
        is_manager = user.has_perm("rota.manage_rota")

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
            date__month=month
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
    target_date = date(year=int(year), month=int(month), day=int(day))
    rotaday, _ = RotaDay.objects.get_or_create(date=target_date)

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

    context = {
        "date": target_date,
        "today": date.today(),
        "rotaday": rotaday,
        "assignments": assignments,
        "rooms_grid": rooms_grid,
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
