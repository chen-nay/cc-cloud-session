"""示例数据：不需要 API key，用于本地预览报告样式、测试推送是否配置成功。"""

from __future__ import annotations

from datetime import datetime, timedelta

from .models import EarningsEvent, Stock
from .report import ET, RECENT_WINDOW, release_time

# (距今天的美东天数, 时段)；None 表示 90 天内暂无日期
UPCOMING = [(1, "amc"), (3, "bmo"), (6, "amc"), (12, "bmo"), (26, "amc"), (45, "bmo"), (80, ""), None]


def sample_events(stocks: list[Stock], now: datetime) -> dict[str, list[EarningsEvent]]:
    today_et = now.astimezone(ET).date()
    events: dict[str, list[EarningsEvent]] = {}
    for i, stock in enumerate(stocks):
        eps = round(0.42 + i * 0.37, 2)
        revenue = (6 + i * 13) * 1e9
        if i == 0:
            # 第一只股票模拟"过去 24 小时刚发布"
            for d in (today_et, today_et - timedelta(days=1)):
                ev = EarningsEvent(stock.symbol, d, "amc", eps, round(eps * 1.06, 2), revenue)
                if now - RECENT_WINDOW < release_time(ev) <= now:
                    events[stock.symbol] = [ev]
                    break
            continue
        pattern = UPCOMING[(i - 1) % len(UPCOMING)]
        if pattern is None:
            events[stock.symbol] = []
            continue
        offset, hour = pattern
        day = today_et + timedelta(days=offset)
        while day.weekday() >= 5:  # 财报不会在周末发布
            day += timedelta(days=1)
        events[stock.symbol] = [EarningsEvent(stock.symbol, day, hour, eps, None, revenue)]
    return events
