"""Server酱 Turbo 推送到微信。文档：https://sct.ftqq.com/docs/"""

from __future__ import annotations

import re

import requests

TITLE_MAX = 32


class ServerChanError(Exception):
    pass


def endpoint(sendkey: str) -> str:
    # Server酱³ 的 key 形如 sctp{uid}t...，接口地址不同
    if sendkey.startswith("sctp"):
        m = re.match(r"^sctp(\d+)t", sendkey)
        if not m:
            raise ServerChanError("SendKey 格式不正确")
        return f"https://{m.group(1)}.push.ft07.com/send/{sendkey}.send"
    return f"https://sctapi.ftqq.com/{sendkey}.send"


def send(sendkey: str, title: str, desp: str, timeout: float = 20) -> dict:
    """发送一条消息。title 不能含换行、最长 32 字；desp 为 Markdown 正文。"""
    title = " ".join(title.split())[:TITLE_MAX]
    try:
        resp = requests.post(endpoint(sendkey), json={"title": title, "desp": desp}, timeout=timeout)
    except requests.RequestException as e:
        # 不把异常原文抛出去：里面的 URL 含有 SendKey
        raise ServerChanError(f"网络错误：{type(e).__name__}") from None
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200 or data.get("code") != 0:
        raise ServerChanError(f"推送失败（HTTP {resp.status_code}）：{data.get('message') or resp.text[:200]}")
    return data
