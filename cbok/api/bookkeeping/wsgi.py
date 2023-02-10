import functools
import json
import webob

from oslo_log import log as logging

from cbok import config

LOG = logging.getLogger(__name__)
CONF = config.CONF


def expected_errors(errors):
    """Decorator API methods which specifies expected exceptions.

    Specify which exceptions may occur when an API method is called. If an
    unexpected exception occurs then return a 500 instead and ask the user
    of the API to file a bug report.
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as exc:
                if isinstance(exc, webob.exc.WSGIHTTPException):
                    if isinstance(errors, int):
                        t_errors = (errors,)
                    else:
                        t_errors = errors
                    if exc.code in t_errors:
                        raise

                LOG.exception("Unexpected exception in API method")
                msg = "Exception: %s" % exc
                raise webob.exc.HTTPInternalServerError(explanation=msg)

        return wrapped

    return decorator


def response_code(code):
    """Attaches response code to a method.

    This decorator associates a response code with a method.  Note
    that the function attributes are directly manipulated; the method
    is not wrapped.
    """

    def decorator(func):
        func.code = code
        return func
    return decorator


class BaseController(object):
    """Default Controller."""

    _view_builder_class = None

    def __init__(self):
        """Initialize controller with a view builder instance."""
        if self._view_builder_class:
            self._view_builder = self._view_builder_class()
        else:
            self._view_builder = None

    @webob.dec.wsgify
    def __call__(self, req):
        """Execute action"""
        try:
            action_args = self._get_action_args(req.environ)
            action = action_args.pop('action', None)
            method = self._get_method(action)
            dict_body = method(req, **action_args)
            body = json.dumps(dict_body) if dict_body else None
            code = getattr(method, 'code', 200)
            content_type = 'application/json'
            charset = 'UTF-8'
        except Exception as err:
            raise err

        return webob.Response(body=body, status=code, charset=charset,
                              content_type=content_type)

    def _get_action_args(self, request_environment):
        args = request_environment['wsgiorg.routing_args'][1].copy()

        try:
            del args['controller']
        except KeyError:
            pass

        try:
            del args['format']
        except KeyError:
            pass

        return args

    def _get_method(self, action):
        return getattr(self, action)
