"""CBoK base exception handling.

Includes decorator for re-raising CBoK-type exceptions.

SHOULD include dedicated exception logging.

"""

from oslo_log import log as logging

import webob.exc
from webob import util as woutil


LOG = logging.getLogger(__name__)


class CBoKException(BaseException):
    """Base CBoK Exception

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property. That msg_fmt will get printf'd
    with the keyword arguments provided to the constructor.

    """
    msg_fmt = "An unknown exception occurred."
    code = 500
    headers = {}
    safe = False

    def __init__(self, message=None, **kwargs):
        self.kwargs = kwargs

        if 'code' not in self.kwargs:
            try:
                self.kwargs['code'] = self.code
            except AttributeError:
                pass

        try:
            if not message:
                message = self.msg_fmt % kwargs
            else:
                message = str(message)
        except Exception:
            # NOTE(kodanevhy): This is done in a separate method so it can be
            # monkey-patched during testing to make it a hard failure.
            self._log_exception()
            message = self.msg_fmt

        self.message = message
        super(CBoKException, self).__init__(message)

    def _log_exception(self):
        # kwargs doesn't match a variable in the message
        # log the issue and the kwargs
        LOG.exception('Exception in string format operation')
        for name, value in self.kwargs.items():
            LOG.error("%s: %s" % (name, value))  # noqa

    def format_message(self):
        # NOTE(kodanevhy): use the first argument to the python Exception
        # object which should be our full CBoKException message, (see __init__)
        return self.args[0]

    def __repr__(self):
        dict_repr = self.__dict__
        dict_repr['class'] = self.__class__.__name__
        return str(dict_repr)


class DBNotAllowed(CBoKException):
    msg_fmt = '%(binary)s attempted direct database access which is ' \
              'not allowed by policy'


class Invalid(CBoKException):
    msg_fmt = "Bad Request - Invalid Parameters"
    code = 400


class TradeTypeNotFound(CBoKException):
    msg_fmt = 'Trade type is not found, fixed choice in %(choices)s.'


class MehNotFound(CBoKException):
    msg_fmt = 'Meh %(meh_id)s is not found.'


class IncoherentBillFlow(CBoKException):
    msg_fmt = 'Incoherent, %(vacancy) days are vacancy, it may be necessary ' \
              'to upload a bill flow with a longer cycle.'


class TimeFormatterMismatched(CBoKException):
    msg_fmt = 'Only allow %(formatter) formatter, but mismatching.'


class ObjectActionError(CBoKException):
    msg_fmt = 'Object action %(action)s failed because: %(reason)s'


class MehExists(CBoKException):
    msg_fmt = 'Meh with id %(id)s already exists.'


class MehUUIDExists(CBoKException):
    msg_fmt = 'Meh with ID %(meh_id)s already exists.'


class DecompressFlowFailed(CBoKException):
    msg_fmt = 'Decompress bill flow failed.'


class InvalidLink(Invalid):
    msg_fmt = 'Link %(link)s invalid, there is 3 times for downloading the ' \
              'flow, but failed just 1 time, please upload the absolutely ' \
              'newest link and wait again.'


class InvalidID(Invalid):
    msg_fmt = 'Invalid ID received %(id)s.'


class Forbidden(CBoKException):
    msg_fmt = "Forbidden"
    code = 403
