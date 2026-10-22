"""Persona 流水线共享的微博文本适配函数。

该模块只处理输入结构和文本清洗，不连接 MongoDB，也不调用模型，便于
Persona 构建与派系分类独立复用和测试。
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterator
from typing import Any


REPOST_PLACEHOLDERS = {"转发微博", "转发", "repost"}


def clean_weibo_text(value: Any) -> str:
    """清洗微博文本；空值和纯转发占位符视为无效文本。"""

    if not isinstance(value, str):
        return ""
    cleaned = html.unescape(value)
    cleaned = re.sub(r"<[^>]+>", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    if cleaned.lower() in REPOST_PLACEHOLDERS:
        return ""
    return cleaned


def get_nested_value(document: dict, *keys: str, default: Any = None) -> Any:
    """按照多层字段路径安全读取字典值。"""

    value: Any = document
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def extract_user_record(document: dict) -> dict:
    """兼容平铺用户文档和包含 ``wb.user`` 的嵌套文档。"""

    candidate = get_nested_value(document, "wb", "user")
    if isinstance(candidate, dict):
        return candidate
    candidate = document.get("user")
    if isinstance(candidate, dict) and "id" in candidate:
        return candidate
    return document


def iterate_post_records(document: dict) -> Iterator[dict]:
    """兼容单条微博文档和 ``wb.weibo`` 列表存储结构。"""

    candidates = (
        get_nested_value(document, "wb", "weibo"),
        document.get("weibo"),
    )
    for candidate in candidates:
        if isinstance(candidate, list):
            yield from (post for post in candidate if isinstance(post, dict))
            return
    yield document


def normalize_user_id(value: Any) -> str:
    """把数据库中的用户或微博 ID 统一为关联用字符串。"""

    return str(value).strip() if value is not None else ""


def split_post_texts(post: dict) -> tuple[str, str, bool]:
    """拆分主题分类文本、用户自身表达文本和转发标记。"""

    own_text = clean_weibo_text(post.get("text"))
    retweet = post.get("retweet")
    is_repost = isinstance(retweet, dict)
    if not is_repost:
        return own_text, own_text, False
    original_text = clean_weibo_text(retweet.get("text"))
    return original_text or own_text, own_text, True


def should_skip_post(post: dict) -> bool:
    """判断微博正文是否为空或只是转发占位符。"""

    return not clean_weibo_text(post.get("text"))

