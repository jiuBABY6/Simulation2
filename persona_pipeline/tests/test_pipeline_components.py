from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PIPELINE_DIR = Path(__file__).resolve().parents[1]
if str(PIPELINE_DIR) not in sys.path:
    sys.path.insert(0, str(PIPELINE_DIR))

from policy_builder import build_global_policy_config
from deepseek_json_client import DeepSeekJsonClient
from text_processing import (
    clean_weibo_text,
    extract_user_record,
    iterate_post_records,
    split_post_texts,
)


class TextProcessingTests(unittest.TestCase):
    def test_normalizes_nested_mongodb_shapes(self) -> None:
        user = extract_user_record({"wb": {"user": {"id": 7}}})
        posts = list(
            iterate_post_records(
                {"wb": {"weibo": [{"id": 1}, {"id": 2}]}}
            )
        )
        self.assertEqual(user["id"], 7)
        self.assertEqual([post["id"] for post in posts], [1, 2])

    def test_repost_keeps_original_content_and_user_expression_separate(self) -> None:
        content, expression, is_repost = split_post_texts(
            {"text": "我的看法", "retweet": {"text": "原微博正文"}}
        )
        self.assertTrue(is_repost)
        self.assertEqual(content, "原微博正文")
        self.assertEqual(expression, "我的看法")
        self.assertEqual(clean_weibo_text("<b> 转发微博 </b>"), "")


class PolicyBuilderTests(unittest.TestCase):
    def test_builds_compatible_reference_population(self) -> None:
        persona = {
            "topic_preference": {
                "社会事件": 0.4,
                "新闻时事": 0.3,
                "娱乐": 0.2,
                "其他": 0.1,
            },
            "information_orientation": {
                "fact_rate": 0.5,
                "opinion_rate": 0.3,
                "questioning_rate": 0.2,
            },
            "action_preference": {
                "repost_preference": 0.6,
                "original_preference": 0.4,
            },
        }
        result = build_global_policy_config([persona])
        self.assertEqual(result["reference_population_size"], 1)
        self.assertEqual(
            result["candidate_rules"]["official_statement"]["clear"][
                "default"
            ],
            ["accept", "wait", "question"],
        )


class DeepSeekJsonClientTests(unittest.TestCase):
    def test_extracts_first_json_object_from_model_text(self) -> None:
        response = Mock()
        response.status_code = 200
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [
                {"message": {"content": '说明文字 {"items": []} 尾部'}}
            ]
        }
        client = DeepSeekJsonClient(
            api_key="test-key",
            endpoint="https://example.invalid",
        )
        with patch("deepseek_json_client.requests.post", return_value=response):
            result = client.request_object(
                {"model": "test"},
                format_error_prefix="format",
                request_error_prefix="request",
            )
        self.assertEqual(result, {"items": []})


if __name__ == "__main__":
    unittest.main()

