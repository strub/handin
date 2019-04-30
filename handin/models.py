# --------------------------------------------------------------------
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import ugettext_lazy as _

# --------------------------------------------------------------------
class UserManager(BaseUserManager):
    use_in_migrations = True

# --------------------------------------------------------------------
class User(AbstractBaseUser, PermissionsMixin):
    login     = models.CharField(max_length = 256, primary_key = True)
    firstname = models.CharField(max_length = 256)
    lastname  = models.CharField(max_length = 256)
    email     = models.EmailField(max_length = 256, db_index = True)
    ou        = models.CharField(max_length = 256)
    cls       = models.CharField(max_length = 256, db_index = True)
    is_active = models.BooleanField(default = True)

    objects = UserManager()

    USERNAME_FIELD = 'login'
    REQUIRED_FIELDS = ['firstname', 'lastname', 'ou', 'cls']

    class Meta:
        verbose_name = _('user')
        verbose_name_plural = _('users')

    def has_usable_password(self):
        return False

    @property
    def fullname(self):
        return ' '.join([self.firstname, self.lastname]).strip()

    def get_full_name(self):
        return self.fullname

    def get_short_name(self):
        return self.fullname

    @property
    def is_staff(self):
        return self.cls == 'Personnel'

    @property
    def is_superuser(self):
        return self.is_staff
