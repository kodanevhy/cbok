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
