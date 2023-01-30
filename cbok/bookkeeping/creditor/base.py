class BaseCreditor:
    def __init__(self, name):
        self.name = name
        self.income = False


class Alipay(BaseCreditor):
    pass


class CreditCard(BaseCreditor):
    pass


class Personnel(BaseCreditor):
    pass
