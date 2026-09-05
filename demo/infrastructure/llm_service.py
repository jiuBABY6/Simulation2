"""DeepSeek JSON 调用服务。

本模块只负责网络请求和 JSON 解析，不包含 Persona 规则或业务决策逻辑。
"""

import json
import threading
import time

import requests

from project_config import (
    DEEPSEEK_API_KEY,
    DEEPSEEK_ENDPOINT,
    DEEPSEEK_MODEL,
    HTTP_RETRY_COUNT,
    HTTP_RETRY_INTERVAL,
    REQUEST_TIMEOUT,
)


# 2026/09/04 Demo性能基线，新增功能：在线程安全的进程内统计各类LLM请求、重试和耗时。
_LLM_STATS_LOCK = threading.Lock()


def _create_stats_bucket():
    """创建一个空的LLM性能统计容器。"""
    return {
        "logical_request_count": 0,
        "http_attempt_count": 0,
        "retry_count": 0,
        "failed_request_count": 0,
        "total_duration_seconds": 0.0,
    }


_LLM_PERFORMANCE_STATS = {
    **_create_stats_bucket(),
    "by_type": {},
}


def reset_llm_performance_stats():
    """清空当前进程的LLM性能统计。"""
    global _LLM_PERFORMANCE_STATS
    with _LLM_STATS_LOCK:
        _LLM_PERFORMANCE_STATS = {
            **_create_stats_bucket(),
            "by_type": {},
        }


def _rounded_stats_bucket(bucket):
    """复制统计容器，并统一耗时精度。"""
    result = dict(bucket)
    result["total_duration_seconds"] = round(
        float(result.get("total_duration_seconds", 0.0)),
        3,
    )
    return result


def get_llm_performance_stats():
    """返回当前进程的LLM性能统计快照。"""
    with _LLM_STATS_LOCK:
        result = _rounded_stats_bucket(_LLM_PERFORMANCE_STATS)
        result["by_type"] = {
            request_type: _rounded_stats_bucket(bucket)
            for request_type, bucket in _LLM_PERFORMANCE_STATS[
                "by_type"
            ].items()
        }
    return result


def merge_llm_performance_stats(*stats_items):
    """合并主进程和多个时间步子进程返回的LLM统计。"""
    merged = {
        **_create_stats_bucket(),
        "by_type": {},
    }
    metric_names = tuple(_create_stats_bucket())

    for stats in stats_items:
        if not isinstance(stats, dict):
            continue
        for metric_name in metric_names:
            value = stats.get(metric_name, 0)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                merged[metric_name] += value

        by_type = stats.get("by_type", {})
        if not isinstance(by_type, dict):
            continue
        for request_type, bucket in by_type.items():
            if not isinstance(bucket, dict):
                continue
            target = merged["by_type"].setdefault(
                str(request_type),
                _create_stats_bucket(),
            )
            for metric_name in metric_names:
                value = bucket.get(metric_name, 0)
                if isinstance(value, (int, float)) and not isinstance(
                    value,
                    bool,
                ):
                    target[metric_name] += value

    result = _rounded_stats_bucket(merged)
    result["by_type"] = {
        request_type: _rounded_stats_bucket(bucket)
        for request_type, bucket in merged["by_type"].items()
    }
    return result


def _record_llm_performance(request_type, duration, attempt_count, failed):
    """记录一次逻辑调用及其实际HTTP尝试。"""
    request_type = str(request_type).strip() or "unknown"
    retry_count = max(int(attempt_count) - 1, 0)
    with _LLM_STATS_LOCK:
        type_stats = _LLM_PERFORMANCE_STATS["by_type"].setdefault(
            request_type,
            _create_stats_bucket(),
        )
        for bucket in (_LLM_PERFORMANCE_STATS, type_stats):
            bucket["logical_request_count"] += 1
            bucket["http_attempt_count"] += int(attempt_count)
            bucket["retry_count"] += retry_count
            bucket["failed_request_count"] += int(bool(failed))
            bucket["total_duration_seconds"] += duration


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


def call_deepseek_json(
    prompt,
    system_prompt,
    temperature=0,
    max_tokens=2000,
    request_type="unknown",
):
    """调用DeepSeek，按请求类型记录性能，并在临时错误发生时重试。"""
    # 2026/09/04 Demo性能基线，修改功能：区分逻辑调用和实际HTTP尝试，并统计完整等待时间。
    start_time = time.perf_counter()
    attempt_count = 0
    succeeded = False
    try:
        if not DEEPSEEK_API_KEY or DEEPSEEK_API_KEY.startswith("请在"):
            raise ValueError("请先在 project_config.py 中填写 DEEPSEEK_API_KEY。")

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": DEEPSEEK_MODEL,
            "thinking": {"type": "disabled"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }

        # 联调修改：统一重试网络、限流、服务端和JSON解析错误 2026/08/21 19：06
        last_error = None
        for attempt in range(1, HTTP_RETRY_COUNT + 1):
            attempt_count = attempt
            try:
                response = requests.post(
                    DEEPSEEK_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
            except requests.RequestException as error:
                last_error = error
            else:
                if response.status_code == 200:
                    finish_reason = None
                    content = ""
                    try:
                        response_data = response.json()
                        choice = response_data["choices"][0]
                        finish_reason = choice.get("finish_reason")
                        content = choice["message"]["content"]
                        result = parse_first_json(content)
                        succeeded = True
                        return result
                    except (
                        ValueError,
                        KeyError,
                        IndexError,
                        TypeError,
                        AttributeError,
                    ) as error:
                        # 2026/08/24 第三次联调问题修复，修改功能：明确记录模型输出截断原因和实际字符数。
                        content_length = (
                            len(content) if isinstance(content, str) else 0
                        )
                        if finish_reason == "length":
                            last_error = ValueError(
                                "模型输出达到 max_tokens 后被截断，"
                                f"输出字符数：{content_length}"
                            )
                        else:
                            last_error = ValueError(
                                f"{error}；finish_reason={finish_reason}；"
                                f"输出字符数：{content_length}"
                            )
                elif response.status_code == 429 or response.status_code >= 500:
                    last_error = RuntimeError(
                        f"HTTP {response.status_code}，{response.text}"
                    )
                else:
                    raise RuntimeError(
                        f"DeepSeek 请求失败且不可重试："
                        f"HTTP {response.status_code}，{response.text}"
                    )

            print(
                f"DeepSeek 请求失败，第 {attempt}/{HTTP_RETRY_COUNT} 次："
                f"{last_error}"
            )
            if attempt < HTTP_RETRY_COUNT:
                time.sleep(HTTP_RETRY_INTERVAL)

        raise RuntimeError(
            f"DeepSeek 请求重试后仍然失败：{last_error}"
        ) from last_error
    finally:
        _record_llm_performance(
            request_type=request_type,
            duration=time.perf_counter() - start_time,
            attempt_count=attempt_count,
            failed=not succeeded,
        )
