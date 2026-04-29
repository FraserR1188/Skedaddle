from __future__ import annotations

from collections import defaultdict

from rota.models import Assignment, CleanRoom, WorkArea


MAX_ISOLATOR_STAFF_PER_BLOCK = 6


def _worst_status(statuses: list[str]) -> str:
    """
    Returns the most severe status from a list.

    Severity order:
    Red > Amber > Green > Grey
    """
    rank = {
        "Red": 4,
        "Amber": 3,
        "Green": 2,
        "Grey": 1,
    }

    if not statuses:
        return "Grey"

    return max(statuses, key=lambda status: rank.get(status, 0))


def _issue(severity: str, message: str, source: str = "") -> dict:
    return {
        "severity": severity,
        "message": message,
        "source": source,
    }


def build_suite_overview(rotaday):
    """
    Builds a read-only operational dashboard data structure for one RotaDay.

    This is intentionally UI-friendly and can later become the same shape
    returned by a JSON API for a React dashboard.
    """

    assignments = list(
        Assignment.objects.filter(rotaday=rotaday)
        .select_related(
            "staff",
            "staff__crew",
            "clean_room",
            "isolator",
            "isolator_section",
            "work_area",
            "shift",
        )
        .order_by(
            "shift_block",
            "clean_room__number",
            "isolator__order",
            "work_area__sort_order",
            "staff__first_name",
            "staff__last_name",
        )
    )

    room_supervisors = defaultdict(lambda: {"AM": [], "PM": []})
    isolator_assignments = defaultdict(lambda: {"AM": [], "PM": []})
    work_area_assignments = defaultdict(lambda: {"AM": [], "PM": []})

    for assignment in assignments:
        if (
            assignment.location_type == Assignment.LocationType.ROOM
            and assignment.clean_room_id
            and assignment.is_room_supervisor
        ):
            room_supervisors[assignment.clean_room_id][assignment.shift_block].append(
                assignment
            )

        elif (
            assignment.location_type == Assignment.LocationType.ISOLATOR
            and assignment.isolator_id
        ):
            isolator_assignments[assignment.isolator_id][assignment.shift_block].append(
                assignment
            )

        elif (
            assignment.location_type == Assignment.LocationType.WORK_AREA
            and assignment.work_area_id
        ):
            work_area_assignments[assignment.work_area_id][
                assignment.shift_block
            ].append(assignment)

    all_issues = []
    cleanroom_cards = []

    cleanrooms = (
        CleanRoom.objects.prefetch_related("isolators")
        .all()
        .order_by("number", "name")
    )

    for room in cleanrooms:
        room_issues = []
        isolator_cards = []

        supervisors_am = room_supervisors[room.id]["AM"]
        supervisors_pm = room_supervisors[room.id]["PM"]

        room_total_am = 0
        room_total_pm = 0

        for isolator in room.isolators.all().order_by("order", "name"):
            bucket = isolator_assignments[isolator.id]

            am_assignments = bucket["AM"]
            pm_assignments = bucket["PM"]

            am_count = len(am_assignments)
            pm_count = len(pm_assignments)

            room_total_am += am_count
            room_total_pm += pm_count

            isolator_issues = []

            if am_count > MAX_ISOLATOR_STAFF_PER_BLOCK:
                isolator_issues.append(
                    _issue(
                        "Red",
                        f"{isolator.name} has more than "
                        f"{MAX_ISOLATOR_STAFF_PER_BLOCK} AM staff assigned.",
                        source=isolator.name,
                    )
                )

            if pm_count > MAX_ISOLATOR_STAFF_PER_BLOCK:
                isolator_issues.append(
                    _issue(
                        "Red",
                        f"{isolator.name} has more than "
                        f"{MAX_ISOLATOR_STAFF_PER_BLOCK} PM staff assigned.",
                        source=isolator.name,
                    )
                )

            if isolator_issues:
                isolator_status = _worst_status(
                    [issue["severity"] for issue in isolator_issues]
                )
            elif am_count == 0 and pm_count == 0:
                isolator_status = "Grey"
            else:
                isolator_status = "Green"

            all_issues.extend(isolator_issues)

            isolator_cards.append(
                {
                    "isolator": isolator,
                    "status": isolator_status,
                    "am_count": am_count,
                    "pm_count": pm_count,
                    "capacity": MAX_ISOLATOR_STAFF_PER_BLOCK,
                    "am_assignments": am_assignments,
                    "pm_assignments": pm_assignments,
                    "issues": isolator_issues,
                }
            )

        has_room_activity = bool(
            supervisors_am
            or supervisors_pm
            or room_total_am > 0
            or room_total_pm > 0
        )

        if room_total_am > 0 and not supervisors_am:
            room_issues.append(
                _issue(
                    "Red",
                    f"{room.name} has AM isolator activity but no AM room supervisor.",
                    source=room.name,
                )
            )

        if room_total_pm > 0 and not supervisors_pm:
            room_issues.append(
                _issue(
                    "Red",
                    f"{room.name} has PM isolator activity but no PM room supervisor.",
                    source=room.name,
                )
            )

        if supervisors_am and room_total_am == 0:
            room_issues.append(
                _issue(
                    "Amber",
                    f"{room.name} has an AM room supervisor but no AM isolator staff assigned.",
                    source=room.name,
                )
            )

        if supervisors_pm and room_total_pm == 0:
            room_issues.append(
                _issue(
                    "Amber",
                    f"{room.name} has a PM room supervisor but no PM isolator staff assigned.",
                    source=room.name,
                )
            )

        all_issues.extend(room_issues)

        room_status_inputs = [issue["severity"] for issue in room_issues]
        room_status_inputs.extend(
            [
                isolator_card["status"]
                for isolator_card in isolator_cards
                if isolator_card["status"] != "Grey"
            ]
        )

        if not has_room_activity:
            room_status = "Grey"
        elif room_status_inputs:
            room_status = _worst_status(room_status_inputs)
        else:
            room_status = "Green"

        cleanroom_cards.append(
            {
                "room": room,
                "status": room_status,
                "supervisors_am": supervisors_am,
                "supervisors_pm": supervisors_pm,
                "isolators": isolator_cards,
                "am_operator_count": room_total_am,
                "pm_operator_count": room_total_pm,
                "has_activity": has_room_activity,
                "issues": room_issues,
            }
        )

    work_area_cards = []

    work_areas = WorkArea.objects.filter(is_active=True).order_by(
        "sort_order",
        "name",
    )

    for area in work_areas:
        bucket = work_area_assignments[area.id]

        am_assignments = bucket["AM"]
        pm_assignments = bucket["PM"]

        am_count = len(am_assignments)
        pm_count = len(pm_assignments)

        area_issues = []

        required_am = area.required_staff_am
        required_pm = area.required_staff_pm

        has_fixed_requirement = required_am > 0 or required_pm > 0

        if required_am > 0:
            if am_count == 0:
                area_issues.append(
                    _issue(
                        "Red",
                        f"{area.name} has no AM cover ({am_count}/{required_am}).",
                        source=area.name,
                    )
                )
            elif am_count < required_am:
                area_issues.append(
                    _issue(
                        "Amber",
                        f"{area.name} has partial AM cover ({am_count}/{required_am}).",
                        source=area.name,
                    )
                )

        if required_pm > 0:
            if pm_count == 0:
                area_issues.append(
                    _issue(
                        "Red",
                        f"{area.name} has no PM cover ({pm_count}/{required_pm}).",
                        source=area.name,
                    )
                )
            elif pm_count < required_pm:
                area_issues.append(
                    _issue(
                        "Amber",
                        f"{area.name} has partial PM cover ({pm_count}/{required_pm}).",
                        source=area.name,
                    )
                )

        if area_issues:
            area_status = _worst_status([issue["severity"] for issue in area_issues])
        elif has_fixed_requirement:
            area_status = "Green"
        elif am_count > 0 or pm_count > 0:
            area_status = "Green"
        else:
            area_status = "Grey"

        all_issues.extend(area_issues)

        work_area_cards.append(
            {
                "area": area,
                "status": area_status,
                "required_am": required_am,
                "required_pm": required_pm,
                "am_count": am_count,
                "pm_count": pm_count,
                "am_assignments": am_assignments,
                "pm_assignments": pm_assignments,
                "has_fixed_requirement": has_fixed_requirement,
                "issues": area_issues,
            }
        )

    required_work_area_cards = [
        card for card in work_area_cards if card["has_fixed_requirement"]
    ]

    covered_required_work_areas = [
        card for card in required_work_area_cards if card["status"] == "Green"
    ]

    active_cleanrooms = [
        card for card in cleanroom_cards if card["has_activity"]
    ]

    green_cleanrooms = [
        card for card in cleanroom_cards if card["status"] == "Green"
    ]

    red_issues = [issue for issue in all_issues if issue["severity"] == "Red"]
    amber_issues = [issue for issue in all_issues if issue["severity"] == "Amber"]

    suite_status_candidates = []

    suite_status_candidates.extend(
        card["status"]
        for card in cleanroom_cards
        if card["status"] != "Grey"
    )

    suite_status_candidates.extend(
        card["status"]
        for card in work_area_cards
        if card["has_fixed_requirement"] or card["status"] != "Grey"
    )

    suite_status = _worst_status(suite_status_candidates)

    suite_summary = {
        "suite_status": suite_status,
        "total_assignments": len(assignments),
        "cleanrooms_total": len(cleanroom_cards),
        "cleanrooms_active": len(active_cleanrooms),
        "cleanrooms_green": len(green_cleanrooms),
        "required_work_areas_total": len(required_work_area_cards),
        "required_work_areas_covered": len(covered_required_work_areas),
        "red_issue_count": len(red_issues),
        "amber_issue_count": len(amber_issues),
        "issue_count": len(all_issues),
    }

    return {
        "suite_summary": suite_summary,
        "issues": all_issues,
        "red_issues": red_issues,
        "amber_issues": amber_issues,
        "cleanroom_cards": cleanroom_cards,
        "work_area_cards": work_area_cards,
    }