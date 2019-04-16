# --------------------------------------------------------------------
import django
import django.template.defaultfilters as defaultfilters

# --------------------------------------------------------------------
register = django.template.Library()

# --------------------------------------------------------------------
@register.filter
def get_item(dictionary, key):
    try: return dictionary.get(key, None)
    except AttributeError: return None

