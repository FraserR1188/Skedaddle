from datetime import date, time

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from rota.models import Assignment, CleanRoom, Crew, Isolator, RotaDay, ShiftTemplate, StaffMember, WorkArea
from validation.models import OperatorValidation


class APSSectionAssignmentWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()

        viewer_permission = Permission.objects.get(codename="rota_viewer")
        manager_permission = Permission.objects.get(codename="rota_manager")

        cls.viewer_user = user_model.objects.create_user(
            username="viewer",
            password="testpass123",
        )
        cls.viewer_user.user_permissions.add(viewer_permission)

        cls.manager_user = user_model.objects.create_user(
            username="manager",
            password="testpass123",
        )
        cls.manager_user.user_permissions.add(viewer_permission, manager_permission)

        cls.crew = Crew.objects.create(name="A", sort_order=1)
        cls.room = CleanRoom.objects.create(number=1, name="Room 1")
        cls.isolator = Isolator.objects.create(
            clean_room=cls.room,
            name="Isolator 1",
            order=1,
        )
        cls.left_section = cls.isolator.sections.get(section="L")
        cls.right_section = cls.isolator.sections.get(section="R")

        cls.am_shift = ShiftTemplate.objects.create(
            name="AM Shift",
            start_time=time(7, 0),
            end_time=time(15, 0),
        )
        cls.pm_shift = ShiftTemplate.objects.create(
            name="PM Shift",
            start_time=time(15, 0),
            end_time=time(23, 0),
        )

        cls.target_date = date(2026, 5, 2)
        cls.rotaday = RotaDay.objects.create(date=cls.target_date)
        cls.url = reverse(
            "daily_rota",
            kwargs={"year": 2026, "month": 5, "day": 2},
        )

        cls.operator_left = StaffMember.objects.create(
            first_name="Alice",
            last_name="Left",
            role="OPERATIVE",
            crew=cls.crew,
            is_active=True,
        )
        cls.operator_right = StaffMember.objects.create(
            first_name="Bob",
            last_name="Right",
            role="OPERATIVE",
            crew=cls.crew,
            is_active=True,
        )
        cls.operator_unvalidated = StaffMember.objects.create(
            first_name="Charlie",
            last_name="Unvalidated",
            role="OPERATIVE",
            crew=cls.crew,
            is_active=True,
        )

        OperatorValidation.objects.create(
            operator=cls.operator_left,
            isolator_section=cls.left_section,
            status=OperatorValidation.Status.VALID,
            valid_from=cls.target_date,
        )
        OperatorValidation.objects.create(
            operator=cls.operator_right,
            isolator_section=cls.right_section,
            status=OperatorValidation.Status.VALID,
            valid_from=cls.target_date,
        )

    def build_post_data(self, **overrides):
        data = {"isolator_id": str(self.isolator.id)}
        for index in range(1, 7):
            data[f"op{index}_staff"] = ""
            data[f"op{index}_block"] = ""
            data[f"op{index}_section"] = ""
        data.update(overrides)
        return data

    def create_assignment(self, **kwargs):
        assignment = Assignment(**kwargs)
        assignment.full_clean()
        assignment.save()
        return assignment

    def test_daily_rota_get_allows_viewer_but_post_requires_manager(self):
        self.client.force_login(self.viewer_user)

        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)

        post_response = self.client.post(
            self.url,
            self.build_post_data(),
        )
        self.assertEqual(post_response.status_code, 403)

    def test_manager_can_save_assignments_with_explicit_sections(self):
        self.client.force_login(self.manager_user)

        response = self.client.post(
            self.url,
            self.build_post_data(
                op1_staff=str(self.operator_left.id),
                op1_block="AM",
                op1_section=str(self.left_section.id),
                op2_staff=str(self.operator_right.id),
                op2_block="PM",
                op2_section=str(self.right_section.id),
            ),
        )

        self.assertEqual(response.status_code, 302)

        assignments = Assignment.objects.filter(
            rotaday=self.rotaday,
            location_type=Assignment.LocationType.ISOLATOR,
        ).order_by("staff__first_name")
        self.assertEqual(assignments.count(), 2)

        assignments_by_staff = {assignment.staff_id: assignment for assignment in assignments}
        self.assertEqual(
            assignments_by_staff[self.operator_left.id].isolator_section_id,
            self.left_section.id,
        )
        self.assertEqual(
            assignments_by_staff[self.operator_left.id].shift_block,
            Assignment.ShiftBlock.AM,
        )
        self.assertEqual(
            assignments_by_staff[self.operator_right.id].isolator_section_id,
            self.right_section.id,
        )
        self.assertEqual(
            assignments_by_staff[self.operator_right.id].shift_block,
            Assignment.ShiftBlock.PM,
        )

    def test_manager_cannot_save_operator_row_without_section(self):
        self.client.force_login(self.manager_user)

        response = self.client.post(
            self.url,
            self.build_post_data(
                op1_staff=str(self.operator_left.id),
                op1_block="AM",
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "Operator 1 requires an isolator section when staff and shift block are selected.",
        )
        self.assertFalse(
            Assignment.objects.filter(
                rotaday=self.rotaday,
                location_type=Assignment.LocationType.ISOLATOR,
            ).exists()
        )

    def test_failed_section_validation_rolls_back_existing_assignments(self):
        existing_assignment = self.create_assignment(
            rotaday=self.rotaday,
            staff=self.operator_left,
            clean_room=self.room,
            isolator=self.isolator,
            isolator_section=self.left_section,
            shift=self.am_shift,
            location_type=Assignment.LocationType.ISOLATOR,
            shift_block=Assignment.ShiftBlock.AM,
        )

        self.client.force_login(self.manager_user)

        response = self.client.post(
            self.url,
            self.build_post_data(
                op1_staff=str(self.operator_left.id),
                op1_block="AM",
                op1_section=str(self.left_section.id),
                op2_staff=str(self.operator_unvalidated.id),
                op2_block="PM",
                op2_section=str(self.right_section.id),
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is not APS validated")

        assignments = Assignment.objects.filter(
            rotaday=self.rotaday,
            location_type=Assignment.LocationType.ISOLATOR,
        )
        self.assertEqual(assignments.count(), 1)
        self.assertTrue(assignments.filter(pk=existing_assignment.pk).exists())

    def test_existing_am_pm_conflicts_are_still_rejected(self):
        work_area = WorkArea.objects.create(
            name="Clean MAL",
            area_type=WorkArea.AreaType.MAL,
            sort_order=1,
        )
        self.create_assignment(
            rotaday=self.rotaday,
            staff=self.operator_left,
            work_area=work_area,
            shift=self.am_shift,
            location_type=Assignment.LocationType.WORK_AREA,
            shift_block=Assignment.ShiftBlock.AM,
        )

        self.client.force_login(self.manager_user)

        response = self.client.post(
            self.url,
            self.build_post_data(
                op1_staff=str(self.operator_left.id),
                op1_block="AM",
                op1_section=str(self.left_section.id),
            ),
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "is already assigned to Clean MAL (AM).")
        self.assertFalse(
            Assignment.objects.filter(
                rotaday=self.rotaday,
                isolator=self.isolator,
                location_type=Assignment.LocationType.ISOLATOR,
            ).exists()
        )

    def test_daily_rota_displays_section_not_recorded_for_legacy_null_section(self):
        Assignment.objects.create(
            rotaday=self.rotaday,
            staff=self.operator_left,
            clean_room=self.room,
            isolator=self.isolator,
            isolator_section=None,
            shift=self.am_shift,
            location_type=Assignment.LocationType.ISOLATOR,
            shift_block=Assignment.ShiftBlock.AM,
        )

        self.client.force_login(self.viewer_user)

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Section not recorded")
