# --------------------------------------------------------------------
import urllib as ul, urllib.request, urllib.parse
import mimeparse as mp, json, jsonschema

from .models import User

# --------------------------------------------------------------------
SCHEMA = dict(
    type       = 'object',
    properties = dict(
        login     = dict(type = 'string', minLength = 1),
        firstname = dict(type = 'string', minLength = 1),
        lastname  = dict(type = 'string', minLength = 1),
        cls       = dict(type = 'string', pattern = r'^[a-zA-Z0-9.-]+$'),
        ou        = dict(type = 'string', minLength = 1),
    ),
    required = ['login', 'firstname', 'lastname', 'cls', 'ou'],
)

# --------------------------------------------------------------------
class XLDAPBackend(object):
    URL = 'https://www.enseignement.polytechnique.fr/informatique/sso/sso.php'

    def authenticate(self, request=None, **credentials):
        login    = credentials.get('username', None)
        password = credentials.get('password', None)

        if login is None or password is None:
            return None
        
        data = dict(login=login, password=password)
        data = ul.parse.urlencode(data).encode('utf-8')
        req  = ul.request.Request(self.URL, data=data)

        req.add_header('Content-Type', 'application/x-www-form-urlencoded; charset=utf-8')
        req.add_header('Accept', 'application/json')

        try:
            with ul.request.urlopen(req) as response:
                ctype = response.info().get_content_type() or ''
                mtype, msub, mdata = mp.parse_mime_type(ctype)
                charset = mdata.get('charset', 'utf-8')

                if (mtype, msub) != ('application', 'json'):
                    return None

                data = response.read().decode(charset)
                data = json.loads(data)

                jsonschema.validate(data, SCHEMA)

                if data['login'] != login:
                    return None

        except (ul.error.HTTPError, ul.error.URLError,
                json.decoder.JSONDecodeError,
                jsonschema.exceptions.ValidationError,
                UnicodeDecodeError) as e:

            print(e); return None

        user = User(
            login     = data['login'],
            email     = '%s@polytechnique.edu' % (data['login'],),
            firstname = data['firstname'],
            lastname  = data['lastname'],
            ou        = data['ou'],
            cls       = data['cls'],
        )
        user.save()

        return user

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None 
