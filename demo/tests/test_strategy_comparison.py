"""三回应方案对照与 Agent 自主行为的离线回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.strategy_behavior import (  # noqa: E402
    apply_strategy_participation_policy,
)
from agents.decision_service import (  # noqa: E402
    decide_agent,
    generate_strategy_expression,
)
from agents.decision_engine import (  # noqa: E402
    build_allowed_choices,
    get_emotion_options,
    validate_cognition_decision,
)
from domain.contracts import (  # noqa: E402
    AgentDecisionInput,
    SimulationContext,
)
from evaluation.metrics import calculate_action_distribution  # noqa: E402
from experiment_runner import (  # noqa: E402
    calculate_strategy_effect_metrics,
    validate_official_response_options,
)
from simulation.options import normalize_simulation_options  # noqa: E402


def _response_options(count=3):
    return {
        "event_id": "event_test",
        "entry_strategy": "combined_policy",
        "stagnation_rounds": 2,
        "negative_rate_improvement_tolerance": 0.05,
        "content_strategies": [
            {
                "strategy_id": f"plan_{index}",
                "strategy_name": f"回应方案{index}",
                "official_statement": f"回应内容{index}",
                "official_statement_status": "clear",
            }
            for index in range(1, count + 1)
        ],
    }


class ResponsePlanValidationTests(unittest.TestCase):
    """三个方案可自由命名，但数量和唯一性必须稳定。"""

    def test_accepts_three_arbitrary_response_plans(self):
        result = validate_official_response_options(
            _response_options(),
            "event_test",
        )
        self.assertEqual(len(result["content_strategies"]), 3)
        self.assertEqual(
            [item["strategy_id"] for item in result["content_strategies"]],
            ["plan_1", "plan_2", "plan_3"],
        )

    def test_rejects_more_or_fewer_than_three_plans(self):
        for count in (2, 4):
            with self.subTest(count=count), self.assertRaisesRegex(
                ValueError,
                "恰好包含 3 个",
            ):
                validate_official_response_options(
                    _response_options(count),
                    "event_test",
                )

    def test_normalizes_explicit_official_evidence_dimensions(self):
        options = _response_options()
        options["content_strategies"][0]["evidence_dimensions"] = {
            "verified_fact": True,
            "unresolved_process": True,
        }

        result = validate_official_response_options(options, "event_test")
        dimensions = result["content_strategies"][0][
            "evidence_dimensions"
        ]

        self.assertTrue(dimensions["verified_fact"])
        self.assertTrue(dimensions["unresolved_process"])
        self.assertFalse(dimensions["completed_action"])

    def test_rejects_unknown_official_evidence_dimension(self):
        options = _response_options()
        options["content_strategies"][0]["evidence_dimensions"] = {
            "target_negative_rate": True,
        }

        with self.assertRaisesRegex(ValueError, "evidence_dimensions 不合法"):
            validate_official_response_options(options, "event_test")


class StrategyEffectMetricTests(unittest.TestCase):
    """覆盖场景结束时的状态历史读取，防止完整实验末尾才暴露缺失导入。"""

    @patch("experiment_runner.read_jsonl", return_value=[])
    def test_effect_metrics_reads_agent_state_history(self, mocked_reader):
        rounds = [
            {
                "step": 1,
                "policy_metrics": {"negative_rate": 0.5},
            },
            {
                "step": 2,
                "policy_metrics": {"negative_rate": 0.4},
            },
        ]

        result = calculate_strategy_effect_metrics(
            rounds,
            Path("scenario/state"),
            response_step=2,
        )

        mocked_reader.assert_called_once_with(
            Path("scenario/state/agent_state_history.jsonl")
        )
        self.assertEqual(result["analysis_start_step"], 2)


class StrategyBehaviorTests(unittest.TestCase):
    """发言门控必须可重复，且不改写 Agent 内部状态。"""

    def setUp(self):
        self.persona = {
            "agent_id": "agent_001",
            "topic_preference": {"社会事件": 0.6},
            "data_info": {"total_posts": 200},
        }
        self.context = {
            "event_id": "event_test",
            "event_labels": {"topic": "社会事件"},
            "current_state": {"step": 2},
        }
        self.decision = {
            "current_emotion": "negative",
            "official_attitude": "wait",
            "will_comment": True,
            "action_type": "original",
            "comment_faction": "观点输出派",
            "expression": {"text": "这是原创表达"},
        }

    def test_gate_is_deterministic_and_preserves_internal_state(self):
        arguments = (
            self.decision,
            self.persona,
            self.context,
            [{"comment_id": "c1", "introduced_step": 2}],
            {"current_emotion": "neutral", "official_attitude": "wait"},
            {"consecutive_comment_rounds": 0},
        )
        first = apply_strategy_participation_policy(*arguments)
        second = apply_strategy_participation_policy(*arguments)

        self.assertEqual(first, second)
        self.assertEqual(first["current_emotion"], "negative")
        self.assertEqual(first["official_attitude"], "wait")
        self.assertEqual(
            first["participation_assessment"]["mode"],
            "persona_state_gate",
        )

    @patch(
        "agents.strategy_behavior._stable_unit_interval",
        return_value=0.0,
    )
    def test_gate_does_not_depend_on_llm_requested_speech(self, _mocked_sample):
        """相同状态输入不得因旧will_comment占位值产生不同门控结果。"""

        arguments = (
            self.persona,
            self.context,
            [{"comment_id": "c1", "introduced_step": 2}],
            {"current_emotion": "neutral", "official_attitude": "wait"},
            {"consecutive_comment_rounds": 0},
        )
        requested = apply_strategy_participation_policy(
            {**self.decision, "will_comment": True},
            *arguments,
        )
        not_requested = apply_strategy_participation_policy(
            {**self.decision, "will_comment": False, "action_type": "silent"},
            *arguments,
        )

        self.assertTrue(requested["will_comment"])
        self.assertTrue(not_requested["will_comment"])
        self.assertEqual(requested["action_type"], not_requested["action_type"])
        self.assertNotIn(
            "llm_requested_speech",
            requested["participation_assessment"],
        )

    @patch(
        "agents.strategy_behavior._stable_unit_interval",
        return_value=0.99,
    )
    def test_first_statement_applicability_is_not_a_state_change(
        self,
        _mocked_sample,
    ):
        """not_applicable到wait不应给所有Agent统一增加状态变化分。"""

        context = {
            **self.context,
            "current_state": {
                "step": 2,
                "official_statement_timing": {"is_new": True},
            },
        }
        result = apply_strategy_participation_policy(
            {**self.decision, "official_attitude": "wait"},
            self.persona,
            context,
            [{"comment_id": "c1", "introduced_step": 2}],
            {
                "current_emotion": "negative",
                "official_attitude": "not_applicable",
            },
            {"consecutive_comment_rounds": 0},
        )

        assessment = result["participation_assessment"]
        self.assertFalse(assessment["state_changed"])
        self.assertEqual(
            assessment["components"]["official_response_motivation"],
            0.02,
        )

    @patch(
        "agents.strategy_behavior._stable_unit_interval",
        return_value=0.99,
    )
    def test_directional_evidence_enters_behavior_gate_without_polarity_bias(
        self,
        _mocked_sample,
    ):
        """状态证据只提供相关度和张力，不按负面标签直接奖励发言。"""

        decision = {
            **self.decision,
            "state_transition_diagnostics": {
                "aggregated_directional_support": {
                    "positive": 0.0,
                    "neutral": 0.2,
                    "negative": 0.75,
                },
                "utility_margin": 0.1,
                "directional_evidence_group_count": 2,
            },
        }
        result = apply_strategy_participation_policy(
            decision,
            self.persona,
            self.context,
            [{"comment_id": "c1", "introduced_step": 2}],
            {"current_emotion": "negative", "official_attitude": "wait"},
            {"consecutive_comment_rounds": 0},
        )

        components = result["participation_assessment"]["components"]
        self.assertEqual(components["directional_evidence_relevance"], 0.06)
        self.assertEqual(components["state_utility_tension"], 0.016)
        self.assertNotIn("negative_emotion_bonus", components)

    def test_strategy_defaults_enable_independent_behavior_modes(self):
        options = normalize_simulation_options({})
        self.assertEqual(options["participation_mode"], "persona_state_gate")
        self.assertEqual(options["action_mode"], "silent_original_reshare")
        self.assertEqual(options["expression_mode"], "agent_generated")
        self.assertEqual(options["memory_mode"], "bounded_event")
        self.assertEqual(options["incremental_comment_count"], 8)

    def test_restored_strategy_state_uses_policy_candidates(self):
        """状态回退后继续使用2026/10/15批次的政策候选集合。"""

        context = {
            **self.context,
            "simulation_options": normalize_simulation_options({}),
            "event_labels": {
                "topic": "社会事件",
                "event_valence": "negative",
            },
        }
        policy = {
            "candidate_rules": {
                "emotion": {"negative": ["neutral", "negative"]}
            }
        }

        self.assertEqual(
            get_emotion_options(context, policy),
            ["neutral", "negative"],
        )

    def test_state_rollback_keeps_current_behavior_actions(self):
        """回退状态守卫时，不得回退沉默、原创、转发动作层。"""

        context = {
            **self.context,
            "simulation_options": normalize_simulation_options({}),
            "event_labels": {
                "topic": "社会事件",
                "event_valence": "negative",
            },
            "current_state": {
                "step": 2,
                "official_statement_status": "none",
            },
        }
        policy = {
            "candidate_rules": {
                "emotion": {"negative": ["neutral", "negative"]},
                "official_statement": {
                    "none": {"default": ["not_applicable"]}
                },
            }
        }

        choices = build_allowed_choices(
            context,
            policy,
            [],
            self.persona,
            {
                "current_emotion": "negative",
                "official_attitude": "not_applicable",
            },
        )

        self.assertEqual(choices["emotion_options"], ["neutral", "negative"])
        self.assertEqual(
            choices["behavior_action_options"],
            ["silent", "original", "reshare"],
        )
        for field in (
            "strategy_decision_guard",
            "decision_guard",
            "strategy_evidence_memory",
        ):
            self.assertNotIn(field, choices)

    def test_exact_visible_copy_is_allowed_as_original(self):
        """Agent明确选择原创时，允许其措辞与公共评论完全相同。"""

        visible_text = "希望尽快公开调查依据并说明后续处理安排。"
        choices = {
            "emotion_options": ["negative", "neutral", "positive"],
            "official_attitude_options": ["not_applicable"],
            "official_statement_status": "none",
            "faction_options": ["观点输出派", "表态判断派"],
            "behavior_action_options": ["silent", "original", "reshare"],
            "visible_comment_ids": ["comment_1"],
            "expression_emotion_options": [
                "negative",
                "neutral",
                "positive",
            ],
            "expression_stance_options": [
                "support",
                "neutral",
                "questioning",
                "criticism",
            ],
            "expression_evidence_ids_allowed": ["comment_1"],
            "_visible_comment_texts": [visible_text],
            "_visible_comment_entries": [
                {
                    "comment_id": "comment_1",
                    "text": visible_text,
                    "faction": "表态判断派",
                }
            ],
        }
        decision = {
            "current_emotion": "negative",
            "official_attitude": "not_applicable",
            "will_comment": True,
            "comment_faction": "观点输出派",
            "action_type": "original",
            "reshare_comment_id": None,
            "expression": {
                "text": visible_text,
                "emotion": "negative",
                "stance": "questioning",
                "evidence_ids": ["comment_1"],
            },
            "decision_reason": {
                "emotion": "事件仍值得关注。",
                "official_attitude": "尚无官方声明。",
                "comment": "希望继续关注处理情况。",
            },
        }

        result = validate_cognition_decision(decision, choices)

        self.assertEqual(result["action_type"], "original")
        self.assertIsNone(result["reshare_comment_id"])
        self.assertEqual(result["expression"]["text"], visible_text)
        self.assertEqual(
            result["expression_similarity_audit"],
            {
                "matched_visible_comment_id": "comment_1",
                "similarity": 1.0,
                "match_type": "exact",
                "accepted": True,
            },
        )

    def test_near_visible_copy_is_allowed_and_audited(self):
        """高度近似表达允许通过，同时保留相似度审计。"""

        visible_text = "希望尽快公开调查依据并说明后续处理安排。"
        choices = {
            "emotion_options": ["negative", "neutral", "positive"],
            "official_attitude_options": ["not_applicable"],
            "official_statement_status": "none",
            "faction_options": ["观点输出派"],
            "behavior_action_options": ["silent", "original", "reshare"],
            "visible_comment_ids": ["comment_1"],
            "expression_emotion_options": [
                "negative",
                "neutral",
                "positive",
            ],
            "expression_stance_options": [
                "support",
                "neutral",
                "questioning",
                "criticism",
            ],
            "expression_evidence_ids_allowed": ["comment_1"],
            "_visible_comment_texts": [visible_text],
            "_visible_comment_entries": [
                {
                    "comment_id": "comment_1",
                    "text": visible_text,
                    "faction": "观点输出派",
                }
            ],
        }
        decision = {
            "current_emotion": "negative",
            "official_attitude": "not_applicable",
            "will_comment": True,
            "comment_faction": "观点输出派",
            "action_type": "original",
            "reshare_comment_id": None,
            "expression": {
                "text": "希望尽快公开调查依据，并说明后续处理安排。",
                "emotion": "negative",
                "stance": "questioning",
                "evidence_ids": ["comment_1"],
            },
            "decision_reason": {
                "emotion": "事件仍值得关注。",
                "official_attitude": "尚无官方声明。",
                "comment": "希望继续关注处理情况。",
            },
        }

        result = validate_cognition_decision(decision, choices)

        self.assertEqual(result["action_type"], "original")
        self.assertEqual(
            result["expression_similarity_audit"]["match_type"],
            "near",
        )
        self.assertTrue(
            result["expression_similarity_audit"]["accepted"]
        )

    @patch(
        "agents.strategy_behavior._choose_action",
        return_value=("original", None),
    )
    @patch(
        "agents.strategy_behavior._stable_unit_interval",
        return_value=0.0,
    )
    @patch("agents.decision_service.call_deepseek_json")
    def test_decision_service_materializes_original_or_audited_silence(
        self,
        mocked_llm,
        _mocked_sample,
        _mocked_action,
    ):
        """状态、行为和原创表达按三个独立阶段形成。"""

        options = normalize_simulation_options({})
        context = {
            **self.context,
            "simulation_options": options,
            "event_labels": {
                "topic": "社会事件",
                "event_valence": "negative",
            },
            "current_state": {
                "step": 2,
                "official_statement": "",
                "official_statement_status": "none",
            },
        }
        mocked_llm.side_effect = [
            {
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
                "decision_reason": {
                    "emotion": "事件后果仍令人担忧。",
                    "official_attitude": "当前没有官方声明。",
                },
            },
            {
                "text": "我更关心调查依据和后续处理是否公开。",
                "emotion": "positive",
                "stance": "support",
                "evidence_ids": ["comment_1"],
            },
        ]
        policy = {
            "candidate_rules": {
                "emotion": {"negative": ["neutral", "negative"]},
                "official_statement": {
                    "none": {"default": ["not_applicable"]}
                },
            }
        }
        decision_input = AgentDecisionInput(
            persona={
                **self.persona,
                "information_orientation": {
                    "fact_rate": 0.5,
                    "opinion_rate": 0.3,
                    "questioning_rate": 0.2,
                },
                "emotion_expression": {
                    "positive_rate": 0.2,
                    "neutral_rate": 0.3,
                    "negative_rate": 0.5,
                },
                "comment_faction_preference": {"观点输出派": 1.0},
                "action_preference": {
                    "original_preference": 0.8,
                    "repost_preference": 0.2,
                },
            },
            context=SimulationContext(context),
            policy=policy,
            visible_comments=(
                {
                    "comment_id": "comment_1",
                    "text": "希望尽快公开调查依据。",
                    "emotion": "negative",
                    "stance": "questioning",
                    "introduced_step": 2,
                },
            ),
            previous_state={
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
                "will_comment": False,
            },
            history_summary={"consecutive_comment_rounds": 0},
        )

        record = decide_agent(
            decision_input,
            correction_feedback=(
                "expression.text与个人可见评论高度相似；请重新生成。"
            ),
        ).to_record()
        result = record["decision"]

        self.assertEqual(result["action_type"], "original")
        self.assertEqual(mocked_llm.call_count, 2)
        self.assertIn(
            "【上一次输出的纠错要求】",
            mocked_llm.call_args_list[0].args[0],
        )
        self.assertIn(
            "expression.text与个人可见评论高度相似",
            mocked_llm.call_args_list[0].args[0],
        )
        state_prompt = mocked_llm.call_args_list[0].args[0]
        self.assertIn("本次只判断内部情绪", state_prompt)
        self.assertNotIn("action_type", state_prompt)
        self.assertNotIn(
            "action_preference",
            state_prompt,
        )
        self.assertIn("公开表达生成器", mocked_llm.call_args_list[1].args[0])
        self.assertIn(
            result["selection_source"],
            {"agent_silence", "agent_original_expression"},
        )
        self.assertEqual(record["decision_method"], "constrained_llm")
        # 2026/10/19，修改功能：内部状态仍由本地证据守卫裁决，
        # 有限生命周期记忆必须随决策返回；旧版临时字段不得复活。
        for field in (
            "strategy_decision_guard",
            "persona_decision_profile",
            "decision_guard",
            "emotion_resolution",
        ):
            self.assertNotIn(field, result)
        self.assertIn("strategy_evidence_memory", result)
        self.assertEqual(
            result["strategy_state_guard"]["guard_version"],
            "strategy_directional_utility_v3",
        )
        self.assertEqual(
            result["selected_comment"]["source_type"],
            "agent_original_expression",
        )
        self.assertEqual(result["selected_comment"]["emotion"], "positive")

    @patch("agents.decision_service.call_deepseek_json")
    def test_expression_validation_retries_only_expression(self, mocked_llm):
        """超长原创文本应携带长度反馈局部重试。"""

        mocked_llm.side_effect = [
            {
                "text": "过" * 281,
                "emotion": "negative",
                "stance": "questioning",
                "evidence_ids": ["comment_1"],
            },
            {
                "text": "希望公开调查依据并说明后续处理。",
                "emotion": "neutral",
                "stance": "questioning",
                "evidence_ids": ["comment_1"],
            },
        ]

        result = generate_strategy_expression(
            self.persona,
            self.context,
            {
                "current_emotion": "negative",
                "official_attitude": "wait",
                "comment_faction": "观点输出派",
            },
            [{"comment_id": "comment_1", "text": "调查仍在进行。"}],
            {"own_comment_history": []},
        )

        self.assertEqual(mocked_llm.call_count, 2)
        self.assertEqual(result["emotion"], "neutral")
        self.assertIn("当前正文长度为281", mocked_llm.call_args_list[1].args[0])

    @patch("agents.decision_service.call_deepseek_json")
    def test_persistent_overlong_expression_is_trimmed_and_audited(
        self,
        mocked_llm,
    ):
        """模型连续忽略长度要求时，在句末安全裁剪并记录审计。"""

        mocked_llm.return_value = {
            "text": ("这是需要保留的完整观点。" * 30),
            "emotion": "negative",
            "stance": "criticism",
            "evidence_ids": ["comment_1"],
        }

        result = generate_strategy_expression(
            self.persona,
            self.context,
            {
                "current_emotion": "negative",
                "official_attitude": "wait",
                "comment_faction": "观点输出派",
            },
            [{"comment_id": "comment_1", "text": "调查仍在进行。"}],
            {"own_comment_history": []},
        )

        self.assertEqual(mocked_llm.call_count, 3)
        self.assertLessEqual(len(result["text"]), 280)
        self.assertEqual(
            result["normalization_audit"]["code"],
            "trimmed_overlong_expression_at_sentence_boundary",
        )


class StrategyActionMetricTests(unittest.TestCase):
    def test_action_distribution_keeps_silence_original_and_reshare(self):
        records = [
            {"decision": {"action_type": "silent", "will_comment": False}},
            {
                "decision": {
                    "action_type": "original",
                    "will_comment": True,
                    "selected_comment": {"text": "原创A"},
                }
            },
            {
                "decision": {
                    "action_type": "original",
                    "will_comment": True,
                    "selected_comment": {"text": "原创A"},
                }
            },
            {"decision": {"action_type": "reshare", "will_comment": True}},
        ]

        result = calculate_action_distribution(records)

        self.assertEqual(result["distribution"]["silent"]["count"], 1)
        self.assertEqual(result["distribution"]["original"]["count"], 2)
        self.assertEqual(result["distribution"]["reshare"]["count"], 1)
        self.assertEqual(result["original_expression_uniqueness_rate"], 0.5)


if __name__ == "__main__":
    unittest.main()
