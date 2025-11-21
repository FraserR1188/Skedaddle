import datetime
from django.shortcuts import render
from .models import RotaDay

def todays_rota(request):
    today = datetime.date.today()
    rotaday = RotaDay.objects.filter(date=today).first()
    assignments = rotaday.assignments.select_related(
        "staff", "isolator__clean_room", "shift"
    ) if rotaday else []

    context = {
        "date": today,
        "rotaday": rotaday,
        "assignments": assignments,
    }
    return render(request, "rota/todays_rota.html", context)