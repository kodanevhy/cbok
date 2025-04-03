from django import http
from django.middleware import csrf
from django.views.generic import base


class CSRFView(base.View):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def setup(self, request, *args, **kwargs):
        super().setup(request, *args, **kwargs)

    def get(self, request):
        """Achieve CSRF token for involving form request.

        An accepted request should contain `X-CSRFToken` in request header and
        `csrftoken` in request cookie. However, CBoK do not render Django
        template, here given a random token used for request header and
        automatically inserted into the request cookie, ensure that the
        attacker cannot request an absolutely same token later.

        It's better that we protect the cookie as possible as we can, like
        encrypt. And the token must NOT carry it elsewhere, except request
        cookie and request header.

        We should claim valid time of csrf token.
        """
        token = csrf.get_token(request)
        resp = http.JsonResponse({'csrf-header': token})

        # Do not reset csrf into response for storing in browser cookie.
        # If CSRF token was set in cookie, `get_token` will generate a matched
        # token and return, otherwise, `get_token` will generate an absolutely
        # new token and set into response cookie.
        request.META['CSRF_COOKIE_USED'] = False
        resp.set_cookie('csrftoken', token,
                        httponly=True,
                        samesite='Strict',
                        max_age=3600)
        return resp
