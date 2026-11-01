"""Finnhub 财报日历数据源。文档：https://finnhub.io/docs/api/earnings-calendar"""

from __future__ import annotations

import logging
import time
from datetime import date

import requests

from .models import EarningsEvent

BASE_URL = "https://finnhub.io/api/v1"
log = logging.getLogger(__name__)


class FinnhubError(Exception):
    pass


class FinnhubAuthError(FinnhubError):
    """API key 无效：所有请求都会失败，应直接终止。"""


class FinnhubClient:
    def __init__(
        self,
        api_key: str,
        session: requests.Session | None = None,
        min_interval: float = 1.1,  # 免费版每分钟 60 次
        max_retries: int = 3,
    ):
        self._api_key = api_key
        self._session = session or requests.Session()
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._last_call = 0.0

    def _throttle(self) -> None:
        wait = self._last_call + self._min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last_call = time.monotonic()

    def _get(self, path: str, params: dict) -> dict:
        for attempt in range(self._max_retries + 1):
            self._throttle()
            try:
                resp = self._session.get(
                    BASE_URL + path,
                    params=params,
                    headers={"X-Finnhub-Token": self._api_key},
                    timeout=15,
                )
            except requests.RequestException as e:
                if attempt < self._max_retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
                raise FinnhubError(f"网络错误：{type(e).__name__}") from None
            if resp.status_code in (401, 403):
                raise FinnhubAuthError(f"Finnhub API key 无效或无权限（HTTP {resp.status_code}）")
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt < self._max_retries:
                    time.sleep(2 ** (attempt + 1))
                    continue
            if not resp.ok:
                raise FinnhubError(f"HTTP {resp.status_code}")
            return resp.json()
        raise FinnhubError("重试次数用尽")  # 理论上不会走到这里

    def earnings_calendar(self, symbol: str, start: date, end: date) -> list[EarningsEvent]:
        data = self._get(
            "/calendar/earnings",
            {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat()},
        )
        events: dict[date, EarningsEvent] = {}
        for item in data.get("earningsCalendar") or []:
            if (item.get("symbol") or "").upper() != symbol.upper():
                continue
            try:
                day = date.fromisoformat(item["date"])
            except (KeyError, TypeError, ValueError):
                continue
            events[day] = EarningsEvent(
                symbol=symbol,
                date=day,
                hour=(item.get("hour") or "").lower(),
                eps_estimate=item.get("epsEstimate"),
                eps_actual=item.get("epsActual"),
                revenue_estimate=item.get("revenueEstimate"),
                revenue_actual=item.get("revenueActual"),
            )
        return [events[d] for d in sorted(events)]
