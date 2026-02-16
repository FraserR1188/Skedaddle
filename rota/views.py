import calendar
from datetime import date, timedelta
from collections import defaultdict

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.mail import send_mail
from django.db import transaction, models, IntegrityError
from django.template.loader import render_to_string
from django.utils import timezone
from django.db.models import Q
from django.urls import reverse
from django.utils.http import urlencode

from .forms import StaffMemberForm
from .models import (
    RotaDay,
    Assignment,
    CleanRoom,
    StaffMember,
    Isolator,
    ShiftTemplate,
    RotaDayAuditEvent,
)

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
# DAILY ROTA
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
    # POST — save assignments
    # -------------------------
    if request.method == "POST":
        if not request.user.has_perm("rota.rota_manager") and not request.user.is_superuser:
            raise PermissionDenied("You do not have permission to edit the rota.")

        isolator = get_object_or_404(Isolator, pk=request.POST.get("isolator_id"))

        # -------------------------
        # Collect selected operators (dedupe by staff+block)
        # -------------------------
        chosen_ops = []
        for i in range(1, 7):
            staff_id = request.POST.get(f"op{i}_staff")
            shift_id = request.POST.get(f"op{i}_shift")
            block = request.POST.get(f"op{i}_block")  # AM/PM
            if staff_id and shift_id and block:
                chosen_ops.append((int(staff_id), int(shift_id), block))

        seen = set()
        chosen_ops = [
            t for t in chosen_ops
            if not ((t[0], t[2]) in seen or seen.add((t[0], t[2])))
        ]

        # -------------------------
        # Collect selected room supervisors (max 4 per block)
        # -------------------------
        supervisor_ids_am = [
            int(sid) for sid in request.POST.getlist("room_supervisors_am") if sid.strip()
        ][:4]
        supervisor_ids_pm = [
            int(sid) for sid in request.POST.getlist("room_supervisors_pm") if sid.strip()
        ][:4]

        # -------------------------
        # Build selected (staff_id, shift_block) pairs for conflict checking
        # -------------------------
        selected_pairs = set()
        for staff_id, _, block in chosen_ops:
            selected_pairs.add((staff_id, block))
        for sid in supervisor_ids_am:
            selected_pairs.add((sid, "AM"))
        for sid in supervisor_ids_pm:
            selected_pairs.add((sid, "PM"))

        # -------------------------
        # "allowed" existing assignments = the ones already belonging to THIS edit context
        # - operators already assigned to this isolator
        # - room supervisors already assigned to this clean_room (as ROOM supervisor)
        # -------------------------
        allowed_qs = (
            Assignment.objects
            .filter(rotaday=rotaday)
            .filter(
                models.Q(isolator=isolator, location_type="ISOLATOR") |
                models.Q(clean_room=isolator.clean_room, location_type="ROOM", is_room_supervisor=True)
            )
            .values_list("id", flat=True)
        )

        # -------------------------
        # Validate conflicts per (staff_id, shift_block)
        # -------------------------
        conflicts = Assignment.objects.none()
        if selected_pairs:
            conflict_q = models.Q()
            for sid, block in selected_pairs:
                conflict_q |= models.Q(staff_id=sid, shift_block=block)

            conflicts = (
                Assignment.objects
                .filter(rotaday=rotaday)
                .filter(conflict_q)
                .exclude(id__in=allowed_qs)
                .select_related("staff", "isolator", "clean_room")
            )

        if conflicts.exists():
            conflict_lines = []
            for a in conflicts:
                if a.isolator_id:
                    where = f"{a.clean_room.name} – {a.isolator.name}"
                elif a.is_room_supervisor:
                    where = f"{a.clean_room.name} – Room supervisor"
                else:
                    where = f"{a.clean_room.name}"
                conflict_lines.append(
                    f"{a.staff.full_name} is already assigned to {where} ({a.shift_block})."
                )

            for line in conflict_lines:
                messages.error(request, line)

            url = reverse("daily_rota", kwargs={"year": year, "month": month, "day": day})
            query = urlencode({"edit_isolator": isolator.id})
            return redirect(f"{url}?{query}")

        # -------------------------
        # No conflicts -> proceed to save (transactional)
        # -------------------------
        try:
            with transaction.atomic():
                # wipe + recreate isolator assignments for this isolator
                Assignment.objects.filter(
                    rotaday=rotaday,
                    isolator=isolator,
                    location_type="ISOLATOR",
                ).delete()

                for staff_id, shift_id, block in chosen_ops:
                    assn = Assignment(
                        rotaday=rotaday,
                        staff_id=staff_id,
                        clean_room=isolator.clean_room,
                        isolator=isolator,
                        shift_id=shift_id,
                        location_type="ISOLATOR",
                        shift_block=block,
                    )
                    assn.full_clean()
                    assn.save()

                # Room supervisors: wipe + recreate for this room (AM + PM)
                Assignment.objects.filter(
                    rotaday=rotaday,
                    clean_room=isolator.clean_room,
                    isolator__isnull=True,
                    location_type="ROOM",
                    is_room_supervisor=True,
                ).delete()

                for sid in supervisor_ids_am:
                    Assignment.objects.create(
                        rotaday=rotaday,
                        staff_id=sid,
                        clean_room=isolator.clean_room,
                        shift=shift_templates[0],
                        location_type="ROOM",
                        is_room_supervisor=True,
                        shift_block="AM",
                    )

                for sid in supervisor_ids_pm:
                    Assignment.objects.create(
                        rotaday=rotaday,
                        staff_id=sid,
                        clean_room=isolator.clean_room,
                        shift=shift_templates[0],
                        location_type="ROOM",
                        is_room_supervisor=True,
                        shift_block="PM",
                    )

        except IntegrityError:
            # DB-level safety net for uniq(rotaday, staff, shift_block)
            messages.error(
                request,
                "Conflict detected while saving: one or more people are already assigned in that AM/PM block.",
            )
            url = reverse("daily_rota", kwargs={"year": year, "month": month, "day": day})
            query = urlencode({"edit_isolator": isolator.id})
            return redirect(f"{url}?{query}")

        messages.success(request, f"Assignments updated for {isolator.name}.")
        return redirect("daily_rota", year=year, month=month, day=day)

    # -------------------------
    # GET — display rota
    # -------------------------
    assignments_qs = Assignment.objects.filter(rotaday=rotaday).select_related(
        "staff", "staff__crew", "clean_room", "isolator", "shift"
    )

    isolator_assignments = {}  # iso_id -> [Assignment]
    room_supervisors_by_room = {}  # room_id -> {"AM": [Staff], "PM": [Staff]}

    for a in assignments_qs:
        if a.isolator_id:
            isolator_assignments.setdefault(a.isolator_id, []).append(a)

        if a.is_room_supervisor:
            room_supervisors_by_room.setdefault(a.clean_room_id, {"AM": [], "PM": []})
            room_supervisors_by_room[a.clean_room_id].setdefault(a.shift_block, [])
            room_supervisors_by_room[a.clean_room_id][a.shift_block].append(a.staff)

    cleanrooms = CleanRoom.objects.prefetch_related("isolators")
    rooms_grid = []

    for room in cleanrooms:
        isolators = list(room.isolators.all().order_by("order", "name"))

        # Force EXACTLY 2 per wall (max 4 rendered)
        if room.number in (1, 3):
            right_wall = isolators[:2]
            left_wall = isolators[2:4]
        else:
            right_wall = isolators[:2]
            left_wall = isolators[2:4]

        for iso in left_wall + right_wall:
            ops = sorted(
                isolator_assignments.get(iso.id, []),
                key=lambda x: (x.staff.first_name.lower(), x.staff.last_name.lower()),
            )

            # Split for display (and for your updated modal summary)
            iso.operator_assignments_am = [a for a in ops if a.shift_block == "AM"]
            iso.operator_assignments_pm = [a for a in ops if a.shift_block == "PM"]

            # Keep legacy list if any other templates still reference it
            iso.operator_assignments = ops

            # Modal still expects 6 "slots" (mixture of AM/PM rows is fine)
            iso.operator_slots = ops + [None] * (6 - len(ops))

            iso.has_assignments = bool(ops)

        sup_bucket = room_supervisors_by_room.get(room.id, {"AM": [], "PM": []})
        room.room_supervisors_am = sup_bucket.get("AM", [])
        room.room_supervisors_pm = sup_bucket.get("PM", [])

        room.room_supervisor_ids_am = [s.id for s in room.room_supervisors_am]
        room.room_supervisor_ids_pm = [s.id for s in room.room_supervisors_pm]

        # Keep legacy fields (if daily_rota.html still uses them)
        room.room_supervisors = room.room_supervisors_am + room.room_supervisors_pm
        room.room_supervisor_ids = room.room_supervisor_ids_am + room.room_supervisor_ids_pm

        rooms_grid.append({
            "room": room,
            "right_wall": right_wall,
            "left_wall": left_wall,
            "room_supervisors": room.room_supervisors,
        })

    staff_list = (
        StaffMember.objects
        .filter(is_active=True)
        .select_related("crew")
        .order_by("crew__sort_order", "first_name", "last_name")
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
    }
    return render(request, "rota/daily_rota.html", context)


