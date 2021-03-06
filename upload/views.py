# --------------------------------------------------------------------
import sys, os, re, datetime as dt, tempfile, zipfile, tempfile, io
import json, shutil, uuid as muuid, docker, math
import multiprocessing as mp, psutil, parsedatetime as pdt, pytz
import itertools as it, humanfriendly as hf, bs4
from   collections import namedtuple, OrderedDict as odict

from   django.conf import settings
from   django.core.exceptions import PermissionDenied, ObjectDoesNotExist
import django.core.paginator as paginator
from   django.core.cache import cache
from   django.core.files.base import File, ContentFile
from   django.core.files.storage import default_storage
import django.forms as forms
import django.http as http
import django.views as views
import django.urls as durls
import django.utils.decorators as udecorators
from   django.views.decorators import http as dhttp
from   django.views.decorators import csrf as dcsrf
import django.db as db
from   django.db.models import Q, Max, FilteredRelation, Prefetch
from   django.contrib import messages
import django.contrib.auth as dauth
from   django.contrib.auth.decorators import login_required, permission_required
import django.shortcuts as dutils
import django.utils as utils, django.utils.timezone, django.utils.dateparse
import django.db as db

import background_task as bt
import background_task.models as btmodels

from . import models

from handin.middleware import eredirect
from handin.models import User

# --------------------------------------------------------------------
ACDIR = os.path.join(os.path.dirname(__file__), 'autocorrect')
ROOT  = os.path.dirname(__file__)

# --------------------------------------------------------------------
def _noexn(cb):
    try:
        cb()
    except:
        pass

# --------------------------------------------------------------------
def sort_groupby(iterable, key):
    return it.groupby(sorted(iterable, key=key), key=key)

# --------------------------------------------------------------------
def distinct_on(iterable, key):
    keys = set()
    for k, x in [(key(x), x) for x in iterable]:
        if k in keys: continue
        keys.add(k); yield x

# --------------------------------------------------------------------
def pandoc_gen(value, template):
    import pypandoc

    template = os.path.join(ROOT, 'pandoc', template + '.html')

    # '--filter', 'pandoc-codeblock-include',

    args = dict(
        to         = 'html5+smart+raw_tex',
        format     = 'markdown',
        extra_args = [
            '--shift-heading-level-by=2',
            '--mathjax=https://cdnjs.cloudflare.com/ajax/libs/mathjax/2.7.6/MathJax.js?config=TeX-AMS-MML_HTMLorMML',
            '--standalone', '--toc', '--toc-depth=4',
            '--template=%s' % (template,),
        ]
    )

    return pypandoc.convert_text(value, **args)

# --------------------------------------------------------------------
class UnseekableStream(io.RawIOBase):
    def __init__(self):
        self._buffer = b''

    def writable(self):
        return True

    def write(self, b):
        if self.closed:
            raise ValueError('stream is closed')
        self._buffer += b; return len(b)

    def get(self):
        chunk, self._buffer = self._buffer, b''
        return chunk

# --------------------------------------------------------------------
REFRESH  = 60
MAXFILES = 30
MAXSIZE  = 50 * 1024 * 1024
MINDELTA = 10
BOOL     = ('1', 'on')

# --------------------------------------------------------------------
REIDENT = r'^[a-zA-Z0-9]+$'
UPRE    = r'<\!--\s*UPLOAD:(\d+)(?::([a-zA-Z0-9-_.]+))?\s*-->'

RSCHEMA = dict(
    type  = 'array',
    items = dict(
        type = 'object',
        additionalProperties = False,
        properties = dict(
            name     = dict(type = 'string', pattern = r'^[^\\]+$'),
            contents = dict(type = 'string')
        ),
    )
)

SCHEMA = dict(
    type = 'object',
    additionalProperties = False,
    properties = dict(
        code        = dict(type = 'string', pattern = REIDENT, minLength = 1),
        subcode     = dict(type = 'string', pattern = REIDENT, minLength = 1),
        promo       = dict(type = 'number', minimum = 1794),
        start       = dict(type = ['string', 'null'], format = 'date'),
        end         = dict(type = ['string', 'null'], format = 'date'),
        lateok      = dict(type = ['boolean']),
        contents    = dict(type = ['string']),
        sign        = dict(type = ['boolean']),
        required    = dict(
            type = 'object',
            additionalProperties = dict(
                type  = 'array',
                items = dict(
                    type       = 'object',
                    properties = dict(
                        start = dict(type = 'number', minimum = 1),
                        end   = dict(type = 'number', minimum = 1),
                    ),
                ),
            ),
        ),
        map = dict(
            type  = 'array',
            items = dict(
                type       = 'object',
                properties = dict(
                    pattern     = dict(type = 'string'),
                    destination = dict(type = 'string'),
                ),
                required = ['pattern', 'destination'],
            ),
        ),
        merge = dict(
            type = 'object',
            additionalProperties = dict(type = 'array', items = dict(type = 'string'))
        ),
        resources = RSCHEMA,
        autocorrect = dict(
            type = 'object',
            additionalProperties = False,
            properties = dict(
                forno = dict(type = 'array', items = dict(type = 'number')),
                extra = RSCHEMA,
            ),
            required = ['forno', 'extra'],
        )
    ),
    required = ['code', 'subcode', 'promo', 'start', 'end',
                'lateok', 'contents', 'resources'],
)

GSCHEMA = dict(
  type  = 'array',
  items = dict(
    type  = 'object',
    additionalProperties = False,
    properties = dict(
        login  = dict(type = 'string', pattern = '^[a-zA-Z0-9-_.]+$'),
        group  = dict(type = 'string', pattern = '^[a-zA-Z0-9]+$'),
    ),
    required = ['login', 'group'],
  ),
)

USCHEMA = dict(
  type  = 'array',
  items = dict(
    type  = 'object',
    additionalProperties = False,
    properties = dict(
        login     = dict(type = 'string', pattern = '^[a-zA-Z0-9-_.]+$'),
        firstname = dict(type = 'string'),
        lastname  = dict(type = 'string'),
        email     = dict(type = 'string'),
    ),
    required = ['login', 'firstname', 'lastname', 'email'],
  ),
)

# --------------------------------------------------------------------
FORM = r'''
<div class="alert alert-primary pt-3">
<form class="form" style="width: 70%%%%;" method="post"
      enctype="multipart/form-data" action="handins/%%(index)d/">

  <div class="form-group">
    <div class="input-group input-file" name="file">
      <span class="input-group-btn">
        <button class="btn btn-choose btn-secondary" type="button">Choose</button>
      </span>
      <input type="text" class="form-control"
             placeholder='Choose one or more files...' readonly="readonly" />
      <span class="input-group-btn">
        <button class="btn btn-primary" type="submit">Submit</button>
      </span>
    </div>
    <div class="input-group">
      <div class="form-check">
        <input type="checkbox" class="form-check-input"
               name="files-reuse" value="1" checked="checked">
        <label class="form-check-label" for="files-reuse">
          Reuse files from previous submissions
          <span class="far fa-question-circle" data-toggle="tooltip"
                title="%s"></span>
        </label>
      </div>
    </div>
    %%(admin)s
  </div>
</form>
</div>
''' % (
  'Missing required files are taken from last submission of this question.',
)

FORM_ADMIN = r'''
    <div class="form-group pt-3">
      <label for="login">
        Submit on behalf of
      </label>
      <select class="form-control autoselect" name="login"
         placeholder="Type to search..." autocomplete="off"></select>
      </select>
    </div>
    <div class="form-group">
      <label for="datetime">
        Force date
      </label>
      <div class="input-group date dtpicker" id="datetimepicker-%(index)d" data-target-input="nearest">
        <input type="text" name="datetime" class="form-control datetimepicker-input" data-target="#datetimepicker-%(index)d" />
        <div class="input-group-append" data-target="#datetimepicker-%(index)d" data-toggle="datetimepicker">
          <div class="input-group-text"><i class="fa fa-calendar"></i></div>
        </div>
      </div>
    </div>
'''

F_REQUIRED     = '<div class="alert alert-light">Expected files: %s</div>'
NO_SUBMIT      = '<div class="alert alert-danger">Upload form is only available when connected</div>'
LATE_SUBMIT    = '<div class="alert alert-danger">Submissions are now closed</div>'
LATE_OK_SUBMIT = '<div class="alert alert-danger">Your submission will be flagged as late</div>'
LAST_SUBMIT    = '<div class="alert alert-info">Last submission: %s</div>'
F_MERGE        = r'''
<div class="alert alert-warning">
  You will have access to the files you submitted to %s. (You do not need
  to resubmit them or to copy their content in the submitted files).

  If you submit files that belong to these previous questions, they will
  be propagated up and the automated tests will be triggered.
</div>
'''

# --------------------------------------------------------------------
def questions_of_contents(contents):
    qst = re.findall(UPRE, contents)
    qst = [(int(x[0]), x[1]) for x in qst]
    qst = sorted(qst, key = lambda x : x[0])
    return odict(qst)

