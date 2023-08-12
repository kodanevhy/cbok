from webob import exc

from cbok import exception
from cbok.api import common
from cbok.api.bookkeeping import wsgi
from cbok.bookkeeping import capers


class CaperController(wsgi.BaseController):
    def __init__(self, **kwargs):
        super(CaperController, self).__init__(**kwargs)

    def index(self, req, caper_id):
        pass

    def show(self, req, caper_uuid):
        try:
            caper = common.get_caper(caper_uuid)
        except exception.CaperNotFound as error:
            raise exc.HTTPNotFound(exception=error.format_message())
        return caper

    def create(self, req):
        create_kwargs = req.json['caper']
        return capers.create(create_kwargs)

    def update(self, req, caper_id):
        pass

    def delete(self, req, caper_id):
        pass
