from datetime import date

import pytest

from earnings_watch import serverchan
from earnings_watch.finnhub import FinnhubAuthError, FinnhubClient, FinnhubError
from earnings_watch.watchlist import parse_watchlist


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self.ok = status < 400
        self._payload = payload

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append((url, params, headers))
        return self.responses.pop(0)


def client(*responses):
    session = FakeSession(*responses)
    return FinnhubClient("KEY", session=session, min_interval=0, max_retries=1), session


def test_watchlist_parsing():
    text = "# 注释\nAAPL 苹果\n msft  微软 # 行尾注释\n\nAAPL 重复\nTSLA\n"
    stocks = parse_watchlist(text)
    assert [(s.symbol, s.name) for s in stocks] == [("AAPL", "苹果"), ("MSFT", "微软"), ("TSLA", "")]


def test_finnhub_parses_and_sorts(monkeypatch):
    payload = {
        "earningsCalendar": [
            {"symbol": "AAPL", "date": "2027-01-28", "hour": "amc", "epsEstimate": 2.5},
            {"symbol": "AAPL", "date": "2026-11-05", "hour": "AMC", "epsEstimate": 1.6, "revenueEstimate": 1e11},
            {"symbol": "OTHER", "date": "2026-11-06"},
            {"symbol": "AAPL", "date": "bad"},
        ]
    }
    c, session = client(FakeResponse(200, payload))
    events = c.earnings_calendar("AAPL", date(2026, 11, 1), date(2027, 2, 1))
    assert [(e.date, e.hour) for e in events] == [(date(2026, 11, 5), "amc"), (date(2027, 1, 28), "amc")]
    assert events[0].revenue_estimate == 1e11
    url, params, headers = session.calls[0]
    assert url.endswith("/calendar/earnings")
    assert params == {"symbol": "AAPL", "from": "2026-11-01", "to": "2027-02-01"}
    assert headers == {"X-Finnhub-Token": "KEY"}


def test_finnhub_retries_on_rate_limit(monkeypatch):
    monkeypatch.setattr("earnings_watch.finnhub.time.sleep", lambda s: None)
    c, _ = client(FakeResponse(429, {}), FakeResponse(200, {"earningsCalendar": []}))
    assert c.earnings_calendar("AAPL", date(2026, 11, 1), date(2027, 2, 1)) == []


def test_finnhub_errors(monkeypatch):
    monkeypatch.setattr("earnings_watch.finnhub.time.sleep", lambda s: None)
    c, _ = client(FakeResponse(401, {}))
    with pytest.raises(FinnhubAuthError):
        c.earnings_calendar("AAPL", date(2026, 11, 1), date(2027, 2, 1))
    c, _ = client(FakeResponse(500, {}), FakeResponse(500, {}))
    with pytest.raises(FinnhubError, match="HTTP 500"):
        c.earnings_calendar("AAPL", date(2026, 11, 1), date(2027, 2, 1))


def test_serverchan_endpoint():
    assert serverchan.endpoint("SCT123abc") == "https://sctapi.ftqq.com/SCT123abc.send"
    assert serverchan.endpoint("sctp42tXYZ") == "https://42.push.ft07.com/send/sctp42tXYZ.send"
