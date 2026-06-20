class Option:
    def __init__(self, name, default=None, help="", required=True):
        self.name = name
        self.default = default
        self.help = help
        self.required = required


class Group:
    def __init__(self, name, options, title=None):
        self.name = name
        self.options = options
        self.title = title
