"""把财报事件整理成分组报告，并渲染成 Server酱 使用的标题 + Markdown 正文。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import EarningsEvent, Stock

ET = ZoneInfo("America/New_York")
BJ = ZoneInfo("Asia/Shanghai")

# 各时段在美东时间的典型发布时刻，用于换算北京时间和"还有几天"
SESSIONS = {
    "bmo": ("盘前", time(8, 0)),
    "amc": ("盘后", time(16, 30)),
    "dmh": ("盘中", time(12, 0)),
}
UNKNOWN_SESSION_TIME = time(16, 30)  # 未公布时段时按盘后估算

EW_URL = "https://www.earningswhispers.com/epsdetails/{symbol}"
WEEKDAYS = "一二三四五六日"
TITLE_MAX = 32  # Server酱 标题上限
RECENT_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class Entry:
    stock: Stock
    event: EarningsEvent
    days: int  # 按北京日期计算，距离今天还有几天


@dataclass
class Report:
    now: datetime  # 北京时间
    total: int
    recent: list[Entry] = field(default_factory=list)  # 过去 24 小时内已发布
    within_7: list[Entry] = field(default_factory=list)
    within_30: list[Entry] = field(default_factory=list)
    later: list[Entry] = field(default_factory=list)
    no_date: list[Stock] = field(default_factory=list)
    failed: list[tuple[Stock, str]] = field(default_factory=list)


def release_time(event: EarningsEvent) -> datetime:
    """财报发布的估计时刻（带时区）。"""
    t = SESSIONS[event.hour][1] if event.hour in SESSIONS else UNKNOWN_SESSION_TIME
    return datetime.combine(event.date, t, tzinfo=ET)


def build_report(
    stocks: list[Stock],
    events: dict[str, list[EarningsEvent]],
    failures: dict[str, str],
    now: datetime,
) -> Report:
    now = now.astimezone(BJ)
    today = now.date()
    report = Report(now=now, total=len(stocks))

    for stock in stocks:
        if stock.symbol in failures:
            report.failed.append((stock, failures[stock.symbol]))
            continue

        ordered = sorted(events.get(stock.symbol, []), key=release_time)
        recent = [ev for ev in ordered if now - RECENT_WINDOW < release_time(ev) <= now]
        report.recent += [Entry(stock, ev, 0) for ev in recent]

        upcoming = next((ev for ev in ordered if release_time(ev) > now), None)
        if upcoming is None:
            if not recent:  # 刚发布完的公司，下一次财报日通常还没出来，不必再列一遍
                report.no_date.append(stock)
            continue

        days = (release_time(upcoming).astimezone(BJ).date() - today).days
        entry = Entry(stock, upcoming, days)
        if days <= 7:
            report.within_7.append(entry)
        elif days <= 30:
            report.within_30.append(entry)
        else:
            report.later.append(entry)

    for bucket in (report.recent, report.within_7, report.within_30, report.later):
        bucket.sort(key=lambda e: (release_time(e.event), e.stock.symbol))
    return report


# ---------- 格式化 ----------

def fmt_day(dt: datetime) -> str:
    return f"{dt:%m/%d} 周{WEEKDAYS[dt.weekday()]}"


def fmt_beijing(event: EarningsEvent) -> str:
    """例如 "11/06 周五 凌晨"；时段未知时只给美东日期。"""
    if event.hour not in SESSIONS:
        return f"美东 {fmt_day(datetime.combine(event.date, time()))} 时段未定"
    bj = release_time(event).astimezone(BJ)
    h = bj.hour
    part = "凌晨" if h < 6 else "上午" if h < 12 else "下午" if h < 18 else "晚间"
    return f"北京 {fmt_day(bj)} {part}"


def fmt_us(event: EarningsEvent) -> str:
    session = SESSIONS[event.hour][0] if event.hour in SESSIONS else "时段未定"
    return f"美东 {fmt_day(datetime.combine(event.date, time()))} {session}"


def fmt_days(days: int) -> str:
    return {0: "今天", 1: "明天", 2: "后天"}.get(days, f"{days} 天后")


def fmt_revenue(value: float | None) -> str | None:
    if not value:
        return None
    yi = value / 1e8
    if yi >= 100:
        return f"{yi:.0f} 亿美元"
    if yi >= 1:
        return f"{yi:.1f} 亿美元"
    return f"{value / 1e4:.0f} 万美元"


def fmt_eps(value: float | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def ew_link(symbol: str) -> str:
    return f"[EW]({EW_URL.format(symbol=symbol.lower())})"


# ---------- 渲染 ----------

def render_title(report: Report) -> str:
    base = f"美股财报 {report.now:%m/%d}"
    if report.within_7:
        head = f"{base}｜7天内{len(report.within_7)}家:"
        symbols = [e.stock.symbol for e in report.within_7]
        full = f"{head} {' '.join(symbols)}"
        if len(full) <= TITLE_MAX:
            return full
        title = head
        for sym in symbols:
            if len(f"{title} {sym} 等") > TITLE_MAX:
                break
            title += f" {sym}"
        return f"{title} 等"
    upcoming = report.within_30 or report.later
    if upcoming:
        first = upcoming[0]
        return f"{base}｜最近: {first.stock.symbol} {fmt_days(first.days)}"[:TITLE_MAX]
    return f"{base}｜近期无财报"[:TITLE_MAX]


def render_markdown(report: Report) -> str:
    now = report.now
    lines = [
        f"### 📅 美股财报日历 · {fmt_day(now)}",
        "",
        f"> 关注 {report.total} 家 · 7 天内 {len(report.within_7)} 家 · "
        f"北京时间 {now:%H:%M} 生成",
        "",
    ]

    if report.recent:
        lines += ["#### 🆕 过去 24 小时已发布", ""]
        for e in report.recent:
            lines.append(f"- **{e.stock.label}** {fmt_beijing(e.event)} · {_eps_result(e.event)} · {ew_link(e.stock.symbol)}")
        lines.append("")

    if report.within_7:
        lines += [f"#### 🔴 7 天内（{len(report.within_7)} 家）", ""]
        for e in report.within_7:
            ev = e.event
            details = []
            if eps := fmt_eps(ev.eps_estimate):
                details.append(f"EPS 预期 {eps}")
            if revenue := fmt_revenue(ev.revenue_estimate):
                details.append(f"营收预期 {revenue}")
            details.append(ew_link(e.stock.symbol))
            lines += [
                f"**{e.stock.label}** · **{fmt_days(e.days)}**",
                "",
                f"- {fmt_beijing(ev)}（{fmt_us(ev)}）",
                f"- {' · '.join(details)}",
                "",
            ]

    for header, bucket in (("🟡 8–30 天", report.within_30), ("⚪ 30 天以上", report.later)):
        if not bucket:
            continue
        lines += [f"#### {header}（{len(bucket)} 家）", ""]
        for e in bucket:
            lines.append(
                f"- **{e.stock.label}** · {fmt_days(e.days)} · {fmt_beijing(e.event)} · {ew_link(e.stock.symbol)}"
            )
        lines.append("")

    if report.no_date:
        lines += ["#### ❔ 90 天内暂无日期", "", "、".join(s.label for s in report.no_date), ""]

    if report.failed:
        lines += ["#### ⚠️ 查询失败", ""]
        lines += [f"- {s.label}：{reason}" for s, reason in report.failed]
        lines.append("")

    lines += [
        "---",
        "",
        "数据来源 Finnhub。较远的日期多为预估，以公司公告为准；"
        "点 EW 可在 Earnings Whispers 查看日期是否已确认及耳语数字。",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _eps_result(ev: EarningsEvent) -> str:
    if ev.eps_actual is None:
        return "实际数据待更新"
    text = f"EPS 实际 {ev.eps_actual:.2f}"
    if ev.eps_estimate is None:
        return text
    mark = "✅ 超预期" if ev.eps_actual > ev.eps_estimate else "❌ 不及预期" if ev.eps_actual < ev.eps_estimate else "➖ 符合预期"
    return f"{text} / 预期 {ev.eps_estimate:.2f} {mark}"
