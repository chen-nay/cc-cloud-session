"""命令行入口：python -m earnings_watch [--dry-run] [--sample]"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import serverchan
from .finnhub import FinnhubAuthError, FinnhubClient, FinnhubError
from .html_report import render_html
from .models import EarningsEvent, EpsBaseline, Stock
from .report import BJ, ET, Report, attach_eps_baseline, build_report, render_markdown, render_title
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


def baseline_lookup(client: FinnhubClient):
    """查询失败不影响整体：只是不显示同比和环比。"""

    def lookup(event: EarningsEvent) -> EpsBaseline:
        try:
            baseline = client.eps_baseline(event.symbol, event.date)
        except FinnhubError as e:
            log.warning("%-6s 历史 EPS 查询失败：%s", event.symbol, e)
            return EpsBaseline()
        log.info("%-6s 上季 EPS：%s，去年同期 EPS：%s", event.symbol, baseline.last_quarter, baseline.year_ago)
        return baseline

    return lookup


def sample_baseline(event: EarningsEvent) -> EpsBaseline:
    """示例数据：假设同比 +20%、环比 +5%。"""
    return EpsBaseline(last_quarter=round(event.eps_estimate / 1.05, 2), year_ago=round(event.eps_estimate / 1.2, 2))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="earnings_watch", description="查询关注列表的美股财报日，并推送到微信")
    parser.add_argument("--watchlist", default="watchlist.txt", help="关注列表文件（默认 watchlist.txt）")
    parser.add_argument("--days", type=int, default=60, help="往后查多少天（默认 60）")
    parser.add_argument("--output", default="output/report.md", help="报告保存位置")
    parser.add_argument("--dry-run", action="store_true", help="只生成报告，不推送")
    parser.add_argument("--sample", action="store_true", help="使用示例数据，不需要 Finnhub API key")
    parser.add_argument("--alert", metavar="TEXT", help="只推送一条告警消息（workflow 失败时使用）")
    parser.add_argument("--site-dir", metavar="DIR", help="生成网页版和报告图片到这个目录（用于 GitHub Pages）")
    parser.add_argument("--site-url", metavar="URL", help="网站的公网地址，用于在消息里引用图片")
    parser.add_argument("--send", metavar="FILE", help="只推送之前生成好的消息（output/message.json）")
    parser.add_argument("--text-only", action="store_true", help="配合 --send：不带图片，只推送文字版")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    sendkey = os.environ.get("SERVERCHAN_SENDKEY", "").strip()

    if args.alert is not None:
        if not sendkey:
            log.error("未设置 SERVERCHAN_SENDKEY")
            return 2
        serverchan.send(sendkey, "美股财报日历：运行失败", args.alert)
        return 0

    if args.send:
        if not sendkey:
            log.error("未设置 SERVERCHAN_SENDKEY")
            return 2
        message = json.loads(Path(args.send).read_text(encoding="utf-8"))
        serverchan.send(sendkey, message["title"], compose_body(message, text_only=args.text_only))
        log.info("已推送到 Server酱（%s）", "文字版" if args.text_only or not message.get("image_url") else "图片 + 文字版")
        return 0

    stocks = load_watchlist(args.watchlist)
    if not stocks:
        log.error("关注列表为空：%s", args.watchlist)
        return 2
    now = datetime.now(tz=BJ)

    client: FinnhubClient | None = None
    if args.sample:
        events, failures = sample_events(stocks, now), {}
    else:
        api_key = os.environ.get("FINNHUB_API_KEY", "").strip()
        if not api_key:
            log.error("未设置 FINNHUB_API_KEY（可先用 --sample 预览）")
            return 2
        client = FinnhubClient(api_key)
        try:
            events, failures = fetch_all(client, stocks, now, args.days)
        except FinnhubAuthError as e:
            log.error("%s", e)
            return 1
        if len(failures) == len(stocks):
            log.error("所有股票都查询失败，不推送")
            return 1

    report = build_report(stocks, events, failures, now, horizon_days=args.days)
    attach_eps_baseline(report, sample_baseline if client is None else baseline_lookup(client))
    title, body = render_title(report), render_markdown(report)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"<!-- {title} -->\n\n{body}", encoding="utf-8")
    print(f"标题：{title}\n\n{body}")
    log.info("报告已保存到 %s", out)

    image_url = build_site(report, Path(args.site_dir), args.site_url) if args.site_dir else None
    message = {"title": title, "text": body, "image_url": image_url, "page_url": args.site_url or None}
    message_path = out.with_name("message.json")
    message_path.write_text(json.dumps(message, ensure_ascii=False, indent=2), encoding="utf-8")

    if args.dry_run:
        log.info("--dry-run：不推送（消息已保存到 %s，可用 --send 推送）", message_path)
        return 0
    if not sendkey:
        log.error("未设置 SERVERCHAN_SENDKEY，无法推送（只想预览请加 --dry-run）")
        return 2
    serverchan.send(sendkey, title, compose_body(message))
    log.info("已推送到 Server酱")
    return 0


def build_site(report: Report, site_dir: Path, site_url: str | None) -> str | None:
    """生成网页版 index.html 和报告图片；返回图片的公网地址（截图失败或没有 site_url 时为 None）。"""
    site_dir.mkdir(parents=True, exist_ok=True)
    html_path = site_dir / "index.html"
    html_path.write_text(render_html(report), encoding="utf-8")
    png_name = f"report-{report.now:%Y%m%d-%H%M}.png"  # 每次文件名不同，避免微信缓存旧图
    try:
        from .snapshot import screenshot

        screenshot(html_path, site_dir / png_name)
    except Exception as e:  # 截图失败不影响文字版推送
        log.warning("生成报告图片失败，只推送文字版：%s", e)
        return None
    log.info("报告图片已生成：%s", site_dir / png_name)
    return f"{site_url.rstrip('/')}/{png_name}" if site_url else None


def compose_body(message: dict, text_only: bool = False) -> str:
    """图片放最上面（方便长按转发），下面附文字版，图片加载不出来时也能看。"""
    text = message["text"]
    if text_only or not message.get("image_url"):
        return text
    head = f"![美股财报日历]({message['image_url']})\n\n"
    if message.get("page_url"):
        head += f"[打开网页版]({message['page_url'].rstrip('/')}/)\n\n"
    return f"{head}---\n\n{text}"


if __name__ == "__main__":
    sys.exit(main())
