import functools
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
