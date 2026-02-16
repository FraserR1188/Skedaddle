from django.utils import timezone

def today(request):
    # returns a real datetime.date, so .year/.month/.day work reliably
    return {"today": timezone.localdate()}
