# --------------------------------------------------------------------
import os, uuid, collections, itertools as it, fnmatch, datetime as dt, json

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
    start      = models.DateField(null = True)
    end        = models.DateField(null = True)
    lateok     = models.BooleanField(default = False)
    contents   = models.TextField()
    tests      = NatListField()
    properties = JSONField(null = True,
        load_kwargs = \
            dict(object_pairs_hook = collections.OrderedDict))

    @property
    def key(self):
        return (self.code, self.subcode, self.promo)

    @property
    def endc(self):
        return \
              dt.datetime.combine(self.end, dt.time()) \
            - dt.timedelta(seconds = 1)

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

    def filemap(self, filename):
        if self.properties is None:
            return filename
        fmap = self.properties.get('map', [])
        for pattern, destination in fmap:
            if fnmatch.fnmatch(filename, pattern):
                return os.path.join(*(destination.split('/') + [filename]))
        return filename

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
    contents   = models.FileField(max_length = 1024, upload_to = resource_upload)
    namespace  = models.CharField(max_length = 128)

    def get_absolute_url(self):
        from django.urls import reverse
        key = self.assignment.key + (self.name,)
        return reverse('upload:resource', args=key)

    def __str__(self):
        return '%s (%s)' % (self.name, self.assignment)

# --------------------------------------------------------------------
def handin_artifact(instance, filename):
    the = instance.assignment
    return 'handins/%s/%s/%d/%s/%s-artifacts/%s' % \
               (the.code, the.subcode, the.promo,
                instance.user.login,
                instance.uuid, filename)

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
    xstatus    = JSONField(null = True)
    xinfos     = JSONField(null = True)
    log        = models.TextField(blank = True)
    artifact   = models.FileField(max_length = 1024, upload_to = handin_artifact, blank = True)

    def save(self, *args, **kwargs):
        self.xinfos = self.compute_xinfos()
        super().save(*args, **kwargs)

    @property
    def late(self):
        if self.assignment.end is None:
            return False
        return self.date.replace(tzinfo=None).date() >= self.assignment.end

    def compute_xinfos(self):
        if self.xstatus is None:
            return None

        aout = []
        for testv in self.xstatus:
            if testv['result'] is None:
                aout.append((testv['name'], 'skipped'))
            else:
                status = testv['result']['status']
                if status not in ('success', 'failure', 'timeout'):
                    status = 'failure'
                aout.append((testv['name'], status))
        return aout

    def failings(self):
        if self.xstatus is None:
            return []
        aout = []
        for testv in self.xstatus:
            if testv['result'] is None or testv['result']['status'] == 'success':
                continue
            aout.append(({ x: testv[x] for x in ('name', 'timeout') }, testv['result']))
        return aout

# --------------------------------------------------------------------
def handin_upload(instance, filename):
    the = instance.handin.assignment
    return 'handins/%s/%s/%d/%s/%s/%s' % \
               (the.code, the.subcode, the.promo,
                instance.handin.user.login,
                instance.uuid, filename)

# --------------------------------------------------------------------
class HandInFile(models.Model):
    uuid     = models.UUIDField(editable    = False,
                                primary_key = True,
                                default     = uuid.uuid4)
    handin   = models.ForeignKey(HandIn, on_delete = models.CASCADE, related_name = 'files')
    name     = models.CharField(max_length = 256)
    contents = models.FileField(max_length = 1024, upload_to = handin_upload)

    @property
    def display_name(self):
        return os.path.basename(self.contents.name)

# --------------------------------------------------------------------
class HandInGrade(models.Model):
    class Meta:
        unique_together = (('assignment', 'user'))

    uuid       = models.UUIDField(editable    = False,
                                  primary_key = True,
                                  default     = uuid.uuid4)
    date       = models.DateTimeField(auto_now_add = True)
    assignment = models.ForeignKey(Assignment, on_delete = models.CASCADE)
    user       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete = models.CASCADE)

# --------------------------------------------------------------------
class HandInGradeHandIn(models.Model):
    class Meta:
        unique_together = (('grade', 'index'))
        ordering = (('index',))

    uuid       = models.UUIDField(editable    = False,
                                  primary_key = True,
                                  default     = uuid.uuid4)
    grade      = models.ForeignKey(HandInGrade, on_delete = models.CASCADE, related_name='handins')
    index      = models.IntegerField()
    handin     = models.ForeignKey(HandIn, on_delete = models.CASCADE, null = True)

# --------------------------------------------------------------------
class HandInGradeComment(models.Model):
    uuid       = models.UUIDField(editable    = False,
                                  primary_key = True,
                                  default     = uuid.uuid4)
    grade      = models.ForeignKey(HandInGrade, on_delete = models.CASCADE)
    author     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete = models.CASCADE)
    timestamp  = models.DateTimeField()
    comment    = models.TextField()
    handinfile = models.ForeignKey(HandInFile, on_delete = models.CASCADE, null = True)
    handinloc  = models.IntegerField(null = True)
    finalized  = models.BooleanField(default = False)
