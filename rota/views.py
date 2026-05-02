import calendar
from datetime import date, timedelta
from collections import defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import IntegrityError, models, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import urlencode

from .forms import StaffMemberForm
from .models import (
    Assignment,
    CleanRoom,
    Isolator,
    RotaDay,
    RotaDayAuditEvent,
    ShiftTemplate,
    StaffMember,
    WorkArea,
)
from .services.suite_overview import build_suite_overview


# ------------------------------------------------------------
# HELPERS
# ------------------------------------------------------------
def is_superuser(user):
    return user.is_superuser


def is_rota_manager(user):
    return user.is_superuser or user.has_perm("rota.rota_manager")


def shift_for_block(block: str) -> ShiftTemplate:
    """
    Return the best matching ShiftTemplate for AM/PM assignments.

    Keeps Assignment.shift populated while the UI works primarily from
    Assignment.shift_block.
    """
    shift_templates = list(ShiftTemplate.objects.all().order_by("start_time"))

    if not shift_templates:
        raise ValidationError("No shift templates configured.")

    block = (block or "").upper().strip()

    if block == "AM":
        for shift in shift_templates:
            shift_name = shift.name.lower()
            if "early" in shift_name or "am" in shift_name or "morning" in shift_name:
                return shift
        return shift_templates[0]

    if block == "PM":
        for shift in reversed(shift_templates):
            shift_name = shift.name.lower()
            if "late" in shift_name or "pm" in shift_name or "afternoon" in shift_name:
                return shift
        return shift_templates[-1]

    return shift_templates[0]


def assignment_location_label(assignment: Assignment) -> str:
    """
    Human-readable location label for conflict messages and emails.
    """
    if (
        assignment.location_type == Assignment.LocationType.WORK_AREA
        and assignment.work_area_id
    ):
        return assignment.work_area.name

    if assignment.isolator_id and assignment.clean_room_id:
        return f"{assignment.clean_room.name} – {assignment.isolator.name}"

    if assignment.is_room_supervisor and assignment.clean_room_id:
        return f"{assignment.clean_room.name} – Room supervisor"

    if assignment.clean_room_id:
        return assignment.clean_room.name

    return "another assignment"


def add_validation_messages(request, exc: ValidationError):
    """
    Render Django ValidationError messages safely through the messages framework.
    """
    if hasattr(exc, "message_dict"):
        for field, messages_list in exc.message_dict.items():
            for message in messages_list:
                messages.error(request, f"{field}: {message}")
        return

    if hasattr(exc, "messages"):
        for message in exc.messages:
            messages.error(request, message)
        return

    messages.error(request, str(exc))


# ------------------------------------------------------------
# HOME
# ------------------------------------------------------------
@login_required
def home(request):
    today = date.today()
    context = {
        "is_authenticated": request.user.is_authenticated,
        "is_manager": request.user.has_perm("rota.rota_manager"),
        "today": today,
    }
    return render(request, "rota/home.html", context)


