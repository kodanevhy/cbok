def action_description(desc):
    def wrapper(func):
        func._description = desc
        return func
    return wrapper


def args(*arg_args, **arg_kwargs):
    def wrapper(func):
        if not hasattr(func, "_args"):
            func._args = []
        func._args.append((arg_args, arg_kwargs))
        return func
    return wrapper


def requires_remote_scriptlet(address_kw="address"):
    """
    Mark a command method that will run remote shell requiring scriptlet.
    The dispatcher will call BaseCommand.ensure_remote_scriptlet(kwargs[address_kw])
    once before invoking the command.
    """
    def wrapper(func):
        func._requires_remote_scriptlet = address_kw
        return func
    return wrapper
