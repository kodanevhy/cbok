import itertools
import os
import shutil
from tempfile import mkdtemp
import time
import zipfile
import zlib

from oslo_concurrency import processutils
from oslo_log import log as logging
import pandas

from cbok import exception
from cbok import utils
from cbok.bookkeeping import common
from cbok.objects import meh


LOG = logging.getLogger(__name__)


def execute(cmd):
    return processutils.execute(*cmd)


class Flow:
    def __init__(self, link):
        self.link = link
        self.csv_path = None
        self.target_dir = None
        self.earliest = '9999-12-31 23:59:59'

    def localize(self, link):
        """Download and VIOLENTLY decompress the bill flow file."""
        self.target_dir = mkdtemp(suffix='.cbok.flow')
        target_unzipped = os.path.join(self.target_dir, 'unzipped')
        compressed_target = os.path.join(self.target_dir, 'wechat.zip')
        cmd = ['wget', link, '-O', compressed_target]
        execute(cmd)
        # Note(koda): WeChat just allow user to download the bill for 3 times,
        # if exceeded, it will return an HTML error page.
        # TODO(koda): mention client don't download flow by itself.
        if not zipfile.is_zipfile(compressed_target):
            raise exception.InvalidLink(link=link)
        unzip_start = time.time()
        meta_chars = '0123456789'
        for char in itertools.product(meta_chars, repeat=6):
            password = ''.join(char)
            try:
                with zipfile.ZipFile(compressed_target) as zf:
                    if os.path.exists(target_unzipped):
                        shutil.rmtree(target_unzipped)
                    zf.extractall(target_unzipped,
                                  pwd=password.encode('utf-8'))
            except (RuntimeError, zlib.error, zipfile.BadZipFile):
                # Note(koda): It will raise a RuntimeError when achieving a
                # bad password for file, means that uncompress the file
                # failed, passing now and let it continue to process the next
                # try. The other errors are expected when unzipping.
                pass
            except Exception as err:
                shutil.rmtree(target_unzipped)
                raise err
            else:
                self.csv_path = common.recursion_directory(target_unzipped)[0]
                if not self.csv_path:
                    raise exception.DecompressFlowFailed()
                LOG.info('Compress flow successfully with password '
                         '%(password)s in %(duration).2f seconds, and generate '
                         'target flow %(path)s.',
                         {'password': password,
                          'duration': (time.time() - unzip_start),
                          'path': self.csv_path})
                break

    def _process_flow(self):
        # Note(koda): Shit tencent mistake: lack 2 ',' in bill flow,
        # result in parsing cells failed.
        with open(self.csv_path, 'r') as fr:
            line = fr.read()
            replaced = line.replace(',,,,,,,,', ',,,,,,,,,,')
            with open(self.csv_path, 'w') as fw:
                fw.write(replaced)

        csv = pandas.read_csv(self.csv_path)
        shutil.rmtree(self.target_dir)
        aggregate = list()
        for index, row in csv.iterrows():
            create_kwargs = dict()
            # Note(koda): The order of the list is absolutely according to
            # the tencent bill flow, so FORBIDDEN to change the order of the
            # follow list.
            init = ['trade_date',
                    'transaction',
                    'counterparty',
                    'commodity',
                    'trade_type',
                    'amount',
                    'payment_method',
                    'trade_state']
            try:
                utils.strtime(row[0])
            except (ValueError, TypeError):
                # Note(koda): There are many redundant lines at the head
                # of tencent bill flow, ignore those lines here.
                pass
            else:
                if utils.strtime(row[0]) < utils.strtime(self.earliest):
                    self.earliest = row[0]
                for i, item in enumerate(init):
                    create_kwargs[init[i]] = row[i]
                aggregate.append(create_kwargs)
        return aggregate

    def extract_current(self):
        """Get the meh only behind the nearest trade date of database."""
        self.localize(self.link)
        try:
            trade_date_db = meh.Meh.nearly_one().trade_date
        except AttributeError:
            LOG.warning('No any meh found in database, maybe it is '
                        'the first time to add bill flow, so here pass '
                        'now without checking the stock.')
            trade_date_db = None

        processed_flow = self._process_flow()
        if trade_date_db:
            vacancy = utils.strtime(self.earliest).tm_yday - \
                utils.strtime(trade_date_db).tm_yday
            if vacancy > 1:
                raise exception.IncoherentBillFlow(vacancy=vacancy)

        current_flow = list()
        for entry in processed_flow:
            if not trade_date_db:
                current_flow.append(entry)
            elif utils.strtime(entry.get('trade_date')) > \
                    utils.strtime(trade_date_db):
                current_flow.append(entry)
        return current_flow
