# --------------------------------------------------------------------
import sys, os, re, datetime as dt, tempfile, zipfile, tempfile, io
import codecs, chardet, shutil, uuid as muuid, docker, math
import multiprocessing as mp, psutil
import itertools as it, humanfriendly as hf
from   collections import namedtuple, OrderedDict as odict

from   django.conf import settings
from   django.core.exceptions import PermissionDenied
import django.core.paginator as paginator
from   django.core.cache import cache
from   django.core.files.base import File, ContentFile
from   django.core.files.storage import default_storage
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
import django.utils as utils, django.utils.timezone
import django.db as db

import background_task as bt
import background_task.models as btmodels

from . import models

from handin.middleware import eredirect

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

    args = dict(
        to         = 'html5+smart+raw_tex',
        format     = 'markdown',
        extra_args = [
            '--filter', 'pandoc-codeblock-include',
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
MAXSIZE  = 10 * 1024 * 1024
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
        contents    = dict(type = 'string'),
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
        resources = RSCHEMA,
        autocorrect = dict(
            type = 'object',
            additionalProperties = False,
            properties = dict(
                forno = dict(type = 'array', items = dict(type = 'number')),
                files = RSCHEMA,
                extra = RSCHEMA,
            ),
            required = ['forno', 'files', 'extra'],
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
        group  = dict(type = 'number', minimum = 1),
    ),
    required = ['login', 'group'],
  ),
)

# --------------------------------------------------------------------
FORM = r'''
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
               name="files-reuse" value="1" id="files-reuse">
        <label class="form-check-label" for="files-reuse">
          Reuse files from previous submissions
          <span class="far fa-question-circle" data-toggle="tooltip"
                title="%s"></span>
        </label>
      </div>
    </div>
  </div>
</form>
''' % (' '.join([
    'Missing required files are taken from (in order):',
    'last submission of this question,',
    'last submissions from previous questions (from last to first)',
  ]))

