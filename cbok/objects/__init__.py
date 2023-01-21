# NOTE(kodanevhy): You may scratch your head as you see code that imports
# this module and then accesses attributes for objects such as Instance,
# etc, yet you do not see these attributes in here. Never fear, there is
# a little bit of magic. When objects are registered, an attribute is set
# on this module automatically, pointing to the newest/latest version of
# the object.


def register_all():
    # NOTE(kodanevhy): You must make sure your object gets imported in this
    # function in order for it to be registered by services that may need
    # to receive it via RPC.
    __import__('cbok.objects.catkin')
    __import__('cbok.objects.meh')
