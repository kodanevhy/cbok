import os
import time

TRADE_TYPE = {'收入': 'incoming', '支出': 'expenditure'}


def decimalization(create_kwargs):
    amount = create_kwargs['amount']
    create_kwargs['amount'] = amount[1:]
    return float(amount[1:])


def stash_datetime(accuracy=False):
    formatter = '%Y-%m-%d %H:%M:%S' if accuracy is True else '%Y-%m-%d'
    return time.strftime(formatter, time.localtime())


def recursion_directory(dirpath):
    recursion_result = []

    def _list(dp):
        files = os.listdir(dp)
        for fi in files:
            fi_d = os.path.join(dp, fi)
            if os.path.isdir(fi_d):
                _list(fi_d)
            else:
                recursion_result.append(os.path.join(dp, fi_d))
        return recursion_result

    return _list(dirpath)
