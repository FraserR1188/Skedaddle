import calendar
from datetime import date as date_cls, timedelta
from django.shortcuts import render
from .models import RotaDay, Assignment, CleanRoom
from django.shortcuts import get_object_or_404, redirect

def monthly_calendar(request, year, month):
    year = int(year)
    month = int(month)

    first_day = date(year, month, 1)
    cal = calendar.Calendar(firstweekday=0)  # Monday = 0
    weeks = cal.monthdatescalendar(year, month)  # list of weeks, each 7 date objects

    # previous & next month for the arrows
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


def daily_rota(request, year, month, day):
    date = date_cls(year=year, month=month, day=day)
    rotaday, _ = RotaDay.objects.get_or_create(date=date)

    assignments = Assignment.objects.filter(rotaday=rotaday).select_related(
        "staff", "staff__crew", "clean_room", "isolator", "shift"
    )

    cleanrooms = CleanRoom.objects.all().prefetch_related("isolators")

    rooms_grid = []
    for room in cleanrooms:
        isolators = list(room.isolators.all())  # ordered by Meta.ordering

        if room.number in (1, 3):
            right_wall = isolators[0:4]
            left_wall = isolators[4:8]
        else:
            right_wall = isolators
            left_wall = []

        rooms_grid.append(
            {
                "room": room,
                "right_wall": right_wall,
                "left_wall": left_wall,
            }
        )

    context = {
        "date": date,
        "rotaday": rotaday,
        "assignments": assignments,
        "rooms_grid": rooms_grid,
    }
    return render(request, "rota/daily_rota.html", context)


def current_month_redirect(request):
    today = date.today()
    return redirect("monthly_calendar", year=today.year, month=today.month)
