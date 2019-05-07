# --------------------------------------------------------------------
import sys, os, re, datetime as dt, tempfile, zipfile, tempfile, io
import codecs, chardet, shutil, uuid as muuid, docker, math
import itertools as it
from   collections import namedtuple

from   django.conf import settings
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
from   django.core.cache import cache
from   django.core.files.base import ContentFile
from   django.core.files.storage import default_storage

import background_task as bt

from . import models

from handin.middleware import eredirect

# --------------------------------------------------------------------
ACDIR = os.path.join(os.path.dirname(__file__), 'autocorrect')
ROOT  = os.path.dirname(__file__)

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
        to         = 'html5+smart+markdown_in_html_blocks',
        format     = 'md',
        extra_args = [
            '--base-header-level=2',
            '--mathjax', '--standalone',
            '--toc', '--toc-depth=4',
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
REIDENT = r'^[a-zA-Z0-9]+$'
UPRE    = r'<\!--\s*UPLOAD:(\d+)\s*-->'

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
    required = ['code', 'subcode', 'promo', 'start', 'end', 'contents', 'resources'],
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
<form class="form" style="width: 70%%;" method="post"
      enctype="multipart/form-data" action="handins/%(index)d/">

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
  </div>
</form>
'''

F_REQUIRED  = '<p class="alert alert-secondary">Expected files: %s<p>'
NO_SUBMIT   = '<p class="alert alert-danger">Upload form is only available when connected</p>'
LATE_SUBMIT = '<p class="alert alert-danger">Submissions are now closed</p>'
LAST_SUBMIT = '<p class="alert alert-info">Last submission: %s</p>'

# --------------------------------------------------------------------
def questions_of_contents(contents):
    qst = re.findall(r'<\!--\s*UPLOAD:(\d+)\s*-->', contents)
    return sorted([int(x) for x in qst])

# --------------------------------------------------------------------
def can_access_assignment(user, the):
    if user.has_perm('upload', 'admin'):
        return True
    return the.start is None or the.start <= dt.datetime.now().date()

# --------------------------------------------------------------------
def get_assignment(request, code, subcode, promo):
    the = models.Assignment.objects.get(code=code, subcode=subcode, promo=promo)
    if the is None: raise http.Http404
    if not can_access_assignment(request.user, the):
        if not request.user.is_authenticated:
            raise eredirect('%s?%s' % (
                dutils.reverse('upload:login'),
                utils.http.urlencode(dict(next = the.get_absolute_url()))
            ))
    return the

# --------------------------------------------------------------------
def _build_nav(user, the, back = True):
    oth = models.Assignment.objects \
                .filter(code=the.code, promo=the.promo) \
                .order_by('subcode') \
                .defer('contents') \
                .all()
    oth = [x for x in oth if can_access_assignment(user, x)]
    oth = [x.subcode for x in oth]
    return dict(oasgn = (the, oth), inasgn = the, back = back)

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
def _defer_check_internal(uuid):
    hdn = models.HandIn.objects.get(pk = uuid)
    the = hdn.assignment
    qst = questions_of_contents(the.contents)

    if hdn.index not in qst or hdn.index not in the.tests:
        hdn.status = 'no-test'; hdn.save()
        return

    totest = models.HandInFile.objects.filter(handin = hdn).all()[:]

    if not totest:
        hdn.status = 'failure'; hdn.save()
        return

    entry = 'Test_%s_%d.java' % (the.subcode, hdn.index)

    test = models.Resource.objects \
                 .filter(namespace  = 'tests/files',
                         assignment = the,
                         name       = entry) \
                 .first()

    if test is None:
        return

    extra = models.Resource.objects \
                  .filter(namespace  = 'tests/extra',
                          assignment = the) \
                  .all()[:]

    def do_recode(filename):
        return os.path.splitext(filename)[1].lower() == '.java'

    try:
        log = []

        with tempfile.TemporaryDirectory() as srcdir:
            with tempfile.TemporaryDirectory() as tstdir:
                log += ['copying files...']
    
                for filename in totest:
                    if do_recode(filename.contents.path):
                        coddet = chardet.universaldetector.UniversalDetector()
                        with filename.contents.open('br') as stream:
                            contents = stream.read()
                        coddet.reset(); coddet.feed(contents); coddet.close()
                        encoding = coddet.result['encoding'] or 'ascii'
                        contents = codecs.decode(contents, encoding)
                        outname  = os.path.basename(filename.name)
                        outname  = os.path.join(srcdir, outname)
                        with open(outname, 'wb') as stream:
                            stream.write(codecs.encode(contents, 'utf-8'))
                    else:
                        shutil.copy(filename.contents.path,
                                    os.path.join(srcdir, filename.name))

                shutil.copy(test.contents.path,
                            os.path.join(srcdir, test.name))
    
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
                    cpu_shares       = 256  ,
                    mem_limit        = 128 * 1024 * 1024,
                    volumes = {
                        os.path.realpath(srcdir): \
                            dict(bind = '/opt/handin/user/src', mode = 'rw'),
                        os.path.realpath(tstdir): \
                            dict(bind = '/opt/handin/user/test', mode = 'rw'),
                        os.path.join(ACDIR, 'libsupport'): \
                            dict(bind = '/opt/handin/user/lib', mode = 'ro'),
                        os.path.join(ACDIR, 'scripts'): \
                            dict(bind = '/opt/handin/user/scripts', mode = 'ro'),
                    }
                )
    
                command = [
                    'timeout', '--preserve-status', '--signal=KILL', '300',
                    '/opt/handin/bin/python3',
                    '/opt/handin/user/scripts/achecker.py',
                    '/opt/handin/user',
                    os.path.splitext(entry)[0],
                ]
    
                log += ['running docker...']
    
                container = dclient.containers.run \
                    ('handin:latest', command, **container)
    
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
                        if status['StatusCode'] == 124:
                            log += ['...timeout']
                        status = 'success' if status['StatusCode'] == 0 else 'failure'
        
                    log += ['...docker ended (%s)' % (status,)]
    
                finally:
                    try:
                        container.remove(v = True, force = True)
                    except docker.errors.APIError:
                        pass

    except Exception as e:
        log += [repr(e)]
        status = 'errored'

    hdn.log    = '\n'.join(log) + '\n'
    hdn.status = status
    hdn.save()

# --------------------------------------------------------------------
@bt.background(queue = 'check')
def _defer_check(uuid):
    try:
        print('CHECK: %s' % (uuid,), file=sys.stderr)
        _defer_check_internal(muuid.UUID(uuid))
        print('DONE: %s' % (uuid,), file=sys.stderr)
    except Exception as e:
        print(e, file=sys.stderr)
        raise

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
    assgns   = it.groupby(assgns, lambda x : (x.code, x.promo))
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
        nt  = namedtuple('Handin', [c[0] for c in cursor.description])
        hdn = [nt(*x) for x in cursor.fetchall()]

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
        .order_by('user__login', 'index', '-date') \
        .defer('log') \
        .all()

    nusers  = len(set([x.user.login for x in lst]))
    stats   = { x: 0 for x in qst }
    uploads = dict()

    for x in lst:
        if x.user.login not in uploads:
            uploads[x.user.login] = (x.user, dict())
        uploads[x.user.login][1].setdefault(x.index, []).append(x)

    for _, handins in uploads.values():
        for i in handins.keys():
            if i in stats: stats[i] += 1
    context = dict(
        the = the, qst = qst, nusers = nusers, stats = stats,
        nav = _build_nav(request.user, the))
    return dutils.render(request, 'uploads_by_questions.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def upload_details_by_login(request, code, subcode, promo, login, index):
    user = dutils.get_object_or_404(dauth.get_user_model(), pk = login)
    the  = get_assignment(request, code, subcode, promo)
    qst  = questions_of_contents(the.contents)

    if index not in qst:
        raise http.Http404('unknown index')

    hdn = models.HandIn.objects \
                .filter(user = user, assignment = the, index = index) \
                .order_by('-date').all()[:]

    context = dict(the = the, index = index, hdns = hdn,
                   nav = _build_nav(request.user, the))

    return dutils.render(request, 'upload_details.html', context)

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

    return dutils.render(request, 'myuploads.html', ctx)

# --------------------------------------------------------------------
@login_required
@dhttp.require_GET
def myupload_details(request, code, subcode, promo, index):
    the = get_assignment(request, code, subcode, promo)
    qst = questions_of_contents(the.contents)

    if index not in qst:
        raise http.Http404('unknown index')

    hdn = models.HandIn.objects \
                .filter(user = request.user, assignment = the, index = index) \
                .order_by('-date').all()[:]

    context = dict(the = the, index = index, hdns = hdn,
                   nav = _build_nav(request.user, the))

    return dutils.render(request, 'myupload_details.html', context)

# --------------------------------------------------------------------
@login_required
@dhttp.require_GET
def download_myupload(request, code, subcode, promo, index):
    the = get_assignment(request, code, subcode, promo)
    qst = questions_of_contents(the.contents)

    if index not in qst:
        raise http.Http404('unknown index')

    hdn = models.HandIn.objects \
                .filter(user = request.user, assignment = the, index = index) \
                .order_by('-date').first()

    if hdn is None:
        raise http.Http404('no uploads')

    resources = models.HandInFile.objects.filter(handin = hdn).all()

    return _download_handin(hdn, resources, inline = False)

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
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def download_all(request, code, subcode, promo):
    the = get_assignment(request, code, subcode, promo)
    handins = models.HandIn.objects \
        .select_related('user', 'assignment') \
        .filter(assignment = the) \
        .defer('log', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
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
        .defer('log', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
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
        .defer('log', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
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
        .defer('log', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
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
        .defer('log', 'assignment__contents', 'assignment__properties', 'assignment__tests') \
        .order_by('-date', 'user__login', 'index') \
        .first()

    if handin is None:
        raise http.Http404('no uploads')

    resources = models.HandInFile.objects.filter(handin = handin).all()

    return _download_handin(handin, resources, inline = True)

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

    if the.end is not None and dt.datetime.now().date() >= the.end:
        messages.error(request,
            'The assignment has been closed')
        return dutils.redirect(url)

    if not files:
        messages.error(request,
            'You must submit at least one file')
        return dutils.redirect(url)

    missing = reqs.difference([x.name for x in files])

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

    _defer_check(str(handin.uuid))

    messages.info(request,
        'Your files for question %d have been submitted' % (index,))

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

        def upload_match(handins):
            def doit(match):
                index = int(match.group(1))
                data  = '<div id="submit-%d" />' % (index,)

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

        def upload_match_nc(match):
            return NO_SUBMIT

        def upload_match_late(match):
            return LATE_SUBMIT

        handins = None
        if self.request.user.is_authenticated:
            if the.end is not None and dt.datetime.now().date() >= the.end:
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

        cache.add(self.get_cache_key(code, subcode, promo, 'header'), header)
        cache.add(self.get_cache_key(code, subcode, promo, 'text'  ), text  )

        return ctx

    def put(self, request, code, subcode, promo):
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
                   contents   = jso['contents'],
                   tests      = [],
                   properties = dict(required = jso.get('required', dict())))

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
    handins = models.HandIn.objects \
                    .select_related('assignment', 'user') \
                    .filter(assignment__code = code, \
                            assignment__subcode = subcode, \
                            assignment__promo = promo) \
                    .filter(Q(status = '') | Q(status = 'errored')) \
                    .order_by('date') \
                    .all()
    for handin in handins:
        _defer_check(str(handin.uuid))

    return http.HttpResponse(str(len(handins)), content_type='text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def recheck_user(request, code, subcode, promo, login):
    handins = dict()

    for handin in \
        models.HandIn.objects \
                     .filter(assignment__code = code, \
                             assignment__subcode = subcode, \
                             assignment__promo = promo) \
                     .filter(user__login = login) \
                     .select_related('assignment', 'user') \
                     .order_by('date') \
                     .all():

        handins.setdefault(handin.index, []).append(handin)

    handins =  { k: v[-1] for k, v in handins.items() }

    for handin in handins.values():
        _defer_check(str(handin.uuid))

    return http.HttpResponse(str(len(handins)), content_type='text/plain')

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def recheck_user_index(request, code, subcode, promo, login, index):
    handin = models.HandIn.objects \
                          .filter(assignment__code = code, \
                                  assignment__subcode = subcode, \
                                  assignment__promo = promo) \
                          .filter(user__login = login, index = index) \
                          .select_related('assignment', 'user') \
                          .order_by('-date') \
                          .first()

    if handin is not None:
        _defer_check(str(handin.uuid))

    return http.HttpResponse('1' if handin else '0', content_type='text/plain')
