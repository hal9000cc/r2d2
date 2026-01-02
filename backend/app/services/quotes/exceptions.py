class R2D2QuotesException(Exception):
    pass


class R2D2ExceptionBadTimeframeValue(R2D2QuotesException):
    def __init__(self, value):
        self.value = value
        super().__init__(f'Bad timeframe value: {value}')


class R2D2QuotesExceptionDataNotReceived(R2D2QuotesException):
    def __init__(self, symbol, date_start, date_end=None, error=None):
        self.symbol = symbol
        self.date_start = date_start
        self.date_end = date_end
        self.error = error
        if date_end:
            super().__init__(f'Data not received! Symbol {self.symbol}, date range {self.date_start} to {self.date_end}. Error: {self.error}')
        else:
            super().__init__(f'Data not received! Symbol {self.symbol}, date {self.date_start}. Error: {self.error}')


