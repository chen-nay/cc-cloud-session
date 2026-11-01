"""把财报事件整理成分组报告，并渲染成 Server酱 使用的标题 + Markdown 正文。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from .models import EarningsEvent, EpsBaseline, Stock

ET = ZoneInfo("America/New_York")
BJ = ZoneInfo("Asia/Shanghai")

# 各时段在美东时间的典型发布时刻，用于换算北京时间和"还有几天"
SESSIONS = {
    "bmo": ("盘前", time(8, 0)),
    "amc": ("盘后", time(16, 30)),
    "dmh": ("盘中", time(12, 0)),
}
UNKNOWN_SESSION_TIME = time(16, 30)  # 未公布时段时按盘后估算

WEEKDAYS = "一二三四五六日"
TITLE_MAX = 32  # Server酱 标题上限
RECENT_WINDOW = timedelta(hours=24)


@dataclass(frozen=True)
class Entry:
    stock: Stock
    event: EarningsEvent
    days: int  # 按北京日期计算，距离今天还有几天
    baseline: EpsBaseline = EpsBaseline()  # 上一季度、去年同期的实际 EPS，用于算环比和同比


@dataclass
class Report:
    now: datetime  # 北京时间
    total: int
    horizon_days: int  # 往后查了多少天
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
    horizon_days: int = 60,
) -> Report:
    now = now.astimezone(BJ)
    today = now.date()
    report = Report(now=now, total=len(stocks), horizon_days=horizon_days)

    for stock in stocks:
        if stock.symbol in failures:
            report.failed.append((stock, failures[stock.symbol]))
            continue

        ordered = sorted(events.get(stock.symbol, []), key=release_time)
        recent = [ev for ev in ordered if now - RECENT_WINDOW < release_time(ev) <= now]
        report.recent += [Entry(stock, ev, 0) for ev in recent]

        upcoming = next((ev for ev in ordered if release_time(ev) > now), None)
        days = None if upcoming is None else (release_time(upcoming).astimezone(BJ).date() - today).days
        if days is None or days > horizon_days:
            if not recent:  # 刚发布完的公司，下一次财报日通常还没出来，不必再列一遍
                report.no_date.append(stock)
            continue

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


def beijing_slot(event: EarningsEvent) -> tuple[datetime, str] | None:
    """发布时刻换算成北京时间，以及"凌晨/上午/下午/晚间"；时段未知时返回 None。"""
    if event.hour not in SESSIONS:
        return None
    bj = release_time(event).astimezone(BJ)
    h = bj.hour
    return bj, "凌晨" if h < 6 else "上午" if h < 12 else "下午" if h < 18 else "晚间"


def us_day(event: EarningsEvent) -> str:
    return fmt_day(datetime.combine(event.date, time()))


def fmt_beijing(event: EarningsEvent) -> str:
    """例如 "北京 11/06 周五 凌晨"；时段未知时只给美东日期。"""
    slot = beijing_slot(event)
    if slot is None:
        return f"美东 {us_day(event)} 时段未定"
    return f"北京 {fmt_day(slot[0])} {slot[1]}"


def session_name(event: EarningsEvent) -> str:
    return SESSIONS[event.hour][0] if event.hour in SESSIONS else "时段未定"


def fmt_us(event: EarningsEvent) -> str:
    return f"美东 {us_day(event)} {session_name(event)}"


def fmt_days(days: int) -> str:
    return {0: "今天", 1: "明天", 2: "后天"}.get(days, f"{days} 天后")


def fmt_revenue(value: float | None) -> str | None:
    """不写币种：多数是美元，但阿里、拼多多等按人民币编制财报，Finnhub 给的可能是人民币。"""
    if not value:
        return None
    yi = value / 1e8
    if yi >= 100:
        return f"{yi:.0f} 亿"
    if yi >= 1:
        return f"{yi:.1f} 亿"
    return f"{value / 1e4:.0f} 万"


def fmt_eps(value: float | None) -> str | None:
    return None if value is None else f"{value:.2f}"


def growth_pct(estimate: float | None, base: float | None) -> float | None:
    """增长百分比；基数亏损或为 0 时百分比没有意义，返回 None。"""
    if estimate is None or base is None or base <= 0:
        return None
    return (estimate - base) / base * 100


# 基数 ≤ 0 时不给百分比，改为直接列出基数
BASE_NAMES = {"同比": "去年同期", "环比": "上季"}


def eps_changes(estimate: float | None, baseline: EpsBaseline) -> list[tuple[str, float | None, float]]:
    """[(同比/环比, 百分比, 基数)]；缺数据的项不返回，基数 ≤ 0 时百分比为 None。"""
    if estimate is None:
        return []
    return [
        (name, growth_pct(estimate, base), base)
        for name, base in (("同比", baseline.year_ago), ("环比", baseline.last_quarter))
        if base is not None
    ]


def fmt_growth(estimate: float | None, baseline: EpsBaseline) -> str:
    """例如 "（同比 +9%，环比 +5%）"；基数亏损或为 0 时改为直接给出基数，如 "上季 -0.05"。"""
    items = [
        f"{name} {pct:+.0f}%" if pct is not None else f"{BASE_NAMES[name]} {base:.2f}"
        for name, pct, base in eps_changes(estimate, baseline)
    ]
    return f"（{'，'.join(items)}）" if items else ""


def attach_eps_baseline(report: Report, lookup: Callable[[EarningsEvent], EpsBaseline]) -> None:
    """给 7 天内（只有这一组显示 EPS 预期）的公司补上上一季度和去年同期的实际 EPS。"""
    report.within_7 = [
        replace(e, baseline=lookup(e.event)) if e.event.eps_estimate is not None else e
        for e in report.within_7
    ]


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
            lines.append(f"- **{e.stock.label}** {fmt_beijing(e.event)} · {_eps_result(e.event)}")
        lines.append("")

    if report.within_7:
        lines += [f"#### 🔴 7 天内（{len(report.within_7)} 家）", ""]
        for e in report.within_7:
            ev = e.event
            details = []
            if eps := fmt_eps(ev.eps_estimate):
                details.append(f"EPS 预期 {eps}{fmt_growth(ev.eps_estimate, e.baseline)}")
            if revenue := fmt_revenue(ev.revenue_estimate):
                details.append(f"营收预期 {revenue}")
            # 时段未定时 fmt_beijing 已经给出美东日期，不必再重复一遍
            when = f"{fmt_beijing(ev)}（{fmt_us(ev)}）" if ev.hour in SESSIONS else fmt_beijing(ev)
            lines += [f"**{e.stock.label}** · **{fmt_days(e.days)}**", "", f"- {when}"]
            if details:
                lines.append(f"- {' · '.join(details)}")
            lines.append("")

    for header, bucket in (
        ("🟡 8–30 天", report.within_30),
        (f"⚪ 31–{report.horizon_days} 天", report.later),
    ):
        if not bucket:
            continue
        lines += [f"#### {header}（{len(bucket)} 家）", ""]
        for e in bucket:
            lines.append(f"- **{e.stock.label}** · {fmt_days(e.days)} · {fmt_beijing(e.event)}")
        lines.append("")

    if report.no_date:
        lines += [
            f"#### ❔ {report.horizon_days} 天内暂无日期",
            "",
            "、".join(s.label for s in report.no_date),
            "",
        ]

    if report.failed:
        lines += ["#### ⚠️ 查询失败", ""]
        lines += [f"- {s.label}：{reason}" for s, reason in report.failed]
        lines.append("")

    lines += [
        "---",
        "",
        "数据来源 Finnhub，预期为分析师一致预期（non-GAAP）；营收按财报货币计，多数为美元，中概股可能为人民币。"
        "标注「时段未定」或较远的日期多为预估，以公司公告为准。",
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
