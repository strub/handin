# --------------------------------------------------------------------
import os
from .base import *

# --------------------------------------------------------------------
os.environ['PYPANDOC_PANDOC'] = 'pandoc'

# --------------------------------------------------------------------
DEBUG = True

# --------------------------------------------------------------------
INTERNAL_IPS += ['127.0.0.1']

# --------------------------------------------------------------------
SECRET_KEY = '^tdf+cis_j3alh2-rvnsk3f^$f%$$ogh^9c+1#gq8ubd+fvx-p'

# --------------------------------------------------------------------
INSTALLED_APPS += [
    'debug_toolbar',
]

# --------------------------------------------------------------------
MIDDLEWARE += ['debug_toolbar.middleware.DebugToolbarMiddleware', ]

# --------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE'   : 'django.db.backends.postgresql_psycopg2',
        'NAME'     : 'handin',
        'USER'     : 'strub',
        'PASSWORD' : '',
        'HOST'     : '',
        'PORT'     : '',
    }
}

#DATABASES = {
#    'default': {
#        'ENGINE': 'django.db.backends.sqlite3',
#        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
#    }
#}

# --------------------------------------------------------------------
EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

# --------------------------------------------------------------------
DEBUG_TOOLBAR_CONFIG = {
    'JQUERY_URL': '',
}

# --------------------------------------------------------------------
MEDIA_URL  = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media')
