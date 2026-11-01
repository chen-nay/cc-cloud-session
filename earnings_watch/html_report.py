"""把报告渲染成手机竖屏宽度的 HTML 页面：既发布成网页，也用来截图推送。

不使用 emoji（服务器上不必装 emoji 字体）；涨跌按 A 股习惯：红涨绿跌。
"""

from __future__ import annotations

from html import escape

from .models import EarningsEvent
from .report import (
    BASE_NAMES,
    Entry,
    Report,
    beijing_slot,
    eps_changes,
    fmt_day,
    fmt_days,
    fmt_eps,
    fmt_revenue,
    session_name,
    us_day,
)

PAGE_WIDTH = 440  # CSS 像素，截图时按 2 倍输出

CSS = """
* { box-sizing: border-box; }
body { margin: 0; background: #f2f3f5; color: #1f2328;
  font-family: "Noto Sans CJK SC", "PingFang SC", "Microsoft YaHei", sans-serif;
  -webkit-font-smoothing: antialiased; }
.page { max-width: 440px; margin: 0 auto; padding: 18px 14px 14px; }
header { padding: 2px 4px 10px; }
.title { font-size: 22px; font-weight: 700; letter-spacing: 0.5px; }
.date { margin-top: 2px; font-size: 14px; color: #6b7280; }
.stats { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; }
.stats span { font-size: 12px; color: #4b5563; background: #fff; border-radius: 999px; padding: 3px 10px; }
.stats b { color: #d92d20; }
section { background: #fff; border-radius: 14px; padding: 12px 14px 4px; margin-top: 10px; }
h2 { margin: 0 0 4px; font-size: 16px; display: flex; align-items: center; gap: 8px; }
h2 .count { font-size: 12px; font-weight: 400; color: #9ca3af; }
.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.red { background: #d92d20; } .amber { background: #e08a00; } .gray { background: #b0b6bf; }
.blue { background: #2f6fde; }
.row { display: grid; grid-template-columns: 74px 1fr auto; gap: 10px; align-items: center;
  padding: 10px 0; border-top: 1px solid #f0f1f3; }
h2 + .row, h2 + .crow { border-top: 0; }
.when .d { font-size: 13px; font-weight: 600; }
.when .t { font-size: 12px; color: #6b7280; margin-top: 1px; }
.name { font-size: 15px; }
.name b { font-weight: 700; margin-right: 4px; }
.name span { color: #4b5563; }
.est { font-size: 12px; color: #6b7280; margin-top: 2px; }
.up { color: #d92d20; font-weight: 600; } .down { color: #12a150; font-weight: 600; }
.badge { font-size: 12px; white-space: nowrap; border-radius: 999px; padding: 2px 9px; }
.badge.hot { background: #fdecea; color: #d92d20; font-weight: 600; }
.badge.warm { background: #fdf3e1; color: #b86e00; }
.badge.cool { background: #f1f2f4; color: #6b7280; }
.badge.beat { background: #fdecea; color: #d92d20; font-weight: 600; }
.badge.miss { background: #e6f6ec; color: #12a150; font-weight: 600; }
.crow { display: grid; grid-template-columns: 1fr auto auto; gap: 10px; align-items: center;
  padding: 8px 0; border-top: 1px solid #f0f1f3; font-size: 14px; }
.crow .w { font-size: 12px; color: #6b7280; white-space: nowrap; }
.chips { padding: 4px 0 10px; display: flex; flex-wrap: wrap; gap: 6px; }
.chips span { font-size: 12px; color: #4b5563; background: #f3f4f6; border-radius: 6px; padding: 3px 8px; }
footer { font-size: 11px; color: #9ca3af; text-align: center; line-height: 1.6; padding: 12px 8px 2px; }
"""


