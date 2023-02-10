from cbok.api.bookkeeping import meh
from cbok import conf

CONF = conf.CONF

ROUTE_TABLE = (
    ('/meh',
     {
         'GET': [meh.MehController, 'index'],
         'POST': [meh.MehController, 'create'],
     }),
    ('/meh/{meh_id}',
     {
         'GET': [meh.MehController, 'show'],
         'PUT': [meh.MehController, 'update'],
         'DELETE': [meh.MehController, 'delete']
     })
)
