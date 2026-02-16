from django import template

register = template.Library()

@register.filter
def vlookup(vmap, key):
    """
    vmap is dict[(operator_id, section_id)] -> OperatorValidation
    key is "operator_id:section_id"
    """
    try:
        operator_id, section_id = key.split(":")
        return vmap.get((int(operator_id), int(section_id)))
    except Exception:
        return None
