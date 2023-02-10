from webob import exc

from oslo_log import log as logging

from cbok import config
from cbok import exception
from cbok.api.bookkeeping import wsgi
from cbok.api.bookkeeping.views import meh as views_meh
from cbok.bookkeeping import common
from cbok.bookkeeping import manager

LOG = logging.getLogger(__name__)
CONF = config.CONF


class MehController(wsgi.BaseController):

    _view_builder_class = views_meh.ViewBuilder

    def __init__(self, **kwargs):
        self.meh_api = manager.MehManager()
        super(MehController, self).__init__(**kwargs)

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
        meh_dict = body['meh']

        def _validata_type(m_type):
            if m_type and m_type not in common.MEH_TYPE:
                raise exception.MehTypeNotFound(choices=common.MEH_TYPE)
        meh_type = _validata_type(meh_dict['meh_type'])
        amount = float(meh_dict['amount'])
        try:
            meh = self.meh_api.create_meh(meh_type, amount,
                                          meh_dict['description'],
                                          meh_dict['relationship'])
        except exception.MehNotFound(meh_dict['relationship']) as error:
            raise exc.HTTPNotFound(explanation=error.format_message())

        return {'meh': meh.uuid}

    def update(self):
        pass

    @wsgi.expected_errors(404)
    def delete(self):
        pass
