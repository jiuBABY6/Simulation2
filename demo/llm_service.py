"""DeepSeek JSON 调用服务。

本模块只负责网络请求和 JSON 解析，不包含 Persona 规则或业务决策逻辑。
"""

import json

import requests

from project_config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_ENDPOINT,
    DEEPSEEK_MODEL,
    REQUEST_TIMEOUT,
)


def parse_first_json(text):
    """从模型返回文本中读取第一个完整 JSON 对象，忽略后续多余文本。"""
    decoder = json.JSONDecoder()
    start = text.find("{")
    if start < 0:
        raise ValueError("模型返回内容中没有 JSON 对象。")
    data, _ = decoder.raw_decode(text[start:])
    if not isinstance(data, dict):
        raise ValueError("模型返回的 JSON 顶层结构不是对象。")
    return data


def call_deepseek_json(prompt, system_prompt, temperature=0, max_tokens=2000):
    """调用 DeepSeek，并解析为一个 JSON 对象。"""
    if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("请在"):
        raise ValueError("请先在 project_config.py 中填写 DEEPSEEK_API_KEY。")

    headers = {
        "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }

    response = requests.post(
        DEEPSEEK_ENDPOINT,
        headers=headers,
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"DeepSeek 请求失败：HTTP {response.status_code}，{response.text}"
        )

    response_data = response.json()
    try:
        content = response_data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError(f"DeepSeek 返回结构异常：{response_data}") from error
    return parse_first_json(content)

