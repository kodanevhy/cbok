from oslo_log import log as logging
from webob import exc

from cbok import config
from cbok import exception
from cbok.api.bookkeeping import wsgi
from cbok.api.bookkeeping.views import meh as views_meh
from cbok.bookkeeping import common
from cbok.bookkeeping import flow
from cbok.bookkeeping import manager

LOG = logging.getLogger(__name__)
CONF = config.CONF


class MehController(wsgi.BaseController):

    _view_builder_class = views_meh.ViewBuilder

    def __init__(self, **kwargs):
        self.meh_api = manager.MehManager()
        super(MehController, self).__init__(**kwargs)

    def index(self, req):
        pass

    @wsgi.expected_errors(404)
    def show(self, req, meh_id):
        try:
            meh = self.meh_api.get_meh(meh_id)
        except exception.MehNotFound(meh_id) as error:
            raise exc.HTTPNotFound(exception=error.format_message())
        response = self._view_builder.show(meh)
        return response

    @wsgi.expected_errors(404)
    def create(self, req):
        """Create meh, support to create a single meh or even batched."""
        create_body = req.json
        flow_link = create_body.get('link', '')
        if flow_link:
            create_kwargs = flow.Flow(flow_link).extract_current()
        else:
            create_kwargs = [create_body]

        batched = []
        for meh_meta in create_kwargs:
            meh = self.meh_api.create_meh(**meh_meta)
            batched.append({'meh': meh.uuid})
        return batched

    def update(self):
        pass

    @wsgi.expected_errors(404)
    def delete(self):
        pass
