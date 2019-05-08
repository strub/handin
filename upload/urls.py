# --------------------------------------------------------------------
from django.urls import path

from . import views

# --------------------------------------------------------------------
app_name = 'upload'

urlpatterns = [
    path('', views.assignments, name='assignments'),

    path('load/', views.load, name='load'),

    path('login/' , views.login , name='login' ),
    path('logout/', views.logout, name='logout'),

    path('groups/<code>/<int:promo>/', views.upload_groups),

    path('agns/<code>/<subcode>/<int:promo>/',
             views.Assignment.as_view(), name='assignment'),

    path('agns/<code>/<subcode>/<int:promo>/handins/<int:index>/',
             views.handin, name='handin'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-uuid/<uuid:uuid>',
             views.upload_details_by_uuid, name='upload_details'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-users/',
             views.uploads_by_users, name='uploads_by_users'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-questions/',
             views.uploads_by_questions, name='uploads_by_questions'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-submissions/',
             views.uploads_by_submissions, name='uploads_by_submissions'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:by-users/<login>/<int:index>',
             views.upload_details_by_login, name='upload_details_by_login'),

    path('agns/<code>/<int:promo>/uploads/:download/',
             views.download_all_code_promo, name='download_all_code_promo'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:download/',
             views.download_all, name='download_all'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:download/:question/<int:index>/',
             views.download_index, name='download_index'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:download/<login>/',
             views.download_login, name='download_login'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:download/<login>/<int:index>/',
             views.download_login_index, name='download_login_index'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:download/<uuid:uuid>',
             views.download_uuid, name='download_uuid'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:my/',
             views.myuploads, name='myuploads'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:my/<int:index>/',
             views.myupload_details, name='myupload'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/:my/download/<int:index>/',
             views.download_myupload, name='myupload-dw'),

    path('agns/<code>/<subcode>/<int:promo>/resources/<path:name>',
             views.resource, name='resource'),

    path('run-check/:uuid/<uuid:uuid>/',
             views.recheck_uuid),

    path('run-check/<code>/<subcode>/<int:promo>/',
             views.recheck, name='check'),

    path('run-check/<code>/<subcode>/<int:promo>/<login>/',
             views.recheck_user, name='check_user'),

    path('run-check/<code>/<subcode>/<int:promo>/<login>/<int:index>/',
             views.recheck_user_index, name='check_user_index'),
]