# ------------------------------------------------------------
# STAFF MANAGEMENT
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def current_month_redirect(request):
    today = date.today()
    return redirect("monthly_calendar", year=today.year, month=today.month)


def is_superuser(user):
    return user.is_superuser


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
        StaffMember.objects
        .select_related("crew")
        .order_by("crew__name", "first_name", "last_name")
    )

    crews_map = defaultdict(list)

    for s in staff_qs:
        crew_name = s.crew.name if s.crew else "No Crew"
        crews_map[crew_name].append(s)

    crew_cards = [{"crew": name, "staff": crews_map[name]} for name in crews_map.keys()]

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
            assns = staff.assignments.select_related(
                "rotaday", "clean_room", "isolator", "shift"
            ).filter(
                rotaday__date__gte=today
            ).order_by(
                "rotaday__date",
                "clean_room__number",
                "isolator__order",
                "shift__start_time",
            )
            results.append({"staff": staff, "assignments": assns})

    return render(
        request,
        "rota/staff_search.html",
        {"query": query, "results": results, "today": date.today()},
    )


def is_rota_manager(user):
    return user.is_superuser or user.has_perm("rota.rota_manager")


@login_required
def publish_rota_day(request, rotaday_id):
    if request.method != "POST":
        raise PermissionDenied("Publish endpoint only accepts POST.")

    if not is_rota_manager(request.user):
        raise PermissionDenied("You do not have permission to publish rotas.")

    rotaday = get_object_or_404(RotaDay, pk=rotaday_id)
    reason = (request.POST.get("reason") or "").strip()

    with transaction.atomic():
        already_published = (rotaday.status == RotaDay.PUBLISHED)

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
                "publish_version": rotaday.publish_
