"""Transport limits for the explicit reference builder, never dashboard reads."""
from contextlib import contextmanager
from functools import partial
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
import threading
import time
from urllib.parse import urlparse, urljoin


class ReferencePaused(BaseException):
    """Escape scoring's graceful Exception handlers without recording false exclusions."""
    def __init__(self, reason, retry_after=900):
        super().__init__(reason)
        self.retry_after = retry_after


def retry_seconds(value):
    try:
        return max(0, float(value))
    except (ValueError, TypeError):
        try:
            return max(0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
        except (ValueError, TypeError, OverflowError):
            return 0


class RequestBudget:
    def __init__(self, interval=1.05, clock=time.monotonic, sleep=time.sleep):
        self.interval, self.clock, self.sleep = interval, clock, sleep
        self.last = None
        self.requests = 0
        self.lock = threading.Lock()

    def send(self, request, method, url, **kwargs):
        # Cookie, crumb, quote, holdings, retries and redirects share this budget.
        host = urlparse(url).hostname or ''
        if not (host == 'yahoo.com' or host.endswith('.yahoo.com') or host.endswith('.yimg.com')):
            raise ReferencePaused('Unexpected market transport host: ' + host)
        kwargs['allow_redirects'] = False
        for attempt in range(3):
            with self.lock:
                if self.last is not None:
                    self.sleep(max(0, self.interval - (self.clock() - self.last)))
                self.last = self.clock()
                self.requests += 1
                response = request(method, url, **kwargs)
            if response.status_code == 429:
                raise ReferencePaused('Yahoo HTTP 429: rate limited', max(900, retry_seconds(response.headers.get('Retry-After'))))
            if response.status_code < 500:
                return response
            if attempt < 2:
                self.sleep(2 ** (attempt + 1))
        raise ReferencePaused('Yahoo service unavailable after three attempts')


@contextmanager
def yahoo_budget():
    """A dedicated session for this sequential CLI run; restore yfinance on exit."""
    import yfinance as yf
    from yfinance._http import requests, HAS_CURL_CFFI
    from yfinance.data import YfData
    budget = RequestBudget()

    class Session(requests.Session):
        def request(self, method, url, **kwargs):
            for _ in range(6):
                response = budget.send(super().request, method, url, **kwargs)
                if response.status_code not in (301, 302, 303, 307, 308):
                    return response
                target = response.headers.get('Location')
                if not target:
                    return response
                url = urljoin(url, target)
                kwargs.pop('params', None)
                if response.status_code == 303 or (response.status_code in (301, 302) and method.upper() == 'POST'):
                    method = 'GET'
                    kwargs.pop('data', None)
                    kwargs.pop('json', None)
            raise ReferencePaused('Yahoo redirect limit exceeded')

    session = Session(**({'impersonate': 'chrome'} if HAS_CURL_CFFI else {}))
    data = YfData()
    previous = data._session
    ticker = yf.Ticker
    yf.Ticker = partial(ticker, session=session)
    try:
        yield budget
    finally:
        yf.Ticker = ticker
        data._set_session(previous)
        session.close()
