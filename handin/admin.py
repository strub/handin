# --------------------------------------------------------------------
from   django.contrib import admin
from   django.contrib.auth.admin import UserAdmin
from   django.forms.models import BaseModelForm
import django.contrib.auth.models as dmodels

from .models import User

# --------------------------------------------------------------------
class CustomUserAdmin(UserAdmin):
    model                = User
    ordering             = ('login',)
    list_display         = ('login', 'firstname', 'lastname', 'cls', 'email')
    list_filter          = ()
    search_fields        = ('login', 'firstname', 'lastname', 'email')
    form                 = BaseModelForm
    add_form             = BaseModelForm
    change_password_form = BaseModelForm

    add_form_template             = None
    change_user_password_template = None

    def has_delete_permission(self, request, obj = None):
        return False

    def has_add_permission(self, request, obj = None):
        return False

    def has_change_permission(self, request, obj = None):
        return False

# --------------------------------------------------------------------
admin.site.register(User, CustomUserAdmin)
admin.site.unregister(dmodels.Group)
