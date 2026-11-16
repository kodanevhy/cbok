from cbok import exception


class NoDiffBetweenHead(exception.CBoKException):
    msg_fmt = "no diff between with your commit and HEAD"


class AnalysisCommitFailed(exception.CBoKException):
    msg_fmt = 'Failed to analysis %(project)s commit'


class InitPodFailed(exception.CBoKException):
    msg_fmt = 'Failed to initial pod: %(service)s'


class CopyChangesFailed(exception.CBoKException):
    msg_fmt = 'Failed to copy changes'


class FinalizeStartupFailed(exception.CBoKException):
    msg_fmt = 'Failed to finalize startup'


class NoSuchImage(exception.CBoKException):
    msg_fmt = 'No such image: %(image)s'


class ProxyBypassError(exception.CBoKException):
    pass


class RepositorySyncError(exception.CBoKException):
    pass


class AgentReplaceError(exception.CBoKException):
    pass


class CompileDeployStateError(exception.CBoKException):
    pass


class GroovyTestSetupError(exception.CBoKException):
    pass


class ZsvHostDiscoveryError(exception.CBoKException):
    pass


class ZsvAlreadyUpToDateError(exception.CBoKException):
    pass


class ZsvArtifactMetadataError(exception.CBoKException):
    pass


class ZsvSshConnectionError(exception.CBoKException):
    def __init__(self, message, returncode):
        super().__init__(message)
        self.returncode = returncode


class ZsvSchemaChecksumMismatchError(exception.CBoKException):
    def __init__(self, message: str, returncode: int = 1):
        self.returncode = returncode
        super().__init__(message)