# --------------------------------------------------------------------
def can_access_assignment(user, the):
    if user.has_perm('upload', 'admin'):
        return True
    return the.start is None or the.start <= dt.datetime.now().date()

# --------------------------------------------------------------------
def get_assignment(request, code, subcode, promo):
    try:
        the = models.Assignment.objects.get(code=code, subcode=subcode, promo=promo)
    except models.Assignment.DoesNotExist:
        the = None
    if the is None: raise http.Http404
    if not can_access_assignment(request.user, the):
        if not request.user.is_authenticated:
            raise eredirect('%s?%s' % (
                dutils.reverse('upload:login'),
                utils.http.urlencode(dict(next = the.get_absolute_url()))
            ))
    return the

# --------------------------------------------------------------------
def _check_shared_secret_internal(request):
    secret = settings.PRE_SHARED_SECRET
    if secret is not None:
        if request.META.get('HTTP_X_SECRET', '') != secret:
            return False
    return True

# --------------------------------------------------------------------
def _check_shared_secret(request):
    if not _check_shared_secret_internal(request):
        raise PermissionDenied

# --------------------------------------------------------------------
def _build_nav(user, the, back = True):
    oth = models.Assignment.objects \
                .order_by('code', 'subcode', 'promo') \
                .defer('contents', 'properties') \
                .all()
    oth = [x for x in oth if can_access_assignment(user, x)]
    oth = { k: list(v) for k, v in sort_groupby(oth, lambda x : x.code) }
    return dict(oasgn = (the, oth), inasgn = the, back = back)

# --------------------------------------------------------------------
def _defer_check_internal(uuid):
    hdn = models.HandIn.objects \
                       .select_related('user', 'assignment') \
                       .defer('assignment__contents', 'log', 'xstatus') \
                       .get(pk = uuid)
    the = hdn.assignment
    qst = questions_of_contents(the.contents)

    hdn.artifact.name = ''
    hdn.status        = ''
    hdn.xstatus       = None
    hdn.save()

    if hdn.index not in qst or hdn.index not in the.tests:
        hdn.status = 'no-test'; hdn.save()
        return

    dhandins = distinct_on(
        models.HandIn.objects \
            .filter(user       = hdn.user,
                    assignment = the,
                    index__in  = the.merges().get(hdn.index, []),
                    date__lte  = hdn.date) \
            .order_by('-date').all(),
        lambda x : x.index
    )
    dhandins = list(reversed(list(dhandins)))
    tocopy   = []
    totest   = []

    for dhandin in dhandins:
        tocopy.extend(models.HandInFile.objects.filter(handin = dhandin).all()[:])
    totest = models.HandInFile.objects.filter(handin = hdn).all()[:]

    if not totest:
        hdn.status = 'failure'; hdn.save()
        return

    extra = models.Resource.objects \
                  .filter(namespace  = 'tests/extra',
                          assignment = the) \
                  .all()[:]

    try:
        log, xstatus = [], ''

        with tempfile.TemporaryDirectory() as srcdir:
            jaildir = os.path.realpath(srcdir)

            with tempfile.TemporaryDirectory() as tstdir, \
                 tempfile.TemporaryDirectory() as artdir, \
                 tempfile.TemporaryDirectory() as outdir:

                log += ['copying files...']
    
                for filename in totest:
                    outname = os.path.join(srcdir, the.filemap(filename.name))
                    
                    if os.path.commonprefix \
                       ([jaildir, os.path.realpath(os.path.dirname(outname))]) != jaildir:

                        raise ValueError('insecure file-map')

                    os.makedirs(os.path.dirname(outname), exist_ok = True)
                    shutil.copy(filename.contents.path, outname)

                for filename in tocopy:
                    outname = os.path.join(srcdir, 'merge', filename.name)
                    os.makedirs(os.path.dirname(outname), exist_ok = True)
                    if not os.path.exists(outname):
                        shutil.copy(filename.contents.path, outname)

                for filename in extra:
                    shutil.copy(filename.contents.path,
                                os.path.join(tstdir, filename.name))
    
                log += ['...done']
    
                dclient = docker.from_env()
    
                container = dict(
                    detach           = True ,
                    stream           = False,
                    auto_remove      = False,
                    stdout           = True ,
                    stderr           = True ,
                    network_disabled = True ,
                    mem_limit        = 512 * 1024 * 1024,
                    log_config       = docker.types.LogConfig(
                        type=docker.types.LogConfig.types.JSON, config = {
                            'max-size': '10m',
                        }
                    ),
                    volumes = {
                        os.path.realpath(srcdir): \
                            dict(bind = '/opt/handin/user/src', mode = 'rw'),
                        os.path.realpath(tstdir): \
                            dict(bind = '/opt/handin/user/test', mode = 'rw'),
                        os.path.realpath(artdir): \
                            dict(bind = '/opt/handin/user/artifacts', mode = 'rw'),
                        os.path.realpath(outdir): \
                            dict(bind = '/opt/handin/user/output', mode = 'rw'),
                        os.path.join(ACDIR, 'scripts'): \
                            dict(bind = '/opt/handin/user/scripts', mode = 'ro'),
                    }
                )
    
                command = [
                    'timeout', '--preserve-status', '--signal=KILL', '240',
                    '/opt/handin/bin/python3',
                    '/opt/handin/user/scripts/achecker-%s-%d.py' % (hdn.assignment.code, hdn.assignment.promo),
                    '/opt/handin/user', str(hdn.assignment.subcode), str(hdn.index)
                ]
    
                log += ['running docker...']
    
                container = dclient.containers.run \
                    ('handin:%s-%d' % (hdn.assignment.code, hdn.assignment.promo), command, **container)
    
                try:
                    for i, line in enumerate(container.logs(stream = True)):
                        if i < 1000:
                            line = line.rstrip(b'\r\n')
                            line = line.decode('utf-8', errors = 'surrogateescape')
                            log += [line]
        
                    status = container.wait()
        
                    if 'Error' in status and status['Error'] is not None:
                        status = 'errored'
                    else:
                        if status['StatusCode'] == (128 + 9):
                            log += ['...timeout']
                        status = 'success' if status['StatusCode'] == 0 else 'failure'
        
                    log += ['...docker ended (%s)' % (status,)]
    
                finally:
                    try:
                        container.remove(v = True, force = True)
                    except docker.errors.APIError:
                        pass

                if os.listdir(artdir):
                    with tempfile.NamedTemporaryFile() as tmpzip:
                        with zipfile.ZipFile(tmpzip.name, 'w', zipfile.ZIP_DEFLATED) as zf:
                            for root, _, filenames in os.walk(artdir):
                                for name in filenames:
                                    name = os.path.join(root, name)
                                    arcn = os.path.relpath(name, artdir)
                                    zf.write(name, arcn)

                        with open(tmpzip.name, 'rb') as zf:
                            hdn.artifact.save('artifacts.zip', File(zf))

                outfile = os.path.join(outdir, 'result.json')
                if os.path.isfile(outfile):
                    # FIXME: check for file size first
                    with open(outfile, 'r') as resultjson:
                        xstatus = json.loads(resultjson.read())

    except Exception as e:
        import traceback
        log     += [traceback.format_exc()]
        status   = 'errored'
        xstatus  = ''

    hdn.log     = ('\n'.join(log) + '\n').replace('\x00', '\\x00')
    hdn.status  = status
    hdn.xstatus = xstatus
    hdn.save()

# --------------------------------------------------------------------
@bt.background(queue = 'check')
def _defer_check_wrapper(uuid):
    try:
        print('CHECK: %s' % (uuid,), file=sys.stderr)
        _defer_check_internal(muuid.UUID(uuid))
        print('DONE: %s' % (uuid,), file=sys.stderr)
    except Exception as e:
        print(e, file=sys.stderr)
        raise

# --------------------------------------------------------------------
def _defer_check(handin, update = True, priority = 0):
    with db.transaction.atomic():
        _defer_check_wrapper(str(handin.uuid), priority = priority)
        if update:
            handin.log, handin.status, handin.xstatus = '', '', None
            handin.save()

# --------------------------------------------------------------------
def _defer_recheck(handin, update = True):
    return _defer_check(handin, update = update, priority = -5)

# --------------------------------------------------------------------
def load(request):
    def _f(x):
        return '%.2f' % (x,)
    ncores      = mp.cpu_count()
    count       = btmodels.Task.objects.count()
    p1, p5, p15 = psutil.getloadavg()
    p1, p5, p15 = p1 / ncores, p5 / ncores, p15 / ncores
    return http.JsonResponse(
        dict(p1 = _f(p1), p5 = _f(p5), p15 = _f(p15), count = count))

