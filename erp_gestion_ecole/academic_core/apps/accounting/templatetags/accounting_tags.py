from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Retourne dictionary[key], utilisé dans les templates pour accéder à des dicts par variable."""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def fcfa(value):
    """Formate un montant en FCFA avec séparateur de milliers."""
    if value is None:
        return '—'
    try:
        return '{:,.0f}'.format(float(value)).replace(',', ' ')
    except (ValueError, TypeError):
        return str(value)
