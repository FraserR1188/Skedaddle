import calendar
from datetime import date, timedelta
from django.db.models import Q

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import (
    login_required,
    permission_required,
    user_passes_test,
)
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone
from django import forms

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
    user = request.user
    is_authenticated = user.is_authenticated

    is_manager = False
    if is_authenticated:
        is_manager = user.has_perm("rota.rota_manager")

    today = date.today()
    context = {
        "is_authenticated": is_authenticated,
        "is_manager": is_manager,
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


@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def daily_rota(request, year, month, day):

    target_date = date(year=int(year), month=int(month), day=int(day))
    rotaday, _ = RotaDay.objects.get_or_create(date=target_date)

    # All shift templates (Early, Core, Late)
    shift_templates = list(ShiftTemplate.objects.all().order_by("start_time"))
    if not shift_templates:
        messages.error(request, "No shift templates configured.")
        return redirect("current_month_redirect")

    # --------------------------------------------------------
    # POST — save isolator assignments & supervisors
    # --------------------------------------------------------
    if request.method == "POST":

        if not request.user.has_perm("rota.rota_manager") and not request.user.is_superuser:
            raise PermissionDenied("You do not have permission to edit the rota.")

        isolator_id = request.POST.get("isolator_id")
        isolator = get_object_or_404(Isolator, pk=isolator_id)

        #
        # DELETE existing ISOLATOR assignments for this isolator/day
        #
        Assignment.objects.filter(
            rotaday=rotaday,
            isolator=isolator,
            location_type="ISOLATOR"
        ).delete()

        #
        # CREATE NEW assignments (up to 6)
        #
        for i in range(1, 7):

            staff_id = request.POST.get(f"op{i}_staff") or None
            shift_id = request.POST.get(f"op{i}_shift") or None

            if not staff_id:
                continue
            if not shift_id:
                continue

            staff = get_object_or_404(StaffMember, pk=staff_id)
            shift = get_object_or_404(ShiftTemplate, pk=shift_id)

            assn = Assignment(
                rotaday=rotaday,
                staff=staff,
                clean_room=isolator.clean_room,
                isolator=isolator,
                shift=shift,
                location_type="ISOLATOR",
                is_room_supervisor=False,
            )

            try:
                assn.full_clean()
                assn.save()
            except ValidationError as e:
                messages.error(request, "; ".join(e.messages))
                return redirect(request.path)

        #
        # SUPERVISORS (unchanged, except batch removed)
        #
        supervisor_ids = request.POST.getlist("room_supervisors")
        supervisor_ids = [int(sid) for sid in supervisor_ids if sid.strip()][:4]

        # Remove unselected supervisors
        Assignment.objects.filter(
            rotaday=rotaday,
            clean_room=isolator.clean_room,
            isolator__isnull=True,
            location_type="ROOM",
            is_room_supervisor=True,
        ).exclude(staff_id__in=supervisor_ids).delete()

        # Keep existing IDs
        existing_sup_ids = set(
            Assignment.objects.filter(
                rotaday=rotaday,
                clean_room=isolator.clean_room,
                isolator__isnull=True,
                location_type="ROOM",
                is_room_supervisor=True,
            ).values_list("staff_id", flat=True)
        )

        # Add missing ones
        for sid in supervisor_ids:
            if sid not in existing_sup_ids:
                staff = get_object_or_404(StaffMember, pk=sid)
                assn = Assignment(
                    rotaday=rotaday,
                    staff=staff,
                    clean_room=isolator.clean_room,
                    isolator=None,
                    shift=shift_templates[0],  # default shift, used only for date grouping
                    location_type="ROOM",
                    is_room_supervisor=True,
                )
                try:
                    assn.full_clean()
                    assn.save()
                except ValidationError as e:
                    messages.error(request, "; ".join(e.messages))
                    return redirect(request.path)

        messages.success(request, f"Assignments updated for {isolator.name}.")
        return redirect("daily_rota", year=target_date.year, month=target_date.month, day=target_date.day)

    # --------------------------------------------------------
    # GET — Display data
    # --------------------------------------------------------
    assignments_qs = Assignment.objects.filter(
        rotaday=rotaday,
    ).select_related(
        "staff",
        "staff__crew",
        "clean_room",
        "isolator",
        "shift",
    )

    # Build maps: isolator → assignments (no batches)
    isolator_assignments = {}
    room_supervisors_by_room = {}

    for a in assignments_qs:
        if a.isolator_id:
            isolator_assignments.setdefault(a.isolator_id, []).append(a)
        if a.is_room_supervisor:
            room_supervisors_by_room.setdefault(a.clean_room_id, []).append(a.staff)

    cleanrooms = CleanRoom.objects.all().prefetch_related("isolators")

    rooms_grid = []

    for room in cleanrooms:
        isolators = list(room.isolators.all())

        # Split into left/right wall (unchanged)
        if room.number in (1, 3):
            right_wall = isolators[0:4]
            left_wall = isolators[4:8]
        else:
            right_wall = isolators
            left_wall = []

        room.room_supervisors = room_supervisors_by_room.get(room.id, [])
        room.room_supervisor_ids = [s.id for s in room.room_supervisors]

        # Attach isolator assignments (up to 6 operator slots)
        for iso in left_wall + right_wall:
            ops = sorted(
                isolator_assignments.get(iso.id, []),
                key=lambda x: x.staff.full_name.lower(),
            )
            iso.operator_assignments = ops
            iso.operator_slots = []
            for idx in range(6):
                iso.operator_slots.append(ops[idx] if idx < len(ops) else None)
            iso.has_assignments = bool(ops)

        rooms_grid.append({
            "room": room,
            "right_wall": right_wall,
            "left_wall": left_wall,
        })


    staff_list = StaffMember.objects.filter(is_active=True).order_by("full_name")

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
        "shift_templates": shift_templates,   # <-- ADDED
        "assignments": assignments_qs,
    }
    return render(request, "rota/daily_rota.html", context)


