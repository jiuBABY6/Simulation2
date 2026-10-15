"""历史校准评论任务与共享生成器兼容性的离线测试。"""

from __future__ import annotations

import sys
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_DIR = PROJECT_ROOT / "demo"
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from comments.generation_service import FACTIONS, normalize_comments
from comments.pool_generator import build_generation_prompt, generate_comment_pool


EVENT = {
    "event_id": "event_test",
    "event_content": "一名学生失联，搜寻仍在继续。",
    "event_labels": {"topic": "新闻时事", "event_valence": "negative"},
}
PROFILES = [
    {
        "profile_id": 1,
        "profile_label": "测试人物",
        "definition": "根据现有信息表达看法。",
    }
]
TASK = {
    "task_id": "initial_001",
    "angle_id": "safety",
    "angle_name": "安全",
    "focus": "关注安全影响",
    "expression_mode": "impact",
    "expression_instruction": "关注事件对公众的影响。",
    "required_emotion": "negative",
}

ANGLE_PLAN = {
    "event_id": "event_test",
    "generation_method": "test_fixture",
    "angles": [
        {
            "angle_id": f"angle_{index}",
            "angle_name": f"角度{index}",
            "focus": f"关注角度{index}",
            "evidence_text": "学生失联",
            "source_type": "event",
        }
        for index in range(1, 9)
    ],
}

INITIAL_OPINION = {
    "event_id": "event_test",
    "mode": "historical_calibration",
    "comment_count": 60,
    "emotion_targets": {
        "negative": 51,
        "neutral": 9,
        "positive": 0,
    },
    "evaluation_role": "initial_condition",
    "source": {"type": "test_fixture"},
}


def _mock_generated_comments(**kwargs) -> list[dict]:
    """按任务返回已规范化评论，避免离线测试访问外部模型。"""
    comments = []
    for task in kwargs["comment_tasks"]:
        task_number = int(task["task_id"].rsplit("_", 1)[-1])
        required_emotion = task.get("required_emotion")
        comments.append(
            {
                "text": f"第{task_number}条离线测试评论，关注学生失联事件。",
                "profile_id": 1,
                "profile_label": "测试人物",
                "topic": "新闻时事",
                "emotion": required_emotion or "neutral",
                "required_emotion": required_emotion,
                "faction": FACTIONS[(task_number - 1) % len(FACTIONS)],
                "orientation": "opinion",
                "stance": "questioning",
                "task_id": task["task_id"],
                "angle_id": task["angle_id"],
                "angle_name": task["angle_name"],
                "angle_focus": task["focus"],
                "expression_mode": task["expression_mode"],
                "expression_instruction": task["expression_instruction"],
            }
        )
    return comments


def _raw_comment(emotion: str) -> dict:
    return {
        "comments": [
            {
                "task_id": "initial_001",
                "text": "学生安危仍无消息，让家属和公众非常担忧。",
                "profile_id": 1,
                "faction": "情绪激进派",
                "emotion": emotion,
                "orientation": "opinion",
                "stance": "support",
            }
        ]
    }


class CalibratedCommentPoolTests(unittest.TestCase):
    # 2026/10/8，新增功能：不符合任务配额的模型评论必须被过滤，不能靠改标签伪造。
    def test_rejects_comment_with_wrong_required_emotion(self) -> None:
        rejection_counts = {}
        comments = normalize_comments(
            _raw_comment("neutral"),
            EVENT,
            PROFILES,
            set(),
            rejection_counts=rejection_counts,
            comment_tasks=[TASK],
        )

        self.assertEqual(comments, [])
        self.assertEqual(rejection_counts["情绪不符合任务"], 1)

    def test_accepts_and_preserves_required_emotion(self) -> None:
        comments = normalize_comments(
            _raw_comment("negative"),
            EVENT,
            PROFILES,
            set(),
            comment_tasks=[TASK],
        )

        self.assertEqual(len(comments), 1)
        self.assertEqual(comments[0]["emotion"], "negative")
        self.assertEqual(comments[0]["required_emotion"], "negative")

    # 2026/10/8，新增功能：五策略未传 initial_opinion 时，提示词不出现历史校准约束。
    def test_default_prompt_keeps_uncalibrated_path(self) -> None:
        ordinary_task = dict(TASK)
        ordinary_task.pop("required_emotion")

        prompt = build_generation_prompt(
            EVENT,
            PROFILES,
            1,
            [ordinary_task],
        )

        self.assertNotIn("同阶段人工舆论背景", prompt)
        self.assertNotIn("required_emotion 完全一致", prompt)
        self.assertIn("覆盖五种评论派系、三种情绪", prompt)

    def test_calibrated_prompt_contains_ratio_constraint_without_public_summary(self) -> None:
        prompt = build_generation_prompt(
            EVENT,
            PROFILES,
            1,
            [TASK],
            INITIAL_OPINION,
        )

        self.assertIn("第一轮人工舆论初始条件", prompt)
        self.assertIn("required_emotion 完全一致", prompt)
        self.assertIn("不得引入真实评论摘要", prompt)
        self.assertNotIn("公众普遍担忧", prompt)

    # 2026/10/8，新增功能：完整评论池必须达到人工配额，并记录可审计的初始化元数据。
    @patch(
        "comments.pool_generator.generate_valid_comment_batch",
        side_effect=_mock_generated_comments,
    )
    @patch(
        "comments.pool_generator.generate_event_angle_plan",
        return_value=ANGLE_PLAN,
    )
    @patch(
        "comments.pool_generator.load_generation_profiles",
        return_value=PROFILES,
    )
    def test_full_calibrated_pool_reaches_exact_emotion_targets(
        self,
        _load_profiles,
        _generate_angles,
        _generate_batch,
    ) -> None:
        result = generate_comment_pool(
            EVENT,
            profile_file="unused.json",
            comment_count=60,
            initial_opinion=INITIAL_OPINION,
        )

        counts = Counter(comment["emotion"] for comment in result["comments"])
        self.assertEqual(
            counts,
            Counter({"negative": 51, "neutral": 9}),
        )
        self.assertEqual(
            result["initialization"]["actual_emotion_counts"],
            INITIAL_OPINION["emotion_targets"],
        )
        self.assertTrue(
            all(
                comment["emotion"] == comment["required_emotion"]
                for comment in result["comments"]
            )
        )

    # 2026/10/8，修改功能：未传人工初始条件时保持原评论池结果结构，隔离五策略实验。
    @patch(
        "comments.pool_generator.generate_valid_comment_batch",
        side_effect=_mock_generated_comments,
    )
    @patch(
        "comments.pool_generator.generate_event_angle_plan",
        return_value=ANGLE_PLAN,
    )
    @patch(
        "comments.pool_generator.load_generation_profiles",
        return_value=PROFILES,
    )
    def test_full_default_pool_has_no_calibration_metadata(
        self,
        _load_profiles,
        _generate_angles,
        _generate_batch,
    ) -> None:
        result = generate_comment_pool(
            EVENT,
            profile_file="unused.json",
            comment_count=60,
        )

        self.assertNotIn("initialization", result)
        self.assertTrue(
            all(
                "required_emotion" not in comment
                for comment in result["comments"]
            )
        )


if __name__ == "__main__":
    unittest.main()
