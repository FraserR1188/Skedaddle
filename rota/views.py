import calendar
from datetime import date, timedelta

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
from django.db.models import Q

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

    shift_templates = list(
        ShiftTemplate.objects.all().order_by("start_time")
    )
    if not shift_templates:
        messages.error(request, "No shift templates configured.")
        return redirect("current_month_redirect")

    # -------------------------
    # POST — save assignments
    # -------------------------
    if request.method == "POST":
        if not request.user.has_perm("rota.rota_manager") and not request.user.is_superuser:
            raise PermissionDenied("You do not have permission to edit the rota.")

        isolator = get_object_or_404(Isolator, pk=request.POST.get("isolator_id"))

        Assignment.objects.filter(
            rotaday=rotaday,
            isolator=isolator,
            location_type="ISOLATOR",
        ).delete()

        for i in range(1, 7):
            staff_id = request.POST.get(f"op{i}_staff")
            shift_id = request.POST.get(f"op{i}_shift")

            if not staff_id or not shift_id:
                continue

            assn = Assignment(
                rotaday=rotaday,
                staff=get_object_or_404(StaffMember, pk=staff_id),
                clean_room=isolator.clean_room,
                isolator=isolator,
                shift=get_object_or_404(ShiftTemplate, pk=shift_id),
                location_type="ISOLATOR",
            )
            assn.full_clean()
            assn.save()

        supervisor_ids = [
            int(sid) for sid in request.POST.getlist("room_supervisors") if sid.strip()
        ][:4]

        Assignment.objects.filter(
            rotaday=rotaday,
            clean_room=isolator.clean_room,
            isolator__isnull=True,
            location_type="ROOM",
            is_room_supervisor=True,
        ).exclude(staff_id__in=supervisor_ids).delete()

        existing = set(
            Assignment.objects.filter(
                rotaday=rotaday,
                clean_room=isolator.clean_room,
                location_type="ROOM",
                is_room_supervisor=True,
            ).values_list("staff_id", flat=True)
        )

        for sid in supervisor_ids:
            if sid not in existing:
                Assignment.objects.create(
                    rotaday=rotaday,
                    staff=get_object_or_404(StaffMember, pk=sid),
                    clean_room=isolator.clean_room,
                    shift=shift_templates[0],
                    location_type="ROOM",
                    is_room_supervisor=True,
                )

        messages.success(request, f"Assignments updated for {isolator.name}.")
        return redirect("daily_rota", year=year, month=month, day=day)

    # -------------------------
    # GET — display rota
    # -------------------------
    assignments_qs = Assignment.objects.filter(rotaday=rotaday).select_related(
        "staff", "staff__crew", "clean_room", "isolator", "shift"
    )

    isolator_assignments = {}
    room_supervisors_by_room = {}

    for a in assignments_qs:
        if a.isolator_id:
            isolator_assignments.setdefault(a.isolator_id, []).append(a)
        if a.is_room_supervisor:
            room_supervisors_by_room.setdefault(a.clean_room_id, []).append(a.staff)

    cleanrooms = CleanRoom.objects.prefetch_related("isolators")
    rooms_grid = []

    for room in cleanrooms:
        isolators = list(room.isolators.all())

        if room.number in (1, 3):
            right_wall, left_wall = isolators[:4], isolators[4:8]
        else:
            right_wall, left_wall = isolators, []

        for iso in left_wall + right_wall:
            ops = sorted(
                isolator_assignments.get(iso.id, []),
                key=lambda x: (x.staff.first_name.lower(), x.staff.last_name.lower()),
            )
            iso.operator_slots = ops + [None] * (6 - len(ops))
            iso.has_assignments = bool(ops)

        rooms_grid.append({
            "room": room,
            "right_wall": right_wall,
            "left_wall": left_wall,
            "room_supervisors": room_supervisors_by_room.get(room.id, []),
        })

    staff = StaffMember.objects.select_related("crew").order_by(
        "crew__sort_order", "first_name", "last_name"
    )

    context = {
        "date": target_date,
        "today": date.today(),
        "rotaday": rotaday,
        "rooms_grid": rooms_grid,
        "staff_list": staff,
        "operators": staff.filter(role="OPERATIVE"),
        "supervisors": staff.filter(role="SUPERVISOR"),
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
    staff = StaffMember.objects.select_related("crew").order_by(
        "crew__sort_order", "first_name", "last_name"
    )
    return render(
        request,
        "rota/staff_list.html",
        {"staff": staff, "today": date.today()},
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
                "publish_version": rotaday.publish_version,
                "published_at": rotaday.published_at.isoformat() if rotaday.published_at else None,
            },
        )

    _send_rota_publish_email(rotaday, reason=reason, is_update=already_published)

    if already_published:
        messages.success(
            request, f"Rota republished (v{rotaday.publish_version}) and email sent."
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
        .select_related("staff", "clean_room", "isolator", "shift")
        .order_by(
            "clean_room__number",
            "isolator__order",
            "shift__start_time",
            "staff__first_name",
            "staff__last_name",
        )
    )

    recipients = sorted(
        {a.staff.email for a in assignments if getattr(a.staff, "email", "").strip()}
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
