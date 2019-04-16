# --------------------------------------------------------------------
import sys, os, re, datetime as dt, tempfile, zipfile

import django.http as http
import django.views as views
import django.urls as durls
import django.utils.decorators as udecorators
from   django.views.decorators import http as dhttp
from   django.views.decorators import csrf as dcsrf
from   django.db.models import Max
import django.contrib.auth as dauth
from   django.contrib.auth.decorators import login_required, permission_required
import django.shortcuts as dutils
import django.utils as utils, django.utils.timezone
import django.db as db
from   django.core.cache import cache
from   django.core.files.base import ContentFile
from   django.core.files.storage import default_storage

from . import models

# --------------------------------------------------------------------
REIDENT = r'^[a-zA-Z0-9]+$'

SCHEMA = dict(
    type       = 'object',
    properties = dict(
        code      = dict(type = 'string', pattern = REIDENT, minLength = 1),
        subcode   = dict(type = 'string', pattern = REIDENT, minLength = 1),
        promo     = dict(type = 'number', minimum = 1794),
        contents  = dict(type = 'string'),
        resources = dict(
            type  = 'array',
            items = dict(
                type       = 'object',
                properties = dict(
                    name     = dict(type = 'string', pattern = r'^[^\\]+$'),
                    contents = dict(type = 'string')
                )
            )
        )
    ),
    required = ['code', 'subcode', 'promo', 'contents', 'resources'],
)

# --------------------------------------------------------------------
FORM = r'''
<form class="form" method="post" enctype="multipart/form-data"
      action="handins/%(index)d/">

  <div class="form-group">
    <div class="input-group input-file" name="file">
      <span class="input-group-btn">
        <button class="btn btn-default btn-choose" type="button">Choose</button>
      </span>
      <input type="text" class="form-control" placeholder='Choose a file...' readonly="readonly" />
      <span class="input-group-btn">
        <button class="btn btn-primary" type="submit">Submit</button>
      </span>
    </div>
  </div>
</form>
'''

LAST_SUBMIT = '<div class="alert alert-info">Last submission: %s</div>'

