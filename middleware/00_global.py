import re

from django.urls import resolve
from django.utils.deprecation import MiddlewareMixin
from oslo_utils import uuidutils

from cbok import utils


class GlobalMiddleware(MiddlewareMixin):
    """Capture global something into request.

    * Resolve URL
    * Request ID
    * Current application name
    * Cleaned form
    """

    def __init__(self, get_response=None):
        super().__init__(get_response)

    def generate_r_id(self):
        uuid_str = uuidutils.generate_uuid()
        return f'req-{uuid_str}'

    def process_request(self, request):
        resolver = resolve(request.path_info)
        request.resolver_match = resolver

        request.request_id = self.generate_r_id()

        # Retrieve app name from path in request
        matched = re.search(r'/(?P<app>[^/]+)/', request.path)
        if matched:
            app = matched.group('app')
            request.exec_app = app
            if app not in utils.applications():
                # If request out of apps, means execute the main
                request.exec_app = 'cbok'

        request.form = None
