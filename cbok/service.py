from oslo_log import log as logging
from oslo_service import service
from oslo_service import wsgi

from cbok import conf
from cbok.api import wsgi as wsgi_api

LOG = logging.getLogger(__name__)
CONF = conf.CONF

PIPELINE = [wsgi_api.Router]


def load_pipeline_wsgi():
    app = PIPELINE[-1]()
    # NOTE(kodanevhy): we didn't have any other middlewares to wrap yet.
    for wsgi_middleware in PIPELINE[-2::-1]:
        app = wsgi_middleware()
    return app


class WSGIAPIService(service.ServiceBase):
    """Provides ability to launch CBoK API from wsgi app."""

    def __init__(self, name, app):
        """Initialize, but do not start the WSGI server.
        :param name: The name of the WSGI server given to the loader.
        :return: None
        """
        super(WSGIAPIService, self).__init__()
        self.name = name
        self.app = app
        self.server = wsgi.Server(CONF, self.name, self.app,
                                  host=CONF.api.host,
                                  port=CONF.api.port)
        LOG.info("Initialize WSGIAPIService: name: %s", self.name)

    def start(self):
        """Start serving this service using loaded configuration
        :return: None
        """
        LOG.info("Start WSGIService: %s", self.server)
        self.server.start()

    def stop(self):
        """Stop serving this API.
        :return: None
        """
        LOG.info("Stop WSGIAPIService: %s", self.server)
        self.server.stop()

    def wait(self):
        """Wait for the service to stop serving this API.
        :return: None
        """
        LOG.info("Wait for WSGIAPIService: %s", self.server)
        self.server.wait()

    def reset(self):
        """Reset server greenpool size to default.
        :return: None
        """
        LOG.info("Reset WSGIAPIService: %s", self.server)
        self.server.reset()


def process_launcher():
    return service.ProcessLauncher(CONF, restart_method='mutate')