# --------------------------------------------------------------------
def questions_of_contents(contents):
    qst = re.findall(r'<\!--\s*UPLOAD:(\d+)\s*-->', contents)
    return sorted([int(x) for x in qst])

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
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def assignments(request):
    assgns   = models.Assignment.objects
    assgns   = assgns.order_by('code', 'subcode', 'promo')[:]
    context  = dict(assignments = assgns)

    return dutils.render(request, 'assignments.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads(request, code, subcode, promo):
    key = dict(code=code, subcode=subcode, promo=promo)
    the = dutils.get_object_or_404(models.Assignment, **key)
    qst = questions_of_contents(the.contents)

    lst = models.HandIn.objects \
        .filter(assignment = the) \
        .select_related('user') \
        .order_by('user__login', 'index', '-date') \
        .all()

    users = dict()
    for x in lst:
        if x.user.login not in users:
            users[x.user.login] = x.user

    uploads = dict()
    for x in lst:
        if x.user.login not in uploads:
            uploads[x.user.login] = (x.user, dict())
        uploads[x.user.login][1].setdefault(x.index, []).append(x)

    pct = { x: 0 for x in qst }

    for _, handins in uploads.values():
        for i in handins.keys():
            if i in pct: pct[i] += 1
    if len(users) > 0:
        pct = { x: y / float(len(users)) for x, y in pct.items() }

    context = dict(
        the = the, qst = qst, users = users, pct = pct,
        uploads = uploads, nav = dict(asgn = the, uploads = the))
    return dutils.render(request, 'uploads.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def uploads_by_questions(request, code, subcode, promo):
    key = dict(code=code, subcode=subcode, promo=promo)
    the = dutils.get_object_or_404(models.Assignment, **key)
    qst = questions_of_contents(the.contents)

    lst = models.HandIn.objects \
        .filter(assignment = the) \
        .select_related('user') \
        .order_by('user__login', 'index', '-date') \
        .all()

    nusers  = len(set([x.user.login for x in lst]))
    pct     = { x: 0 for x in qst }
    uploads = dict()

    for x in lst:
        if x.user.login not in uploads:
            uploads[x.user.login] = (x.user, dict())
        uploads[x.user.login][1].setdefault(x.index, []).append(x)

    for _, handins in uploads.values():
        for i in handins.keys():
            if i in pct: pct[i] += 1
    if nusers > 0:
        pct = { x: y / float(nusers) for x, y in pct.items() }

    context = dict(
        the = the, qst = qst, nusers = nusers, pct = pct,
        nav = dict(asgn = the, uploads = the))
    return dutils.render(request, 'uploads_by_questions.html', context)

# --------------------------------------------------------------------
@login_required
@permission_required('upload.admin', raise_exception=True)
@dhttp.require_GET
def upload_by_user_index(request, code, subcode, promo, index, login):
    key = dict(code=code, subcode=subcode, promo=promo)
    the = dutils.get_object_or_404(models.Assignment, **key)

    handin = models.HandIn.objects \
        .filter(assignment = the, index = index, user__login = login) \
        .order_by('-date') \
        .first()

    if handin is None:
        return http.HttpResponseNotFound()

    resources = models.HandInFile.objects.filter(handin = handin).all()

    if len(resources) == 0:
        return http.HttpHttpResponseNotFound()

    if len(resources) == 1:
        response = http.FileResponse(
            resources[0].contents.open(), content_type = 'text/plain')
        response['Content-Disposition'] = 'inline'
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
        fname = '%s-%s-%s-%d-%d.zip' % (login, code, subcode, promo, index)
        fname = ''.join([x for x in fname if x.isalnum() or x in '-.'])
        response['Content-Disposition'] = 'attachment; filename="%s"' % (fname,)
        return response

    finally:
        os.remove(tmp.name)

# --------------------------------------------------------------------
@login_required                 # FIXME
@dhttp.require_POST
@udecorators.method_decorator(dcsrf.csrf_exempt) # FIXME
def handin(request, code, subcode, promo, index):
    key = dict(code=code, subcode=subcode, promo=promo)
    the = dutils.get_object_or_404(models.Assignment, **key)

    if 'file' in request.FILES:
        with db.transaction.atomic():
            handin = models.HandIn(
                user       = request.user,
                assignment = the,
                index      = index,
                date       = dt.datetime.now(),
            )
            handin.save()

            for stream in request.FILES.getlist('file'):
                data = b''.join(stream.chunks()) # FIXME
                recd = models.HandInFile(
                    handin   = handin,
                    name     = stream.name,
                )
                recd.contents.save(stream.name, ContentFile(data))
                recd.save()

    url = dutils.reverse \
        ('upload:assignment', args=(code, subcode, promo))
    url = url + '#submit-%d' % (index,)

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

    def get_context_data(self, code, subcode, promo, *args, **kw):
        from .templatetags.pandoc_filter import pandoc_gen

        ctx = super().get_context_data(*args, **kw)
        key = dict(code=code, subcode=subcode, promo=promo)
        the = dutils.get_object_or_404(models.Assignment, **key)
        oth = models.Assignment.objects.filter \
                  (code=code, promo=promo).order_by('subcode').values('subcode')
        oth = [x['subcode'] for x in oth]

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
                    date  = handins[index]
                    date  = date.astimezone(utils.timezone.get_current_timezone())
                    date  = date.strftime('%B %d, %Y (%H:%M:%S)')
                    data += LAST_SUBMIT % (utils.html.escape(date),)
                data += FORM % (dict(index = index))
                return data

            return doit

        handins = None
        if self.request.user.is_authenticated:
            handins = models.HandIn.objects \
                .filter(assignment = the, user = self.request.user) \
                .values('index') \
                .annotate(lastdate = Max('date')) \
                .values('index', 'lastdate') \
                .all()[:]
            handins = { int(x['index']): x['lastdate'] for x in handins }

            text = re.sub(r'<\!--\s*UPLOAD:(\d+)\s*-->', upload_match(handins), text)

        ctx['the'     ] = the
        ctx['nav'     ] = dict(oth = (the, oth), uploads = the)
        ctx['handins' ] = handins
        ctx['contents'] = dict(header = header, text = text)

        cache.add(self.get_cache_key(code, subcode, promo, 'header'), header)
        cache.add(self.get_cache_key(code, subcode, promo, 'text'  ), text  )

        return ctx

    def put(self, request, code, subcode, promo):
        import json, jsonschema, mimeparse as mp, base64, binascii, magic

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

        key = dict(code=code, subcode=subcode, promo=promo)
        dfl = dict(contents = jso['contents'])

        mime = magic.Magic(mime = True)

        with db.transaction.atomic():
            asg, _ = models.Assignment.objects.update_or_create(dfl, **key)
            asg.resource_set.all().delete()
            for res in jso['resources']:
                ctype = mime.from_buffer(res['contents'])
                ctype = ctype if ctype else 'application/octet-stream'

                ores = models.Resource(
                    name       = res['name'],
                    ctype      = ctype,
                    assignment = asg,
                )
                ores.contents.save(res['name'], ContentFile(res['contents']))
                ores.save()

        for extra in self.EXTRA:
            cache.delete(self.get_cache_key(code, subcode, promo, extra))

        return http.HttpResponse("OK\r\n")

# --------------------------------------------------------------------
@dhttp.require_GET
def resource(requet, code, subcode, promo, name):
    key = dict(code=code, subcode=subcode, promo=promo)
    the = dutils.get_object_or_404(models.Assignment, **key)
    key = dict(assignment=the, name=name)
    the = dutils.get_object_or_404(models.Resource, **key)
    rep = http.FileResponse(the.contents.open(), content_type = the.ctype)

    rep['Content-Disposition'] = 'inline'; return rep
