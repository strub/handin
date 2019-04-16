# --------------------------------------------------------------------
import uuid

from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import ugettext_lazy as _
from django.db.models.signals import post_delete
from django.dispatch import receiver

# --------------------------------------------------------------------
class Assignment(models.Model):
    class Meta:
        unique_together = (('code', 'subcode', 'promo'))
        ordering = (('code', 'subcode', 'promo'))

    code     = models.CharField(max_length = 128)
    subcode  = models.CharField(max_length = 128)
    promo    = models.IntegerField()
    contents = models.TextField()

    @property
    def key(self):
        return (self.code, self.subcode, self.promo)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('upload:assignment', args=self.key)

    def __str__(self):
        return '%s (%s) - %s' % (self.code, self.promo, self.subcode)

# --------------------------------------------------------------------
def resource_upload(instance, filename):
    the = instance.assignment
    return 'asgn/%s/%s/%d/%s' % (the.code, the.subcode, the.promo, filename)

# --------------------------------------------------------------------
class Resource(models.Model):
    uuid       = models.UUIDField(editable    = False,
                                  primary_key = True,
                                  default     = uuid.uuid4)
    assignment = models.ForeignKey(Assignment, on_delete = models.CASCADE)
    name       = models.CharField(max_length = 256)
    ctype      = models.CharField(max_length = 128)
    contents   = models.FileField(upload_to = resource_upload)

    def get_absolute_url(self):
        from django.urls import reverse
        key = self.assignment.key + (self.name,)
        return reverse('upload:resource', args=key)

    def __str__(self):
        return '%s (%s)' % (self.name, self.assignment)

# --------------------------------------------------------------------
class HandIn(models.Model):
    uuid       = models.UUIDField(editable    = False,
                                  primary_key = True,
                                  default     = uuid.uuid4)
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete = models.CASCADE)
    assignment = models.ForeignKey(Assignment, on_delete = models.CASCADE)
    index      = models.IntegerField()
    date       = models.DateTimeField(auto_now_add = True)
    status     = models.CharField(max_length = 16, blank = True)
    log        = models.TextField(blank = True)

# --------------------------------------------------------------------
def handin_upload(instance, filename):
    the = instance.handin.assignment
    return 'handins/%s/%s/%d/%s/%s' % \
               (the.code, the.subcode, the.promo,
                instance.handin.user.login, filename)

# --------------------------------------------------------------------
class HandInFile(models.Model):
    uuid       = models.UUIDField(editable    = False,
                                  primary_key = True,
                                  default     = uuid.uuid4)
    handin     = models.ForeignKey(HandIn, on_delete = models.CASCADE)
    name       = models.CharField(max_length = 256)
    contents   = models.FileField(upload_to = handin_upload)
