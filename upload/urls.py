# --------------------------------------------------------------------
from django.urls import include, path

from . import views

# --------------------------------------------------------------------
app_name = 'upload'

urlpatterns = [
    path('', views.assignments, name='assignments'),

    path('load/', views.load, name='load'),

    path('login/' , views.login , name='login' ),
    path('logout/', views.logout, name='logout'),

    path('groups/<code>/<int:promo>/', views.upload_groups),


    path('agns/<code>/<int:promo>/uploads/:download/',
        views.download_all_code_promo, name='download_all_code_promo'),

    path('agns/<code>/<subcode>/<int:promo>/', include([
        path('', views.Assignment.as_view(), name='assignment'),

        path('handins/<int:index>/', views.handin, name='handin'),

        path('uploads/', include([
            path(':by-uuid/<uuid:uuid>',
                     views.upload_details_by_uuid, name='upload_details'),

            path(':by-users/', include([
                path('',
                     views.uploads_by_users, name='uploads_by_users'),

                path('<login>/',
                     views.uploads_by_login, name='uploads_by_login'),

                path('<login>/<int:index>/', include([
                    path('',
                         views.upload_details_by_login_index, name='upload_details_by_login_index'),

                    path(':version/<int:version>/',
                         views.upload_details_by_login_index, name='upload_details_by_login_index'),
                ])),
            ])),

            path(':by-questions/',
                     views.uploads_by_questions, name='uploads_by_questions'),

            path(':by-submissions/',
                     views.uploads_by_submissions, name='uploads_by_submissions'),

            path(':activity/', include([
                path('',
                     views.uploads_activity, name='uploads_activity'),

                path(':data/',
                     views.uploads_activity_data, name='uploads_activity_data'),
            ])),

            path(':download/', include([
                path('',
                     views.download_all, name='download_all'),

                path(':question/<int:index>/',
                     views.download_index, name='download_index'),

                path('<login>/',
                     views.download_login, name='download_login'),

                path('<login>/<int:index>/',
                     views.download_login_index, name='download_login_index'),

                path('<uuid:uuid>',
                     views.download_uuid, name='download_uuid'),

                path('<uuid:uuid>/:data/',
                     views.download_uuid_data, name='download_uuid_data'),
            ])),

            path(':artifact/', include([
                path('<login>/<int:index>/',
                     views.artifact_login_index, name='artifact_login_index'),

                path('<uuid:uuid>',
                     views.artifact_uuid, name='artifact_uuid'),
            ])),

            path(':my/', include([
                path('',
                     views.myuploads, name='myuploads'),

                path('<int:index>/',
                     views.myupload_details, name='myupload'),

                path(':download/<int:index>/',
                     views.download_myupload, name='myupload-dw'),

                path(':artifacts/<int:index>/',
                     views.artifacts_myupload, name='myupload-art'),
            ])),

#            path(':stats/', include([
#                path('', views.stats, name='stats'),
#                path(':data/', views.stats_data, name='stats_data'),
#            ])),
        ])),

        path('grades/', include([
            path(':login/<login>/', include([
                path('', views.grade_view, name='grade_view'),

                path(':files/', views.grade_get_files, name='grade_get_files'),

                path(':comments/', views.grade_comments, name='grade_comments'),

                path(':comments/<uuid:uuid>/', views.grade_comments_edit, name='grade_comments_edit'),

                path(':start/', views.grade_start, name='grade_start'),

                path(':end/', views.grade_end, name='grade_end'),
            ])),
        ])),

        path('resources/<path:name>', views.resource, name='resource'),

        path(':status/', views.status, name='status'),
    ])),

    path('run-check/', include([
        path(':uuid/<uuid:uuid>/',
             views.recheck_uuid),

        path('<code>/<subcode>/<int:promo>/', include([
            path('',
                 views.recheck, name='check'),

            path(':by-users/<login>/',
                 views.recheck_user, name='check_user'),

            path(':by-users/<login>/<int:index>/',
                 views.recheck_user_index, name='check_user_index'),

            path(':by-questions/<int:index>/',
                 views.recheck_index, name='check_index'),
        ])),
    ])),

    path('agns/:clean/', views.clean),

    path(':autocomplete/:users/', views.autocomplete_users, name='ac_users'),
]
