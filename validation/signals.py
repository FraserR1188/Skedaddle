import re

from django.db.models.signals import post_save
from django.dispatch import receiver

from rota.models import Isolator
from .models import IsolatorSection


ISOLATOR_SIDE_SUFFIX_RE = re.compile(r"(?:^|[\s_-])([LR])$", re.IGNORECASE)


@receiver(post_save, sender=Isolator)
def create_default_sections(sender, instance, created, **kwargs):
    """
    Automatically create APS sections whenever a new Isolator is created.

    Side-named isolators such as "Isolator 1 L" represent one APS target,
    so only the matching section is created. Generic isolators keep L/R.
    """
    if created:
        side_match = ISOLATOR_SIDE_SUFFIX_RE.search(instance.name.strip())
        sections = (
            [side_match.group(1).upper()]
            if side_match
            else [
                IsolatorSection.SectionType.LEFT,
                IsolatorSection.SectionType.RIGHT,
            ]
        )

        for section in sections:
            IsolatorSection.objects.get_or_create(
                isolator=instance,
                section=section,
                defaults={"is_active": True},
            )
