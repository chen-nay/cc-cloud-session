"""与数据源无关的数据结构。以后接入 Earnings Whispers 等数据源时复用。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class Stock:
    symbol: str
    name: str = ""

    @property
    def label(self) -> str:
        if self.name and self.name.upper() != self.symbol:
            return f"{self.symbol} {self.name}"
        return self.symbol


@dataclass(frozen=True)
class EarningsEvent:
    symbol: str
    date: date  # 美东日期
    hour: str = ""  # "bmo" 盘前 / "amc" 盘后 / "dmh" 盘中 / "" 未知
    eps_estimate: float | None = None
    eps_actual: float | None = None
    revenue_estimate: float | None = None
    revenue_actual: float | None = None


@dataclass(frozen=True)
class EpsBaseline:
    """用来和即将发布这一季的 EPS 预期做比较的历史实际 EPS。"""

    last_quarter: float | None = None  # 上一季度实际（算环比）
    year_ago: float | None = None  # 去年同一季度实际（算同比）
