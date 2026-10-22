"""Persona 分类任务共用的 DeepSeek JSON 请求客户端。"""

from __future__ import annotations

import json
import time
from typing import Any

import requests


class DeepSeekBadRequestError(RuntimeError):
    """DeepSeek 拒绝请求内容时保留服务端错误详情。"""


class DeepSeekResponseFormatError(RuntimeError):
    """响应成功但无法解析出 JSON 对象。"""


class DeepSeekJsonClient:
    """封装分类脚本共同使用的认证、重试和 JSON 对象解析。"""

    def __init__(
        self,
        *,
        api_key: str,
        endpoint: str,
        timeout: int = 90,
        retry_count: int = 3,
    ) -> None:
        self.api_key = api_key
        self.endpoint = endpoint
        self.timeout = timeout
        self.retry_count = retry_count

    def request_object(
        self,
        payload: dict[str, Any],
        *,
        format_error_prefix: str,
        request_error_prefix: str,
    ) -> dict[str, Any]:
        """请求并解析首个 JSON 对象，保持原有指数退避规则。"""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        last_error: Exception | None = None
        for attempt in range(self.retry_count):
            try:
                response = requests.post(
                    self.endpoint,
                    headers=headers,
                    json=payload,
                    timeout=self.timeout,
                )
                if response.status_code == 400:
                    try:
                        error_detail = json.dumps(
                            response.json(), ensure_ascii=False
                        )
                    except ValueError:
                        error_detail = response.text
                    raise DeepSeekBadRequestError(error_detail[:1000])
                response.raise_for_status()
                content = response.json()["choices"][0]["message"][
                    "content"
                ].strip()
                json_start = content.find("{")
                if json_start < 0:
                    raise ValueError("DeepSeek returned no JSON object.")
                parsed, _ = json.JSONDecoder().raw_decode(content[json_start:])
                if not isinstance(parsed, dict):
                    raise ValueError(
                        "The first JSON value returned by DeepSeek is not an object."
                    )
                return parsed
            except DeepSeekBadRequestError:
                raise
            except (
                requests.RequestException,
                KeyError,
                TypeError,
                ValueError,
                json.JSONDecodeError,
            ) as error:
                last_error = error
                time.sleep(2**attempt)

        if isinstance(
            last_error, (KeyError, TypeError, ValueError, json.JSONDecodeError)
        ):
            raise DeepSeekResponseFormatError(
                f"{format_error_prefix}: {last_error}"
            )
        raise RuntimeError(f"{request_error_prefix}: {last_error}")

