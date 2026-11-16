from cbok import exception


class ConfigValidateFailed(exception.CBoKException):
    msg_fmt = ("Config validate failed: %(err_msg)s, please comment out the "
               "whole section if you want to disable the feature")
    code = 400
