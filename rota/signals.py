# rota/signals.py
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver

from .models import Assignment, RotaDayAuditEvent


def _assignment_snapshot(a: Assignment) -> dict:
    return {
        "staff_id": a.staff_member_id,
        "staff_name": getattr(a.staff_member, "name", str(a.staff_member)) if a.staff_member_id else None,
        "room_id": a.cleanroom_id,
        "room_name": getattr(a.cleanroom, "name", str(a.cleanroom)) if a.cleanroom_id else None,
        "isolator_id": a.isolator_id,
        "isolator_name": getattr(a.isolator, "name", str(a.isolator)) if a.isolator_id else None,
        "shift_id": a.shift_template_id,
        "shift_name": getattr(a.shift_template, "name", str(a.shift_template)) if a.shift_template_id else None,
    }


@receiver(pre_save, sender=Assignment)
def assignment_pre_save(sender, instance: Assignment, **kwargs):
    if not instance.pk:
        instance._before_snapshot = None
        return

    try:
        old = Assignment.objects.select_related(
            "staff_member", "cleanroom", "isolator", "shift_template"
        ).get(pk=instance.pk)
        instance._before_snapshot = _assignment_snapshot(old)
    except Assignment.DoesNotExist:
        instance._before_snapshot = None


@receiver(post_save, sender=Assignment)
def assignment_post_save(sender, instance: Assignment, created: bool, **kwargs):
    rota_day = instance.rota_day  # adjust if your FK is named differently
    after = _assignment_snapshot(instance)
    before = getattr(instance, "_before_snapshot", None)

    if created:
        summary = (
            f"Assigned {after['staff_name']} to {after['room_name']}"
            f"{' – ' + after['isolator_name'] if after['isolator_name'] else ''}"
            f"{' (' + after['shift_name'] + ')' if after['shift_name'] else ''}"
        )
        RotaDayAuditEvent.objects.create(
            rota_day=rota_day,
            event_type=RotaDayAuditEvent.ASSIGNMENT_CREATED,
            actor=None,  # set later if you want request.user (see note below)
            summary=summary,
            after_json=after,
        )
    else:
        # Only log if meaningful change
        if before != after:
            summary = (
                f"Updated assignment for {after['staff_name']} "
                f"({before.get('room_name') if before else 'unknown'} → {after['room_name']})"
            )
            RotaDayAuditEvent.objects.create(
                rota_day=rota_day,
                event_type=RotaDayAuditEvent.ASSIGNMENT_UPDATED,
                actor=None,
                summary=summary,
                before_json=before,
                after_json=after,
            )


@receiver(post_delete, sender=Assignment)
def assignment_post_delete(sender, instance: Assignment, **kwargs):
    rota_day = instance.rota_day
    before = _assignment_snapshot(instance)
    summary = f"Removed assignment for {before['staff_name']} from {before['room_name']}"
    RotaDayAuditEvent.objects.create(
        rota_day=rota_day,
        event_type=RotaDayAuditEvent.ASSIGNMENT_DELETED,
        actor=None,
        summary=summary,
        before_json=before,
    )
