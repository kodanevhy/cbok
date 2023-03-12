import collections
from urllib import parse as urlparse

from oslo_log import log as logging

import cbok.conf

CONF = cbok.conf.CONF

LOG = logging.getLogger(__name__)


class ViewBuilder(object):
    """Model API responses as dictionaries."""

    def _get_project_id(self, request):
        """Get project id from request url if present or empty string
        otherwise
        """
        project_id = request.environ["nova.context"].project_id
        if project_id and project_id in request.url:
            return project_id
        return ''

    def _get_links(self, request, identifier, collection_name):
        return [{
            "rel": "self",
            "href": self._get_href_link(request, identifier, collection_name),
        },
        {
            "rel": "bookmark",
            "href": self._get_bookmark_link(request,
                                            identifier,
                                            collection_name),
        }]

    def _get_next_link(self, request, identifier, collection_name):
        """Return href string with proper limit and marker params."""
        params = collections.OrderedDict(sorted(request.params.items()))
        params["marker"] = identifier
        prefix = self._update_compute_link_prefix(request.application_url)
        url = url_join(prefix,
                       self._get_project_id(request),
                       collection_name)
        return "%s?%s" % (url, urlparse.urlencode(params))

    def _get_href_link(self, request, identifier, collection_name):
        """Return an href string pointing to this object."""
        prefix = self._update_compute_link_prefix(request.application_url)
        return url_join(prefix,
                        self._get_project_id(request),
                        collection_name,
                        str(identifier))

    def _get_bookmark_link(self, request, identifier, collection_name):
        """Create a URL that refers to a specific resource."""
        base_url = remove_trailing_version_from_href(request.application_url)
        base_url = self._update_compute_link_prefix(base_url)
        return url_join(base_url,
                        self._get_project_id(request),
                        collection_name,
                        str(identifier))

    def _get_collection_links(self,
                              request,
                              items,
                              collection_name,
                              id_key="uuid"):
        """Retrieve 'next' link, if applicable. This is included if:
        1) 'limit' param is specified and equals the number of items.
        2) 'limit' param is specified but it exceeds CONF.api.max_limit,
        in this case the number of items is CONF.api.max_limit.
        3) 'limit' param is NOT specified but the number of items is
        CONF.api.max_limit.
        """
        links = []
        max_items = min(
            int(request.params.get("limit", CONF.api.max_limit)),
            CONF.api.max_limit)
        if max_items and max_items == len(items):
            last_item = items[-1]
            if id_key in last_item:
                last_item_id = last_item[id_key]
            elif 'id' in last_item:
                last_item_id = last_item["id"]
            else:
                last_item_id = last_item["flavorid"]
            links.append({
                "rel": "next",
                "href": self._get_next_link(request,
                                            last_item_id,
                                            collection_name),
            })
        return links

    def _update_link_prefix(self, orig_url, prefix):
        if not prefix:
            return orig_url
        url_parts = list(urlparse.urlsplit(orig_url))
        prefix_parts = list(urlparse.urlsplit(prefix))
        url_parts[0:2] = prefix_parts[0:2]
        url_parts[2] = prefix_parts[2] + url_parts[2]
        return urlparse.urlunsplit(url_parts).rstrip('/')

    def _update_glance_link_prefix(self, orig_url):
        return self._update_link_prefix(orig_url, CONF.api.glance_link_prefix)

    def _update_compute_link_prefix(self, orig_url):
        return self._update_link_prefix(orig_url, CONF.api.compute_link_prefix)
