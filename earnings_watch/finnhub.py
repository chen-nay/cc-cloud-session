"""Finnhub 财报日历数据源。文档：https://finnhub.io/docs/api/earnings-calendar"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

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

    def _get(self, path: str, params: dict) -> Any:
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

    def eps_year_ago(self, symbol: str, report_date: date) -> float | None:
        """即将在 report_date 发布的这一季，去年同一季度的实际 EPS（non-GAAP）。"""
        return year_ago_actual(self._get("/stock/earnings", {"symbol": symbol}), report_date)


def year_ago_actual(rows: list[dict] | None, report_date: date) -> float | None:
    """从 /stock/earnings 的结果中找出"去年同期"的实际 EPS。

    免费版只返回最近 4 个已公布季度。对苹果、英伟达这类财年和自然年不一致的公司，
    这个接口和财报日历的季度编号口径不同，所以按财季结束日期对应：
    最近一个已公布季度往前推 3 个季度，就是即将发布这一季的去年同期。
    """
    periods: list[tuple[date, float]] = []
    for row in rows or []:
        try:
            periods.append((date.fromisoformat(row["period"]), float(row["actual"])))
        except (KeyError, TypeError, ValueError):
            continue
    if not periods:
        return None
    periods.sort(reverse=True)
    latest = periods[0][0]
    # 正常情况下，最近一个已公布季度结束后约 3～6 个月发布下一季财报；
    # 不在这个范围内说明数据没对齐（比如最新一季还没收录），宁可不显示
    if not 95 <= (report_date - latest).days <= 190:
        return None
    target = latest - timedelta(days=273)
    for period, actual in periods:
        if abs((period - target).days) <= 20:
            return actual
    return None
