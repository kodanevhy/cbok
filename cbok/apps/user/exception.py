from cbok.base_exception import CBoKException


class UserExists(CBoKException):
    msg_fmt = 'User %(username)s already exists'
    code = 400


class UserNotFound(CBoKException):
    msg_fmt = 'User %(username)s not found'
    code = 404


class UserAlreadyLogin(CBoKException):
    msg_fmt = 'User %(username)s already login'
