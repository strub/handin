# --------------------------------------------------------------------
from   django.conf import settings
from   django.contrib import admin
from   django.urls import include, path, re_path
import django.views.defaults, django.views.static

# --------------------------------------------------------------------
urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('upload.urls')),
    path(':impersonate/', include('impersonate.urls')),
]

if settings.DEBUG:
    import debug_toolbar
    urlpatterns = [
        path('__debug__/', include(debug_toolbar.urls)),
    ] + urlpatterns

if settings.DEBUG:
    urlpatterns += [
        re_path(r'^media/(?P<path>.*)$',
        django.views.static.serve, {
            'document_root': settings.MEDIA_ROOT,
        }),
    ]
