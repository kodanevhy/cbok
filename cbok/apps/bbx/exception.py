from cbok.base_exception import CBoKException


class NoDiffBetweenHead(CBoKException):
    msg_fmt = "no diff between with your commit and HEAD"


class AnalysisCommitFailed(CBoKException):
    msg_fmt = 'Failed to analysis %(project)s commit'


class InitPodFailed(CBoKException):
    msg_fmt = 'Failed to initial pod: %(service)s'


class CopyChangesFailed(CBoKException):
    msg_fmt = 'Failed to copy changes'


class FinalizeStartupFailed(CBoKException):
    msg_fmt = 'Failed to finalize startup'


class NoSuchImage(CBoKException):
    msg_fmt = 'No such image: %(image)s'
