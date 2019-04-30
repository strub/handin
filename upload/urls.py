# --------------------------------------------------------------------
from django.urls import path

from . import views

# --------------------------------------------------------------------
app_name = 'upload'

urlpatterns = [
    path('', views.assignments, name='assignments'),

    path('login/' , views.login , name='login' ),
    path('logout/', views.logout, name='logout'),

    path('groups/<code>/<int:promo>/', views.upload_groups),

    path('agns/<code>/<subcode>/<int:promo>/',
             views.Assignment.as_view(), name='assignment'),

    path('agns/<code>/<subcode>/<int:promo>/handins/<int:index>/',
             views.handin, name='handin'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-users/',
             views.uploads_by_users, name='uploads_by_users'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-questions/',
             views.uploads_by_questions, name='uploads_by_questions'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-users/<login>/<int:index>',
             views.upload_details_by_login, name='upload_details_by_login'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:download/<login>/<int:index>/',
             views.download_upload, name='download_upload'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:my/',
             views.myuploads, name='myuploads'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:my/<int:index>/',
             views.myupload_details, name='myupload'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:my/download/<int:index>/',
             views.download_myupload, name='myupload-dw'),

    path('agns/<code>/<subcode>/<int:promo>/resources/<path:name>',
             views.resource, name='resource'),

    path('run-check/',
             views.check, name='check'),
]
