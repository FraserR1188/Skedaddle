from django import template

register = template.Library()


@register.filter
def get_item(d, key):
    if isinstance(d, dict):
        return d.get(key)
    return None


@register.filter
def status_key(value):
    return str(value or "grey").strip().lower()


@register.filter
def status_glyph(value):
    status = status_key(value)
    if status == "green":
        return "ok"
    if status == "amber":
        return "!"
    if status == "red":
        return "x"
    return "-"


@register.filter
def initials(value):
    if hasattr(value, "first_name") and hasattr(value, "last_name"):
        parts = [value.first_name, value.last_name]
    else:
        parts = str(value or "").replace("_", " ").split()

    letters = [part[0] for part in parts if part]
    return "".join(letters[:2]).upper() or "S"


@register.filter
def staff_names(assignments):
    names = []

    for assignment in assignments or []:
        staff = getattr(assignment, "staff", None)
        if staff:
            names.append(staff.full_name)

    return ", ".join(names)
