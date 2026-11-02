"""企业微信群"消息推送"（原"群机器人"）。文档：https://developer.work.weixin.qq.com/document/path/91770

只能添加到内部群；每个机器人每分钟最多 20 条。
"""

from __future__ import annotations

import base64
import hashlib

import requests

MARKDOWN_MAX_BYTES = 4096
IMAGE_MAX_BYTES = 2 * 1024 * 1024  # base64 编码前


class WeComError(Exception):
    pass


def _post(webhook_url: str, payload: dict, timeout: float = 20) -> dict:
    try:
        resp = requests.post(webhook_url, json=payload, timeout=timeout)
    except requests.RequestException as e:
        # 不把异常原文抛出去：里面的 URL 含有 webhook key
        raise WeComError(f"网络错误：{type(e).__name__}") from None
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200 or data.get("errcode") != 0:
        raise WeComError(f"推送失败（HTTP {resp.status_code}）：{data.get('errmsg') or resp.text[:200]}")
    return data


def truncate_utf8(text: str, max_bytes: int) -> str:
    """按 UTF-8 字节数截断，不切坏多字节字符。"""
    raw = text.encode("utf-8")
    if len(raw) <= max_bytes:
        return text
    return raw[: max_bytes - 3].decode("utf-8", errors="ignore") + "…"


def send_markdown(webhook_url: str, content: str) -> dict:
    """markdown 只支持标题、加粗、链接、引用和三种颜色（info 绿 / comment 灰 / warning 橙红）。"""
    content = truncate_utf8(content, MARKDOWN_MAX_BYTES)
    return _post(webhook_url, {"msgtype": "markdown", "markdown": {"content": content}})


def send_image(webhook_url: str, image: bytes) -> dict:
    """图片直接显示在群聊里；JPG/PNG，编码前不超过 2MB。"""
    if len(image) > IMAGE_MAX_BYTES:
        raise WeComError(f"图片 {len(image) / 1024 / 1024:.1f}MB，超过 2MB 上限")
    payload = {
        "msgtype": "image",
        "image": {"base64": base64.b64encode(image).decode("ascii"), "md5": hashlib.md5(image).hexdigest()},
    }
    return _post(webhook_url, payload)
