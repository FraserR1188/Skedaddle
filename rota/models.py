from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class CleanRoom(models.Model):
    name = models.CharField(max_length=50, unique=True)
    description = models.TextField(blank=True)

    def __str__(self):
        return self.name


class Isolator(models.Model):
    clean_room = models.ForeignKey(CleanRoom, on_delete=models.CASCADE, related_name="isolators")
    name = models.CharField(max_length=50)  # e.g. "Twin 1 Left", "Twin 1 Right"
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("clean_room", "name")

    def __str__(self):
        return f"{self.clean_room.name} - {self.name}"


class StaffMember(models.Model):
    # You can later link this to a real User via OneToOne if needed
    full_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    mobile_number = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=50, blank=True)  # e.g. Tech, Pharmacist, Checker
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.full_name


class ShiftTemplate(models.Model):
    """Defines a type of shift – useful if you always have similar patterns."""
    name = models.CharField(max_length=50)  # e.g. "Early", "Late", "Full Day"
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.name} ({self.start_time}–{self.end_time})"


class RotaDay(models.Model):
    date = models.DateField(unique=True)

    def __str__(self):
        return self.date.isoformat()


class Assignment(models.Model):
    """Who is on which isolator/room on a given day and shift."""
    rotaday = models.ForeignKey(RotaDay, on_delete=models.CASCADE, related_name="assignments")
    staff = models.ForeignKey(StaffMember, on_delete=models.CASCADE, related_name="assignments")
    isolator = models.ForeignKey(Isolator, on_delete=models.CASCADE, related_name="assignments")
    shift = models.ForeignKey(ShiftTemplate, on_delete=models.PROTECT, related_name="assignments")
    notes = models.CharField(max_length=255, blank=True)

    class Meta:
        unique_together = ("rotaday", "staff", "isolator", "shift")

    def __str__(self):
        return f"{self.rotaday} - {self.staff} @ {self.isolator} ({self.shift})"