from django import template

register = template.Library()


@register.filter
def get_item(mapping, key):
    """
    Safe dictionary-style lookup for templates.
    Returns None when the value cannot be resolved.
    """
    try:
        if mapping is None:
            return None
        return mapping.get(key)
    except AttributeError:
        return None
