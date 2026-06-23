from django.db.models.signals import post_save
from django.dispatch import receiver

from rota.models import Isolator
from .models import IsolatorSection


@receiver(post_save, sender=Isolator)
def create_default_sections(sender, instance, created, **kwargs):
    """
    Automatically create APS sections whenever a new Isolator is created.

    APS always needs both Left and Right sections so the assignment pages and
    validation matrix can show the full layout for each isolator.
    """
    if created:
        for section in (
            IsolatorSection.SectionType.LEFT,
            IsolatorSection.SectionType.RIGHT,
        ):
            IsolatorSection.objects.get_or_create(
                isolator=instance,
                section=section,
                defaults={"is_active": True},
            )
