from datetime import date, datetime

from earnings_watch.models import EarningsEvent, Stock
from earnings_watch.report import (
    BJ,
    TITLE_MAX,
    build_report,
    fmt_beijing,
    fmt_revenue,
    render_markdown,
    render_title,
)
from earnings_watch.sample import sample_events

# 北京时间 2026-11-02（周一）10:00 = 美东 11-01（周日）21:00，美国已切换回冬令时
NOW = datetime(2026, 11, 2, 10, 0, tzinfo=BJ)


def ev(symbol, day, hour="amc", **kw):
    return EarningsEvent(symbol, day, hour, **kw)


def test_beijing_time_conversion_winter():
    # 冬令时：美东 = 北京 - 13 小时
    assert fmt_beijing(ev("A", date(2026, 11, 5), "amc")) == "北京 11/06 周五 凌晨"
    assert fmt_beijing(ev("A", date(2026, 11, 5), "bmo")) == "北京 11/05 周四 晚间"


def test_beijing_time_conversion_summer():
    # 夏令时：美东 = 北京 - 12 小时
    assert fmt_beijing(ev("A", date(2026, 7, 30), "amc")) == "北京 07/31 周五 凌晨"
    assert fmt_beijing(ev("A", date(2026, 7, 30), "bmo")) == "北京 07/30 周四 晚间"


def test_unknown_session_shows_us_date():
    assert fmt_beijing(ev("A", date(2026, 11, 5), "")) == "美东 11/05 周四 时段未定"


def test_buckets_and_days():
    stocks = [Stock(s) for s in ["A", "B", "C", "D", "E", "F", "G"]]
    events = {
        "A": [ev("A", date(2026, 11, 2), "bmo")],  # 北京 11/02 晚间 → 今天
        "B": [ev("B", date(2026, 11, 2), "amc")],  # 北京 11/03 凌晨 → 明天
        "C": [ev("C", date(2026, 11, 20), "amc")],  # 北京 11/21 → 19 天
        "D": [ev("D", date(2026, 12, 20), "amc")],  # 北京 12/21 → 49 天
        "E": [],
        "G": [ev("G", date(2027, 1, 28), "amc")],  # 超出 60 天，算作暂无日期
    }
    report = build_report(stocks, events, {"F": "HTTP 500"}, NOW)
    assert [(e.stock.symbol, e.days) for e in report.within_7] == [("A", 0), ("B", 1)]
    assert [(e.stock.symbol, e.days) for e in report.within_30] == [("C", 19)]
    assert [(e.stock.symbol, e.days) for e in report.later] == [("D", 49)]
    assert [s.symbol for s in report.no_date] == ["E", "G"]
    assert [(s.symbol, r) for s, r in report.failed] == [("F", "HTTP 500")]
    md = render_markdown(report)
    assert "#### ⚪ 31–60 天（1 家）" in md
    assert "#### ❔ 60 天内暂无日期" in md


def test_just_released_goes_to_recent_and_next_event_is_upcoming():
    # 美东 10/30 盘后 = 北京 10/31 凌晨，已超过 24 小时；美东 11/01 盘前 = 北京 11/01 21:00，在 24 小时内
    events = {
        "A": [
            ev("A", date(2026, 10, 30), "amc", eps_estimate=1.0, eps_actual=1.2),
            ev("A", date(2026, 11, 1), "bmo", eps_estimate=1.0, eps_actual=0.9),
            ev("A", date(2026, 12, 15), "amc"),
        ]
    }
    report = build_report([Stock("A")], events, {}, NOW)
    assert [e.event.date for e in report.recent] == [date(2026, 11, 1)]
    assert report.later[0].event.date == date(2026, 12, 15)
    assert "EPS 实际 0.90 / 预期 1.00 ❌ 不及预期" in render_markdown(report)


def test_just_released_without_next_date_is_not_listed_as_no_date():
    events = {"A": [ev("A", date(2026, 11, 1), "bmo")]}
    report = build_report([Stock("A")], events, {}, NOW)
    assert len(report.recent) == 1
    assert report.no_date == []


def test_label_skips_name_equal_to_symbol():
    assert Stock("AMD", "AMD").label == "AMD"
    assert Stock("AAPL", "苹果").label == "AAPL 苹果"


def test_title_fits_serverchan_limit():
    stocks = [Stock(f"SYM{i}") for i in range(10)]
    events = {s.symbol: [ev(s.symbol, date(2026, 11, 3))] for s in stocks}
    title = render_title(build_report(stocks, events, {}, NOW))
    assert len(title) <= TITLE_MAX
    assert title.startswith("美股财报 11/02｜7天内10家: SYM")
    assert title.endswith(" 等")
    assert "\n" not in title


def test_title_without_upcoming_in_7_days():
    report = build_report([Stock("A")], {"A": [ev("A", date(2026, 11, 20))]}, {}, NOW)
    assert render_title(report) == "美股财报 11/02｜最近: A 19 天后"
    assert render_title(build_report([Stock("A")], {"A": []}, {}, NOW)) == "美股财报 11/02｜近期无财报"


def test_revenue_format():
    assert fmt_revenue(102.3e9) == "1023 亿美元"
    assert fmt_revenue(5.25e8) == "5.2 亿美元"
    assert fmt_revenue(3.4e7) == "3400 万美元"
    assert fmt_revenue(None) is None


def test_markdown_sections_without_links():
    stocks = [Stock("NVDA", "英伟达")]
    events = {"NVDA": [ev("NVDA", date(2026, 11, 4), "amc", eps_estimate=1.25, revenue_estimate=5.4e10)]}
    md = render_markdown(build_report(stocks, events, {}, NOW))
    assert "🔴 7 天内（1 家）" in md
    assert "**NVDA 英伟达** · **3 天后**" in md
    assert "北京 11/05 周四 凌晨（美东 11/04 周三 盘后）" in md
    assert "EPS 预期 1.25 · 营收预期 540 亿美元" in md
    assert "earningswhispers" not in md


def test_unknown_session_is_not_repeated_in_7_day_section():
    md = render_markdown(build_report([Stock("ARM")], {"ARM": [ev("ARM", date(2026, 11, 5), "")]}, {}, NOW))
    assert "- 美东 11/05 周四 时段未定\n" in md
    assert "（美东" not in md


def test_sample_data_fills_every_section():
    stocks = [Stock(f"S{i}") for i in range(10)]
    report = build_report(stocks, sample_events(stocks, NOW), {}, NOW)
    assert report.recent and report.within_7 and report.within_30 and report.later and report.no_date


def test_7_day_entry_without_estimates_has_no_empty_line():
    md = render_markdown(build_report([Stock("X")], {"X": [ev("X", date(2026, 11, 4), "amc")]}, {}, NOW))
    assert "- 北京 11/05 周四 凌晨（美东 11/04 周三 盘后）\n\n" in md
    assert "\n- \n" not in md
