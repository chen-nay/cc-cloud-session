import json
from datetime import date, datetime

from earnings_watch import __main__ as cli
from earnings_watch import serverchan, snapshot
from earnings_watch.html_report import render_html
from earnings_watch.models import EarningsEvent, Stock
from earnings_watch.report import BJ, attach_year_ago, build_report

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=BJ)


def sample_report():
    stocks = [Stock("NVDA", "英伟达"), Stock("ARM"), Stock("X", "<script>"), Stock("MU", "美光"), Stock("Z")]
    events = {
        "NVDA": [EarningsEvent("NVDA", date(2026, 11, 4), "amc", eps_estimate=1.25, revenue_estimate=5.4e10)],
        "ARM": [EarningsEvent("ARM", date(2026, 11, 5), "", eps_estimate=0.48)],
        "X": [EarningsEvent("X", date(2026, 11, 20), "bmo")],
        "MU": [EarningsEvent("MU", date(2026, 12, 15), "amc")],
        "Z": [],
    }
    report = build_report(stocks, events, {}, NOW)
    attach_year_ago(report, lambda ev: {"NVDA": 0.81, "ARM": 0.52}[ev.symbol])
    return report


def test_render_html_sections_and_values():
    page = render_html(sample_report())
    assert "<b>NVDA</b><span>英伟达</span>" in page
    assert '<span class="up">同比 +54%</span>' in page  # 红涨
    assert '<span class="down">同比 -8%</span>' in page  # 绿跌
    assert "营收预期 540 亿" in page
    assert "美东 · 时段未定" in page
    assert "7 天内" in page and "8–30 天" in page and "31–60 天" in page and "60 天内暂无日期" in page
    assert "&lt;script&gt;" in page and "<script>" not in page


def test_compose_body():
    message = {"title": "t", "text": "文字版", "image_url": "https://x.io/p/a.png", "page_url": "https://x.io/p"}
    body = cli.compose_body(message)
    assert body.startswith("![美股财报日历](https://x.io/p/a.png)\n\n[打开网页版](https://x.io/p/)")
    assert body.endswith("文字版")
    assert cli.compose_body(message, text_only=True) == "文字版"
    assert cli.compose_body({**message, "image_url": None}) == "文字版"


def test_build_site_returns_image_url(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "screenshot", lambda html, png: png.write_bytes(b"png"))
    url = cli.build_site(sample_report(), tmp_path, "https://chen-nay.github.io/cc-cloud-session/")
    assert url == "https://chen-nay.github.io/cc-cloud-session/report-20261102-1000.png"
    assert (tmp_path / "index.html").exists() and (tmp_path / "report-20261102-1000.png").exists()


def test_build_site_falls_back_to_text_when_screenshot_fails(tmp_path, monkeypatch):
    def broken(html, png):
        raise RuntimeError("no browser")

    monkeypatch.setattr(snapshot, "screenshot", broken)
    assert cli.build_site(sample_report(), tmp_path, "https://x.io") is None
    assert (tmp_path / "index.html").exists()


def test_send_previously_built_message(tmp_path, monkeypatch):
    path = tmp_path / "message.json"
    path.write_text(json.dumps({"title": "标题", "text": "正文", "image_url": "https://x.io/a.png", "page_url": None}))
    sent = []
    monkeypatch.setattr(serverchan, "send", lambda key, title, body: sent.append((key, title, body)))
    monkeypatch.setenv("SERVERCHAN_SENDKEY", "SCTkey")
    assert cli.main(["--send", str(path)]) == 0
    assert cli.main(["--send", str(path), "--text-only"]) == 0
    assert sent[0] == ("SCTkey", "标题", "![美股财报日历](https://x.io/a.png)\n\n---\n\n正文")
    assert sent[1] == ("SCTkey", "标题", "正文")
