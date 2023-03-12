import time

TRADE_TYPE = ['incoming', 'expenditure']


def decimalization_amount(create_kwargs):
    return float(create_kwargs['amount'])


def stash_datetime(accuracy=False):
    formatter = '%Y-%m-%d %H:%M:%S' if accuracy is True else '%Y-%m-%d'
    return time.strftime(formatter, time.localtime())
