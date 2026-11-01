"""命令行入口：python -m earnings_watch [--dry-run] [--sample]"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import serverchan
from .finnhub import FinnhubAuthError, FinnhubClient, FinnhubError
from .models import EarningsEvent, Stock
from .report import BJ, ET, build_report, render_markdown, render_title
from .sample import sample_events
from .watchlist import load_watchlist

log = logging.getLogger("earnings_watch")


def fetch_all(
    client: FinnhubClient, stocks: list[Stock], now: datetime, days: int
) -> tuple[dict[str, list[EarningsEvent]], dict[str, str]]:
    today_et = now.astimezone(ET).date()
    start = today_et - timedelta(days=2)  # 往前多查两天，用于"过去 24 小时已发布"
    end = today_et + timedelta(days=days)
    events: dict[str, list[EarningsEvent]] = {}
    failures: dict[str, str] = {}
    for stock in stocks:
        try:
            events[stock.symbol] = client.earnings_calendar(stock.symbol, start, end)
            log.info("%-6s %s", stock.symbol, [e.date.isoformat() for e in events[stock.symbol]])
        except FinnhubAuthError:
            raise
        except FinnhubError as e:
            failures[stock.symbol] = str(e)
            log.warning("%-6s 查询失败：%s", stock.symbol, e)
    return events, failures


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="earnings_watch", description="查询关注列表的美股财报日，并推送到微信")
    parser.add_argument("--watchlist", default="watchlist.txt", help="关注列表文件（默认 watchlist.txt）")
    parser.add_argument("--days", type=int, default=90, help="往后查多少天（默认 90）")
    parser.add_argument("--output", default="output/report.md", help="报告保存位置")
    parser.add_argument("--dry-run", action="store_true", help="只生成报告，不推送")
    parser.add_argument("--sample", action="store_true", help="使用示例数据，不需要 Finnhub API key")
    parser.add_argument("--alert", metavar="TEXT", help="只推送一条告警消息（workflow 失败时使用）")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()

    if args.alert is not None:
        if not sendkey:
            log.error("未设置 SERVERCHAN_SENDKEY")
            return 2
        serverchan.send(sendkey, "美股财报日历：运行失败", args.alert)
        return 0

    stocks = load_watchlist(args.watchlist)
    if not stocks:
        log.error("关注列表为空：%s", args.watchlist)
        return 2
    now = datetime.now(tz=BJ)

    if args.sample:
        events, failures = sample_events(stocks, now), {}
    else:
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        if not api_key:
            log.error("未设置 FINNHUB_API_KEY（可先用 --sample 预览）")
            return 2
        try:
            events, failures = fetch_all(FinnhubClient(api_key), stocks, now, args.days)
        except FinnhubAuthError as e:
            log.error("%s", e)
            return 1
        if len(failures) == len(stocks):
            log.error("所有股票都查询失败，不推送")
            return 1

    report = build_report(stocks, events, failures, now)
    title, body = render_title(report), render_markdown(report)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"<!-- {title} -->\n\n{body}", encoding="utf-8")
    print(f"标题：{title}\n\n{body}")
    log.info("报告已保存到 %s", out)

    if args.dry_run:
        log.info("--dry-run：不推送")
        return 0
    if not sendkey:
        log.error("未设置 SERVERCHAN_SENDKEY，无法推送（只想预览请加 --dry-run）")
        return 2
    serverchan.send(sendkey, title, body)
    log.info("已推送到 Server酱")
    return 0


if __name__ == "__main__":
    sys.exit(main())
