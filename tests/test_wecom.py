import base64
import hashlib
from datetime import date, datetime

import pytest

from earnings_watch import wecom
from earnings_watch.models import EarningsEvent, Stock
from earnings_watch.report import BJ, build_report, render_wecom_markdown

NOW = datetime(2026, 11, 2, 10, 0, tzinfo=BJ)


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


@pytest.fixture
def posted(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return FakeResponse(200, {"errcode": 0, "errmsg": "ok"})

    monkeypatch.setattr(wecom.requests, "post", fake_post)
    return calls


def test_send_image_payload(posted):
    png = b"\x89PNG fake image"
    wecom.send_image("https://hook", png)
    url, payload = posted[0]
    assert url == "https://hook"
    assert payload["msgtype"] == "image"
    assert base64.b64decode(payload["image"]["base64"]) == png
    assert payload["image"]["md5"] == hashlib.md5(png).hexdigest()


def test_send_image_rejects_over_2mb(posted):
    with pytest.raises(wecom.WeComError, match="超过 2MB"):
        wecom.send_image("https://hook", b"x" * (2 * 1024 * 1024 + 1))
    assert posted == []


def test_send_markdown_truncates_to_4096_bytes(posted):
    wecom.send_markdown("https://hook", "财" * 2000)  # 6000 字节
    content = posted[0][1]["markdown"]["content"]
    assert len(content.encode("utf-8")) <= 4096
    assert content.endswith("…")


def test_error_code_raises(monkeypatch):
    monkeypatch.setattr(
        wecom.requests, "post", lambda url, json=None, timeout=None: FakeResponse(200, {"errcode": 93000, "errmsg": "invalid webhook url"})
    )
    with pytest.raises(wecom.WeComError, match="invalid webhook url"):
        wecom.send_markdown("https://hook", "hi")


def test_wecom_markdown_groups_7_day_entries_by_day():
    stocks = [Stock("AAPL", "苹果"), Stock("PLTR", "Palantir"), Stock("AMD"), Stock("NVDA", "英伟达"), Stock("DDOG")]
    events = {
        "AAPL": [EarningsEvent("AAPL", date(2026, 11, 2), "amc")],  # 明天
        "PLTR": [EarningsEvent("PLTR", date(2026, 11, 2), "amc")],  # 明天
        "AMD": [EarningsEvent("AMD", date(2026, 11, 3), "amc")],  # 后天
        "NVDA": [EarningsEvent("NVDA", date(2026, 11, 18), "amc")],  # 不在 7 天内
        "DDOG": [EarningsEvent("DDOG", date(2026, 11, 1), "bmo", eps_estimate=0.55, eps_actual=0.60)],  # 刚发布
    }
    md = render_wecom_markdown(build_report(stocks, events, {}, NOW))
    assert '7 天内 <font color="warning">3</font> 家' in md
    assert '> <font color="warning">明天</font>　AAPL 苹果 · PLTR Palantir' in md
    assert '> <font color="warning">后天</font>　AMD' in md
    assert '> **刚发布** DDOG <font color="warning">超预期</font>' in md
    assert "NVDA" not in md


def test_wecom_markdown_when_nothing_within_7_days():
    md = render_wecom_markdown(build_report([Stock("A")], {"A": []}, {}, NOW))
    assert "未来 7 天没有关注的公司发财报" in md
