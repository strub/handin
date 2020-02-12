# --------------------------------------------------------------------
from .base import *

import decouple

# --------------------------------------------------------------------
DOTENV_FILE = '/etc/handin/env'
env_config  = decouple.Config(decouple.RepositoryEnv(DOTENV_FILE))

# --------------------------------------------------------------------
DEBUG = False

SECRET_KEY = env_config.get('SECRET_KEY')

PRE_SHARED_SECRET = env_config.get('PRE_SHARED_SECRET')

ALLOWED_HOSTS = env_config.get('ALLOWED_HOSTS',
    cast = lambda v : [s.strip() for s in v.split()])

CACHES = {
    'default': {
        'BACKEND'  : 'django.core.cache.backends.memcached.MemcachedCache',
        'LOCATION' : '127.0.0.1:11211',
        'TIMEOUT'  : 3600,
    }
}

# --------------------------------------------------------------------
INSTALLED_APPS += [
  'dbbackup',
]

DBBACKUP_STORAGE = 'django.core.files.storage.FileSystemStorage'
DBBACKUP_STORAGE_OPTIONS = { 'location': env_config.get('BACKUP_DIR') }

# --------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE'   : 'django.db.backends.postgresql_psycopg2',
        'NAME'     : 'handin',
        'USER'     : 'handin',
        'PASSWORD' : '',
        'HOST'     : '',
        'PORT'     : '',
    }
}

EMAIL_BACKEND       = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST          = 'localhost'
EMAIL_PORT          = 587
EMAIL_HOST_USER     = None
EMAIL_HOST_PASSWORD = None
EMAIL_USE_TLS       = True

# --------------------------------------------------------------------
MEDIA_URL  = '/media/'
MEDIA_ROOT = env_config.get('MEDIA_ROOT')

# --------------------------------------------------------------------
BACKGROUND_TASK_ASYNC_THREADS = \
    env_config.get('BACKGROUND_TASK_ASYNC_THREADS', cast = int)
