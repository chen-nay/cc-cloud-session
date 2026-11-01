"""用无头浏览器把 HTML 报告截成 PNG。需要 playwright；中文显示需要系统装有中文字体。"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from .html_report import PAGE_WIDTH

log = logging.getLogger(__name__)


def screenshot(html_path: Path, png_path: Path, scale: int = 2) -> None:
    from playwright.sync_api import Error, sync_playwright

    with sync_playwright() as p:
        # 优先用 playwright 自带的 Chromium；没装的话退回到系统里的 Chrome（GitHub 的 Ubuntu 机器自带）
        try:
            browser = p.chromium.launch(executable_path=os.environ.get("CHROMIUM_PATH") or None)
        except Error as e:
            log.warning("启动 Chromium 失败，改用系统 Chrome：%s", str(e).splitlines()[0])
            browser = p.chromium.launch(channel="chrome")
        try:
            page = browser.new_page(viewport={"width": PAGE_WIDTH, "height": 800}, device_scale_factor=scale)
            page.goto(html_path.resolve().as_uri())
            page.evaluate("document.fonts.ready")
            png_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(png_path), full_page=True)
        finally:
            browser.close()
