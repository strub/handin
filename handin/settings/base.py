# --------------------------------------------------------------------
import os

# --------------------------------------------------------------------
BASE_DIR = os.path.realpath(os.path.join(__file__, *['..'] * 3))

# --------------------------------------------------------------------
ALLOWED_HOSTS = []
INTERNAL_IPS  = []

# --------------------------------------------------------------------
PRE_SHARED_SECRET = None

# --------------------------------------------------------------------
# Application definition

INSTALLED_APPS = [
    'upload.apps.UploadConfig',
    'handin.apps.HandinConfig',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'django_cleanup.apps.CleanupConfig',
    'background_task',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'handin.middleware.RedirectMiddleware',
]

ROOT_URLCONF = 'handin.urls'

# --------------------------------------------------------------------
# Templates 
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.jinja2.Jinja2',
        'DIRS': [],
        'APP_DIRS': True,
        'NAME': 'jinja',
        'OPTIONS': {
            'environment': 'handin.jinja2.environment',
        },
    },

    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# --------------------------------------------------------------------
# WSGI
WSGI_APPLICATION = 'handin.wsgi.application'

# --------------------------------------------------------------------
# Authentication
AUTHENTICATION_BACKENDS = (
    'handin.auth.XLDAPBackend',
)

AUTH_USER_MODEL = 'handin.User'
LOGIN_URL       = 'upload:login'

# --------------------------------------------------------------------
# Internationalization
# https://docs.djangoproject.com/en/2.2/topics/i18n/

LANGUAGE_CODE = 'en-us'
TIME_ZONE     = 'Europe/Paris'
USE_I18N      = True
USE_L10N      = True
USE_TZ        = True

# --------------------------------------------------------------------
# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/2.2/howto/static-files/

STATIC_URL = '/static/'

STATICFILES_DIRS = [
    os.path.join(BASE_DIR, 'static'),
]

# --------------------------------------------------------------------
# Background tasks

MAX_ATTEMPTS = 4
MAX_RUN_TIME = 90
BACKGROUND_TASK_RUN_ASYNC = True
BACKGROUND_TASK_ASYNC_THREADS = 4

# --------------------------------------------------------------------
from django.contrib.messages import constants as messages

MESSAGE_TAGS = {
  messages.DEBUG   : 'alert-info'   ,
  messages.INFO    : 'alert-info'   ,
  messages.SUCCESS : 'alert-success',
  messages.WARNING : 'alert-warning',
  messages.ERROR   : 'alert-danger' ,
}

# --------------------------------------------------------------------
# Logging
# 
# LOGGING = {
#     'version': 1,
#     'disable_existing_loggers': False,
#     'handlers': {
#         'console': {
#             'level': 'DEBUG',
#             'class': 'logging.StreamHandler',
#         }
#     },
#     'loggers': {
#         'django.db.backends': {
#             'handlers': ['console'],
#             'level': 'DEBUG',
#         },
#     }
# }
