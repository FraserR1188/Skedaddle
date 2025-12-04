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

    Business rules:
    - Production Operators can only work in the isolator making batches.
      They cannot be supervisors.
    - Production Supervisors can supervise (room) and also make batches in isolators.
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

    # Batch (1–8) for isolator assignments
    batch_number = models.PositiveSmallIntegerField(
        choices=[(i, f"Batch {i}") for i in range(1, 9)],
        null=True,
        blank=True,
    )

    # Flag to mark room supervisor assignments
    is_room_supervisor = models.BooleanField(default=False)

    class Meta:
        # Avoid duplicate staff/location/shift/batch rows
        unique_together = (
            "rotaday",
            "staff",
            "clean_room",
            "isolator",
            "shift",
            "batch_number",
        )

    def clean(self):
        """
        Enforce role + location rules.

        - If location_type == "ISOLATOR":
            * isolator must be set
            * batch_number must be 1–8 (not null)
            * staff.role can be OPERATIVE or SUPERVISOR

        - If location_type == "ROOM":
            * isolator must be null
            * staff.role must be SUPERVISOR
            * batch_number must be null
        """
        errors = {}

        # ISOLATOR rules
        if self.location_type == "ISOLATOR":
            if self.isolator is None:
                errors["isolator"] = "Isolator location must have an isolator selected."
            if self.batch_number is None:
                errors["batch_number"] = "Isolator assignments must have a batch number (1–8)."
            # Both OPERATIVE and SUPERVISOR are allowed here,
            # so no role restriction needed for isolators.

        # ROOM rules
        if self.location_type == "ROOM":
            if self.isolator is not None:
                errors["isolator"] = "Room assignments must not have an isolator set."
            if self.staff and self.staff.role != "SUPERVISOR":
                errors["staff"] = "Only Production Supervisors should be assigned to the room."
            if self.batch_number is not None:
                errors["batch_number"] = "Room assignments must not have a batch number."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        loc = self.clean_room.name
        if self.isolator:
            loc += f" - {self.isolator.name}"
        batch = f" [Batch {self.batch_number}]" if self.batch_number else ""
        return f"{self.rotaday} {self.shift} | {self.staff} @ {loc}{batch}"