# ------------------------------------------------------------
# MONTHLY CALENDAR
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def monthly_calendar(request, year, month):
    year = int(year)
    month = int(month)

    first_day = date(year, month, 1)
    cal = calendar.Calendar(firstweekday=0)
    weeks = cal.monthdatescalendar(year, month)

    prev_month_date = (first_day - timedelta(days=1)).replace(day=1)
    next_month_date = (first_day + timedelta(days=31)).replace(day=1)

    rotadays = set(
        RotaDay.objects.filter(
            date__year=year,
            date__month=month,
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


# ------------------------------------------------------------
# DAILY ROTA / ASSIGNMENT MANAGEMENT
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def daily_rota(request, year, month, day):
    target_date = date(int(year), int(month), int(day))
    rotaday, _ = RotaDay.objects.get_or_create(date=target_date)

    shift_templates = list(ShiftTemplate.objects.all().order_by("start_time"))
    if not shift_templates:
        messages.error(request, "No shift templates configured.")
        today = date.today()
        return redirect("monthly_calendar", year=today.year, month=today.month)

    # -------------------------
    # POST — save cleanroom/isolator assignments
    # -------------------------
    if request.method == "POST":
        if not is_rota_manager(request.user):
            raise PermissionDenied("You do not have permission to edit the rota.")

        isolator = get_object_or_404(Isolator, pk=request.POST.get("isolator_id"))

        chosen_ops = []
        for i in range(1, 7):
            staff_id = (request.POST.get(f"op{i}_staff") or "").strip()
            block = (request.POST.get(f"op{i}_block") or "").strip().upper()
            section_id = (request.POST.get(f"op{i}_section") or "").strip()

            if staff_id and block and not section_id:
                messages.error(
                    request,
                    (
                        f"Operator {i} requires an isolator section when "
                        "staff and shift block are selected."
                    ),
                )
                url = reverse(
                    "daily_rota",
                    kwargs={"year": year, "month": month, "day": day},
                )
                query = urlencode({"edit_isolator": isolator.id})
                return redirect(f"{url}?{query}")

            if staff_id and block and section_id:
                chosen_ops.append((int(staff_id), block, int(section_id)))

        seen = set()
        chosen_ops = [
            item
            for item in chosen_ops
            if not ((item[0], item[1]) in seen or seen.add((item[0], item[1])))
        ]

        supervisor_ids_am = [
            int(sid)
            for sid in request.POST.getlist("room_supervisors_am")
            if sid.strip()
        ][:4]

        supervisor_ids_pm = [
            int(sid)
            for sid in request.POST.getlist("room_supervisors_pm")
            if sid.strip()
        ][:4]

        selected_pairs = set()

        for staff_id, block, _section_id in chosen_ops:
            selected_pairs.add((staff_id, block))

        for supervisor_id in supervisor_ids_am:
            selected_pairs.add((supervisor_id, Assignment.ShiftBlock.AM))

        for supervisor_id in supervisor_ids_pm:
            selected_pairs.add((supervisor_id, Assignment.ShiftBlock.PM))

        allowed_qs = (
            Assignment.objects.filter(rotaday=rotaday)
            .filter(
                models.Q(
                    isolator=isolator,
                    location_type=Assignment.LocationType.ISOLATOR,
                )
                | models.Q(
                    clean_room=isolator.clean_room,
                    location_type=Assignment.LocationType.ROOM,
                    is_room_supervisor=True,
                )
            )
            .values_list("id", flat=True)
        )

        conflicts = Assignment.objects.none()

        if selected_pairs:
            conflict_q = models.Q()

            for staff_id, block in selected_pairs:
                conflict_q |= models.Q(staff_id=staff_id, shift_block=block)

            conflicts = (
                Assignment.objects.filter(rotaday=rotaday)
                .filter(conflict_q)
                .exclude(id__in=allowed_qs)
                .select_related("staff", "clean_room", "isolator", "work_area")
            )

        if conflicts.exists():
            for assignment in conflicts:
                messages.error(
                    request,
                    (
                        f"{assignment.staff.full_name} is already assigned to "
                        f"{assignment_location_label(assignment)} "
                        f"({assignment.shift_block})."
                    ),
                )

            url = reverse(
                "daily_rota",
                kwargs={"year": year, "month": month, "day": day},
            )
            query = urlencode({"edit_isolator": isolator.id})
            return redirect(f"{url}?{query}")

        try:
            with transaction.atomic():
                Assignment.objects.filter(
                    rotaday=rotaday,
                    isolator=isolator,
                    location_type=Assignment.LocationType.ISOLATOR,
                ).delete()

                for staff_id, block, section_id in chosen_ops:
                    assignment = Assignment(
                        rotaday=rotaday,
                        staff_id=staff_id,
                        clean_room=isolator.clean_room,
                        isolator=isolator,
                        isolator_section_id=section_id,
                        shift=shift_for_block(block),
                        location_type=Assignment.LocationType.ISOLATOR,
                        shift_block=block,
                    )
                    assignment.full_clean()
                    assignment.save()

                Assignment.objects.filter(
                    rotaday=rotaday,
                    clean_room=isolator.clean_room,
                    isolator__isnull=True,
                    location_type=Assignment.LocationType.ROOM,
                    is_room_supervisor=True,
                ).delete()

                for supervisor_id in supervisor_ids_am:
                    assignment = Assignment(
                        rotaday=rotaday,
                        staff_id=supervisor_id,
                        clean_room=isolator.clean_room,
                        shift=shift_for_block("AM"),
                        location_type=Assignment.LocationType.ROOM,
                        is_room_supervisor=True,
                        shift_block=Assignment.ShiftBlock.AM,
                    )
                    assignment.full_clean()
                    assignment.save()

                for supervisor_id in supervisor_ids_pm:
                    assignment = Assignment(
                        rotaday=rotaday,
                        staff_id=supervisor_id,
                        clean_room=isolator.clean_room,
                        shift=shift_for_block("PM"),
                        location_type=Assignment.LocationType.ROOM,
                        is_room_supervisor=True,
                        shift_block=Assignment.ShiftBlock.PM,
                    )
                    assignment.full_clean()
                    assignment.save()

        except IntegrityError:
            messages.error(
                request,
                (
                    "Conflict detected while saving: one or more people are already "
                    "assigned in that AM/PM block."
                ),
            )
            url = reverse(
                "daily_rota",
                kwargs={"year": year, "month": month, "day": day},
            )
            query = urlencode({"edit_isolator": isolator.id})
            return redirect(f"{url}?{query}")

        except ValidationError as exc:
            add_validation_messages(request, exc)
            url = reverse(
                "daily_rota",
                kwargs={"year": year, "month": month, "day": day},
            )
            query = urlencode({"edit_isolator": isolator.id})
            return redirect(f"{url}?{query}")

        messages.success(request, f"Assignments updated for {isolator.name}.")
        return redirect("daily_rota", year=year, month=month, day=day)

    # -------------------------
    # GET — display assignment management page
    # -------------------------
    assignments_qs = Assignment.objects.filter(rotaday=rotaday).select_related(
        "staff",
        "staff__crew",
        "clean_room",
        "isolator",
        "isolator_section",
        "work_area",
        "shift",
    )

    isolator_assignments = {}
    room_supervisors_by_room = {}

    for assignment in assignments_qs:
        if assignment.isolator_id:
            isolator_assignments.setdefault(assignment.isolator_id, []).append(
                assignment
            )

        if assignment.is_room_supervisor and assignment.clean_room_id:
            room_supervisors_by_room.setdefault(
                assignment.clean_room_id,
                {"AM": [], "PM": []},
            )
            room_supervisors_by_room[assignment.clean_room_id].setdefault(
                assignment.shift_block,
                [],
            )
            room_supervisors_by_room[assignment.clean_room_id][
                assignment.shift_block
            ].append(assignment.staff)

    cleanrooms = CleanRoom.objects.prefetch_related("isolators__sections").order_by(
        "number",
        "name",
    )
    rooms_grid = []

    for room in cleanrooms:
        isolators = list(room.isolators.all().order_by("order", "name"))

        # Keep your existing split logic for now.
        right_wall = isolators[:2]
        left_wall = isolators[2:4]

        for isolator in left_wall + right_wall:
            isolator.active_sections = [
                section for section in isolator.sections.all() if section.is_active
            ]
            ops = sorted(
                isolator_assignments.get(isolator.id, []),
                key=lambda item: (
                    item.staff.first_name.lower(),
                    item.staff.last_name.lower(),
                ),
            )

            isolator.operator_assignments_am = [
                assignment
                for assignment in ops
                if assignment.shift_block == Assignment.ShiftBlock.AM
            ]
            isolator.operator_assignments_pm = [
                assignment
                for assignment in ops
                if assignment.shift_block == Assignment.ShiftBlock.PM
            ]

            isolator.operator_assignments = ops
            isolator.operator_slots = ops + [None] * max(0, 6 - len(ops))
            isolator.has_assignments = bool(ops)

        supervisor_bucket = room_supervisors_by_room.get(
            room.id,
            {"AM": [], "PM": []},
        )

        room.room_supervisors_am = supervisor_bucket.get("AM", [])
        room.room_supervisors_pm = supervisor_bucket.get("PM", [])

        room.room_supervisor_ids_am = [
            staff.id for staff in room.room_supervisors_am
        ]
        room.room_supervisor_ids_pm = [
            staff.id for staff in room.room_supervisors_pm
        ]

        room.room_supervisors = (
            room.room_supervisors_am + room.room_supervisors_pm
        )
        room.room_supervisor_ids = (
            room.room_supervisor_ids_am + room.room_supervisor_ids_pm
        )

        rooms_grid.append(
            {
                "room": room,
                "right_wall": right_wall,
                "left_wall": left_wall,
                "room_supervisors": room.room_supervisors,
            }
        )

    staff_list = (
        StaffMember.objects.filter(is_active=True)
        .select_related("crew")
        .order_by("crew__sort_order", "crew__name", "first_name", "last_name")
    )

    operators = staff_list.filter(role="OPERATIVE")
    supervisors = staff_list.filter(role="SUPERVISOR")

    context = {
        "date": target_date,
        "today": date.today(),
        "rotaday": rotaday,
        "rooms_grid": rooms_grid,
        "staff_list": staff_list,
        "operators": operators,
        "supervisors": supervisors,
        "shift_templates": shift_templates,
        "assignments": assignments_qs,
        "overview": build_suite_overview(rotaday),
    }

    return render(request, "rota/daily_rota.html", context)


# ------------------------------------------------------------
# SUITE OVERVIEW
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def suite_overview(request, year, month, day):
    target_date = date(int(year), int(month), int(day))
    rotaday, _ = RotaDay.objects.get_or_create(date=target_date)

    overview = build_suite_overview(rotaday)

    context = {
        "date": target_date,
        "today": date.today(),
        "rotaday": rotaday,
        "overview": overview,
    }

    return render(request, "rota/suite_overview.html", context)


# ------------------------------------------------------------
# WORK AREA ASSIGNMENT MANAGEMENT
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def work_area_assignment(request, year, month, day, area_id):
    target_date = date(int(year), int(month), int(day))
    rotaday, _ = RotaDay.objects.get_or_create(date=target_date)

    work_area = get_object_or_404(WorkArea, pk=area_id, is_active=True)

    existing_assignments = (
        Assignment.objects.filter(
            rotaday=rotaday,
            location_type=Assignment.LocationType.WORK_AREA,
            work_area=work_area,
        )
        .select_related("staff", "staff__crew", "work_area", "shift")
        .order_by(
            "shift_block",
            "staff__crew__sort_order",
            "staff__crew__name",
            "staff__first_name",
            "staff__last_name",
        )
    )

    existing_am = [
        assignment
        for assignment in existing_assignments
        if assignment.shift_block == Assignment.ShiftBlock.AM
    ]
    existing_pm = [
        assignment
        for assignment in existing_assignments
        if assignment.shift_block == Assignment.ShiftBlock.PM
    ]

    selected_am_ids = [assignment.staff_id for assignment in existing_am]
    selected_pm_ids = [assignment.staff_id for assignment in existing_pm]

    staff_list = (
        StaffMember.objects.filter(is_active=True)
        .select_related("crew")
        .order_by("crew__sort_order", "crew__name", "first_name", "last_name")
    )

    if request.method == "POST":
        if not is_rota_manager(request.user):
            raise PermissionDenied("You do not have permission to edit the rota.")

        selected_am_ids = [
            int(staff_id)
            for staff_id in request.POST.getlist("staff_am")
            if str(staff_id).strip()
        ]

        selected_pm_ids = [
            int(staff_id)
            for staff_id in request.POST.getlist("staff_pm")
            if str(staff_id).strip()
        ]

        selected_am_ids = list(dict.fromkeys(selected_am_ids))
        selected_pm_ids = list(dict.fromkeys(selected_pm_ids))

        selected_pairs = set()

        for staff_id in selected_am_ids:
            selected_pairs.add((staff_id, Assignment.ShiftBlock.AM))

        for staff_id in selected_pm_ids:
            selected_pairs.add((staff_id, Assignment.ShiftBlock.PM))

        allowed_assignment_ids = list(existing_assignments.values_list("id", flat=True))

        conflicts = Assignment.objects.none()

        if selected_pairs:
            conflict_q = models.Q()

            for staff_id, block in selected_pairs:
                conflict_q |= models.Q(staff_id=staff_id, shift_block=block)

            conflicts = (
                Assignment.objects.filter(rotaday=rotaday)
                .filter(conflict_q)
                .exclude(id__in=allowed_assignment_ids)
                .select_related("staff", "clean_room", "isolator", "work_area")
            )

        if conflicts.exists():
            for assignment in conflicts:
                messages.error(
                    request,
                    (
                        f"{assignment.staff.full_name} is already assigned to "
                        f"{assignment_location_label(assignment)} "
                        f"({assignment.shift_block})."
                    ),
                )

            return redirect(
                "work_area_assignment",
                year=year,
                month=month,
                day=day,
                area_id=area_id,
            )

        before_json = {
            "work_area": work_area.name,
            "AM": [assignment.staff.full_name for assignment in existing_am],
            "PM": [assignment.staff.full_name for assignment in existing_pm],
        }

        try:
            with transaction.atomic():
                Assignment.objects.filter(
                    rotaday=rotaday,
                    location_type=Assignment.LocationType.WORK_AREA,
                    work_area=work_area,
                ).delete()

                for staff_id in selected_am_ids:
                    assignment = Assignment(
                        rotaday=rotaday,
                        staff_id=staff_id,
                        work_area=work_area,
                        shift=shift_for_block("AM"),
                        shift_block=Assignment.ShiftBlock.AM,
                        location_type=Assignment.LocationType.WORK_AREA,
                    )
                    assignment.full_clean()
                    assignment.save()

                for staff_id in selected_pm_ids:
                    assignment = Assignment(
                        rotaday=rotaday,
                        staff_id=staff_id,
                        work_area=work_area,
                        shift=shift_for_block("PM"),
                        shift_block=Assignment.ShiftBlock.PM,
                        location_type=Assignment.LocationType.WORK_AREA,
                    )
                    assignment.full_clean()
                    assignment.save()

                after_staff_am = (
                    StaffMember.objects.filter(id__in=selected_am_ids)
                    .order_by("crew__sort_order", "crew__name", "first_name", "last_name")
                    .values_list("first_name", "last_name")
                )

                after_staff_pm = (
                    StaffMember.objects.filter(id__in=selected_pm_ids)
                    .order_by("crew__sort_order", "crew__name", "first_name", "last_name")
                    .values_list("first_name", "last_name")
                )

                after_json = {
                    "work_area": work_area.name,
                    "AM": [
                        f"{first_name} {last_name}".strip()
                        for first_name, last_name in after_staff_am
                    ],
                    "PM": [
                        f"{first_name} {last_name}".strip()
                        for first_name, last_name in after_staff_pm
                    ],
                }

                RotaDayAuditEvent.objects.create(
                    rotaday=rotaday,
                    event_type=RotaDayAuditEvent.ASSIGNMENT_UPDATED,
                    actor=request.user,
                    summary=f"Updated work-area assignments for {work_area.name}.",
                    before_json=before_json,
                    after_json=after_json,
                )

        except IntegrityError:
            messages.error(
                request,
                (
                    "Conflict detected while saving: one or more people are already "
                    "assigned in that AM/PM block."
                ),
            )
            return redirect(
                "work_area_assignment",
                year=year,
                month=month,
                day=day,
                area_id=area_id,
            )

        except ValidationError as exc:
            add_validation_messages(request, exc)
            return redirect(
                "work_area_assignment",
                year=year,
                month=month,
                day=day,
                area_id=area_id,
            )

        messages.success(request, f"Assignments updated for {work_area.name}.")

        return redirect(
            "suite_overview",
            year=year,
            month=month,
            day=day,
        )

    context = {
        "date": target_date,
        "today": date.today(),
        "rotaday": rotaday,
        "work_area": work_area,
        "staff_list": staff_list,
        "existing_am": existing_am,
        "existing_pm": existing_pm,
        "selected_am_ids": selected_am_ids,
        "selected_pm_ids": selected_pm_ids,
    }

    return render(request, "rota/work_area_assignment.html", context)


# ------------------------------------------------------------
# STAFF MANAGEMENT
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def current_month_redirect(request):
    today = date.today()
    return redirect("monthly_calendar", year=today.year, month=today.month)


@login_required
@user_passes_test(is_superuser)
def staff_create(request):
    form = StaffMemberForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        staff = form.save()
        messages.success(request, f"Staff member '{staff.full_name}' created.")
        return redirect("staff_list")

    return render(
        request,
        "rota/staff_create.html",
        {"form": form, "today": date.today()},
    )


@login_required
@user_passes_test(is_superuser)
def staff_list(request):
    staff_qs = (
        StaffMember.objects.select_related("crew")
        .order_by("crew__sort_order", "crew__name", "first_name", "last_name")
    )

    crews_map = defaultdict(list)

    for staff in staff_qs:
        crew_name = staff.crew.name if staff.crew else "No Crew"
        crews_map[crew_name].append(staff)

    crew_cards = [
        {"crew": crew_name, "staff": crews_map[crew_name]}
        for crew_name in crews_map.keys()
    ]

    return render(
        request,
        "rota/staff_list.html",
        {"crew_cards": crew_cards, "today": date.today()},
    )


@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def staff_search(request):
    query = request.GET.get("q", "").strip()
    results = []

    if query:
        staff_qs = StaffMember.objects.filter(
            Q(first_name__icontains=query) | Q(last_name__icontains=query),
            is_active=True,
        ).order_by("first_name", "last_name")

        today = date.today()

        for staff in staff_qs:
            assignments = (
                staff.assignments.select_related(
                    "rotaday",
                    "clean_room",
                    "isolator",
                    "work_area",
                    "shift",
                )
                .filter(rotaday__date__gte=today)
                .order_by(
                    "rotaday__date",
                    "shift_block",
                    "clean_room__number",
                    "isolator__order",
                    "work_area__sort_order",
                    "shift__start_time",
                )
            )

            results.append({"staff": staff, "assignments": assignments})

    return render(
        request,
        "rota/staff_search.html",
        {"query": query, "results": results, "today": date.today()},
    )


# ------------------------------------------------------------
# PUBLISHING
# ------------------------------------------------------------
@login_required
def publish_rota_day(request, rotaday_id):
    if request.method != "POST":
        raise PermissionDenied("Publish endpoint only accepts POST.")

    if not is_rota_manager(request.user):
        raise PermissionDenied("You do not have permission to publish rotas.")

    rotaday = get_object_or_404(RotaDay, pk=rotaday_id)
    reason = (request.POST.get("reason") or "").strip()

    with transaction.atomic():
        already_published = rotaday.status == RotaDay.PUBLISHED

        rotaday.mark_published(request.user)
        rotaday.save()

        RotaDayAuditEvent.objects.create(
            rotaday=rotaday,
            event_type=(
                RotaDayAuditEvent.REPUBLISHED
                if already_published
                else RotaDayAuditEvent.PUBLISHED
            ),
            actor=request.user,
            summary=(
                ("Republished rota" + (f": {reason}" if reason else ""))
                if already_published
                else "Published rota"
            ),
            after_json={
                "publish_version": rotaday.publish_version,
                "published_at": (
                    rotaday.published_at.isoformat()
                    if rotaday.published_at
                    else None
                ),
            },
        )

    _send_rota_publish_email(rotaday, reason=reason, is_update=already_published)

    if already_published:
        messages.success(
            request,
            f"Rota republished (v{rotaday.publish_version}) and email sent.",
        )
    else:
        messages.success(request, "Rota published and email sent.")

    return redirect(
        "daily_rota",
        year=rotaday.date.year,
        month=rotaday.date.month,
        day=rotaday.date.day,
    )


def _send_rota_publish_email(rotaday: RotaDay, reason: str, is_update: bool):
    assignments = (
        Assignment.objects.filter(rotaday=rotaday)
        .select_related("staff", "clean_room", "isolator", "work_area", "shift")
        .order_by(
            "shift_block",
            "clean_room__number",
            "isolator__order",
            "work_area__sort_order",
            "shift__start_time",
            "staff__first_name",
            "staff__last_name",
        )
    )

    recipients = sorted(
        {
            assignment.staff.email
            for assignment in assignments
            if getattr(assignment.staff, "email", "").strip()
        }
    )

    if not recipients:
        return

    subject = (
        f"UPDATED rota published – {rotaday.date.isoformat()}"
        if is_update
        else f"Daily rota published – {rotaday.date.isoformat()}"
    )

    body = render_to_string(
        "rota/emails/rota_published.txt",
        {
            "rotaday": rotaday,
            "assignments": assignments,
            "is_update": is_update,
            "reason": reason,
        },
    )

    send_mail(
        subject=subject,
        message=body,
        from_email=None,
        recipient_list=recipients,
        fail_silently=False,
    )
