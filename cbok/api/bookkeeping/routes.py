from routes import Mapper
from routes import middleware
import webob

from cbok.api.bookkeeping import catkin
from cbok import conf

CONF = conf.CONF

ROUTE_TABLE = (
    ('/catkin',
     {
         'GET': [catkin.CatkinController, 'show'],
         'POST': [catkin.CatkinController, 'create'],
         'PUT': [catkin.CatkinController, 'update'],
         'DELETE': [catkin.CatkinController, 'delete']
     }),
)


class RouterMiddleware(object):
    """WSGI middleware that maps incoming requests to WSGI apps."""

    @staticmethod
    def _register_routes(mapper):
        for path, methods in ROUTE_TABLE:
            for method, controller_info in methods.items():
                controller = controller_info[0]()
                action = controller_info[1]
                prefix = '/{api_url}'.format(api_url=CONF.api.api_url)
                mapper.connect('%s%s' % (prefix, path),
                               conditions=dict(method=[method]),
                               controller=controller,
                               action=action)

        # Register special routes.
        # controller = server.HealthyController()
        # mapper.connect('/healthy',
        #                conditions=dict(method=['GET']),
        #                controller=controller,
        #                action='show')

    def __init__(self):
        """Register routes"""
        self.map = Mapper()
        self._register_routes(self.map)
        self._router = middleware.RoutesMiddleware(self._dispatch, self.map)

    @webob.dec.wsgify
    def __call__(self, req):
        """Route the incoming request to a controller based on self.map.

        If no match, return a 404.

        """
        return self._router

    @staticmethod
    @webob.dec.wsgify
    def _dispatch(req):
        """Dispatch the request to the appropriate controller.

        Called by self._router after matching the incoming request to a route
        and putting the information into req.environ.  Either returns 404
        or the routed WSGI app's response.

        """
        match = req.environ['wsgiorg.routing_args'][1]
        if not match:
            return webob.exc.HTTPNotFound()
        app = match['controller']
        return app
