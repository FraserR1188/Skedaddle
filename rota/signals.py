# rota/signals.py
from django.db.models.signals import pre_save, post_save, post_delete
from django.dispatch import receiver

from .models import Assignment, RotaDayAuditEvent


def _assignment_snapshot(a: Assignment) -> dict:
    return {
        "staff_id": a.staff_id,
        "staff_name": a.staff.full_name if a.staff_id else None,
        "room_id": a.clean_room_id,
        "room_name": a.clean_room.name if a.clean_room_id else None,
        "isolator_id": a.isolator_id,
        "isolator_name": a.isolator.name if a.isolator_id else None,
        "shift_id": a.shift_id,
        "shift_name": a.shift.name if a.shift_id else None,
    }


@receiver(pre_save, sender=Assignment)
def assignment_pre_save(sender, instance: Assignment, **kwargs):
    if not instance.pk:
        instance._before_snapshot = None
        return

    try:
        old = Assignment.objects.select_related(
            "staff", "clean_room", "isolator", "shift"
        ).get(pk=instance.pk)
        instance._before_snapshot = _assignment_snapshot(old)
    except Assignment.DoesNotExist:
        instance._before_snapshot = None


@receiver(post_save, sender=Assignment)
def assignment_post_save(sender, instance: Assignment, created: bool, **kwargs):
    rotaday = instance.rotaday  # correct FK name in your model

    after = _assignment_snapshot(instance)
    before = getattr(instance, "_before_snapshot", None)

    if created:
        summary = (
            f"Assigned {after['staff_name']} to {after['room_name']}"
            f"{' – ' + after['isolator_name'] if after['isolator_name'] else ''}"
            f"{' (' + after['shift_name'] + ')' if after['shift_name'] else ''}"
        )
        RotaDayAuditEvent.objects.create(
            rotaday=rotaday,
            event_type=RotaDayAuditEvent.ASSIGNMENT_CREATED,
            actor=None,
            summary=summary,
            after_json=after,
        )
    else:
        if before != after:
            summary = (
                f"Updated assignment for {after['staff_name']} "
                f"({before.get('room_name') if before else 'unknown'} → {after['room_name']})"
            )
            RotaDayAuditEvent.objects.create(
                rotaday=rotaday,
                event_type=RotaDayAuditEvent.ASSIGNMENT_UPDATED,
                actor=None,
                summary=summary,
                before_json=before,
                after_json=after,
            )


@receiver(post_delete, sender=Assignment)
def assignment_post_delete(sender, instance: Assignment, **kwargs):
    rotaday = instance.rotaday
    before = _assignment_snapshot(instance)

    summary = f"Removed assignment for {before['staff_name']} from {before['room_name']}"
    RotaDayAuditEvent.objects.create(
        rotaday=rotaday,
        event_type=RotaDayAuditEvent.ASSIGNMENT_DELETED,
        actor=None,
        summary=summary,
        before_json=before,
    )
