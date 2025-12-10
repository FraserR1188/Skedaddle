from django.db import models
from django.core.exceptions import ValidationError


class CleanRoom(models.Model):
    number = models.PositiveSmallIntegerField(unique=True)
    name = models.CharField(max_length=50)  # "Cleanroom 1" etc.

    def __str__(self):
        return self.name


class Isolator(models.Model):
    clean_room = models.ForeignKey(
        CleanRoom,
        on_delete=models.CASCADE,
        related_name="isolators",
    )
    name = models.CharField(max_length=50)  # "Isolator 1", "Isolator 2"
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ("clean_room", "name")
        ordering = ["clean_room__number", "order"]

    def __str__(self):
        return f"{self.clean_room.name} - {self.name}"


class Crew(models.Model):
    name = models.CharField(max_length=20, unique=True)  # "Crew A", "Crew B", "Crew C"

    def __str__(self):
        return self.name


class StaffMember(models.Model):
    ROLE_CHOICES = [
        ("OPERATIVE", "Production Operative"),
        ("SUPERVISOR", "Production Supervisor"),
    ]

    full_name = models.CharField(max_length=100)
    email = models.EmailField(blank=True)
    mobile_number = models.CharField(max_length=20, blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    crew = models.ForeignKey(
        Crew,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff",
    )
    is_active = models.BooleanField(default=True)

    def __str__(self):
        crew = f" ({self.crew})" if self.crew else ""
        return f"{self.full_name} - {self.get_role_display()}{crew}"

    class Meta:
        permissions = [
            ("rota_manager", "Can manage rota (create/update/delete)"),
            ("rota_viewer", "Can view rota"),
        ]


class ShiftTemplate(models.Model):
    name = models.CharField(max_length=50)  # "Early", "Core", "Late"
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.name} {self.start_time}-{self.end_time}"


class RotaDay(models.Model):
    date = models.DateField(unique=True)

    def __str__(self):
        return self.date.isoformat()


class Assignment(models.Model):
    """
    One person on one location (room or isolator) for a given day and shift.
    Now supports up to 6 operators per isolator, no batch numbers.
    """

    LOCATION_TYPES = [
        ("ROOM", "Room (Supervisor)"),
        ("ISOLATOR", "Isolator (Operative/Supervisor)"),
    ]

    rotaday = models.ForeignKey(
        RotaDay,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    staff = models.ForeignKey(
        StaffMember,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    clean_room = models.ForeignKey(
        CleanRoom,
        on_delete=models.CASCADE,
        related_name="assignments",
    )
    isolator = models.ForeignKey(
        Isolator,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assignments",
    )
    shift = models.ForeignKey(
        ShiftTemplate,
        on_delete=models.PROTECT,
        related_name="assignments",
    )
    location_type = models.CharField(
        max_length=10,
        choices=LOCATION_TYPES,
    )
    notes = models.CharField(max_length=255, blank=True)

    # Supervisors still need this flag
    is_room_supervisor = models.BooleanField(default=False)

    class Meta:
        # A staff member cannot be scheduled twice on the same day
        unique_together = ("rotaday", "staff")

    def clean(self):
        """
        Updated rules (NO batch system):
        - ROOM:
            * Must be a supervisor
            * isolator must be null
        - ISOLATOR:
            * isolator must be set
            * Can have up to 6 staff assigned
        """
        errors = {}

        # ROOM rules
        if self.location_type == "ROOM":
            if self.isolator is not None:
                errors["isolator"] = "Room assignments must not have an isolator."
            if self.staff and self.staff.role != "SUPERVISOR":
                errors["staff"] = "Only supervisors can be assigned to the clean room."
            self.is_room_supervisor = True

        # ISOLATOR rules
        if self.location_type == "ISOLATOR":
            if self.isolator is None:
                errors["isolator"] = "Isolator assignments must select an isolator."

            # enforce max 6 people per isolator per day
            existing = Assignment.objects.filter(
                rotaday=self.rotaday,
                isolator=self.isolator
            ).exclude(id=self.id).count()

            if existing >= 6:
                errors["isolator"] = "This isolator already has 6 assigned operators."

            self.is_room_supervisor = False  # isolator staff are not supervisors here

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        loc = self.clean_room.name
        if self.isolator:
            loc += f" - {self.isolator.name}"
        return f"{self.rotaday} {self.shift} | {self.staff} @ {loc}"
