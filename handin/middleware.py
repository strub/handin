# --------------------------------------------------------------------
from django import shortcuts

# --------------------------------------------------------------------
class Redirect(Exception):
    def __init__(self, url):
        self.url = url

# --------------------------------------------------------------------
def eredirect(url):
    raise Redirect(url)

# --------------------------------------------------------------------
class RedirectMiddleware(object):
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if isinstance(exception, Redirect):
            return shortcuts.redirect(exception.url)
