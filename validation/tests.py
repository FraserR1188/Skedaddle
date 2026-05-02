from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from rota.models import CleanRoom, Crew, Isolator, StaffMember


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
        StaffMember.objects.create(
            first_name="Alice",
            last_name="Operator",
            role="OPERATIVE",
            crew=crew,
            is_active=True,
        )
        room = CleanRoom.objects.create(number=1, name="Room 1")
        Isolator.objects.create(
            clean_room=room,
            name="Isolator 1",
            order=1,
        )

    def test_validation_cards_renders_without_template_syntax_error(self):
        self.client.force_login(self.manager_user)

        response = self.client.get(reverse("validation:validation_cards"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alice Operator")
        self.assertContains(response, "Validated:")
