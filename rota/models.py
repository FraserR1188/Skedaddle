from django.db import models
from django.core.exceptions import ValidationError
from django.conf import settings
from django.utils import timezone


class CleanRoom(models.Model):
    number = models.PositiveSmallIntegerField(unique=True)
    name = models.CharField(max_length=50)

    def __str__(self):
        return self.name


class Isolator(models.Model):
    clean_room = models.ForeignKey(
        CleanRoom,
        on_delete=models.CASCADE,
        related_name="isolators",
    )
    name = models.CharField(max_length=50)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        unique_together = ("clean_room", "name")
        ordering = ["clean_room__number", "order"]

    def __str__(self):
        return f"{self.clean_room.name} - {self.name}"


class Crew(models.Model):
    name = models.CharField(max_length=20, unique=True)
    # Allows enforced ordering: Crew A, Crew B, Crew C etc.
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class StaffMember(models.Model):
    ROLE_CHOICES = [
        ("OPERATIVE", "Production Operative"),
        ("SUPERVISOR", "Production Supervisor"),
    ]

    first_name = models.CharField(max_length=50)
    last_name = models.CharField(max_length=50)

    email = models.EmailField(blank=True)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    crew = models.ForeignKey(
        Crew,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="staff",
    )
    is_active = models.BooleanField(default=True)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __str__(self):
        crew = f" ({self.crew})" if self.crew else ""
        return f"{self.full_name} - {self.get_role_display()}{crew}"

    class Meta:
        permissions = [
            ("rota_manager", "Can manage rota (create/update/delete)"),
            ("rota_viewer", "Can view rota"),
        ]
        # Default ordering for admin + list views etc.
        ordering = ["crew__sort_order", "crew__name", "first_name", "last_name"]


class ShiftTemplate(models.Model):
    name = models.CharField(max_length=50)
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.name} {self.start_time}-{self.end_time}"


class RotaDay(models.Model):
    """
    Represents a single calendar day for rota planning.
    """

    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"

    STATUS_CHOICES = [
        (DRAFT, "Draft"),
        (PUBLISHED, "Published"),
    ]

    date = models.DateField(unique=True)
    status = models.CharField(
        max_length=12,
        choices=STATUS_CHOICES,
        default=DRAFT,
    )
    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="published_rotadays",
    )
    publish_version = models.PositiveIntegerField(default=0)

    def mark_published(self, user):
        """
        Marks the rota as published or republished.
        """
        if self.status != self.PUBLISHED:
            self.status = self.PUBLISHED
            self.publish_version = 1
        else:
            self.publish_version += 1

        self.published_at = timezone.now()
        self.published_by = user

    def __str__(self):
        return self.date.isoformat()


class RotaDayAuditEvent(models.Model):
    """
    Immutable audit trail for a single rota day.
    """

    ASSIGNMENT_CREATED = "ASSIGNMENT_CREATED"
    ASSIGNMENT_UPDATED = "ASSIGNMENT_UPDATED"
    ASSIGNMENT_DELETED = "ASSIGNMENT_DELETED"
    PUBLISHED = "PUBLISHED"
    REPUBLISHED = "REPUBLISHED"

    EVENT_CHOICES = [
        (ASSIGNMENT_CREATED, "Assignment created"),
        (ASSIGNMENT_UPDATED, "Assignment updated"),
        (ASSIGNMENT_DELETED, "Assignment deleted"),
        (PUBLISHED, "Published"),
        (REPUBLISHED, "Republished"),
    ]

    rotaday = models.ForeignKey(
        RotaDay,
        on_delete=models.CASCADE,
        related_name="audit_events",
    )
    event_type = models.CharField(max_length=32, choices=EVENT_CHOICES)
    timestamp = models.DateTimeField(auto_now_add=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="rota_audit_events",
    )
    summary = models.CharField(max_length=255)

    before_json = models.JSONField(null=True, blank=True)
    after_json = models.JSONField(null=True, blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.rotaday} | {self.get_event_type_display()} | {self.timestamp}"


class Assignment(models.Model):
    """
    One person on one location (room or isolator) for a given day and shift.
    Supports up to 6 operators per isolator.
    """
    class ShiftBlock(models.TextChoices):
        AM = "AM", "AM"
        PM = "PM", "PM"
        # Later: CORE = "CORE", "Core"; EVE = "EVE", "Evening"

    shift_block = models.CharField(
        max_length=8,
        choices=ShiftBlock.choices,
        default=ShiftBlock.AM,
        db_index=True,
    )

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
        null=True,
        blank=True,
    )
    location_type = models.CharField(
        max_length=10,
        choices=LOCATION_TYPES,
    )
    notes = models.CharField(max_length=255, blank=True)

    is_room_supervisor = models.BooleanField(default=False)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["rotaday", "staff", "shift_block"],
                name="uniq_staff_per_rotaday_shiftblock",
            ),
        ]

def clean(self):
    errors = {}

    # -------------------------
    # Phase A rule: shift_block is required (AM/PM)
    # -------------------------
    if not getattr(self, "shift_block", None):
        errors["shift_block"] = "Shift block is required (AM/PM)."

    # -------------------------
    # Location-specific rules
    # -------------------------
    if self.location_type == "ROOM":
        if self.isolator is not None:
            errors["isolator"] = "Room assignments must not have an isolator."
        if self.staff and self.staff.role != "SUPERVISOR":
            errors["staff"] = "Only supervisors can be assigned to the clean room."
        self.is_room_supervisor = True

        # Option 1: ShiftTemplate optional metadata (no validation required)
        # If you want to enforce "no shift template for room supervisors", uncomment:
        # if self.shift_id is not None:
        #     errors["shift"] = "Room supervisors do not require a shift template; use AM/PM only."

    elif self.location_type == "ISOLATOR":
        if self.isolator is None:
            errors["isolator"] = "Isolator assignments must select an isolator."

        existing = (
            Assignment.objects
            .filter(rotaday=self.rotaday, isolator=self.isolator, location_type="ISOLATOR")
            .exclude(id=self.id)
            .count()
        )
        if existing >= 6:
            errors["isolator"] = "This isolator already has 6 assigned operators."

        self.is_room_supervisor = False

        # Option 1: ShiftTemplate optional metadata (no validation required)

    else:
        errors["location_type"] = "Invalid location type."

    if errors:
        raise ValidationError(errors)


    def __str__(self):
        loc = self.clean_room.name
        if self.isolator:
            loc += f" - {self.isolator.name}"
        return f"{self.rotaday} {self.shift} | {self.staff} @ {loc}"