# --------------------------------------------------------------------
@dhttp.require_GET
def status(request, code, subcode, promo):
    KEYS = {
        'success' : 'ok',
        'no-test' : 'ok',
        'failure' : 'ko',
        ''        : 'mb',
    }

    the     = get_assignment(request, code, subcode, promo)
    data    = dict(ok = [], ko = [], mb = [])
    uploads = set()

    if request.user.is_authenticated:
        for hdn in models.HandIn.objects \
                    .filter(assignment = the, user = request.user) \
                    .values('index', 'status', 'date') \
                    .order_by('-date') \
                    .all():

            if hdn['index'] in uploads:
                continue
            uploads.add(hdn['index'])
            data[KEYS.get(hdn['status'], 'ko')].append(hdn['index'])

    for v in data.values():
        v.sort()

    return http.JsonResponse(data)

# --------------------------------------------------------------------
@dhttp.require_http_methods(['GET', 'POST'])
def login(request):
    if request.user.is_authenticated:
        return dutils.redirect('upload:assignments')
    if request.method == 'GET':
        return dutils.render(request, 'login.html')
    username = request.POST.get('username', None)
    password = request.POST.get('password', None)
    user     = None

    if username is not None and password is not None:
        user = dauth.authenticate(username = username, password = password)
    if user is not None and user.is_active:
        dauth.login(request, user)
        next = request.POST.get('next', None)
        if next is None:
            next = request.GET.get('next', durls.reverse('upload:assignments'))
        return http.HttpResponseRedirect(next)
    return http.HttpResponseRedirect(durls.reverse('upload:login'))

# --------------------------------------------------------------------
def logout(request):
    dauth.logout(request)
    next = request.GET.get('next', durls.reverse('upload:assignments'))
    return http.HttpResponseRedirect(next)

# --------------------------------------------------------------------
@dhttp.require_http_methods(['PUT'])
@dcsrf.csrf_exempt
def upload_users(request):
    _check_shared_secret(request)

    import json, jsonschema, mimeparse as mp, base64, binascii

    mtype, msub, mdata = mp.parse_mime_type(request.content_type)

    if (mtype, msub) != ('application', 'json'):
        return http.HttpResponseBadRequest()

    charset = mdata.get('charset', 'utf-8')

    try:
        body = request.body.decode(charset)
        jso  = json.loads(body)

        jsonschema.validate(jso, USCHEMA)

    except (json.decoder.JSONDecodeError,
            jsonschema.exceptions.ValidationError,
            UnicodeDecodeError) as e:
        return http.HttpResponseBadRequest()

    with db.transaction.atomic():
        for user in jso:
            user, _ = dauth.get_user_model().objects.get_or_create(
                login    = user['login'],
                defaults = dict(
                    firstname = user['firstname'],
                    lastname  = user['lastname'],
                    email     = user['email'],
                    ou        = 'cn=imported',
                    cls       = 'Etudiants',
                ),
            )

    return http.HttpResponse("OK\r\n", content_type = 'text/plain')

# --------------------------------------------------------------------
@dhttp.require_http_methods(['PUT'])
@dcsrf.csrf_exempt
def upload_groups(request, code, promo):
    _check_shared_secret(request)

    import json, jsonschema, mimeparse as mp, base64, binascii

    mtype, msub, mdata = mp.parse_mime_type(request.content_type)

    if (mtype, msub) != ('application', 'json'):
        return http.HttpResponseBadRequest()

    charset = mdata.get('charset', 'utf-8')

    try:
        body = request.body.decode(charset)
        jso  = json.loads(body)

        jsonschema.validate(jso, GSCHEMA)

    except (json.decoder.JSONDecodeError,
            jsonschema.exceptions.ValidationError,
            UnicodeDecodeError) as e:
        return http.HttpResponseBadRequest()

    gname  = '%s:%d' % (code, promo)
    groups = set([x['group'] for x in jso])

    with db.transaction.atomic():
        dauth.models.Group.objects \
            .filter(name__startswith = gname + ':') \
            .delete()

        groups = {
            x: dauth.models.Group.objects.get_or_create(
                   name = '%s:%s' % (gname, x)
               )[0] for x in groups
        }

        for g1 in jso:
            try:
                user = dauth.get_user_model().objects.get(login = g1['login'])
            except ObjectDoesNotExist:
                continue
            user.groups.add(groups[g1['group']]); user.save()

    return http.HttpResponse("OK\r\n", content_type = 'text/plain')

# --------------------------------------------------------------------
@dhttp.require_GET
def assignments(request):
    assgns   = models.Assignment.objects \
                     .order_by('code', 'promo', 'subcode') \
                     .defer('contents') \
                     .all()
    assgns   = [x for x in assgns if can_access_assignment(request.user, x)]
    assgns   = sort_groupby(assgns, lambda x : (x.code, x.promo))
    assgns   = { k: list(v) for k, v in assgns }
    context  = dict(assignments = assgns)

    return dutils.render(request, 'assignments.html', context)

# --------------------------------------------------------------------
SQL_GROUPS = r"""
select u.login as login, g.name as gname
  from       handin_user as u
  inner join handin_user_groups as ug
             on u.login = ug.user_id
  inner join auth_group as g
             on g.id = ug.group_id
  where g.name like %s"""

SQL_HANDINS = r"""
select u.login as login,
       (u.firstname || ' ' || u.lastname) as fullname,
       h."index" as idx,
       h.status as status, h.xinfos as xinfos, h.date as date
  from       upload_handin as h
  inner join handin_user as u
             on h.user_id = u.login
  where h.assignment_id = %s
    and u.cls = 'Etudiants'

  order by date desc
"""

