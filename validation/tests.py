from datetime import timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from rota.models import CleanRoom, Crew, Isolator, StaffMember
from validation.models import IsolatorSection, OperatorValidation
from validation.services import check_operator_valid_for_section


class ValidationCardsTemplateTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        manager_permission = Permission.objects.get(codename="rota_manager")

        cls.manager_user = user_model.objects.create_user(
            username="validation-manager",
            password="testpass123",
        )
        cls.manager_user.user_permissions.add(manager_permission)

        crew = Crew.objects.create(name="A", sort_order=1)
        cls.staff = StaffMember.objects.create(
            first_name="Alice",
            last_name="Operator",
            role="OPERATIVE",
            crew=crew,
            is_active=True,
        )
        room = CleanRoom.objects.create(number=1, name="Room 1")
        cls.isolator = Isolator.objects.create(
            clean_room=room,
            name="Isolator 1",
            order=1,
        )
        cls.left_section = cls.isolator.sections.get(section="L")

    def test_validation_cards_renders_without_template_syntax_error(self):
        self.client.force_login(self.manager_user)

        response = self.client.get(reverse("validation:validation_cards"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Section Clearance Matrix")
        self.assertContains(response, "Alice Operator")
        self.assertContains(response, "Can work")

    def test_quick_update_statuses_feed_backend_eligibility(self):
        self.client.force_login(self.manager_user)
        url = reverse("validation:validation_quick_update")
        referer = reverse("validation:validation_cards")
        expires_on = timezone.localdate() + timedelta(days=30)

        response = self.client.post(
            url,
            {
                "operator_id": self.staff.id,
                "section_id": self.left_section.id,
                "status": OperatorValidation.Status.VALID,
                "expires_on": expires_on.isoformat(),
            },
            HTTP_REFERER=referer,
        )

        self.assertEqual(response.status_code, 302)
        validation = OperatorValidation.objects.get(
            operator=self.staff,
            isolator_section=self.left_section,
        )
        self.assertEqual(validation.status, OperatorValidation.Status.VALID)
        self.assertEqual(validation.expires_on, expires_on)
        self.assertTrue(
            check_operator_valid_for_section(self.staff, self.left_section).ok
        )

        response = self.client.post(
            url,
            {
                "operator_id": self.staff.id,
                "section_id": self.left_section.id,
                "status": OperatorValidation.Status.IN_TRAINING,
                "expires_on": expires_on.isoformat(),
            },
            HTTP_REFERER=referer,
        )

        self.assertEqual(response.status_code, 302)
        validation.refresh_from_db()
        self.assertEqual(validation.status, OperatorValidation.Status.IN_TRAINING)
        self.assertIsNone(validation.expires_on)
        result = check_operator_valid_for_section(self.staff, self.left_section)
        self.assertFalse(result.ok)
        self.assertIn("In Training", result.reason)

        response = self.client.post(
            url,
            {
                "operator_id": self.staff.id,
                "section_id": self.left_section.id,
                "status": "NONE",
            },
            HTTP_REFERER=referer,
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            OperatorValidation.objects.filter(
                operator=self.staff,
                isolator_section=self.left_section,
            ).exists()
        )


class APSMatrixSectionCountTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        user_model = get_user_model()
        manager_permission = Permission.objects.get(codename="rota_manager")

        cls.manager_user = user_model.objects.create_user(
            username="aps-matrix-manager",
            password="testpass123",
        )
        cls.manager_user.user_permissions.add(manager_permission)

        crew = Crew.objects.create(name="A", sort_order=1)
        StaffMember.objects.create(
            first_name="Arin",
            last_name="Powell",
            role="OPERATIVE",
            crew=crew,
            is_active=True,
        )
        room = CleanRoom.objects.create(number=1, name="Room 1")

        cls.iso_left = Isolator.objects.create(
            clean_room=room,
            name="Isolator 1 L",
            order=1,
        )
        cls.iso_right = Isolator.objects.create(
            clean_room=room,
            name="Isolator 1 R",
            order=2,
        )

        # Existing live data had both L/R rows for side-named isolators.
        # Keep that shape here and assert the APS matrix only uses the
        # matching target section from each isolator.
        IsolatorSection.objects.create(
            isolator=cls.iso_left,
            section=IsolatorSection.SectionType.RIGHT,
            is_active=True,
        )
        IsolatorSection.objects.create(
            isolator=cls.iso_right,
            section=IsolatorSection.SectionType.LEFT,
            is_active=True,
        )

    def test_side_named_isolators_render_one_aps_target_each(self):
        self.client.force_login(self.manager_user)

        response = self.client.get(reverse("validation:validation_cards"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total_sides"], 2)
        self.assertEqual(
            [
                (column["iso_label"], column["side_label"])
                for column in response.context["columns"]
            ],
            [("Iso 1", "L"), ("Iso 1", "R")],
        )
