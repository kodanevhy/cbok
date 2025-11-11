from cbok import base_exception


class InvalidParam(base_exception.CBoKException):
    msg_fmt = 'Bad Request - Invalid Parameters'
    code = 400


class MalformedURL(base_exception.CBoKException):
    msg_fmt = 'Bad Request - Malformed URL'
    code = 400


class CannotLocateProject(base_exception.CBoKException):
    msg_fmt = 'Cannot locate project'
    code = 400


class ShouldNotVirtualEnv(base_exception.CBoKException):
    msg_fmt = "Shouldn't be in virtual environment"
