from django.db.models.signals import post_save
from django.dispatch import receiver

from rota.models import Isolator
from .models import IsolatorSection


@receiver(post_save, sender=Isolator)
def create_default_sections(sender, instance, created, **kwargs):
    """
    Automatically create L/R sections whenever a new Isolator is created.
    """
    if created:
        for section in [
            IsolatorSection.SectionType.LEFT,
            IsolatorSection.SectionType.RIGHT,
        ]:
            IsolatorSection.objects.get_or_create(
                isolator=instance,
                section=section,
                defaults={"is_active": True},
            )