F_REQUIRED     = '<div class="alert alert-light">Expected files: %s</div>'
NO_SUBMIT      = '<div class="alert alert-danger">Upload form is only available when connected</div>'
LATE_SUBMIT    = '<div class="alert alert-danger">Submissions are now closed</div>'
LATE_OK_SUBMIT = '<div class="alert alert-danger">Your submission will be flagged as late</div>'
LAST_SUBMIT    = '<div class="alert alert-info">Last submission: %s</div>'

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
    hdn.save()

    if hdn.index not in qst or hdn.index not in the.tests:
        hdn.status = 'no-test'; hdn.save()
        return

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
                    log_config       = {
                        'max-size': '10m',
                    },
                    mem_limit        = 512 * 1024 * 1024,
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
                    'timeout', '--preserve-status', '--signal=KILL', '180',
                    '/opt/handin/bin/python3',
                    '/opt/handin/user/scripts/achecker-%s-%d.py' % (hdn.assignment.code, hdn.assignment.promo),
                    '/opt/handin/user',
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
                        xstatus = resultjson.read()

    except Exception as e:
        import traceback
        log     += [traceback.format_exc()]
        status   = 'errored'
        xstatus  = ''

    hdn.log     = ('\n'.join(log) + '\n').replace('\x00', '\\x00')
    hdn.status  = status
    hdn.xstatus = xstatus.replace('\x00', '\\x00')
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
            handin.log, handin.status = '', ''
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
                   name = '%s:%d' % (gname, x)
               )[0] for x in groups
        }

        for g1 in jso:
            user, _ = dauth.get_user_model().objects.get_or_create(
                login    = g1['login'],
                defaults = dict(
                    firstname = '<imported>',
                    lastname  = '<imported>',
                    email     = 'imported@example.com',
                    ou        = 'cn=imported',
                    cls       = 'Etudiants',
                ),
            )
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
       h.status as status, h.date as date
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

        cursor.execute(SQL_GROUPS, [gname + ':%'])
        nt  = namedtuple('Group', [c[0] for c in cursor.description])
        grp = [nt(*x) for x in cursor.fetchall()]

    groups  = dict()

    for entry in grp:
        groups.setdefault(entry.login, set()) \
              .add(int(entry.gname[len(gname)+1:]))
    groups = { k: min(v) for k, v in groups.items() }

    users   = dict()
    uploads = dict()

    for x in hdn:
        if the.end is not None and x.date.replace(tzinfo=None).date() >= the.end:
            x = x._replace(late = True)

        if x.login not in users:
            users[x.login] = (x.login, x.fullname)

        ugroup = groups.get(x.login, None)
        gdict  = uploads.setdefault(ugroup, dict())

        if x.login not in gdict:
            gdict[x.login] = dict()
        gdict[x.login].setdefault(x.idx, []).append(x)

    context = dict(
        the    = the, qst = qst, uploads = uploads, users = users,
        groups = sorted(uploads.keys(), key = \
                            lambda x : math.inf if x is None else x),
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
                           .defer('log', 'xstatus', 'artifact') \
                           .all()
    uploads = paginator.Paginator(uploads, 100).get_page(request.GET.get('page'))

    context = dict(
        the = the, qst = qst, uploads = uploads,
        nav = _build_nav(request.user, the))
    context['refresh'] = REFRESH

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

    ctx = dict(the = the, rqs = rqs, qst = qst,
               nav = _build_nav(request.user, the))
    ctx['refresh'] = REFRESH

    return dutils.render(request, 'myuploads.html', ctx)

# --------------------------------------------------------------------
def _upload_details(request, code, subcode, promo, flt, view, must):
    the = get_assignment(request, code, subcode, promo)
    hdn = models.HandIn.objects \
                .select_related('user') \
                .filter(assignment = the) \
                .filter(flt) \
                .order_by('-date') \
                .first()
    dat = None

    if hdn is None:
        if must:
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
    context['refresh'] = REFRESH

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
def upload_details_by_login_index(request, code, subcode, promo, login, index):
    user = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    view = 'upload_details_by_login_index.html'
    flt  = Q(user = user, index = index)
    return _upload_details(request, code, subcode, promo, flt, view, False)

# --------------------------------------------------------------------
def _download_handin(handin, resources, inline = True):
    if len(resources) == 0:
        raise http.Http404('no resources')

    if len(resources) == 1:
        response = http.FileResponse(
            resources[0].contents.open(), content_type = 'text/plain')
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

    if the.end is not None and not the.lateok:
        if dt.datetime.now().date() >= the.end:
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
                         .filter(user = request.user) \
                         .values('date') \
                         .order_by('-date') \
                         .first()

    if lastd is not None:
        diffd = utils.timezone.now() - lastd['date']

    if diffd is not None and diffd.total_seconds() - MINDELTA < -1.0:
        messages.error(request,
            'You are submitting files too fast (wait %d second(s))' % \
                (MINDELTA - diffd.total_seconds()))
        return dutils.redirect(url)

    reuse   = request.POST.get('files-reuse', '').lower() in BOOL
    rmap    = set()
    rlist   = []
    missing = reqs.difference([x.name for x in files])

    if missing and reuse:
        try:
            for hdn in models.HandIn.objects \
                             .filter(assignment = the,
                                     user = request.user,
                                     index__lte = index) \
                             .defer('log', 'artifact') \
                             .order_by('-index', '-date') \
                             .all():
    
                if hdn.index in rmap:
                    continue
    
                rmap.add(hdn.index)
                for fle in hdn.handinfile_set.all():
                    if fle.name in missing:
                        missing.remove(fle.name)
                        rlist.append((hdn, fle))
                    if not missing:
                        raise StopIteration

        except StopIteration:
            pass

    if missing:
        messages.error(request,
            'The following files are missing: ' +
            ', '.join(sorted(missing)))
        return dutils.redirect(url)

    with db.transaction.atomic():
        handin = models.HandIn(
            user       = request.user,
            assignment = the,
            index      = index,
            date       = utils.timezone.now(),
        )
        handin.save()

        for stream in files:
            data = b''.join(stream.chunks()) # FIXME
            recd = models.HandInFile(
                handin   = handin,
                name     = stream.name,
            )
            recd.contents.save(stream.name, ContentFile(data))
            recd.save()

        for _, rfile in rlist:
            with open(rfile.contents.path, 'rb') as rfilefd:
                recd = models.HandInFile(
                    handin = handin,
                    name   = rfile.name,
                )
                recd.contents.save(rfile.name, File(rfilefd))
                recd.save()

    _defer_check(handin, update = False)

    messages.info(request,
        'Your files for question %d have been submitted' % (index,))

    if rlist:
        rlv = { k.name : v for v, k in rlist }
        rlv = [(k, rlv[k]) for k in sorted(rlv.keys())]
        messages.info(request,
            'The following files have been copied from your previous submissions: ' + \
            ', '.join(['%s (Q%d)' % (k, v.index) for k, v in rlv]))

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
            cache.set(self.get_cache_key(code, subcode, promo, 'text'), text)

        if header is None:
            header = pandoc_gen(the.contents, 'header')
            cache.set(self.get_cache_key(code, subcode, promo, 'header'), header)

        now  = dt.datetime.now()
        late = the.end is not None and now.date() > the.end

        def upload_match(handins):
            def doit(match):
                index = int(match.group(1))
                data  = '<div id="submit-%d"></div>' % (index,)

                if late:
                    data += LATE_OK_SUBMIT

                if index in handins:
                    date  = handins[index]['date']
                    date  = date.astimezone(utils.timezone.get_current_timezone())
                    date  = date.strftime('%B %d, %Y (%H:%M:%S)')
                    data += LAST_SUBMIT % (utils.html.escape(date),)

                data += FORM % (dict(index = index))

                reqs = the.required(index)
                if reqs:
                    reqs  = utils.html.escape(', '.join(sorted(reqs)))
                    data += F_REQUIRED % (reqs,)

                return data

            return doit

        def upload_match_late(match):
            return LATE_SUBMIT

        def upload_match_nc(match):
            return NO_SUBMIT

        handins = None
        if self.request.user.is_authenticated:
            if late and not the.lateok:
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
                for res in jso['autocorrect']['files']:
                    res['contents'] = \
                        base64.b64decode(res['contents'], validate = True)
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
                for res in acorrect['files']:
                    self.save_resource(asg, res, 'tests/files')
                for res in acorrect['extra']:
                    self.save_resource(asg, res, 'tests/extra')

        for extra in self.EXTRA:
            cache.delete(self.get_cache_key(code, subcode, promo, extra))

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
def recheck(request, code, subcode, promo):
    force = request.GET.get('force', '').lower() in BOOL
    flt   = Q() if force else Q(status = '') | Q(status = 'errored')

    handins = models.HandIn.objects \
                    .select_related('assignment', 'user') \
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
