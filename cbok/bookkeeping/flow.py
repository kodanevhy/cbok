import itertools
import os
from tempfile import mktemp
import zipfile

from oslo_concurrency import processutils
from oslo_log import log as logging
import pandas

from cbok import exception
from cbok.objects import meh
from cbok import utils


LOG = logging.getLogger(__name__)


def execute(cmd):
    return processutils.execute(*cmd)


class Flow:
    def __init__(self, link):
        self.localize(link)
        self.csv_path = None
        self.earliest = '9999-12-31 23:59:59'

    def localize(self, link):
        """Download and VIOLENTLY decompress the bill flow file."""
        compressed_target = mktemp(suffix='.flow.wechat.zip')
        parent_temp = os.path.dirname(compressed_target)
        cmd = ['wget', link, '-O', compressed_target]
        execute(cmd)
        meta_chars = '0123456789'
        for char in itertools.permutations(meta_chars, 6):
            password = ''.join(char)
            try:
                with zipfile.ZipFile(compressed_target) as zf:
                    zf.extractall(parent_temp, pwd=password.encode('utf-8'))
            except RuntimeError:
                # Note(koda): It will raise a RuntimeError when achieving a
                # bad password for file, means that uncompress the file
                # failed, passing now and let it continue to process the next
                # try.
                pass
            else:
                cmd = ['ls', os.path.join(parent_temp, '微信支付账单\*')]
                self.csv_path = execute(cmd)
                if not self.csv_path:
                    raise exception.DecompressFlowFailed()

    def _process_flow(self):
        # Note(koda): Shit tencent mistake: lack 2 ',' in bill flow,
        # result in parsing cells failed.
        # cmd = ['sed', '-i', '"s/,,,,,,,,/,,,,,,,,,,/g"', self.csv_path]
        # execute(cmd)
        csv = pandas.read_csv(self.csv_path)
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
