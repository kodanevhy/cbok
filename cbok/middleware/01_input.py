import logging
import json

from django import http
from django.http import multipartparser
from django.utils.deprecation import MiddlewareMixin

LOG = logging.getLogger(__name__)


class InputMiddleware(MiddlewareMixin):
    """Part of BadRequest - Invalid parameter"""

    def __init__(self, get_response=None):
        super().__init__(get_response)

    def _capture_400_response(self, request, invalid_form):
        err_msg = dict()
        err_msg['exec_app'] = request.exec_app
        for err_field in invalid_form.errors:
            err_msg['field'] = err_field
            err = invalid_form.errors[err_field]
            err_msg['message'] = err[0]
            err_format = {'Unformed': err_msg}
            return err_format

    def process_request(self, request):
        resolver = request.resolver_match
        form_class = resolver.kwargs.get('form_class')
        if not form_class:
            return

        content_type = request.META.get("CONTENT_TYPE", "")

        if content_type.startswith("application/json"):
            try:
                body = json.loads(request.body.decode("utf-8"))
            except json.JSONDecodeError:
                body = {}
        else:
            # multipart / form-urlencoded
            body = request.POST.dict()
        request.parsed_body = body

        try:
            form = form_class(request.parsed_body)
        except multipartparser.MultiPartParserError as e:
            raise Exception("No request body found in POST")
        if form.is_valid():
            request.form = form
            return

        err_format = self._capture_400_response(request, form)
        LOG.error(err_format)
        return http.HttpResponseBadRequest(json.dumps(err_format))
