import json
from datetime import date, datetime

from earnings_watch import __main__ as cli
from earnings_watch import serverchan, snapshot, wecom
from earnings_watch.html_report import render_html
from earnings_watch.models import EarningsEvent, EpsBaseline, Stock
from earnings_watch.report import BJ, attach_eps_baseline, build_report

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
    baselines = {
        "NVDA": EpsBaseline(last_quarter=1.30, year_ago=0.81),
        "ARM": EpsBaseline(last_quarter=-0.02, year_ago=0.52),
    }
    attach_eps_baseline(report, lambda ev: baselines[ev.symbol])
    return report


def test_render_html_sections_and_values():
    page = render_html(sample_report())
    assert "<b>NVDA</b><span>英伟达</span>" in page
    assert '<span class="up">同比 +54%</span>' in page  # 红涨
    assert '<span class="down">环比 -4%</span>' in page  # 绿跌
    assert '<span class="down">同比 -8%</span>' in page
    assert "上季 -0.02" in page  # 上季亏损时不给百分比
    assert "营收预期 540 亿" in page
    assert "美东 · 未定" in page
    assert "7 天内" in page and "8–30 天" in page and "31–60 天" in page and "60 天内暂无日期" in page
    assert "&lt;script&gt;" in page and "<script>" not in page


def test_compose_body():
    message = {"title": "t", "text": "文字版", "image_url": "https://x.io/p/a.png", "page_url": "https://x.io/p"}
    body = cli.compose_body(message)
    assert body.startswith("![美股财报日历](https://x.io/p/a.png)\n\n[打开网页版](https://x.io/p/)")
    assert body.endswith("文字版")
    assert cli.compose_body(message, no_pages=True) == "文字版"
    assert cli.compose_body({**message, "image_url": None}) == "文字版"


def test_build_site_returns_image_path(tmp_path, monkeypatch):
    monkeypatch.setattr(snapshot, "screenshot", lambda html, png: png.write_bytes(b"png"))
    path = cli.build_site(sample_report(), tmp_path)
    assert path == tmp_path / "report-20261102-1000.png" and path.exists()
    assert (tmp_path / "index.html").exists()


def test_build_site_falls_back_to_text_when_screenshot_fails(tmp_path, monkeypatch):
    def broken(html, png):
        raise RuntimeError("no browser")

    monkeypatch.setattr(snapshot, "screenshot", broken)
    assert cli.build_site(sample_report(), tmp_path) is None
    assert (tmp_path / "index.html").exists()


class Recorder:
    """记录 Server酱 和企业微信收到的消息；fail 指定的渠道抛出异常。"""

    def __init__(self, monkeypatch, fail=()):
        self.sent = []

        def serverchan_send(key, title, body):
            if "serverchan" in fail:
                raise serverchan.ServerChanError("boom")
            self.sent.append(("serverchan", title, body))

        def wecom_markdown(url, content):
            if "wecom" in fail:
                raise wecom.WeComError("boom")
            self.sent.append(("wecom-md", url, content))

        monkeypatch.setattr(serverchan, "send", serverchan_send)
        monkeypatch.setattr(wecom, "send_markdown", wecom_markdown)
        monkeypatch.setattr(wecom, "send_image", lambda url, image: self.sent.append(("wecom-img", url, image)))


def write_message(tmp_path, **overrides):
    image = tmp_path / "report.png"
    image.write_bytes(b"PNG")
    message = {
        "title": "标题",
        "text": "正文",
        "wecom_markdown": "### 摘要",
        "image_path": str(image),
        "image_url": "https://x.io/p/report.png",
        "page_url": "https://x.io/p",
        **overrides,
    }
    path = tmp_path / "message.json"
    path.write_text(json.dumps(message, ensure_ascii=False), encoding="utf-8")
    return path


def test_send_to_both_channels(tmp_path, monkeypatch):
    rec = Recorder(monkeypatch)
    monkeypatch.setenv("SERVERCHAN_SENDKEY", "SCTkey")
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://hook")
    assert cli.main(["--send", str(write_message(tmp_path))]) == 0
    assert [s[0] for s in rec.sent] == ["serverchan", "wecom-md", "wecom-img"]
    assert rec.sent[0][2].startswith("![美股财报日历](https://x.io/p/report.png)")
    assert rec.sent[1][2] == "### 摘要\n[打开网页版](https://x.io/p/)"
    assert rec.sent[2] == ("wecom-img", "https://hook", b"PNG")


def test_send_without_pages_still_uploads_image_to_wecom(tmp_path, monkeypatch):
    rec = Recorder(monkeypatch)
    monkeypatch.setenv("SERVERCHAN_SENDKEY", "SCTkey")
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://hook")
    assert cli.main(["--send", str(write_message(tmp_path)), "--no-pages"]) == 0
    assert rec.sent[0] == ("serverchan", "标题", "正文")  # 不引用网页上的图片
    assert rec.sent[1][2] == "### 摘要"  # 不附网页链接
    assert rec.sent[2][0] == "wecom-img"  # 图片直接上传，不依赖网页


def test_only_configured_channels_are_used(tmp_path, monkeypatch):
    rec = Recorder(monkeypatch)
    monkeypatch.delenv("SERVERCHAN_SENDKEY", raising=False)
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://hook")
    assert cli.main(["--send", str(write_message(tmp_path))]) == 0
    assert [s[0] for s in rec.sent] == ["wecom-md", "wecom-img"]
    monkeypatch.delenv("WECOM_WEBHOOK_URL")
    assert cli.main(["--send", str(write_message(tmp_path))]) == 2  # 一个渠道都没配置


def test_one_channel_failing_does_not_block_the_other(tmp_path, monkeypatch):
    rec = Recorder(monkeypatch, fail=("serverchan",))
    monkeypatch.setenv("SERVERCHAN_SENDKEY", "SCTkey")
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://hook")
    assert cli.main(["--send", str(write_message(tmp_path))]) == 1
    assert [s[0] for s in rec.sent] == ["wecom-md", "wecom-img"]


def test_alert_goes_to_all_channels(monkeypatch):
    rec = Recorder(monkeypatch)
    monkeypatch.setenv("SERVERCHAN_SENDKEY", "SCTkey")
    monkeypatch.setenv("WECOM_WEBHOOK_URL", "https://hook")
    assert cli.main(["--alert", "出错了"]) == 0
    assert rec.sent[0] == ("serverchan", "美股财报日历：运行失败", "出错了")
    assert rec.sent[1] == ("wecom-md", "https://hook", "**美股财报日历：运行失败**\n出错了")
