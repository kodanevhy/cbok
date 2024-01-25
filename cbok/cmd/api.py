import sys

from oslo_log import log as logging

import cbok.conf
from cbok import config
from cbok import service

CONF = cbok.conf.CONF
LOG = logging.getLogger(__name__)


# TODO(kodanevhy): Provide app enable/disable ability.
def main():
    config.parse_args(sys.argv)
    logging.setup(CONF, 'cbok')
    app = service.load_pipeline_wsgi()

    # Setup server.
    launcher = service.process_launcher()
    api_server = service.WSGIAPIService('cbok_api', app)
    launcher.launch_service(api_server, workers=CONF.api.api_works)
    launcher.wait()


if __name__ == '__main__':
    main()
