# --------------------------------------------------------------------
from django.contrib.staticfiles.storage import staticfiles_storage
from django.urls import reverse

from jinja2 import Environment

# --------------------------------------------------------------------
def myreverse(name, *args):
    return reverse(name, args=args)

# --------------------------------------------------------------------
def environment(**options):
    env = Environment(**options)
    env.globals.update({
        'static' : staticfiles_storage.url,
        'url'    : myreverse,
    })
    return env
