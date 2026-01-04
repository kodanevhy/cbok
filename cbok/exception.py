import logging

LOG = logging.getLogger(__name__)


class CBoKException(Exception):
    """Base cbok Exception.

    To correctly use this class, inherit from it and define
    a 'msg_fmt' property. That msg_fmt will get printf'd
    with the keyword arguments provided to the constructor.

    """
    msg_fmt = 'An unknown exception occurred.'
    code = 500

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
            # NOTE: This is done in a separate method, so it can be
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
            LOG.error('%s: %s' % (name, value))  # noqa

    def format_message(self):
        # NOTE: use the first argument to the python Exception object
        # which should be our full CBoKException message, (see __init__)
        return self.args[0]

    def __repr__(self):
        dict_repr = self.__dict__
        dict_repr['class'] = self.__class__.__name__
        return str(dict_repr)


class InvalidParam(CBoKException):
    msg_fmt = 'Bad Request - Invalid Parameters'
    code = 400


class MalformedURL(CBoKException):
    msg_fmt = 'Bad Request - Malformed URL'
    code = 400


class CannotLocateProject(CBoKException):
    msg_fmt = 'Cannot locate project'
    code = 400


class ShouldNotVirtualEnv(CBoKException):
    msg_fmt = "Shouldn't be in virtual environment"


class ConfigValidateFailed(CBoKException):
    msg_fmt = "Config validate failed: %(err_msg)s, please comment out the "\
              "whole section if you want to disable the feature"
    code = 400
