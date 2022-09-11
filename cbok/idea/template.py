import os

import cbok

CONF = cbok.conf.CONF

FILE_FORMAT_CHAR_MAP = {'txt': '[]', 'md': '# '}
FILE_FORMAT = [suffix for suffix in FILE_FORMAT_CHAR_MAP]


class Template:
    """Common class for idea template.

    The class would create a file including idea options from
    user-customized configuration into the workspace directory.

    :param filename: The filename of idea template comes from idea api.
    """

    def __init__(self, filename):
        self._ensure_filename(filename)
        self.file_format = self.filename.split('.')[-1]

    def _ensure_filename(self, filename):
        # NOTE(mizar): The filename may be formatted to 'a.b',
        # so here it adds a prefix and replaces '.' to '_'.
        if filename.split('.')[-1] not in FILE_FORMAT:
            # TODO(mizar): Log a warning message for the none prefix file.
            self.filename = filename.replace('.', '_') + FILE_FORMAT[0]

    def create(self):
        try:
            # NOTE(mizar): 'with open' may not create upper directory
            # automatically.
            if not os.path.exists(CONF.workspace):
                os.mkdir(CONF.workspace)
            else:
                if os.listdir(CONF.workspace):
                    raise Exception('The workspace directory %(workspace)s '
                                    'already exists and may not be empty.' %
                                    {'workspace': CONF.workspace})

            abs_workspace = os.path.join(CONF.workspace_abs_path,
                                         CONF.workspace)
            enter_line = '\n' * 2
            for entry in CONF.entry:
                if self.file_format == FILE_FORMAT[0]:
                    entry = FILE_FORMAT_CHAR_MAP.get(self.file_format)[0] + \
                            entry + FILE_FORMAT_CHAR_MAP.get(self.file_format)[1]
                else:
                    entry = FILE_FORMAT_CHAR_MAP.get(self.file_format) + entry
                with open(os.path.join(abs_workspace, self.filename), 'a+',
                          encoding='utf-8') as f:
                    f.write(entry + enter_line)
        except Exception as e:
            raise 'Unexpected exception occurred: %(message)s.' % \
                  {'message': e}

    def update(self):
        pass