# ------------------------------------------------------------
# Helpers / Staff Management
# ------------------------------------------------------------
@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def current_month_redirect(request):
    today = date.today()
    return redirect("monthly_calendar", year=today.year, month=today.month)


class StaffMemberForm(forms.ModelForm):
    class Meta:
        model = StaffMember
        fields = ["full_name", "email", "mobile_number", "role", "crew", "is_active"]


def is_superuser(user):
    return user.is_superuser


@login_required
@user_passes_test(is_superuser)
def staff_create(request):
    if request.method == "POST":
        form = StaffMemberForm(request.POST)
        if form.is_valid():
            staff = form.save()
            messages.success(request, f"Staff member '{staff.full_name}' created.")
            return redirect("staff_list")
    else:
        form = StaffMemberForm()

    return render(
        request,
        "rota/staff_create.html",
        {"form": form, "today": date.today()},
    )


@login_required
@user_passes_test(is_superuser)
def staff_list(request):
    staff = StaffMember.objects.order_by("full_name")
    return render(
        request,
        "rota/staff_list.html",
        {"staff": staff, "today": date.today()},
    )

from django.db.models import Q
# (you already have other imports above)


@login_required
@permission_required("rota.rota_viewer", raise_exception=True)
def staff_search(request):
    """
    Allow any rota viewer to search for a staff member and see
    all of their assignments (what, where, and which day).
    Now shows shift-based assignments (no batches).
    """
    query = request.GET.get("q", "").strip()
    results = []

    if query:
        staff_qs = (
            StaffMember.objects.filter(
                is_active=True,
                full_name__icontains=query,
            )
            .order_by("full_name")
        )

        today = date.today()

        for staff in staff_qs:
            assns = (
                staff.assignments.select_related(
                    "rotaday",
                    "clean_room",
                    "isolator",
                    "shift",
                )
                .filter(rotaday__date__gte=today)
                .order_by(
                    "rotaday__date",
                    "clean_room__number",
                    "isolator__order",
                    "shift__start_time",
                )
            )
            results.append(
                {
                    "staff": staff,
                    "assignments": assns,
                }
            )

    context = {
        "query": query,
        "results": results,
        "today": date.today(),  # used by navbar
    }
    return render(request, "rota/staff_search.html", context)

def is_rota_manager(user):
    # Adapt to your existing permissions/groups logic
    return user.is_superuser or user.groups.filter(name="Rota Managers").exists()


@login_required
def publish_rota_day(request, rotaday_id):
    if not is_rota_manager(request.user):
        messages.error(request, "You do not have permission to publish rotas.")
        return redirect("daily_rota")  # adjust

    rotaday = get_object_or_404(RotaDay, pk=rotaday_id)

    if request.method != "POST":
        return redirect("daily_rota_by_id", rotaday_id=rotaday.id)  # adjust

    reason = (request.POST.get("reason") or "").strip()

    with transaction.atomic():
        already_published = (rotaday.status == RotaDay.PUBLISHED)

        rotaday.mark_published(request.user)
        rotaday.save()

        RotaDayAuditEvent.objects.create(
            rota_day=rotaday,
            event_type=RotaDayAuditEvent.REPUBLISHED if already_published else RotaDayAuditEvent.PUBLISHED,
            actor=request.user,
            summary=("Republished rota" + (f": {reason}" if reason else "")) if already_published else "Published rota",
            after_json={
                "publish_version": rotaday.publish_version,
                "published_at": rotaday.published_at.isoformat() if rotaday.published_at else None,
            },
        )

    # Send email *after* commit (simple version; good enough for now)
    _send_rota_publish_email(rotaday, reason=reason, is_update=already_published)

    if already_published:
        messages.success(request, f"Rota republished (v{rotaday.publish_version}) and email sent.")
    else:
        messages.success(request, "Rota published and email sent.")

    return redirect("daily_rota_by_id", rotaday_id=rotaday.id)  # adjust


def _send_rota_publish_email(rotaday: RotaDay, reason: str, is_update: bool):
    assignments = Assignment.objects.filter(rota_day=rotaday).select_related(
        "staff_member", "cleanroom", "isolator", "shift_template"
    )

    # Choose recipients: only staff assigned that day
    recipients = []
    for a in assignments:
        email = getattr(a.staff_member, "email", None)
        if email:
            recipients.append(email)
    recipients = sorted(set(recipients))

    if not recipients:
        return

    subject = (
        f"UPDATED rota published – {rotaday}"
        if is_update
        else f"Daily rota published – {rotaday}"
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
        from_email=None,  # uses DEFAULT_FROM_EMAIL
        recipient_list=recipients,
        fail_silently=False,
    )