from oslo_log import log as logging

from cbok.api.bookkeeping import common
import cbok.conf
from cbok import utils

CONF = cbok.conf.CONF


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model a server API response as a python dictionary."""

    _collection_name = 'meh'

    _fault_statuses = (
        "ERROR", "DELETED"
    )

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()

    def create(self, request, instance):
        """View that should be returned when an instance is created."""

        server = {
            "server": {
                "id": instance["uuid"],
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
                # NOTE(sdague): historically this was the
                # os-disk-config extension, but now that extensions
                # are gone, we merge these attributes here.
                "OS-DCF:diskConfig": (
                    'AUTO' if instance.get('auto_disk_config') else 'MANUAL'),
            },
        }
        return server

    def basic(self, request, instance, show_extra_specs=False,
              show_extended_attr=None, show_host_status=None,
              show_sec_grp=None, bdms=None, cell_down_support=False,
              show_user_data=False):
        """Generic, non-detailed view of an instance."""
        if cell_down_support and 'display_name' not in instance:
            # NOTE(tssurya): If the microversion is >= 2.69, this boolean will
            # be true in which case we check if there are instances from down
            # cells (by checking if their objects have missing keys like
            # `display_name`) and return partial constructs based on the
            # information available from the nova_api database.
            return {
                "server": {
                    "id": instance.uuid,
                    "status": "UNKNOWN",
                    "links": self._get_links(request,
                                             instance.uuid,
                                             self._collection_name),
                },
            }
        return {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
            },
        }

    def show(self, meh):
        """Detailed view of a single instance."""

        meh = {
            "meh": {
                "id": meh["uuid"],
                "type": meh["type"],
                "relationship": meh.get("relationship") or "",
                "amount": meh["amount"],
                "description": meh["description"],
                "worthy": meh.get("worthy") or "",
                "ready": meh.get("ready") or "",
                "created": utils.isotime(meh["created_at"]),
                "updated": utils.isotime(meh["updated_at"]),
                "deleted": utils.isotime(meh["deleted_at"]),
            },
        }
        return meh

    def index(self, request, instances, cell_down_support=False):
        """Show a list of servers without many details."""
        coll_name = self._collection_name
        return self._list_view(self.basic, request, instances, coll_name,
                               False, cell_down_support=cell_down_support)

    def detail(self, request, instances, cell_down_support=False):
        """Detailed view of a list of instance."""
        coll_name = self._collection_name + '/detail'

        instance_uuids = [inst['uuid'] for inst in instances]

        # NOTE(gmann): pass show_sec_grp=False in _list_view() because
        # security groups for detail method will be added by separate
        # call to self._add_security_grps by passing the all servers
        # together. That help to avoid multiple neutron call for each server.
        servers_dict = self._list_view(self.show, request, instances,
                                       # We process host_status in aggregate.
                                       show_host_status=False,
                                       show_sec_grp=False,
                                       cell_down_support=cell_down_support)

        return servers_dict

    def _list_view(self, func, request, servers, coll_name, show_extra_specs,
                   show_extended_attr=None, show_host_status=None,
                   show_sec_grp=False, bdms=None, cell_down_support=False):
        """Provide a view for a list of servers.

        :param func: Function used to format the server data
        :param request: API request
        :param servers: List of servers in dictionary format
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query
        :param show_extended_attr: If the server extended attributes should be
                        included in the response dict.
        :param show_host_status: If the host status should be included in
                        the response dict.
        :param show_sec_grp: If the security group should be included in
                        the response dict.
        :param bdms: Instances bdms info from multiple cells.
        :param cell_down_support: True if the API (and caller) support
                                  returning a minimal instance
                                  construct if the relevant cell is
                                  down.
        :returns: Server data in dictionary format
        """
        server_list = [func(request, server,
                            show_extra_specs=show_extra_specs,
                            show_extended_attr=show_extended_attr,
                            show_host_status=show_host_status,
                            show_sec_grp=show_sec_grp, bdms=bdms,
                            cell_down_support=cell_down_support)["server"]
                       for server in servers
                       # Filter out the fake marker instance created by the
                       # fill_virtual_interface_list online data migration.
                       if server.uuid != 'id']
        servers_links = self._get_collection_links(request,
                                                   servers,
                                                   coll_name)
        servers_dict = dict(servers=server_list)

        if servers_links:
            servers_dict["servers_links"] = servers_links

        return servers_dict
