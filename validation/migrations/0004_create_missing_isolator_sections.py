from django.db import migrations


def create_missing_isolator_sections(apps, schema_editor):
    Isolator = apps.get_model("rota", "Isolator")
    IsolatorSection = apps.get_model("validation", "IsolatorSection")

    for isolator in Isolator.objects.all():
        for section in (
            IsolatorSection.SectionType.LEFT,
            IsolatorSection.SectionType.RIGHT,
        ):
            section_obj, _created = IsolatorSection.objects.get_or_create(
                isolator=isolator,
                section=section,
                defaults={"is_active": True},
            )
            if not section_obj.is_active:
                section_obj.is_active = True
                section_obj.save(update_fields=["is_active"])


class Migration(migrations.Migration):

    dependencies = [
        ("validation", "0003_auto_20260216_1356"),
    ]

    operations = [
        migrations.RunPython(create_missing_isolator_sections, migrations.RunPython.noop),
    ]