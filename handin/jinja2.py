# --------------------------------------------------------------------
from   django.contrib.staticfiles.storage import staticfiles_storage
from   django.urls import reverse
import django.utils as utils
import django.utils.timezone as tz

from jinja2 import Environment

# --------------------------------------------------------------------
def myreverse(name, *args):
    return reverse(name, args=args)

# --------------------------------------------------------------------
def mydate(date):
    date = date.astimezone(utils.timezone.get_current_timezone())
    return date.strftime('%B %d, %Y (%H:%M:%S)')

# --------------------------------------------------------------------
def environment(**options):
    env = Environment(**options)
    env.globals.update({
        'static' : staticfiles_storage.url,
        'url'    : myreverse,
        'date'   : mydate,
        'now'    : tz.now(),
    })
    return env