@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads_by_users(request, code, subcode, promo):
    the   = get_assignment(request, code, subcode, promo)
    qst   = questions_of_contents(the.contents)
    gname = '%s:%d' % (code, promo)

    with db.connection.cursor() as cursor:
        cursor.execute(SQL_HANDINS, [the.pk])
        nt  = namedtuple('Handin', [c[0] for c in cursor.description] + ['late'])
        hdn = [nt(*x + (False,)) for x in cursor.fetchall()]
        for i, x in enumerate(hdn):
            if x.xinfos is not None:
                hdn[i] = x._replace(xinfos = json.loads(x.xinfos))

        cursor.execute(SQL_GROUPS, [gname + ':%'])
        nt  = namedtuple('Group', [c[0] for c in cursor.description])
        grp = [nt(*x) for x in cursor.fetchall()]

    grades = models.HandInGrade.objects \
                               .filter(assignment = the) \
                               .select_related('user') \
                               .all()
    grades = { x.user.login: x for x in grades }

    groups  = dict()
    users   = dict()
    uploads = dict()

    for entry in grp:
        groups.setdefault(entry.login, set()) \
              .add(entry.gname[len(gname)+1:])
    groups = { k: min(v) for k, v in groups.items() }

    for x in hdn:
        if the.end is not None and x.date.replace(tzinfo=None).date() >= the.end:
            x = x._replace(late = True)

        if x.login not in users:
            ugrade = grades.get(x.login, None)
            ugrade = 'none' if ugrade is None else ('done' if ugrade.finalized else 'started')
            users[x.login] = (x.login, x.fullname, ugrade)

        ugroup = groups.get(x.login, None)
        gdict  = uploads.setdefault(ugroup, dict())

        if x.login not in gdict:
            gdict[x.login] = dict()
        gdict[x.login].setdefault(x.idx, []).append(x)

    context = dict(
        the    = the, qst = qst, uploads = uploads, users = users, grades = grades,
        groups = sorted(uploads.keys(), key = \
                            lambda x : '' if x is None else x),
        nav    = _build_nav(request.user, the))

    return dutils.render(request, 'uploads_by_users.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads_by_questions(request, code, subcode, promo):
    the = get_assignment(request, code, subcode, promo)
    qst = questions_of_contents(the.contents)

    lst = models.HandIn.objects \
        .select_related('user') \
        .filter(assignment = the, user__cls = 'Etudiants') \
        .order_by('-date') \
        .defer('log', 'xstatus', 'artifact') \
        .all()

    users   = set()
    uploads = dict()
    stats   = { k: dict(ok = 0, ko = 0, mb = 0, er = 0) for k in qst }

    KEYS = {
        'success' : 'ok',
        'no-test' : 'ok',
        'failure' : 'ko',
        ''        : 'mb',
    }

    for hdn in lst:
        if hdn.index not in qst:
            continue
        users.add(hdn.user.login)
        forno = uploads.setdefault(hdn.index, set())
        if hdn.user.login in forno:
            continue
        forno.add(hdn.user.login)
        stats[hdn.index][KEYS.get(hdn.status, 'er')] += 1

    context = dict(
        the = the, qst = qst, users = len(users), stats = stats,
        nav = _build_nav(request.user, the))

    return dutils.render(request, 'uploads_by_questions.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads_by_submissions(request, code, subcode, promo):
    the     = get_assignment(request, code, subcode, promo)
    qst     = questions_of_contents(the.contents)
    uploads = models.HandIn.objects \
                           .select_related('user', 'assignment') \
                           .filter(assignment = the) \
                           .order_by('-date') \
                           .defer('log', 'artifact', 'xstatus') \
                           .all()
    uploads = paginator.Paginator(uploads, 100).get_page(request.GET.get('page'))

    context = dict(
        the = the, qst = qst, uploads = uploads,
        nav = _build_nav(request.user, the))
    # context['refresh'] = REFRESH

    return dutils.render(request, 'uploads_by_submissions.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads_activity(request, code, subcode, promo):
    the     = get_assignment(request, code, subcode, promo)
    context = dict(the = the, nav = _build_nav(request.user, the))

    return dutils.render(request, 'uploads_activity.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads_activity_data(request, code, subcode, promo):
    the     = get_assignment(request, code, subcode, promo)
    context = dict(the = the, nav = _build_nav(request.user, the))
    handins = models.HandIn.objects \
                           .filter(assignment = the) \
                           .order_by('-date') \
                           .values('date') \
                           .all()[:2000]
    handins = [x['date'].date() for x in handins]

    return http.JsonResponse(dict(dates = list(handins)))

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads_by_login(request, code, subcode, promo, login):
    the  = get_assignment(request, code, subcode, promo)
    user = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    qst  = questions_of_contents(the.contents)
    rqs  = dict()

    for rq in models.HandIn.objects \
                    .filter(user = user, assignment = the) \
                    .all():

        rqs.setdefault(rq.index, []).append(rq)

    rqs = { k: max(v, key = lambda x : x.date) \
                for k, v in rqs.items() }

    for q in qst: rqs.setdefault(q, None)

    ctx = dict(the = the, rqs = rqs, qst = qst, user = user,
               nav = _build_nav(request.user, the))

    return dutils.render(request, 'uploads_by_login.html', ctx)

# --------------------------------------------------------------------
@login_required
@dhttp.require_GET
def myuploads(request, code, subcode, promo):
    the = get_assignment(request, code, subcode, promo)
    qst = questions_of_contents(the.contents)
    rqs = dict()

    for rq in models.HandIn.objects \
                    .filter(user = request.user, assignment = the) \
                    .all():

        rqs.setdefault(rq.index, []).append(rq)

    rqs = { k: max(v, key = lambda x : x.date) \
                for k, v in rqs.items() }

    for q in qst: rqs.setdefault(q, None)

    grade = models.HandInGrade.objects \
                  .filter(assignment = the, user = request.user) \
                  .prefetch_related('comments', 'handins', 'handins__handin', 'handins__handin__files') \
                  .first()

    if grade is not None:
        if not grade.finalized:
            grade = None

    ctx = dict(the = the, rqs = rqs, qst = qst, grade = grade,
               nav = _build_nav(request.user, the))
    # ctx['refresh'] = REFRESH

    return dutils.render(request, 'myuploads.html', ctx)

# --------------------------------------------------------------------
def _upload_details(request, code, subcode, promo, flt, view, must, offset = None):
    the = get_assignment(request, code, subcode, promo)
    dat = None
    hdn = models.HandIn.objects \
                       .select_related('user') \
                       .filter(assignment = the) \
                       .filter(flt) \
                       .order_by('-date')

    if offset is None:
        hdn = hdn.first()
    else:
        try:
            hdn = hdn[len(hdn) - offset]
        except IndexError:
            hdn = None

    if hdn is None:
        if must or offset is not None:
            raise http.Http404('no handin')
    else:
        cnt = list(models.HandIn.objects \
                    .filter(assignment = the, user = hdn.user, index = hdn.index) \
                    .order_by('-date') \
                    .values('uuid', 'date') \
                    .all())
        cnt = sorted(cnt, key = lambda x : x['date'])
        cnt = ({ x['uuid']: i for i, x in enumerate(cnt) }[hdn.uuid] + 1, len(cnt))
        fls = []

        if hdn.artifact.name:
            fls = zipfile.ZipFile(hdn.artifact.path).namelist()
            fls = [x for x in fls if os.path.splitext(x)[1].lower() == '.jpg']
            fls = sorted(fls)

        dat = dict(hdn = hdn, cnt = cnt, fls = fls, asgn = the)

    context = dict(the = the, data = dat, nav = _build_nav(request.user, the))
    # context['refresh'] = REFRESH

    return dutils.render(request, view, context)

# --------------------------------------------------------------------
@login_required
@dhttp.require_GET
def myupload_details(request, code, subcode, promo, index):
    view = 'myupload_details.html'
    flt  = Q(user = request.user, index = index)
    return _upload_details(request, code, subcode, promo, flt, view, False)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def upload_details_by_uuid(request, code, subcode, promo, uuid):
    view = 'upload_details.html'
    flt  = Q(uuid = uuid)
    return _upload_details(request, code, subcode, promo, flt, view, True)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def upload_details_by_login_index(request, code, subcode, promo, login, index, version = None):
    user = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    view = 'upload_details_by_login_index.html'
    flt  = Q(user = user, index = index)
    return _upload_details(request, code, subcode, promo, flt, view, False, version)

# --------------------------------------------------------------------
def _download_handin(handin, resources, inline = True):
    if len(resources) == 0:
        raise http.Http404('no resources')

    if len(resources) == 1:
        with resources[0].contents.open() as stream:
            import magic

            ctype = magic.Magic(mime = True).from_buffer(stream.read(2048))
            ctype = ctype if ctype else 'text/plain'

        response = http.FileResponse(
            resources[0].contents.open(), content_type = ctype)
        response['Content-Disposition'] = \
            '%s; filename="%s"' % ('inline' if inline else 'attachment',
                                   resources[0].name)
        return response

    tmp = tempfile.NamedTemporaryFile(delete = False)
    try:
        with open(tmp.name, 'wb') as stream:
            with zipfile.ZipFile(stream, 'w') as zipf:
                for resource in resources:
                    with resource.contents.open() as istream:
                        zipf.writestr(resource.name, istream.read())
        response = http.FileResponse(
            open(tmp.name, 'rb'), content_type = 'application/zip')
        fname = '%s-%s-%s-%d-%d.zip' % (handin.user.login,
                                        handin.assignment.code,
                                        handin.assignment.subcode,
                                        handin.assignment.promo,
                                        handin.index)
        fname = ''.join([x for x in fname if x.isalnum() or x in '-.'])
        response['Content-Disposition'] = 'attachment; filename="%s"' % (fname,)
        return response

    finally:
        os.remove(tmp.name)

# --------------------------------------------------------------------
def _stream_handins(fname, pattern, handins):
    def generator():
        stream = UnseekableStream()

        with zipfile.ZipFile(stream, mode='x') as zf:
            def create_dirs(path, seen):
                if '/' in path:
                    create_dirs(path.rsplit('/', 1)[0], seen)
                if path not in seen:
                    zinfo = zipfile.ZipInfo('%s/' % (path,))
                    zinfo.external_attr = 0o755 << 16
                    with zf.open(zinfo, mode='w'):
                        seen.add(path)

            seen = set()

            for handin in handins:
                resources = models.HandInFile.objects \
                               .filter(handin = handin) \
                               .all()
                for resource in resources:
                    data     = dict(login   = handin.user,
                                    code    = handin.assignment.code,
                                    subcode = handin.assignment.subcode,
                                    promo   = handin.assignment.promo,
                                    index   = handin.index)
                    dirname  = '%s/%s' % (fname, pattern % data)

                    if handin.late:
                        dirname = '%s/LATE' % (dirname,)

                    filename = '%s/%s' % (dirname, resource.name)

                    create_dirs(dirname, seen)
                    zinfo = zipfile.ZipInfo.from_file(
                        resource.contents.path, filename)
                    zinfo.external_attr = 0o644 << 16
                    with open(resource.contents.path, 'rb') as entry, \
                         zf.open(zinfo, mode='w') as output:
                        for chunk in iter(lambda : entry.read(16384), b''):
                            output.write(chunk); yield stream.get()
        yield stream.get()

    response = http.StreamingHttpResponse(
        generator(), content_type = 'application/zip')
    response['Content-Disposition'] = 'attachment; filename=%s.zip' % (fname,)

    return response

# --------------------------------------------------------------------
def _fetch_artifact(request, code, subcode, promo, flt):
    the = get_assignment(request, code, subcode, promo)

    handin = models.HandIn.objects \
        .select_related('user', 'assignment') \
        .filter(assignment = the) \
        .filter(flt) \
        .defer('log', 'xstatus', 'artifact', 'assignment__contents',
               'assignment__properties', 'assignment__tests') \
        .order_by('-date', 'user__login', 'index') \
        .first()

    if handin is None:
        raise http.Http404('no handin')
    if not handin.artifact.name:
        raise http.Http404('no artifact for handin')

    response = http.FileResponse(
        handin.artifact.open(), content_type = 'application/zip')
    response['Content-Disposition'] = \
        'attachment; filename="artifacts.zip"'

    return response

# --------------------------------------------------------------------
@login_required
@dhttp.require_GET
def download_myupload(request, code, subcode, promo, index):
    the = get_assignment(request, code, subcode, promo)

    hdn = models.HandIn.objects \
                .filter(user = request.user, assignment = the, index = index) \
                .order_by('-date').first()

    if hdn is None:
        raise http.Http404('no uploads')

    resources = models.HandInFile.objects.filter(handin = hdn).all()

    return _download_handin(hdn, resources, inline = False)

# --------------------------------------------------------------------
@login_required
@dhttp.require_GET
def artifacts_myupload(request, code, subcode, promo, index):
    flt  = Q(user = request.user, index = index)
    args = [request, code, subcode, promo, flt]
    return _fetch_artifact(*args)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_uuid(request, code, subcode, promo, uuid):
    the = get_assignment(request, code, subcode, promo)
    qst = questions_of_contents(the.contents)
    hdn = models.HandIn.objects \
                .filter(assignment = the, uuid = uuid) \
                .first()

    if hdn is None:
        raise http.Http404('unknown handin UUID for assignment')

    resources = models.HandInFile.objects.filter(handin = hdn).all()

    return _download_handin(hdn, resources, inline = False)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def artifact_uuid(request, code, subcode, promo, uuid):
    flt  = Q(uuid = uuid)
    args = [request, code, subcode, promo, flt]
    return _fetch_artifact(*args)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_uuid_data(request, code, subcode, promo, uuid):
    import base64

    the = get_assignment(request, code, subcode, promo)
    qst = questions_of_contents(the.contents)
    hdn = models.HandIn.objects \
                .filter(assignment = the, uuid = uuid) \
                .first()

    if hdn is None:
        raise http.Http404('unknown handin UUID for assignment')

    resources = models.HandInFile.objects.filter(handin = hdn).all()
    json      = []

    for resource in resources:
        with resource.contents.open('rb') as stream:
            contents = base64.b64encode(stream.read()).decode('ascii');
            json.append(dict(name = resource.name, contents = contents))

    return http.JsonResponse(dict(resources = json))

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_all(request, code, subcode, promo):
    the = get_assignment(request, code, subcode, promo)
    handins = models.HandIn.objects \
        .select_related('user', 'assignment') \
        .filter(assignment = the) \
        .defer('log', 'artifact', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
        .order_by('-date', 'user__login', 'index') \
        .all()
    handins = distinct_on(handins, lambda x : (x.user.login, x.index))
    pattern = '%(login)s/%(index)d'
    fname   = '%s-%s-%d' % (code, subcode, promo)

    return _stream_handins(fname, pattern, handins)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_all_code_promo(request, code, promo):
    handins = models.HandIn.objects \
        .select_related('user', 'assignment') \
        .filter(assignment__code = code, assignment__promo = promo) \
        .defer('log', 'xstatus', 'artifact', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
        .order_by('assignment__subcode', '-date', 'user__login', 'index') \
        .all()
    handins = list(distinct_on(handins, lambda x : (x.user.login, x.index)))
    pattern = '%(subcode)s/%(login)s/%(index)d'
    fname   = '%s-%d' % (code, promo)

    return _stream_handins(fname, pattern, handins)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_login(request, code, subcode, promo, login):
    the = get_assignment(request, code, subcode, promo)
    handins = models.HandIn.objects \
        .select_related('user', 'assignment') \
        .filter(assignment = the, user__login = login) \
        .defer('log', 'xstatus', 'artifact', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
        .order_by('-date', 'user__login', 'index') \
        .all()
    handins = distinct_on(handins, lambda x : (x.user.login, x.index))
    pattern = '%(login)s/%(index)d'
    fname   = '%s-%s-%d-%s' % (code, subcode, promo, login)

    return _stream_handins(fname, pattern, handins)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_index(request, code, subcode, promo, index):
    the = get_assignment(request, code, subcode, promo)
    handins = models.HandIn.objects \
        .select_related('user', 'assignment') \
        .filter(assignment = the, index = index) \
        .defer('log', 'xstatus', 'artifact', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
        .order_by('-date', 'user__login', 'index') \
        .all()
    handins = distinct_on(handins, lambda x : (x.user.login, x.index))
    pattern = '%(login)s/%(index)d'
    fname   = '%s-%s-%d-q%d' % (code, subcode, promo, index)

    return _stream_handins(fname, pattern, handins)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_login_index(request, code, subcode, promo, login, index):
    the = get_assignment(request, code, subcode, promo)

    handin = models.HandIn.objects \
        .select_related('user', 'assignment') \
        .filter(assignment = the, index = index, user__login = login) \
        .defer('log', 'xstatus', 'artifact', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
        .order_by('-date', 'user__login', 'index') \
        .first()

    if handin is None:
        raise http.Http404('no uploads')

    resources = models.HandInFile.objects.filter(handin = handin).all()

    return _download_handin(handin, resources, inline = True)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def artifact_login_index(request, code, subcode, promo, login, index):
    flt  = Q(user__login = login, index = index)
    args = [request, code, subcode, promo, flt]
    return _fetch_artifact(*args)

# --------------------------------------------------------------------
@login_required                 # FIXME
@dhttp.require_POST
@udecorators.method_decorator(dcsrf.csrf_exempt) # FIXME
def handin(request, code, subcode, promo, index):
    the   = get_assignment(request, code, subcode, promo)
    files = request.FILES.getlist('file', [])
    reqs  = the.required(index)
    url   = dutils.reverse \
                ('upload:assignment', args=(code, subcode, promo))
    url   = url + '#submit-%d' % (index,)

    login = request.POST.get('login', '').strip()
    fdate = request.POST.get('datetime', '').strip()

    if login:
        if not request.user.has_perm('upload.admin'):
            return http.HttpResponseForbidden()
        user = User.objects.get(pk = login)
        if user is None:
            messages.error(request, 'Cannot find: ' + login)
            return dutils.redirect(url)
    else:
        user = request.user

    if fdate:
        if not request.user.has_perm('upload.admin'):
            return http.HttpResponseForbidden()
        try:
            subdate, _ = pdt.Calendar().parseDT(fdate)
        except ValueError:
            messages.error(request, 'Invalid date-time: ' + fdate)
            return dutils.redirect(url)
        subdate = subdate.astimezone(utils.timezone.get_current_timezone())
        subdate = subdate.astimezone(pytz.timezone('UTC'))
    else:
        subdate = utils.timezone.now()

    if the.end is not None and not the.lateok:
        if subdate.date() >= the.end:
            messages.error(request,
                'The assignment has been closed')
            return dutils.redirect(url)

    if not files:
        messages.error(request,
            'You must submit at least one file')
        return dutils.redirect(url)

    if len(files) > MAXFILES:
        messages.error(request,
            'You cannot upload more than %d files' % (MAXFILES,))
        return dutils.redirect(url)

    for ufile in files:
        if ufile.size > MAXSIZE:
            messages.error(request, "`%s' is more than %s" % \
                (ufile.name, hf.format_size(MAXSIZE, binary=True)))
            return dutils.redirect(url)

    diffd = None
    lastd = models.HandIn.objects \
                         .filter(user = user) \
                         .values('date') \
                         .order_by('-date') \
                         .first()

#    if lastd is not None:
#        diffd = subdate - lastd['date']
#
#    if diffd is not None and diffd.total_seconds() - MINDELTA < -1.0:
#        messages.error(request,
#            'You are submitting files too fast (wait %d second(s))' % \
#                (MINDELTA - diffd.total_seconds()))
#        return dutils.redirect(url)

    reuse  = request.POST.get('files-reuse', '').lower() in BOOL
    submit = {}

    submit[index] = dict(files = { x.name: x for x in files })
    del files                   # avoid using this one later

    merge = list(reversed(sorted(the.merges().get(index, []))))

    for merge1 in merge:
        if merge1 >= index:
            continue
        for mreq in the.required(merge1):
            if mreq not in submit[index]['files']:
                continue
            if merge1 not in submit:
                submit[merge1] = dict(files = {})
            submit[merge1]['files'][mreq] = submit[index]['files'][mreq]
            del submit[index]['files'][mreq]

    for merge1, submit1 in submit.items():
        submit1['missing'] = \
            the.required(merge1).difference(submit1['files'].keys())
        submit1['rlist'] = []

        if not submit1['missing'] or not reuse:
            continue

        reusehd = models.HandIn.objects \
            .filter(assignment = the, user = user, index = merge1) \
            .defer('log', 'xstatus', 'xinfos', 'artifact') \
            .order_by('-date') \
            .first()

        if reusehd is None:
            continue

        for fle in reusehd.files.all():
            if fle.name in submit1['missing']:
                submit1['missing'].remove(fle.name)
                submit1['rlist'].append((reusehd, fle))

    missing = list(sorted([
        (merge1, x)
            for merge1, submit1 in submit.items()
            for x in submit1['missing']
    ], key = lambda v : (-v[0], v[1])))

    if missing:
        missing = [f'{name} (Pb.{i})' for i, name in missing]
        messages.error(request,
            'The following files are missing: ' + ', '.join(sorted(missing)))
        return dutils.redirect(url)

    handins = []

    with db.transaction.atomic():
        for merge1 in reversed(sorted(submit.keys())):
            submit1 = submit[merge1]

            handin = models.HandIn(
                user       = user,
                assignment = the,
                index      = merge1,
                date       = subdate,
            )
            handin.save()
    
            for stream in submit1['files'].values():
                data = b''.join(stream.chunks()) # FIXME
                recd = models.HandInFile(
                    handin   = handin,
                    name     = stream.name,
                )
                recd.contents.save(stream.name, ContentFile(data))
                recd.save()
    
            for _, rfile in submit1['rlist']:
                with open(rfile.contents.path, 'rb') as rfilefd:
                    recd = models.HandInFile(
                        handin = handin,
                        name   = rfile.name,
                    )
                    recd.contents.save(rfile.name, File(rfilefd))
                    recd.save()

            handins.append(handin)

    for i, handin in enumerate(handins):
        _defer_check(handin, update = (i == 0))

    messages.info(request,
        'Your files for question %d have been submitted' % (index,))

    if len(submit) > 1:
        others = list(sorted(set(submit.keys()).difference({ index })))
        messages.info(request,
            'Some files have been propagated to the following questions: ' +
            ', '.join(map(str, others)))

    if submit[index]['rlist']:
        rlv = list(sorted({ k[1].name for k in submit[index]['rlist'] }))
        messages.info(request,
            'The following files have been copied from your previous submissions: ' + \
            ', '.join(rlv))

    return dutils.redirect(url)

# --------------------------------------------------------------------
class Assignment(views.generic.TemplateView):
    template_name = 'assignment.html'
    http_method_names = ['get', 'put']

    @udecorators.method_decorator(dcsrf.csrf_exempt)
    def dispatch(self, request, *args, **kwargs):
        return super().dispatch(request, *args, **kwargs)

    @classmethod
    def get_cache_key(cls, code, subcode, promo, extra):
        return 'template-%s-%s-%d-%s' % (code, subcode, promo, extra)
    EXTRA = ('text', 'header')

    @classmethod
    def save_resource(cls, asg, res, namespace):
        import magic

        mime  = magic.Magic(mime = True)
        ctype = mime.from_buffer(res['contents'])
        ctype = ctype if ctype else 'application/octet-stream'

        ores = models.Resource(
            name       = res['name'],
            ctype      = ctype,
            assignment = asg,
            namespace  = namespace,
        )
        ores.contents.save(res['name'], ContentFile(res['contents']))
        ores.save()

    def get_context_data(self, code, subcode, promo, *args, **kw):
        ctx = super().get_context_data(*args, **kw)
        the = get_assignment(self.request, code, subcode, promo)

        text   = cache.get(self.get_cache_key(code, subcode, promo, 'text'  ))
        header = cache.get(self.get_cache_key(code, subcode, promo, 'header'))

        if text is None:
            text = pandoc_gen(the.contents, 'contents')
            text = bs4.BeautifulSoup(text, 'html.parser')
            for tag in text.find_all('table'):
                tag['class'] = tag.get('class', []) + \
                    ['table', 'table-striped', 'table-borderless', 'table-hover', 'table-sm']
            for tag in text.find_all('thead'):
                tag['class'] = tag.get('class', []) + ['thead-dark']
            text = str(text)
            cache.set(self.get_cache_key(code, subcode, promo, 'text'), text)

        if header is None:
            header = pandoc_gen(the.contents, 'header')
            cache.set(self.get_cache_key(code, subcode, promo, 'header'), header)

        now  = dt.datetime.now()
        late = the.end is not None and now.date() > the.end

        def upload_match(handins):
            def doit(match):
                index = int(match.group(1))
                data  = '<span id="submit-%d"></span>' % (index,)

                if late:
                    data += LATE_OK_SUBMIT

                if index in handins:
                    date  = handins[index]['date']
                    date  = date.astimezone(utils.timezone.get_current_timezone())
                    date  = date.strftime('%B %d, %Y (%H:%M:%S)')
                    data += LAST_SUBMIT % (utils.html.escape(date),)

                adm   = FORM_ADMIN if self.request.user.has_perm('upload:admin') else ''
                adm   = adm % (dict(index = index))
                data += FORM % (dict(index = index, admin = adm))

                reqs = the.required(index)
                if reqs:
                    reqs  = utils.html.escape(', '.join(sorted(reqs)))
                    data += F_REQUIRED % (reqs,)
                deps = the.merges().get(index, [])
                if deps:
                    data = F_MERGE % (', '.join('Pb.%d' % x for x in sorted(set(deps)))) + data

                return data

            return doit

        def upload_match_late(match):
            return LATE_SUBMIT

        def upload_match_nc(match):
            return NO_SUBMIT

        handins = None
        if self.request.user.is_authenticated:
            if not (self.request.user.has_perm('upload.admin')) and (late and not the.lateok):
                text = re.sub(UPRE, upload_match_late, text)
            else:
                handins = dict()
                for hdn in models.HandIn.objects \
                    .filter(assignment = the, user = self.request.user) \
                    .values('index', 'status', 'date') \
                    .all():
    
                    handins.setdefault(hdn['index'], []).append(hdn)
    
                handins = { k: max(v, key = lambda v : v['date']) \
                                for k, v in handins.items() }
    
                text = re.sub(UPRE, upload_match(handins), text)
        else:
            text = re.sub(UPRE, upload_match_nc, text)

        ctx['the'     ] = the
        ctx['nav'     ] = _build_nav(self.request.user, the, back = False)
        ctx['handins' ] = handins
        ctx['contents'] = dict(header = header, text = text)

        return ctx

    def put(self, request, code, subcode, promo):
        _check_shared_secret(request)

        import json, jsonschema, mimeparse as mp, base64, binascii

        mtype, msub, mdata = mp.parse_mime_type(request.content_type)

        if (mtype, msub) != ('application', 'json'):
            return http.HttpResponseBadRequest()

        charset = mdata.get('charset', 'utf-8')

        try:
            body = request.body.decode(charset)
            jso  = json.loads(body)

            jsonschema.validate(jso, SCHEMA)
            for res in jso['resources']:
                res['contents'] = \
                    base64.b64decode(res['contents'], validate = True)

            if 'autocorrect' in jso:
                for res in jso['autocorrect']['extra']:
                    res['contents'] = \
                        base64.b64decode(res['contents'], validate = True)

        except (json.decoder.JSONDecodeError,
                jsonschema.exceptions.ValidationError,
                UnicodeDecodeError, binascii.Error) as e:
            return http.HttpResponseBadRequest()

        jsokey = jso['code'], jso['subcode'], jso['promo']
        if jsokey != (code, subcode, promo):
            return http.HttpResponseBadRequest()

        rnames = [x['name'] for x in jso['resources']]
        if len(rnames) != len(set(rnames)):
            return http.HttpResponseBadRequest()

        acorrect = jso.get('autocorrect', None)

        key = dict(code=code, subcode=subcode, promo=promo)
        dfl = dict(start      = jso['start'],
                   end        = jso['end'],
                   lateok     = jso['lateok'],
                   contents   = jso['contents'],
                   tests      = [],
                   properties = dict(required = jso.get('required', dict()),
                                     map      = jso.get('map', [])))
        if jso.get('merge', None):
            dfl['properties']['merge'] = jso['merge']

        if acorrect is not None:
            dfl['tests'] = acorrect['forno']

        with db.transaction.atomic():
            asg, _ = models.Assignment.objects.update_or_create(dfl, **key)
            asg.resource_set.all().delete()
            asg.save()          # Delete all resource files

        with db.transaction.atomic():
            for res in jso['resources']:
                self.save_resource(asg, res, 'resource')
            if acorrect is not None:
                for res in acorrect['extra']:
                    self.save_resource(asg, res, 'tests/extra')

        for extra in self.EXTRA:
            cache.delete(self.get_cache_key(code, subcode, promo, extra))

        return http.HttpResponse("OK\r\n", content_type = 'text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def delete_assignment(request, code, subcode, promo):
    get_assignment(request, code, subcode, promo).delete()
    return http.HttpResponse("OK\r\n", content_type = 'text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def delete_all_assignments(request, code, promo):
    for the in models.Assignment.objects.filter(code = code, promo = promo).all():
        the.delete()
    return http.HttpResponse("OK\r\n", content_type = 'text/plain')

# --------------------------------------------------------------------
@dhttp.require_GET
def resource(request, code, subcode, promo, name):
    the = get_assignment(request, code, subcode, promo)
    key = dict(assignment=the, name=name, namespace='resource')
    the = dutils.get_object_or_404(models.Resource, **key)
    rep = http.FileResponse(the.contents.open(), content_type = the.ctype)

    rep['Content-Disposition'] = 'inline'; return rep

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def grade_view(request, code, subcode, promo, login):
    the    = get_assignment(request, code, subcode, promo)
    user   = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    grades = models.HandInGrade.objects
    grades = grades.filter(user = user, assignment = the)
    grades = grades.prefetch_related(
        'handins', 'handins__handin', 'handins__handin__files').first()

    qst = set()

    if grades is not None:
        for handin in grades.handins.all():
            if handin.handin is None:
                continue
            xinfos = handin.handin.xinfos
            if xinfos is None:
                continue
            qst.update(x[0] for x in xinfos)

    ctxt = dict(grades = grades, the = the, user = user,
                qst = sorted(qst), nav = _build_nav(request.user, the))
    return dutils.render(request, 'grade_view.html', ctxt)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def grade_finalize_all(request, code, subcode, promo):
    the = get_assignment(request, code, subcode, promo)

    models.HandInGrade.objects \
                      .filter(assignment = the) \
                      .update(finalized = True)

    messages.info(request, 'All grades have been marked as finalized')

    uargs = dict(code = code, subcode = subcode, promo = promo)
    url = durls.reverse('upload:uploads_by_users', kwargs = uargs)
    return http.HttpResponseRedirect(url)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def grade_get_files(request, code, subcode, promo, login):
    the    = get_assignment(request, code, subcode, promo)
    user   = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    grades = models.HandInGrade.objects.filter(user = user, assignment = the)
    grades = grades.prefetch_related('handins', 'handins__handin', 'handins__handin__files')
    grades = grades.first()

    if grades is None:
        raise http.Http404        

    files = []

    for handin in grades.handins.order_by('index').all():
        if handin.handin is None:
            continue
        for filec in handin.handin.files.all():
            with filec.contents.open() as stream:
                files.append(dict(
                    name     = os.path.basename(filec.name),
                    index    = handin.handin.index,
                    uuid     = filec.uuid,
                    contents = stream.read().decode('utf-8', errors = 'replace'),
                ))

    comments = grades.comments.select_related('author', 'handinfile')
    comments = comments.order_by('timestamp')
    jscm     = {}

    for comment in comments.all():
        jscm.setdefault(str(comment.handinfile.uuid), []) \
            .append(dict(
                uuid      = comment.uuid,
                author    = comment.author.fullname,
                timestamp = comment.timestamp,
                comment   = comment.comment,
                lineno    = comment.handinloc,
                tags      = comment.tags,
                delta     = comment.delta,
            ))

    return http.JsonResponse(dict(
        finalized = grades.finalized,
        files     = files,
        comments  = jscm,
    ))

# --------------------------------------------------------------------
class AddGradeCommentForm(forms.Form):
    uuid    = forms.UUIDField()
    index   = forms.IntegerField(min_value = 0)
    lineno  = forms.IntegerField(min_value = 0)
    comment = forms.CharField(strip = True)
    tags    = forms.CharField(required = False)
    delta   = forms.IntegerField(min_value = -100, max_value = 100, required = False)

    def clean(self):
        data = self.cleaned_data
        tags = data.get('tags', None)
        if tags is not None:
            tags = [x.strip() for x in tags.split(',')]
            tags = [x for x in tags if x] or None
            data['tags'] = tags
        if data.get('delta', None) is not None:
            if data.get('tags', None) is None:
                data['delta'] = None
        return data

@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_POST
@dcsrf.csrf_exempt              # FIXME
def grade_comments(request, code, subcode, promo, login):
    the    = get_assignment(request, code, subcode, promo)
    user   = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    grades = models.HandInGrade.objects.filter(user = user, assignment = the)
    grades = grades.first()

    if grades is None:
        raise http.Http404        
    if grades.finalized:
        return http.JsonResponse(dict(ok = False, jsc = None))

    form = AddGradeCommentForm(request.POST)

    if form.is_valid():
        data  = form.cleaned_data
        filec = models.HandInFile.objects.filter(
            uuid               = data['uuid'],
            handin__user       = user,
            handin__index      = data['index'],
            handin__assignment = the,
        ).first()

        if filec is not None:
            comment = models.HandInGradeComment()
            comment.grade      = grades
            comment.author     = request.user
            comment.comment    = data['comment']
            comment.handinfile = filec
            comment.handinloc  = data['lineno']
            comment.tags       = data['tags']
            comment.delta      = data['delta']

            comment.save()

            jsc = dict(
                uuid      = comment.uuid,
                author    = comment.author.fullname,
                timestamp = comment.timestamp,
                comment   = comment.comment,
                lineno    = comment.handinloc,
                tags      = comment.tags,
                delta     = comment.delta,
            )

            return http.JsonResponse(dict(ok = True, jsc = jsc))

    return http.JsonResponse(dict(ok = False, jsc = None))

# --------------------------------------------------------------------
class ModifyGradeCommentForm(forms.Form):
    comment = forms.CharField(strip = True)
    tags    = forms.CharField(required = False)
    delta   = forms.IntegerField(min_value = -100, max_value = 100, required = False)

    def clean(self):
        data = self.cleaned_data
        tags = data.get('tags', None)
        if tags is not None:
            tags = [x.strip() for x in tags.split(',')]
            tags = [x for x in tags if x] or None
            data['tags'] = tags
        if data.get('delta', None) is not None:
            if data.get('tags', None) is None:
                data['delta'] = None
        return data

@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_POST
@dcsrf.csrf_exempt              # FIXME
def grade_comments_edit(request, code, subcode, promo, login, uuid):
    the    = get_assignment(request, code, subcode, promo)
    user   = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    grades = models.HandInGrade.objects.filter(user = user, assignment = the)
    grades = grades.first()

    if grades is None:
        raise http.Http404        
    if grades.finalized:
        return http.JsonResponse(dict(ok = False, jsc = None))

    comment = grades.comments.filter(uuid = uuid).first()

    if comment is None:
        raise http.Http404

    if 'delete' in request.POST:
        comment.delete()
        return http.JsonResponse(dict(ok = True, jsc = None))

    form = ModifyGradeCommentForm(request.POST)

    if not form.is_valid():
        return http.JsonResponse(dict(ok = False, jsc = None))

    data = form.cleaned_data

    comment.comment = data['comment']
    comment.tags    = data['tags']
    comment.delta   = data['delta']
    comment.save()

    return http.JsonResponse(dict(ok = True, jsc = dict(
        uuid      = comment.uuid,
        author    = comment.author.fullname,
        timestamp = comment.timestamp,
        comment   = comment.comment,
        lineno    = comment.handinloc,
        tags      = comment.tags,
        delta     = comment.delta,
    )))

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_POST
def grade_start(request, code, subcode, promo, login):
    the  = get_assignment(request, code, subcode, promo)
    user = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    crt  = False

    with db.transaction.atomic():
        grquery = models.HandInGrade.objects.filter(user = user, assignment = the)
        grquery = grquery.first()

        if grquery is None:
            qsts = questions_of_contents(the.contents)
            hdns = []

            for question in qsts:
                handin = models.HandIn.objects \
                    .filter(assignment = the     ,
                            user       = user    ,
                            index      = question) \
                    .defer('xstatus', 'xinfos') \
                    .order_by('-date') \
                    .first()
                hdns.append((question, handin))

            grading = models.HandInGrade()
            grading.assignment = the
            grading.user       = user
            grading.save()

            for index, handin in hdns:
                hdng = models.HandInGradeHandIn()
                hdng.handin = handin
                hdng.index  = index
                hdng.grade  = grading
                hdng.save()
        else:
            grquery.finalized = False
            grquery.save()

    if crt:
        messages.info(request, 'Grading started for %s' % (login,))
    uargs = dict(code = code, subcode = subcode, promo = promo, login = login)
    url = durls.reverse('upload:grade_view', kwargs = uargs)
    return http.HttpResponseRedirect(url)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_POST
def grade_end(request, code, subcode, promo, login):
    the  = get_assignment(request, code, subcode, promo)
    user = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    crt  = False

    with db.transaction.atomic():
        grquery = models.HandInGrade.objects.filter(user = user, assignment = the)
        grquery = grquery.first()

        if grquery is None:
            raise http.Http404

        grquery.finalized = True
        grquery.save()

    if crt:
        messages.info(request, 'Grading finalized for %s' % (login,))
    uargs = dict(code = code, subcode = subcode, promo = promo, login = login)
    url = durls.reverse('upload:grade_view', kwargs = uargs)
    return http.HttpResponseRedirect(url)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def recheck(request, code, subcode, promo):
    force = request.GET.get('force', '').lower() in BOOL
    flt   = Q() if force else (Q(status = '') | Q(status = 'errored'))

    handins = models.HandIn.objects \
                    .select_related('assignment', 'user') \
                    .defer('log', 'xstatus', 'artifact', 'assignment__contents',
                           'assignment__properties', 'assignment__tests') \
                    .filter(assignment__code = code, \
                            assignment__subcode = subcode, \
                            assignment__promo = promo) \
                    .filter(flt) \
                    .order_by('-date') \
                    .all()

    with db.transaction.atomic():
        for handin in handins:
            _defer_recheck(handin)

    return http.HttpResponse(str(len(handins)), content_type='text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def recheck_user(request, code, subcode, promo, login):
    force   = request.GET.get('force', '').lower() in BOOL
    deep    = request.GET.get('deep' , '').lower() in BOOL
    handins = set()
    count   = 0

    with db.transaction.atomic():
        for handin in \
            models.HandIn.objects \
                    .select_related('assignment', 'user') \
                    .defer('log', 'xstatus', 'artifact', 'assignment__contents',
                           'assignment__properties', 'assignment__tests') \
                    .filter(assignment__code = code, \
                            assignment__subcode = subcode, \
                            assignment__promo = promo) \
                    .filter(user__login = login) \
                    .order_by('-date') \
                    .defer('log', 'xstatus', 'artifact') \
                    .all():

            if not deep:
                if handin.index in handins:
                    continue
                handins.add(handin.index)

            if not force and handin.status != '':
                continue
    
            count += 1; _defer_recheck(handin)

    return http.HttpResponse(str(count), content_type='text/plain')


# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def recheck_index(request, code, subcode, promo, index):
    force   = request.GET.get('force', '').lower() in BOOL
    deep    = request.GET.get('deep' , '').lower() in BOOL
    handins = set()
    count   = 0

    with db.transaction.atomic():
        for handin in \
            models.HandIn.objects \
                    .select_related('assignment', 'user') \
                    .defer('log', 'xstatus', 'artifact', 'assignment__contents',
                           'assignment__properties', 'assignment__tests') \
                    .filter(assignment__code = code, \
                            assignment__subcode = subcode, \
                            assignment__promo = promo) \
                    .filter(index = index) \
                    .order_by('-date') \
                    .defer('log', 'xstatus', 'artifact') \
                    .all():
    
            if not deep:
                key = handin.index, handin.user.login
                if key in handins:
                    continue
                handins.add(key)

            if not force and handin.status != '':
                continue

            count += 1; _defer_recheck(handin)

    return http.HttpResponse(str(count), content_type='text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def recheck_user_index(request, code, subcode, promo, login, index):
    force = request.GET.get('force', '').lower() in BOOL
    deep  = request.GET.get('deep' , '').lower() in BOOL

    handins = models.HandIn.objects \
                          .select_related('assignment', 'user') \
                          .defer('log', 'xstatus', 'artifact', 'assignment__contents',
                                 'assignment__properties', 'assignment__tests') \
                          .filter(assignment__code = code, \
                                  assignment__subcode = subcode, \
                                  assignment__promo = promo) \
                          .filter(user__login = login, index = index) \
                          .order_by('-date') \
                          .defer('log', 'xstatus', 'artifact') \
                          .all()

    if not deep:
        handins = handins[:1]

    if not force:
        handins = [x for x in handins if x.status == '']

    with db.transaction.atomic():
        for handin in handins:
            _defer_recheck(handin)

    return http.HttpResponse(str(len(handins)), content_type='text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def recheck_uuid(request, uuid):
    handin = models.HandIn.objects.get(pk = uuid)

    if handin is not None:
        _defer_recheck(handin)

    return http.HttpResponse('1' if handin else '0', content_type='text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def clean(request):
    aout = models.HandIn.objects.filter(~Q(user__cls = 'Etudiants')).delete()
    return http.HttpResponse(repr(aout), content_type = 'text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def stats(request, code, subcode, promo):
    the  = get_assignment(request, code, subcode, promo)
    ctxt = dict(nav = _build_nav(request.user, the), the = the)
    return dutils.render(request, 'stats.html', ctxt)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def autocomplete_users(request):
    users, q = [], request.GET.get('q', '').strip()

    if len(q) >= 2:
        users = User.objects \
            .filter(login__contains = q) \
            .values_list('login', 'firstname', 'lastname') \
            .all()
        users = [
            dict(value = x[0], text = ' '.join(x[1:]))
            for x in users
        ]

    return http.JsonResponse(users, safe = False)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def summary(request, code, promo):
    assignments = \
        models.Assignment.objects \
            .filter(code = code, promo = promo) \
            .order_by('subcode') \
            .all()[:]

    users = \
        dauth.get_user_model().objects \
            .filter(handin__assignment__in = assignments) \
            .order_by('login') \
            .distinct().all()[:]

    summary = {}

    for assignment in assignments:
        handins = { x.login : {} for x in users }

        for handin in models.HandIn.objects \
                         .filter(assignment = assignment) \
                         .select_related('user') \
                         .order_by('-date').all():

            if handin.index not in handins[handin.user.login]:
                handins[handin.user.login][handin.index] = handin

        questions = {}

        for uhandin in handins.values():
            for handin in uhandin.values():
                if handin.index not in questions:
                    questions[handin.index] = None
                xstatus = handin.compute_xinfos()
                if xstatus is not None and len(xstatus) > 0:
                    if questions[handin.index] is None:
                        questions[handin.index] = []
                    questions[handin.index] = questions[handin.index] + \
                        [x[0] for x in xstatus if x[0] not in questions[handin.index]]

        summary[assignment.subcode] = { x.login : {} for x in users }

        for login, uinfo in summary[assignment.subcode].items():
            for index, question in questions.items():
                handin = handins[login].get(index, None)

                if question is None:
                    uinfo[index] = \
                        handin is not None and handin.status in ('success', 'no-test')
                else:
                    xstatus = [] if handin is None else handin.compute_xinfos()
                    xstatus = [] if xstatus is None else xstatus
                    xstatus = { k: v for k, v in xstatus }

                    for subindex in question:
                        uinfo['{}/{}'.format(index, subindex)] = \
                            xstatus.get(subindex) in ('success', 'no-test')
                        
        summary[assignment.subcode][None] = questions

    import xlsxwriter, tempfile

    with tempfile.NamedTemporaryFile(
        prefix = '{}-{}'.format(code, promo),
        suffix = '.xlsx') as output:
        
        workbook = xlsxwriter.Workbook(output.name)
        bold     = workbook.add_format(dict(bold = True, bg_color = '#CCCCCC'))
        fko      = workbook.add_format({'bg_color'   : '#FFC7CE',
                                        'font_color' : '#9C0006'})
        fok      = workbook.add_format({'bg_color'   : '#C6EFCE',
                                        'font_color' : '#006100'})

        for assignment in assignments:
            questions = summary[assignment.subcode][None]
            worksheet = workbook.add_worksheet(assignment.subcode)
    
            worksheet.set_column(0, 0, 30)

            column = 1
    
            for index in sorted(questions.keys()):
                question = questions[index]
    
                if question is None:
                    worksheet.write(0, column, index, bold)
                    column += 1
                else:
                    for subindex in question:
                        worksheet.write(0, column, '{}/{}'.format(index, subindex), bold)
                        column += 1
    
            for i, user in enumerate(users):
                worksheet.write(i+1, 0, user.login, bold)
    
                column, uinfo = 1, summary[assignment.subcode][user.login]
    
                for index in sorted(questions.keys()):
                    question = questions[index]
    
                    if question is None:
                        worksheet.write(i+1, column, uinfo[index])
                        column += 1
                    else:
                        for subindex in question:
                            worksheet.write(i+1, column, uinfo['{}/{}'.format(index, subindex)])
                            column += 1
    
            worksheet.conditional_format(
                1, 1, len(users), column-1,
                {'type'     : 'cell'    ,
                 'criteria' : 'equal to',
                 'value'    :  False    ,
                 'format'   :  fko      })

            worksheet.conditional_format(
                1, 1, len(users), column-1,
                {'type'     : 'cell'    ,
                 'criteria' : 'equal to',
                 'value'    :  True     ,
                 'format'   :  fok      })

        workbook.close()

        response = open(output.name, 'r+b')
        response = http.HttpResponse(response,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = \
            'attachment; filename={}-{}.xlsx'.format(code, promo)

        return response

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def students_of_code_promo(request, code, promo):
    gname    = '%s:%d' % (code, promo)
    students = dauth.get_user_model() \
                    .objects \
                    .prefetch_related('groups') \
                    .filter(groups__name__startswith = gname + ':') \
                    .order_by('login') \
                    .all()[:]
    groups   = {}

    for student in students:
        groups[student.login] = \
            [x.name[len(gname)+1:] for x in student.groups.all()
                 if x.name.startswith(gname + ':')]
        groups[student.login].sort()

    context = dict(students = students, groups = groups, code = code, promo = promo)
    return dutils.render(request, 'students_of_code_promo.html', context)
