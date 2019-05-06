# --------------------------------------------------------------------
import uuid, collections

from django.conf import settings
from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.contrib.auth.base_user import BaseUserManager
from django.utils.translation import ugettext_lazy as _
from django.db.models.signals import post_delete
from django.dispatch import receiver
from jsonfield import JSONField

# --------------------------------------------------------------------
class NatListField(models.TextField):
    description   = "Stores a list of non-negative integers"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def to_python(self, value):
        if not value:
            value = []
        if isinstance(value, list):
            return value
        return [int(x) for x in value.split()]

    def from_db_value(self, value, expression, connection, context):
        return self.to_python(value)

    def get_prep_value(self, value):
        if value is None:
            return value
        return ' '.join('%d' % (x,) for x in value)

    def value_to_string(self, obj):
        return self.get_db_prep_value(self._get_val_from_obj(obj))

# --------------------------------------------------------------------
class Assignment(models.Model):
    class Meta:
        unique_together = (('code', 'subcode', 'promo'))
        ordering = (('code', 'subcode', 'promo'))

    code       = models.CharField(max_length = 128)
    subcode    = models.CharField(max_length = 128)
    promo      = models.IntegerField()
    start      = models.DateField()
    contents   = models.TextField()
    tests      = NatListField()
    properties = JSONField(null = True,
        load_kwargs = \
            dict(object_pairs_hook = collections.OrderedDict))

    @property
    def key(self):
        return (self.code, self.subcode, self.promo)

    def get_absolute_url(self):
        from django.urls import reverse
        return reverse('upload:assignment', args=self.key)

    def required(self, index):
        if self.properties is None:
            return set()

        reqs, aout = self.properties.get('required', dict()), set()
        for req, indices in reqs.items():
            for index0 in indices:
                start = index0.get('start', None)
                end   = index0.get('end'  , None)
                if \
                   (start is not None and index < start) or \
                   (end   is not None and index > end  ) \
                : continue
                aout.add(req); break

        return aout

    def __str__(self):
        return '%s (%s) - %s' % (self.code, self.promo, self.subcode)

# --------------------------------------------------------------------
def resource_upload(instance, filename):
    the = instance.assignment
    return 'asgn/%s/%s/%s/%d/%s' % \
        (instance.namespace, the.code, the.subcode, the.promo, filename)

# --------------------------------------------------------------------
class Resource(models.Model):
    uuid       = models.UUIDField(editable    = False,
                                  primary_key = True,
                                  default     = uuid.uuid4)
    assignment = models.ForeignKey(Assignment, on_delete = models.CASCADE)
    name       = models.CharField(max_length = 256)
    ctype      = models.CharField(max_length = 128)
    contents   = models.FileField(upload_to = resource_upload)
    namespace  = models.CharField(max_length = 128)

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
