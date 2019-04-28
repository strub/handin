# --------------------------------------------------------------------
from django.urls import path

from . import views

# --------------------------------------------------------------------
app_name = 'upload'

urlpatterns = [
    path('', views.assignments, name='assignments'),
    path('login/', views.login, name='login'),
    path('logout/', views.logout, name='logout'),

    path('agns/<code>/<subcode>/<int:promo>/',
             views.Assignment.as_view(), name='assignment'),

    path('agns/<code>/<subcode>/<int:promo>/handins/<int:index>/',
             views.handin, name='handin'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/',
             views.uploads, name='uploads'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/my/',
             views.myuploads, name='myuploads'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/my/<int:index>/',
             views.myupload, name='myupload'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/my/check/<int:index>/',
             views.check, name='check'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/my/download/<int:index>/',
             views.download_myupload, name='myupload-dw'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/questions/<int:index>/<login>/',
             views.upload_by_user_index, name='upload_by_user_index'),

    path('agns/<code>/<subcode>/<int:promo>/uploads/questions/:all/',
             views.uploads_by_questions, name='uploads_by_questions'),

    path('agns/<code>/<subcode>/<int:promo>/resources/<path:name>',
             views.resource, name='resource'),
]
