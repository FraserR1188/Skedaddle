import calendar
from datetime import date
from django.shortcuts import render
from .models import RotaDay
from django.shortcuts import get_object_or_404, redirect

def monthly_calendar(request, year, month):
    cal = calendar.Calendar(firstweekday=0)  # Monday = 0
    days_iter = cal.itermonthdates(year, month)

    # Build weeks as a list of lists, each with exactly 7 entries
    weeks = []
    week = []
    for d in days_iter:
        week.append(d)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        # pad last week if needed (normally not required, but safe)
        while len(week) < 7:
            week.append(None)
        weeks.append(week)

    rotadays = set(
        RotaDay.objects
        .filter(date__year=year, date__month=month)
        .values_list("date", flat=True)
    )

    context = {
        "year": year,
        "month": month,
        "month_name": calendar.month_name[month],
        "weeks": weeks,
        "rotadays": rotadays,
        "today": date.today(),
    }
    return render(request, "rota/monthly_calendar.html", context)


def daily_rota(request, year, month, day):
    selected_date = date(year, month, day)

    # Try to find a RotaDay; if none exists, rotaday will be None
    rotaday = RotaDay.objects.filter(date=selected_date).first()

    if rotaday:
        assignments = Assignment.objects.filter(rotaday=rotaday)
    else:
        assignments = []

    context = {
        "date": selected_date,
        "rotaday": rotaday,
        "assignments": assignments,
    }
    return render(request, "rota/daily_rota.html", context)


def current_month_redirect(request):
    today = date.today()
    return redirect("monthly_calendar", year=today.year, month=today.month)
