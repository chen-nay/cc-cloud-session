from datetime import date

import pytest

from earnings_watch import serverchan
from earnings_watch.finnhub import FinnhubAuthError, FinnhubClient, FinnhubError, year_ago_actual
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


def history(*rows):
    return [{"period": p, "actual": a, "estimate": None, "symbol": "X"} for p, a in rows]


def test_year_ago_actual_calendar_fiscal_year():
    rows = history(("2026-06-30", 0.65), ("2026-03-31", 0.55), ("2025-12-31", 0.50), ("2025-09-30", 0.46))
    assert year_ago_actual(rows, date(2026, 11, 4)) == 0.46


def test_year_ago_actual_non_calendar_fiscal_year():
    # 苹果这类财季结束日不在月底的公司
    rows = history(("2026-06-27", 1.57), ("2026-03-28", 1.65), ("2025-12-27", 2.40), ("2025-09-27", 1.85))
    assert year_ago_actual(rows, date(2026, 10, 29)) == 1.85


def test_year_ago_actual_skips_when_data_not_aligned():
    rows = history(("2026-03-31", 0.55), ("2025-12-31", 0.50), ("2025-09-30", 0.46), ("2025-06-30", 0.40))
    assert year_ago_actual(rows, date(2026, 11, 4)) is None  # 最新一季还没收录
    assert year_ago_actual(history(("2026-06-30", 0.65)), date(2026, 11, 4)) is None  # 去年同期不在结果里
    assert year_ago_actual([{"period": "2026-06-30", "actual": None}], date(2026, 11, 4)) is None
    assert year_ago_actual([], date(2026, 11, 4)) is None


def test_eps_year_ago_calls_earnings_endpoint():
    rows = history(("2026-06-30", 0.65), ("2026-03-31", 0.55), ("2025-12-31", 0.50), ("2025-09-30", 0.46))
    c, session = client(FakeResponse(200, rows))
    assert c.eps_year_ago("DDOG", date(2026, 11, 4)) == 0.46
    assert session.calls[0][0].endswith("/stock/earnings")
    assert session.calls[0][1] == {"symbol": "DDOG"}
