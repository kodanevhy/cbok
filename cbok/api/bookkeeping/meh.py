from webob import exc

from oslo_log import log as logging

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
    def create(self, req, body):
        """Create meh, support to create a single meh or even batched."""
        if req.link:
            create_kwargs = flow.Flow(req.link).extract_current()
        else:
            create_kwargs = list(body['meh'])

        def _validata_trade_type(m_type):
            if m_type and m_type not in common.TRADE_TYPE:
                raise exception.TradeTypeNotFound(choices=common.TRADE_TYPE)
        batched = []
        for meh_meta in create_kwargs:
            _validata_trade_type(meh_meta['type'])
            common.decimalization_amount(meh_meta)
            try:
                meh = self.meh_api.create_meh(**meh_meta)
            except exception.MehNotFound(meh_meta['relationship']) as error:
                raise exc.HTTPNotFound(explanation=error.format_message())
            batched.append({'meh': meh.uuid})
        return batched

    def update(self):
        pass

    @wsgi.expected_errors(404)
    def delete(self):
        pass
