#!/usr/bin/env python

# Purify CBoK cuz it includes large files such as images, cache file etc.
# and achieve CBoK in optional.

import os

from oslo_concurrency import processutils

cbok_main = '~/Workspace/PycharmProjects/me/cbok/'
cbok_backup = os.path.join(os.path.dirname(cbok_main), 'cbok_bak')
gitignore_path = os.path.join(cbok_backup, '.gitignore')


def execute(cmd):
    return processutils.execute(*cmd)


class GitIgnoreParser(object):

    def __init__(self, achieved=False):
        self.achieved = achieved
        self.protected = []
        self.recursion_result = []
        self.recursion_result_directory = []

    def recursion_directory(self, dirpath):
        files = os.listdir(dirpath)
        for fi in files:
            fi_d = os.path.join(dirpath, fi)
            if os.path.isdir(fi_d):
                self.recursion_directory(fi_d)
            else:
                self.recursion_result.append(os.path.join(dirpath, fi_d))
        return self.recursion_result

    def list_all_directories(self, dirpath):
        files = os.listdir(dirpath)
        for fi in files:
            fi_d = os.path.join(dirpath, fi)
            if os.path.isfile(fi_d):
                continue
            else:
                self.recursion_result_directory.append(fi_d)
                self.list_all_directories(fi_d)
        return self.recursion_result_directory

    @staticmethod
    def _exist():
        return True if os.path.exists(gitignore_path) else False

    @staticmethod
    def _do_backup():
        cmd = ['cp', '-r', cbok_main, cbok_backup]
        execute(cmd)

    @staticmethod
    def _do_achieve():
        cmd = ['tar', 'zcvf',
               os.path.join(os.path.dirname('cbok_main'), 'cbok.tar.gz'),
               cbok_backup]
        execute(cmd)

    def _purify(self):
        if not self._exist():
            raise FileNotFoundError('Cannot find gitignore file'
                                    ' in %(filepath)s', gitignore_path)

        for directory in self.list_all_directories(cbok_backup):
            if directory.endswith('__pycache__'):
                os.removedirs(directory)

        with open(cbok_backup.join('.gitignore'), 'r') as ig_file:
            for entry in ig_file.readlines():
                if not entry:
                    continue
                if entry.startswith('!'):
                    self.protected.append(cbok_backup.join(entry[1:]))

        with open(cbok_backup.join('.gitignore'), 'r') as ig_file:
            for entry in ig_file.readlines():
                if not entry:
                    continue
                if not entry.startswith('!'):
                    _abs = cbok_backup.join(entry)
                    # Some files in a directory.
                    if _abs.endswith('*'):
                        for result in self.recursion_directory(_abs[:-1]):
                            if result not in self.protected:
                                os.remove(result)
                    # A single file.
                    elif os.path.isfile(_abs):
                        os.remove(_abs)
                    # A directory but not be ignored, that mean all file
                    # in the directory should be removed.
                    else:
                        os.removedirs(_abs)

    def purify(self):
        self._do_backup()
        self._purify()
        if self.achieved:
            self._do_achieve()
            os.removedirs(cbok_backup)


if __name__ == '__main__':
    GitIgnoreParser(achieved=True).purify()
