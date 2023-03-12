from oslo_concurrency import processutils
import pandas

from cbok import exception
from cbok.objects import meh
from cbok import utils


def execute(cmd):
    return processutils.execute(*cmd)


class Flow:
    def __init__(self, link):
        self.link = link
        self.download()
        self.csv_path = '../../微信支付账单(20230304-20230311).csv'
        self.earliest = '9999-12-31 23:59:59'

    def download(self):
        save_path = '/tmp/flow.csv'
        cmd = ['wget', self.link, '-O', save_path]
        execute(cmd)
        self.csv_path = save_path

    def _process_flow(self):
        # Note(koda): Shit tencent mistake: lack 2 ',' in bill flow,
        # result in parsing cells failed.
        # cmd = ['sed', '-i', '"s/,,,,,,,,/,,,,,,,,,,/g"', self.csv_path]
        # execute(cmd)
        csv = pandas.read_csv(self.csv_path)
        aggregate = list()
        for index, row in csv.iterrows():
            create_kwargs = dict()
            # Note(koda): Forbidden to change the order in the follow list.
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
                pass
            else:
                if utils.strtime(row[0]) < utils.strtime(self.earliest):
                    self.earliest = row[0]
                for i, item in enumerate(init):
                    create_kwargs[init[i]] = row[i]
                aggregate.append(create_kwargs)
        return aggregate

    def extract_current(self):
        trade_date_db = meh.Meh.nearly_one().trade_date

        processed_flow = self._process_flow()
        vacancy = utils.strtime(self.earliest).tm_yday - \
            utils.strtime(trade_date_db).tm_yday
        if vacancy > 1:
            raise exception.IncoherentBillFlow(vacancy=vacancy)

        new_flow = list()
        for entry in processed_flow:
            if utils.strtime(entry.get('trade_date')) > \
                    utils.strtime(trade_date_db):
                new_flow.append(entry)
        return new_flow
