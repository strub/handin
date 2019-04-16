# --------------------------------------------------------------------
"""
https://docs.djangoproject.com/en/2.2/howto/deployment/wsgi/
"""

# --------------------------------------------------------------------
import os

from django.core.wsgi import get_wsgi_application

# --------------------------------------------------------------------
os.environ['DJANGO_SETTINGS_MODULE'] = 'handin.settings.deploy'
application = get_wsgi_application()
