from __future__ import annotations

from pathlib import Path

from .models import Stock


def parse_watchlist(text: str) -> list[Stock]:
    """每行一个股票代码，后面可选跟一个显示名称；# 之后是注释。重复的代码只保留第一个。"""
    stocks: list[Stock] = []
    seen: set[str] = set()
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split(maxsplit=1)
        symbol = parts[0].upper()
        if symbol in seen:
            continue
        seen.add(symbol)
        stocks.append(Stock(symbol, parts[1].strip() if len(parts) > 1 else ""))
    return stocks


def load_watchlist(path: str | Path) -> list[Stock]:
    return parse_watchlist(Path(path).read_text(encoding="utf-8"))