def render_html(report: Report) -> str:
    now = report.now
    parts = [
        "<!doctype html>",
        '<html lang="zh-CN"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>美股财报日历 {now:%m/%d}</title>",
        f"<style>{CSS}</style></head><body><main class=\"page\">",
        "<header>",
        '<div class="title">美股财报日历</div>',
        f'<div class="date">{now:%Y/%m/%d} 周{"一二三四五六日"[now.weekday()]} · 北京时间 {now:%H:%M} 更新</div>',
        '<div class="stats">',
        f"<span>关注 {report.total} 家</span>",
        f"<span>7 天内 <b>{len(report.within_7)}</b> 家</span>",
        f"<span>8–30 天 {len(report.within_30)} 家</span>",
        "</div></header>",
    ]

    if report.recent:
        parts.append(_section_head("blue", "过去 24 小时已发布", len(report.recent)))
        parts += [_recent_row(e) for e in report.recent]
        parts.append("</section>")

    if report.within_7:
        parts.append(_section_head("red", "7 天内", len(report.within_7)))
        parts += [_hot_row(e) for e in report.within_7]
        parts.append("</section>")

    for color, label, badge, bucket in (
        ("amber", "8–30 天", "warm", report.within_30),
        ("gray", f"31–{report.horizon_days} 天", "cool", report.later),
    ):
        if bucket:
            parts.append(_section_head(color, label, len(bucket)))
            parts += [_compact_row(e, badge) for e in bucket]
            parts.append("</section>")

    if report.no_date:
        parts.append(_section_head("gray", f"{report.horizon_days} 天内暂无日期", len(report.no_date)))
        parts.append('<div class="chips">')
        parts += [f"<span>{_label(s.symbol, s.label)}</span>" for s in report.no_date]
        parts.append("</div></section>")

    if report.failed:
        parts.append(_section_head("gray", "查询失败", len(report.failed)))
        parts.append('<div class="chips">')
        parts += [f"<span>{escape(s.label)}：{escape(reason)}</span>" for s, reason in report.failed]
        parts.append("</div></section>")

    parts += [
        "<footer>数据来源 Finnhub · 预期为分析师一致预期（non-GAAP）<br>"
        "营收按财报货币计，多数为美元，中概股可能为人民币<br>"
        "标注「时段未定」及较远的日期多为预估，以公司公告为准</footer>",
        "</main></body></html>",
    ]
    return "\n".join(parts)


def _section_head(color: str, label: str, count: int) -> str:
    return f'<section><h2><i class="dot {color}"></i>{escape(label)}<span class="count">{count} 家</span></h2>'


def _label(symbol: str, label: str) -> str:
    name = label[len(symbol):].strip()
    return f"<b>{escape(symbol)}</b><span>{escape(name)}</span>" if name else f"<b>{escape(symbol)}</b>"


def _when(event: EarningsEvent) -> tuple[str, str]:
    """(日期, 补充说明)：时段已知时给北京时间，否则给美东日期。"""
    slot = beijing_slot(event)
    if slot is None:
        return us_day(event), "美东 · 未定"  # 太长会在窄列里折成三行
    return fmt_day(slot[0]), f"{slot[1]} · {session_name(event)}"


def _hot_row(e: Entry) -> str:
    ev = e.event
    d, t = _when(ev)
    details = []  # EPS 和营收各占一行，避免手机宽度下折行
    if eps := fmt_eps(ev.eps_estimate):
        for name, pct, base in eps_changes(ev.eps_estimate, e.baseline):
            if pct is not None:
                cls = "up" if pct >= 0 else "down"
                eps += f' · <span class="{cls}">{name} {pct:+.0f}%</span>'
            else:
                eps += f" · {BASE_NAMES[name]} {base:.2f}"
        details.append(f"EPS 预期 {eps}")
    if revenue := fmt_revenue(ev.revenue_estimate):
        details.append(f"营收预期 {revenue}")
    est = "".join(f'<div class="est">{line}</div>' for line in details)
    return (
        f'<div class="row"><div class="when"><div class="d">{d}</div><div class="t">{t}</div></div>'
        f'<div><div class="name">{_label(e.stock.symbol, e.stock.label)}</div>{est}</div>'
        f'<div class="badge hot">{fmt_days(e.days)}</div></div>'
    )


def _compact_row(e: Entry, badge: str) -> str:
    d, t = _when(e.event)
    when = f"{d} {t.split(' · ')[0]}" if beijing_slot(e.event) else f"美东 {d}"
    return (
        f'<div class="crow"><div class="name">{_label(e.stock.symbol, e.stock.label)}</div>'
        f'<div class="w">{when}</div><div class="badge {badge}">{fmt_days(e.days)}</div></div>'
    )


def _recent_row(e: Entry) -> str:
    ev = e.event
    d, t = _when(ev)
    if ev.eps_actual is None:
        result, badge = "实际数据待更新", ""
    else:
        result = f"EPS 实际 {ev.eps_actual:.2f}"
        badge = ""
        if ev.eps_estimate is not None:
            result += f" / 预期 {ev.eps_estimate:.2f}"
            if ev.eps_actual > ev.eps_estimate:
                badge = '<div class="badge beat">超预期</div>'
            elif ev.eps_actual < ev.eps_estimate:
                badge = '<div class="badge miss">不及预期</div>'
            else:
                badge = '<div class="badge cool">符合预期</div>'
    return (
        f'<div class="row"><div class="when"><div class="d">{d}</div><div class="t">{t}</div></div>'
        f'<div><div class="name">{_label(e.stock.symbol, e.stock.label)}</div>'
        f'<div class="est">{result}</div></div>{badge or "<div></div>"}</div>'
    )
