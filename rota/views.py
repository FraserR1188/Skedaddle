import calendar
from datetime import date, timedelta
from django.shortcuts import render
from .models import RotaDay, Assignment
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
