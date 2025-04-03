import importlib
import inspect
import logging

from django import http
from django.utils.deprecation import MiddlewareMixin

from cbok.exceptions import base_exception

LOG = logging.getLogger(__name__)


class ExcMiddleware(MiddlewareMixin):
    """Global capturing of all service errors.

    All service exceptions are classified according to the app. If exception
    occurs in an application service, an attempt will be made to capture it in
    the exceptions in the current application and the main application. If it
    cannot be captured, a message of `Uncontrollable exception` will be logged,
    means that raising the exception from the other applications.

    NOTE: Only support the exceptions in services, any cases as follows would
    not be captured, and raised 500 by Django.
    * exceptions in middleware.
    * exceptions caused by non-standard use of Django, sometimes.
    """

    def __init__(self, get_response=None):
        super().__init__(get_response)
        self.main_exc_module = importlib.import_module(
            'cbok.exceptions')
        self.supported = {
            400: http.HttpResponseBadRequest,
            404: http.HttpResponseNotFound,
            # unexpected exception or general service error without
            # claiming code
            500: http.HttpResponseServerError
        }
        self.uncontrollable = False

    def process_exception(self, request, exception):
        try:
            app_exc_module = importlib.import_module(
                '%s.exceptions' % request.exec_app)
        except ModuleNotFoundError:
            app_exc_module = None

        in_module = [app_exc_module, self.main_exc_module] \
            if app_exc_module else [self.main_exc_module]

        for m in in_module:
            err_matched = self._handle_exception(m, exception)
            if isinstance(err_matched, http.HttpResponse):
                return err_matched

    def _log_uncontrollable(self, exc):
        """Unexpected executing the other app's exception"""

        self.uncontrollable = True
        LOG.warning('Uncontrollable exception %s' %
                    exc.__class__.__name__)

    def _map_http_resp(self, exc_service):
        if self.uncontrollable:
            return self.supported[500]

        if not hasattr(exc_service, 'code'):
            raise

        code = exc_service.code
        if code not in self.supported:
            LOG.warning('Unsupported exception code')
            raise

        http_exc = self.supported[code]
        format_msg = exc_service.format_message()
        LOG.exception(format_msg)
        return http_exc(format_msg)

    def _handle_exception(self, exc_module, exc):
        for name, cls in inspect.getmembers(exc_module):
            # Only reserve subclasses of service base exception,
            # and except for base itself.
            if not issubclass(type(cls), type) or \
                    not issubclass(cls, base_exception.CBoKException):
                continue
            if name == base_exception.CBoKException.__name__:
                continue

            if isinstance(exc, cls):
                return self._map_http_resp(exc)

        # Already iterated all exceptions from the current and main
        # application, but still not be captured.
        if exc_module == self.main_exc_module:
            if issubclass(type(exc), base_exception.CBoKException):
                self._log_uncontrollable(exc)
            return self._map_http_resp(exc)
