from oslo_log import log as logging

from cbok import config
from cbok.api import wsgi

LOG = logging.getLogger(__name__)
CONF = config.CONF


class CatkinController:
    @wsgi.expected_errors(404)
    @wsgi.response_code(204)
    def show(self):
        pass

    @wsgi.response_code(204)
    def create(self, count, source, relationship):

        pass

    def update(self):
        pass

    @wsgi.expected_errors(404)
    def delete(self):
        pass
