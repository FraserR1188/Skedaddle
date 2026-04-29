from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
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
        ordering = ["crew__sort_order", "crew__name", "first_name", "last_name"]


class ShiftTemplate(models.Model):
    name = models.CharField(max_length=50)
    start_time = models.TimeField()
    end_time = models.TimeField()

    def __str__(self):
        return f"{self.name} {self.start_time}-{self.end_time}"


class WorkArea(models.Model):
    """
    Represents non-isolator operational areas in the aseptic suite.

    Examples:
    - Clean MAL
    - Dirty MAL
    - Support Room 1-4
    - Visual Inspection 1-4
    - Overlabelling

    These areas can have AM/PM staffing requirements without needing to be
    modelled as cleanrooms or isolators.
    """

    class AreaType(models.TextChoices):
        MAL = "MAL", "MAL"
        SUPPORT_ROOM = "SUPPORT_ROOM", "Support Room"
        VISUAL_INSPECTION = "VISUAL_INSPECTION", "Visual Inspection"
        OVERLABELLING = "OVERLABELLING", "Overlabelling"
        OTHER = "OTHER", "Other"

    name = models.CharField(max_length=80, unique=True)

    area_type = models.CharField(
        max_length=30,
        choices=AreaType.choices,
        default=AreaType.OTHER,
    )

    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    required_staff_am = models.PositiveSmallIntegerField(default=0)
    required_staff_pm = models.PositiveSmallIntegerField(default=0)

    requires_supervisor = models.BooleanField(default=False)
    requires_validation = models.BooleanField(default=False)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name


class RotaDay(models.Model):
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
    One person assigned to one location for a given rota day and AM/PM block.

    Supported assignment types:
    - ROOM: cleanroom supervisor assignment
    - ISOLATOR: isolator / isolator-section assignment
    - WORK_AREA: non-isolator operational area assignment

    Core rule:
    - A staff member can only have one assignment per rota day per AM/PM block.
    """

    class ShiftBlock(models.TextChoices):
        AM = "AM", "AM"
        PM = "PM", "PM"

    class LocationType(models.TextChoices):
        ROOM = "ROOM", "Room (Supervisor)"
        ISOLATOR = "ISOLATOR", "Isolator (Operative/Supervisor)"
        WORK_AREA = "WORK_AREA", "Work Area"

    shift_block = models.CharField(
        max_length=8,
        choices=ShiftBlock.choices,
        default=ShiftBlock.AM,
        db_index=True,
    )

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
        null=True,
        blank=True,
        related_name="assignments",
        help_text="Required for room and isolator assignments. Not required for work-area assignments.",
    )

    isolator = models.ForeignKey(
        Isolator,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="assignments",
    )

    isolator_section = models.ForeignKey(
        "validation.IsolatorSection",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assignments",
        help_text="Required for isolator assignments, e.g. Isolator 1 Left/Right.",
    )

    work_area = models.ForeignKey(
        WorkArea,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assignments",
        help_text="Required for work-area assignments, e.g. Clean MAL or Visual Inspection 1.",
    )

    shift = models.ForeignKey(
        ShiftTemplate,
        on_delete=models.PROTECT,
        related_name="assignments",
        null=True,
        blank=True,
    )

    location_type = models.CharField(
        max_length=12,
        choices=LocationType.choices,
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

        if not self.shift_block:
            errors["shift_block"] = "Shift block is required (AM/PM)."

        if self.location_type == self.LocationType.ROOM:
            self._clean_room_assignment(errors)

        elif self.location_type == self.LocationType.ISOLATOR:
            self._clean_isolator_assignment(errors)

        elif self.location_type == self.LocationType.WORK_AREA:
            self._clean_work_area_assignment(errors)

        else:
            errors["location_type"] = "Invalid location type."

        if errors:
            raise ValidationError(errors)

    def _clean_room_assignment(self, errors):
        """
        Validate cleanroom supervisor assignment.
        """
        self.is_room_supervisor = True

        if self.clean_room_id is None:
            errors["clean_room"] = "Room assignments must select a clean room."

        if self.isolator_id is not None:
            errors["isolator"] = "Room assignments must not have an isolator."

        if self.isolator_section_id is not None:
            errors["isolator_section"] = "Room assignments must not have an isolator section."

        if self.work_area_id is not None:
            errors["work_area"] = "Room assignments must not have a work area."

        if self.staff_id and self.staff.role != "SUPERVISOR":
            errors["staff"] = "Only supervisors can be assigned to the clean room."

    def _clean_isolator_assignment(self, errors):
        """
        Validate isolator assignment.

        Isolator assignments require:
        - clean_room
        - isolator
        - isolator_section
        - valid APS status for the selected isolator section
        """
        self.is_room_supervisor = False

        if self.clean_room_id is None:
            errors["clean_room"] = "Isolator assignments must select a clean room."

        if self.isolator_id is None:
            errors["isolator"] = "Isolator assignments must select an isolator."

        if self.isolator_section_id is None:
            errors["isolator_section"] = "Isolator assignments must select an isolator section."

        if self.work_area_id is not None:
            errors["work_area"] = "Isolator assignments must not have a work area."

        if self.isolator_id is not None and self.clean_room_id is not None:
            if self.isolator.clean_room_id != self.clean_room_id:
                errors["clean_room"] = "Selected isolator does not belong to the selected clean room."

        if self.isolator_section_id is not None and self.isolator_id is not None:
            if self.isolator_section.isolator_id != self.isolator_id:
                errors["isolator_section"] = "Selected isolator section does not belong to the selected isolator."

        if self.rotaday_id and self.isolator_id and self.shift_block:
            existing = (
                Assignment.objects
                .filter(
                    rotaday=self.rotaday,
                    shift_block=self.shift_block,
                    isolator=self.isolator,
                    location_type=self.LocationType.ISOLATOR,
                )
                .exclude(id=self.id)
                .count()
            )

            if existing >= 6:
                errors["isolator"] = "This isolator already has 6 assigned operators for this shift block."

        if self.staff_id and self.isolator_section_id and self.rotaday_id:
            from validation.services import is_operator_valid_for_section

            ok, reason = is_operator_valid_for_section(
                operator=self.staff,
                isolator_section=self.isolator_section,
                on_date=self.rotaday.date,
            )

            if not ok:
                errors["staff"] = (
                    f"{self.staff.full_name} is not APS validated for "
                    f"{self.isolator_section}: {reason}"
                )

    def _clean_work_area_assignment(self, errors):
        """
        Validate non-isolator work-area assignment.

        Current work areas include:
        - Clean MAL
        - Dirty MAL
        - Support Rooms
        - Visual Inspection
        - Overlabelling
        """
        self.is_room_supervisor = False

        if self.work_area_id is None:
            errors["work_area"] = "Work-area assignments must select a work area."

        if self.clean_room_id is not None:
            errors["clean_room"] = "Work-area assignments must not have a clean room."

        if self.isolator_id is not None:
            errors["isolator"] = "Work-area assignments must not have an isolator."

        if self.isolator_section_id is not None:
            errors["isolator_section"] = "Work-area assignments must not have an isolator section."

        if self.work_area_id is not None:
            if self.work_area.requires_supervisor and self.staff_id:
                if self.staff.role != "SUPERVISOR":
                    errors["staff"] = f"{self.work_area.name} requires a supervisor."

            if self.work_area.requires_validation:
                errors["work_area"] = (
                    f"{self.work_area.name} is configured as requiring validation, "
                    "but work-area validation rules have not been implemented yet."
                )

    def __str__(self):
        if self.location_type == self.LocationType.WORK_AREA and self.work_area_id:
            loc = self.work_area.name
        elif self.clean_room_id:
            loc = self.clean_room.name

            if self.isolator_id:
                loc += f" - {self.isolator.name}"

            if self.isolator_section_id:
                loc += f" ({self.isolator_section})"
        else:
            loc = "Unassigned location"

        shift = self.shift.name if self.shift else self.shift_block

        return f"{self.rotaday} {shift} | {self.staff} @ {loc}"