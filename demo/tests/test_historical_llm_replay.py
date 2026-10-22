"""历史公众语境约束下由LLM直接决策的离线回归测试。"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.decision_engine import (
    build_allowed_choices,
    build_decision_prompt,
    build_generated_expression_comment,
    collect_current_evidence,
    validate_cognition_decision,
)
from agents.evidence_appraisal import appraise_evidence_for_persona
from agents.decision_profile import (
    build_persona_decision_profile,
    build_personalized_decision_guard,
)
from agents.decision_service import decide_one_agent
from agents.historical_participation import (
    apply_historical_participation_policy,
)
from agents.state_store import (
    AgentStateStore,
    count_consecutive_comment_rounds,
)
from comments.incremental_generator import complete_incremental_comments
from simulation.options import normalize_simulation_options
from simulation.evidence_policy import (
    build_official_statement_evidence_units,
)
from simulation.context_exposure import personalize_event_context
from simulation.propagation import (
    comment_persona_relevance_weight,
    sample_visible_comments,
)


def _context(statement=True):
    return {
        "event_id": "event_test",
        "event_content": "测试历史事件",
        "event_labels": {"topic": "新闻时事", "event_valence": "negative"},
        "simulation_options": {
            "emotion_choice_mode": "evidence_based_all",
            "incremental_comment_count": 50,
            "active_opinion_window": 2,
        },
        "current_state": {
            "step": 3,
            "simulation_mode": "historical_replay",
            "official_statement": "阶段性调查通报" if statement else "",
            "official_statement_status": "incomplete" if statement else "none",
            "public_context": {
                "verified_updates": [
                    {
                        "evidence_id": "verified_3",
                        "content": "调查仍在继续",
                        "update_kind": "status_continuation",
                        "evidence_strength": "background",
                        "evidence_target": "investigation_process",
                        "claim_id": "official_statement_step_3",
                    }
                ],
            },
            "individual_public_context": {
                "public_discourse": [
                    {
                        "context_id": "public_3",
                        "content": "公众继续追问关键信息",
                        "status": "public_question",
                        "unresolved_concern": True,
                    }
                ],
                "positive_evidence": [
                    {
                        "evidence_id": "positive_3",
                        "content": "通报公开了部分核查过程",
                        "target": "official_response",
                    }
                ],
            },
        },
    }


PERSONA = {
    "agent_id": "agent_test",
    "emotion_expression": {
        "negative_rate": 0.4,
        "neutral_rate": 0.4,
        "positive_rate": 0.2,
    },
    "information_orientation": {
        "fact_rate": 0.4,
        "opinion_rate": 0.3,
        "questioning_rate": 0.3,
    },
    "topic_preference": {"新闻时事": 1.0},
    "comment_faction_preference": {},
}


class HistoricalLlmReplayTests(unittest.TestCase):
    def test_options_do_not_define_a_historical_response_mode(self):
        options = normalize_simulation_options(_context())
        self.assertNotIn("historical_response_mode", options)
        self.assertEqual(
            options["visibility"],
            {"neighbor_comment_count": 4, "public_comment_count": 11},
        )
        self.assertEqual(options["network"], {"neighbors_per_agent": 5})
        self.assertEqual(options["incremental_comment_count"], 50)

    def test_historical_network_topology_can_be_overridden_per_event(self):
        context = _context()
        context["simulation_options"]["network"] = {
            "neighbors_per_agent": 10
        }

        options = normalize_simulation_options(context)

        self.assertEqual(options["network"], {"neighbors_per_agent": 10})

    def test_neighbor_visibility_cannot_exceed_network_degree(self):
        context = _context()
        context["simulation_options"]["network"] = {
            "neighbors_per_agent": 5
        }
        context["simulation_options"]["visibility"] = {
            "neighbor_comment_count": 6,
            "public_comment_count": 9,
        }

        with self.assertRaisesRegex(ValueError, "不能大于"):
            normalize_simulation_options(context)

    def test_five_strategy_options_keep_global_visibility_config(self):
        context = _context()
        context["simulation_options"][
            "emotion_choice_mode"
        ] = "policy_constrained"

        options = normalize_simulation_options(context)

        self.assertNotIn("visibility", options)
        self.assertNotIn("network", options)
        self.assertNotIn("context_exposure", options)

    def test_llm_receives_all_evidence_supported_emotion_choices(self):
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [
                {
                    "comment_id": "comment_negative",
                    "text": "仍有问题需要解释",
                    "emotion": "negative",
                    "stance": "questioning",
                    "introduced_step": 3,
                },
                {
                    "comment_id": "comment_neutral",
                    "text": "等待进一步调查",
                    "emotion": "neutral",
                    "stance": "neutral",
                    "introduced_step": 3,
                },
            ],
            PERSONA,
            previous_state={},
        )

        self.assertEqual(
            choices["emotion_options"],
            ["positive", "neutral", "negative"],
        )
        self.assertEqual(len(choices["official_attitude_options"]), 1)
        self.assertEqual(
            choices["official_attitude_options"][0],
            choices["official_attitude_resolution"]["official_attitude"],
        )
        self.assertNotIn("conditioned_response", choices)
        self.assertNotIn("historical_response_mode", choices)
        self.assertEqual(
            choices["expression_stance_options"],
            ["support", "neutral", "questioning", "criticism"],
        )

    # 2026/10/10 Persona差异化决策，回归保护：上一轮状态先作为
    # 个体基线，Persona决定证据关注方式，群体多数不能直接覆盖个体判断。
    def test_prompt_uses_persona_state_baseline_before_evidence_change(self):
        candidates = [
            {
                "comment_id": "comment_negative",
                "text": "仍有问题需要解释",
                "emotion": "negative",
                "stance": "questioning",
                "introduced_step": 3,
            }
        ]
        previous_state = {
            "current_emotion": "negative",
            "official_attitude": "wait",
            "will_comment": True,
            "last_action": "comment",
            "last_comment_faction": "观点输出派",
            "last_comment_id": "comment_previous",
        }
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            candidates,
            PERSONA,
            previous_state=previous_state,
        )

        prompt = build_decision_prompt(
            _context(),
            choices,
            candidates,
            previous_state,
            {
                "history_step_count": 1,
                "own_comment_history": [],
            },
        )

        self.assertIn("上一轮状态是本轮默认基线", prompt)
        self.assertIn("Persona主导决策方式而不预设结论", prompt)
        self.assertIn("群体多数意见", prompt)
        self.assertIn("该证据为何会影响当前Persona", prompt)
        self.assertIn("没有新的合适表达时可以保持沉默", prompt)
        self.assertNotIn("证据优先级是", prompt)

    def test_emergency_fallback_uses_legacy_neutral_comments(self):
        comments = complete_incremental_comments(
            event_context=_context(),
            profiles=[{"profile_id": 1, "profile_label": "测试人物"}],
            existing_comments=[],
            generated_comments=[],
            selected_comment_ids=set(),
            target_count=2,
            comment_tasks=[
                {"task_id": "negative", "required_emotion": "negative"},
                {"task_id": "positive", "required_emotion": "positive"},
            ],
        )

        self.assertEqual(
            [comment["emotion"] for comment in comments],
            ["neutral", "neutral"],
        )
        self.assertTrue(
            all("fallback_required_emotion" not in item for item in comments)
        )

    def _decision(self):
        return {
            "current_emotion": "neutral",
            "official_attitude": "wait",
            "will_comment": False,
            "comment_faction": None,
            "persona_factors": ["questioning_orientation"],
            "emotion_target": "public_discourse",
            "emotion_evidence_ids": ["public_3"],
            "official_attitude_evidence_ids": [
                "official_statement_step_3"
            ],
            "expression": None,
            "decision_reason": {
                "emotion": "仍有问题，但新增讨论只支持从负面转为中性观望。",
                "official_attitude": "声明尚不完整，继续等待。",
                "comment": "没有新的合适表达，因此保持沉默。",
            },
        }

    def test_state_change_requires_new_evidence(self):
        previous_state = {
            "current_emotion": "negative",
            "official_attitude": "wait",
        }
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state=previous_state,
        )
        choices["state_change_evidence_ids"] = []
        # 故意绕过规则层候选，单独验证深层证据编号校验仍然有效。
        choices["emotion_options"] = ["negative", "neutral"]
        choices["emotion_resolution"] = {}

        with self.assertRaisesRegex(ValueError, "情绪变化必须引用"):
            validate_cognition_decision(self._decision(), choices)

    def test_background_update_cannot_trigger_state_change(self):
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={
                "current_emotion": "negative",
                "official_attitude": "wait",
            },
        )

        self.assertNotIn(
            "verified_3",
            choices["state_change_evidence_ids"],
        )
        evidence = {
            item["evidence_id"]: item
            for item in choices["available_emotion_evidence"]
        }
        self.assertEqual(
            evidence["verified_3"]["evidence_strength"],
            "background",
        )

    def test_new_incomplete_statement_is_moderate_not_strong(self):
        evidence = {
            item["evidence_id"]: item
            for item in collect_current_evidence(_context(), [])
        }

        self.assertEqual(
            evidence["official_statement_step_3"]["evidence_strength"],
            "moderate",
        )

    def test_same_strong_fact_has_persona_specific_impact(self):
        evidence = [
            {
                "evidence_id": "confirmed_fact",
                "evidence_type": "historical_verified_update",
                "evidence_target": "fact_clarification",
                "evidence_strength": "strong",
                "is_new_this_step": True,
            }
        ]
        fact_persona = {
            **PERSONA,
            "topic_preference": {"新闻时事": 1.0},
            "information_orientation": {
                "fact_rate": 1.0,
                "opinion_rate": 0.0,
                "questioning_rate": 0.0,
            },
        }
        unrelated_persona = {
            **PERSONA,
            "topic_preference": {"新闻时事": 0.0, "娱乐": 1.0},
            "information_orientation": {
                "fact_rate": 0.0,
                "opinion_rate": 1.0,
                "questioning_rate": 0.0,
            },
        }

        fact_view = appraise_evidence_for_persona(
            evidence,
            fact_persona,
            _context(),
            {"current_emotion": "neutral"},
        )[0]
        unrelated_view = appraise_evidence_for_persona(
            evidence,
            unrelated_persona,
            _context(),
            {"current_emotion": "neutral"},
        )[0]

        self.assertGreater(
            fact_view["personal_impact"]["emotion_score"],
            unrelated_view["personal_impact"]["emotion_score"],
        )
        self.assertIn("emotion_change_mode", fact_view["personal_impact"])

    def test_same_claim_summary_and_statement_do_not_count_twice(self):
        context = _context()
        context["current_state"]["public_context"]["verified_updates"][0].update(
            {
                "update_kind": "procedural_update",
                "evidence_strength": "moderate",
            }
        )
        unrelated_persona = {
            **PERSONA,
            "topic_preference": {"新闻时事": 0.0, "娱乐": 1.0},
            "information_orientation": {
                "fact_rate": 0.0,
                "opinion_rate": 1.0,
                "questioning_rate": 0.0,
            },
        }
        previous_state = {
            "current_emotion": "negative",
            "official_attitude": "wait",
        }
        choices = build_allowed_choices(
            context,
            {"candidate_rules": {"official_statement": {}}},
            [],
            unrelated_persona,
            previous_state=previous_state,
        )
        guard = choices["decision_guard"]
        # verified_3与官方声明属于同一claim，连续更新前只保留影响更强者。
        self.assertEqual(guard["distinct_new_evidence_count"], 3)

    def test_emotion_and_official_attitude_are_independent(self):
        previous_state = {
            "current_emotion": "negative",
            "official_attitude": "wait",
        }
        context = _context()
        context["current_state"]["official_statement_status"] = "clear"
        choices = build_allowed_choices(
            context,
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state=previous_state,
        )
        decision = self._decision()
        decision["current_emotion"] = "negative"
        decision["official_attitude"] = choices[
            "official_attitude_options"
        ][0]

        validated = validate_cognition_decision(decision, choices)

        self.assertEqual(validated["current_emotion"], "negative")
        self.assertEqual(
            validated["official_attitude"],
            choices["official_attitude_options"][0],
        )
        self.assertIn(validated["claim_position"], {"accepted", "unresolved", "challenged"})
        self.assertIn(
            validated["process_evaluation"],
            {"satisfied", "partial", "dissatisfied"},
        )
        self.assertTrue(validated["evidence_appraisal"])
        self.assertIn(
            "personal_impact",
            validated["evidence_appraisal"][0],
        )

    def test_continuous_guard_rejects_non_resolved_extreme_emotion(self):
        previous_state = {
            "current_emotion": "negative",
            "official_attitude": "wait",
        }
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state=previous_state,
        )
        choices["strong_evidence_ids"] = []
        decision = self._decision()
        decision["current_emotion"] = "positive"
        decision["emotion_target"] = "official_response"
        decision["emotion_evidence_ids"] = ["positive_3"]

        self.assertNotIn("positive", choices["emotion_options"])
        with self.assertRaisesRegex(ValueError, "不在允许选项"):
            validate_cognition_decision(decision, choices)

    def test_persona_decision_profile_is_stable_and_differentiated(self):
        policy = {
            "orientation_quantiles": {
                "fact_rate": {"p25": 0.2, "p75": 0.7},
                "opinion_rate": {"p25": 0.2, "p75": 0.7},
                "questioning_rate": {"p25": 0.2, "p75": 0.7},
            },
            "emotion_quantiles": {},
        }
        fact_persona = {
            **PERSONA,
            "information_orientation": {
                "fact_rate": 0.8,
                "opinion_rate": 0.1,
                "questioning_rate": 0.1,
            },
        }
        questioning_persona = {
            **PERSONA,
            "information_orientation": {
                "fact_rate": 0.1,
                "opinion_rate": 0.1,
                "questioning_rate": 0.8,
            },
        }

        fact_profile = build_persona_decision_profile(
            fact_persona,
            policy,
            _context(),
        )
        repeated = build_persona_decision_profile(
            fact_persona,
            policy,
            _context(),
        )
        questioning_profile = build_persona_decision_profile(
            questioning_persona,
            policy,
            _context(),
        )

        self.assertEqual(fact_profile, repeated)
        self.assertEqual(
            fact_profile["profile_version"],
            "persona_decision_v3",
        )
        self.assertLess(
            fact_profile["official_acceptance_threshold"],
            questioning_profile["official_acceptance_threshold"],
        )
        self.assertIn("emotion_change_threshold", fact_profile)
        self.assertNotIn("response_speed", fact_profile)

    def test_open_emotion_candidate_is_resolved_by_personal_utility(self):
        """候选开放后不再由LLM机械保持上一轮情绪。"""

        profile = {
            "orientation": {"fact": 0.5, "opinion": 0.3, "questioning": 0.2},
            "emotion_prior": {"positive": 0.1, "neutral": 0.8, "negative": 0.2},
            "state_inertia": 0.4,
            "emotion_change_threshold": 0.3,
            "emotion_switch_margin": 0.018,
            "attitude_change_threshold": 0.55,
            "official_acceptance_threshold": 0.55,
            "official_question_threshold": 0.25,
            "process_satisfaction_threshold": 0.55,
        }
        evidence = [
            {
                "evidence_id": "neutral_update",
                "evidence_group_id": "neutral_update",
                "evidence_type": "historical_verified_update",
                "evidence_target": "fact_clarification",
                "evidence_strength": "strong",
                "is_new_this_step": True,
                "emotion": "neutral",
                "personal_impact": {
                    "emotion_score": 0.7,
                    "official_attitude_score": 0.5,
                    "emotion_change_mode": "adjacent_allowed",
                },
            }
        ]

        guard = build_personalized_decision_guard(
            evidence,
            profile,
            {"current_emotion": "negative", "official_attitude": "wait"},
            ["positive", "neutral", "negative"],
            ["accept", "wait", "question"],
            "none",
        )

        self.assertEqual(guard["emotion_options"], ["neutral"])
        self.assertEqual(
            guard["emotion_resolution"]["transition_reason"],
            "changed_after_personal_margin",
        )
        self.assertEqual(
            guard["emotion_resolution"]["supporting_evidence_ids"],
            ["neutral_update"],
        )

    def test_weak_single_signal_keeps_previous_emotion_candidate(self):
        context = _context(statement=False)
        context["current_state"]["public_context"] = {
            "verified_updates": []
        }
        context["current_state"]["individual_public_context"] = {
            "public_discourse": [],
            "positive_evidence": [],
        }
        choices = build_allowed_choices(
            context,
            {"candidate_rules": {"official_statement": {}}},
            [
                {
                    "comment_id": "weak_neighbor",
                    "text": "有人仍然表示担忧。",
                    "emotion": "negative",
                    "stance": "questioning",
                    "introduced_step": 3,
                }
            ],
            PERSONA,
            previous_state={
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
            },
        )

        self.assertEqual(choices["emotion_options"], ["neutral"])
        self.assertEqual(
            choices["official_attitude_options"],
            ["not_applicable"],
        )
        self.assertIn("decision_guard", choices)

    def test_first_official_attitude_is_resolved_per_persona(self):
        """首次出现通告时也应由个体规则裁决，而不是交给LLM自由选择。"""

        policy = {
            "candidate_rules": {"official_statement": {}},
            "orientation_quantiles": {
                "fact_rate": {"p25": 0.2, "p75": 0.7},
                "opinion_rate": {"p25": 0.2, "p75": 0.7},
                "questioning_rate": {"p25": 0.2, "p75": 0.7},
            },
        }
        personas = [
            {
                **PERSONA,
                "information_orientation": {
                    "fact_rate": 0.8,
                    "opinion_rate": 0.1,
                    "questioning_rate": 0.1,
                },
            },
            {
                **PERSONA,
                "information_orientation": {
                    "fact_rate": 0.1,
                    "opinion_rate": 0.1,
                    "questioning_rate": 0.8,
                },
            },
        ]
        option_sets = []
        for persona in personas:
            choices = build_allowed_choices(
                _context(),
                policy,
                [],
                persona,
                previous_state={
                    "current_emotion": "negative",
                    "official_attitude": "not_applicable",
                },
            )
            option_sets.append(tuple(choices["official_attitude_options"]))

        self.assertTrue(all(len(options) == 1 for options in option_sets))

    def test_official_statement_units_share_one_claim_group(self):
        context = _context()
        context["current_state"]["official_statement"] = (
            "警方正在调查核查。经查已确认有关身份。将依法追究责任。"
        )

        units = build_official_statement_evidence_units(
            context["current_state"]
        )

        self.assertEqual(len(units), 3)
        self.assertEqual(
            {item["evidence_group_id"] for item in units},
            {"official_statement_step_3"},
        )
        self.assertEqual(
            {item["evidence_target"] for item in units},
            {
                "investigation_process",
                "fact_clarification",
                "process_accountability",
            },
        )
        self.assertEqual(
            [item["unresolved_concern"] for item in units],
            [True, False, True],
        )

    def test_completed_fact_is_not_hidden_by_pending_responsibility(self):
        context = _context()
        context["current_state"]["official_statement"] = (
            "受害人已接受伤情检查，案件事实和责任正在进一步核查。"
            "调查处理结果将及时向社会公布。"
        )

        units = build_official_statement_evidence_units(
            context["current_state"]
        )

        self.assertEqual(units[0]["evidence_target"], "fact_clarification")
        self.assertTrue(units[0]["unresolved_concern"])

    def test_evidence_fields_do_not_leak_into_five_strategy_mode(self):
        """历史复现的证据契约不能改变五策略原有决策输出结构。"""

        context = _context()
        context["simulation_options"][
            "emotion_choice_mode"
        ] = "policy_constrained"
        choices = build_allowed_choices(
            context,
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={
                "current_emotion": "negative",
                "official_attitude": "wait",
            },
        )
        decision = {
            "current_emotion": choices["emotion_options"][0],
            "official_attitude": "wait",
            "will_comment": False,
            "comment_faction": None,
            "decision_reason": {
                "emotion": "沿用五策略的原有受约束决策。",
                "official_attitude": "声明尚不完整，继续等待。",
                "comment": "本轮保持沉默。",
            },
        }

        validated = validate_cognition_decision(decision, choices)

        self.assertNotIn("persona_factors", validated)
        self.assertNotIn("emotion_evidence_ids", validated)
        self.assertNotIn("official_attitude_evidence_ids", validated)
        self.assertNotIn("evidence_appraisal", validated)
        state = AgentStateStore().build_state_record(
            "event_test",
            3,
            "agent_test",
            validated,
        )["state"]
        self.assertNotIn("response_memory", state)
        self.assertNotIn("latent_emotion_score", state)

    def test_public_discourse_is_personalized_but_verified_fact_is_shared(self):
        context = _context()
        # personalize_event_context接收原始逐轮结构；个体字段由该函数生成。
        context["current_state"]["public_context"].update(
            context["current_state"].pop("individual_public_context")
        )
        context["simulation_options"] = normalize_simulation_options(context)

        views = [
            personalize_event_context(context, f"agent_{index}")
            for index in range(30)
        ]
        exposure_flags = ["public_3" in ids for _, ids in views]

        self.assertIn(True, exposure_flags)
        self.assertIn(False, exposure_flags)
        for personalized, visible_ids in views:
            state = personalized["current_state"]
            self.assertEqual(
                state["public_context"]["verified_updates"][0][
                    "evidence_id"
                ],
                "verified_3",
            )
            self.assertNotIn("public_discourse", state["public_context"])
            visible_discourse = state["individual_public_context"][
                "public_discourse"
            ]
            self.assertEqual(bool(visible_discourse), "public_3" in visible_ids)

    def test_public_comment_weight_uses_persona_long_term_preferences(self):
        comment = {
            "topic": "新闻时事",
            "orientation": "fact",
            "emotion": "neutral",
            "faction": "观点输出派",
        }
        matched = {
            "topic_preference": {"新闻时事": 1.0},
            "information_orientation": {"fact_rate": 1.0},
            "emotion_expression": {"neutral_rate": 1.0},
            "comment_faction_preference": {"观点输出派": 1.0},
        }
        unmatched = {
            "topic_preference": {"娱乐": 1.0},
            "information_orientation": {"opinion_rate": 1.0},
            "emotion_expression": {"negative_rate": 1.0},
            "comment_faction_preference": {"吃瓜派": 1.0},
        }

        self.assertGreater(
            comment_persona_relevance_weight(comment, matched),
            comment_persona_relevance_weight(comment, unmatched),
        )

    def test_persona_public_sampling_is_reproducible_and_differentiated(self):
        comments = []
        for index in range(40):
            fact_comment = index < 20
            comments.append(
                {
                    "comment_id": f"comment_{index}",
                    "introduced_step": 1,
                    "topic": "新闻时事" if fact_comment else "娱乐",
                    "orientation": "fact" if fact_comment else "opinion",
                    "emotion": "neutral",
                    "faction": "观点输出派",
                }
            )
        fact_persona = {
            "topic_preference": {"新闻时事": 1.0},
            "information_orientation": {"fact_rate": 1.0},
        }
        opinion_persona = {
            "topic_preference": {"娱乐": 1.0},
            "information_orientation": {"opinion_rate": 1.0},
        }

        fact_view = sample_visible_comments(
            comments,
            "agent_test",
            "event_test",
            1,
            10,
            2026,
            persona=fact_persona,
        )
        repeated_fact_view = sample_visible_comments(
            comments,
            "agent_test",
            "event_test",
            1,
            10,
            2026,
            persona=fact_persona,
        )
        opinion_view = sample_visible_comments(
            comments,
            "agent_test",
            "event_test",
            1,
            10,
            2026,
            persona=opinion_persona,
        )

        self.assertEqual(fact_view, repeated_fact_view)
        self.assertNotEqual(
            [item["comment_id"] for item in fact_view],
            [item["comment_id"] for item in opinion_view],
        )

    def test_consecutive_comment_rounds_stop_at_latest_silence(self):
        self.assertEqual(
            count_consecutive_comment_rounds(
                [
                    {"will_comment": True},
                    {"will_comment": False},
                    {"will_comment": True},
                    {"will_comment": True},
                ]
            ),
            2,
        )

    def test_history_participation_silences_weak_repeated_participation(self):
        persona = {
            **PERSONA,
            "topic_preference": {"新闻时事": 0.1, "其他": 0.9},
            "action_preference": {"original_preference": 0.0},
        }
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "comment_faction": "观点输出派",
                "expression": {
                    "text": "目前仍需等待更多能够核实的信息。",
                    "emotion": "neutral",
                    "stance": "neutral",
                    "evidence_ids": ["public_3"],
                },
            }
        )

        assessed = apply_historical_participation_policy(
            decision,
            persona,
            _context(),
            [],
            {
                "current_emotion": "neutral",
                "official_attitude": "wait",
            },
            {
                "consecutive_comment_rounds": 3,
                "own_comment_history": [],
            },
        )

        self.assertFalse(assessed["will_comment"])
        self.assertEqual(
            assessed["silence_reason"],
            "consecutive_comment_fatigue",
        )
        self.assertTrue(
            assessed["participation_assessment"]["policy_overrode_llm"]
        )

    def test_strong_evidence_does_not_bypass_participation_fatigue(self):
        persona = {
            **PERSONA,
            "topic_preference": {"新闻时事": 0.1, "其他": 0.9},
            "action_preference": {"original_preference": 0.0},
        }
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "comment_faction": "观点输出派",
                "emotion_evidence_ids": ["verified_3"],
                "expression": {
                    "text": "新增核查进展值得继续关注。",
                    "emotion": "neutral",
                    "stance": "neutral",
                    "evidence_ids": ["verified_3"],
                },
            }
        )

        context = _context()
        context["current_state"]["public_context"]["verified_updates"][0].update(
            {
                "update_kind": "confirmed_fact",
                "evidence_strength": "strong",
                "evidence_target": "fact_clarification",
            }
        )

        assessed = apply_historical_participation_policy(
            decision,
            persona,
            context,
            [],
            {
                "current_emotion": "neutral",
                "official_attitude": "wait",
            },
            {
                "consecutive_comment_rounds": 3,
                "own_comment_history": [],
            },
        )

        self.assertFalse(assessed["will_comment"])
        self.assertEqual(
            assessed["silence_reason"],
            "consecutive_comment_fatigue",
        )
        self.assertIn(
            "verified_3",
            assessed["participation_assessment"][
                "used_strong_evidence_ids"
            ],
        )

    def test_participation_score_does_not_reward_emotion_polarity(self):
        """相同Persona和证据下，负面状态不能比中性状态天然更易发言。"""

        persona = {
            **PERSONA,
            "action_preference": {"original_preference": 0.5},
        }

        def assess(emotion):
            decision = self._decision()
            decision.update(
                {
                    "current_emotion": emotion,
                    "will_comment": True,
                    "comment_faction": "观点输出派",
                    "expression": {
                        "text": "本轮新增信息仍需要结合后续证据判断。",
                        "emotion": "neutral",
                        "stance": "neutral",
                        "evidence_ids": ["public_3"],
                    },
                }
            )
            return apply_historical_participation_policy(
                decision,
                persona,
                _context(),
                [],
                {"current_emotion": emotion, "official_attitude": "wait"},
                {"consecutive_comment_rounds": 0, "own_comment_history": []},
            )

        neutral = assess("neutral")
        negative = assess("negative")
        self.assertEqual(
            neutral["participation_assessment"]["participation_score"],
            negative["participation_assessment"]["participation_score"],
        )
        self.assertTrue(
            neutral["participation_assessment"]["emotion_independent_scoring"]
        )

    def test_history_comment_is_original_and_evidence_bounded(self):
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "comment_faction": "观点输出派",
                "expression": {
                    "text": "调查仍在继续，现阶段应等待更多可核实信息。",
                    "emotion": "neutral",
                    "stance": "neutral",
                    "evidence_ids": ["verified_3"],
                },
            }
        )

        validated = validate_cognition_decision(decision, choices)
        comment = build_generated_expression_comment(
            validated,
            _context(),
            PERSONA,
        )

        self.assertEqual(comment["source_type"], "agent_original_expression")
        self.assertEqual(comment["emotion"], "neutral")
        self.assertEqual(comment["evidence_ids"], ["verified_3"])
        self.assertTrue(comment["comment_id"].startswith("agent_comment_"))

    def test_history_expression_rejects_unseen_evidence(self):
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "comment_faction": "观点输出派",
                "expression": {
                    "text": "引用了不可见信息。",
                    "emotion": "neutral",
                    "stance": "neutral",
                    "evidence_ids": ["future_evidence"],
                },
            }
        )

        with self.assertRaisesRegex(ValueError, "不可用的证据编号"):
            validate_cognition_decision(decision, choices)

    def test_silent_decision_discards_superfluous_expression(self):
        """不发言时多余草稿不应让整名Agent失败。"""

        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision["expression"] = {
            "text": "模型虽然生成了草稿，但已经决定不公开发言。",
            "emotion": "neutral",
            "stance": "neutral",
            "evidence_ids": ["verified_3"],
        }

        validated = validate_cognition_decision(decision, choices)

        self.assertFalse(validated["will_comment"])
        self.assertIsNone(validated["expression"])
        self.assertIsNone(validated["comment_faction"])
        self.assertIn(
            "discarded_expression_for_silence",
            validated["output_normalizations"],
        )

    def test_silent_decision_accepts_missing_expression_field(self):
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision.pop("expression")

        validated = validate_cognition_decision(decision, choices)

        self.assertIsNone(validated["expression"])
        self.assertIn(
            "filled_null_expression_for_silence",
            validated["output_normalizations"],
        )

    def test_silent_no_statement_decision_fills_empty_fields(self):
        context = _context(statement=False)
        choices = build_allowed_choices(
            context,
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision["official_attitude"] = "not_applicable"
        decision.pop("official_attitude_evidence_ids")
        decision.pop("comment_faction")

        validated = validate_cognition_decision(decision, choices)

        self.assertEqual(validated["official_attitude_evidence_ids"], [])
        self.assertIsNone(validated["comment_faction"])
        self.assertIn(
            "filled_empty_attitude_evidence_without_statement",
            validated["output_normalizations"],
        )
        self.assertIn(
            "filled_null_comment_faction_for_silence",
            validated["output_normalizations"],
        )

    def test_commenting_decision_still_requires_expression(self):
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "comment_faction": "观点输出派",
            }
        )
        decision.pop("expression")

        with self.assertRaisesRegex(ValueError, "缺少expression"):
            validate_cognition_decision(decision, choices)

    def test_commenting_decision_still_requires_faction(self):
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "expression": {
                    "text": "我将继续关注已经公布的调查进展。",
                    "emotion": "neutral",
                    "stance": "neutral",
                    "evidence_ids": ["verified_3"],
                },
            }
        )
        decision.pop("comment_faction")

        with self.assertRaisesRegex(ValueError, "缺少comment_faction"):
            validate_cognition_decision(decision, choices)

    def test_expression_emotion_is_independent_from_internal_guard(self):
        """内部状态保持中性时，公开表达仍可呈现有证据的负面语气。"""

        context = _context(statement=False)
        context["current_state"]["public_context"] = {
            "verified_updates": []
        }
        context["current_state"]["individual_public_context"] = {
            "public_discourse": [],
            "positive_evidence": [],
        }
        candidate = {
            "comment_id": "weak_negative",
            "text": "仍然有人对目前情况感到担忧。",
            "emotion": "negative",
            "stance": "questioning",
            "introduced_step": 3,
        }
        choices = build_allowed_choices(
            context,
            {"candidate_rules": {"official_statement": {}}},
            [candidate],
            PERSONA,
            previous_state={
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
            },
        )
        self.assertEqual(choices["emotion_options"], ["neutral"])
        self.assertIn("negative", choices["expression_emotion_options"])
        decision = self._decision()
        decision.update(
            {
                "official_attitude": "not_applicable",
                "official_attitude_evidence_ids": [],
                "will_comment": True,
                "comment_faction": "观点输出派",
                "emotion_evidence_ids": ["weak_negative"],
                "expression": {
                    "text": "目前信息有限，但我仍然感到担忧。",
                    "emotion": "negative",
                    "stance": "questioning",
                    "evidence_ids": ["weak_negative"],
                },
            }
        )

        validated = validate_cognition_decision(decision, choices)

        self.assertEqual(validated["current_emotion"], "neutral")
        self.assertEqual(validated["expression"]["emotion"], "negative")

    def test_history_expression_allows_exact_comment_copy(self):
        candidate = {
            "comment_id": "visible_1",
            "text": "请继续公布可核实的调查进展。",
            "emotion": "neutral",
            "stance": "neutral",
            "introduced_step": 3,
        }
        choices = build_allowed_choices(
            _context(),
            {"candidate_rules": {"official_statement": {}}},
            [candidate],
            PERSONA,
            previous_state={},
        )
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "comment_faction": "观点输出派",
                "expression": {
                    "text": candidate["text"],
                    "emotion": "neutral",
                    "stance": "neutral",
                    "evidence_ids": ["visible_1"],
                },
            }
        )

        validated = validate_cognition_decision(decision, choices)

        self.assertEqual(validated["expression"]["text"], candidate["text"])
        self.assertEqual(
            validated["expression_similarity_audit"]["match_type"],
            "exact",
        )
        self.assertTrue(
            validated["expression_similarity_audit"]["accepted"]
        )

    @patch("agents.decision_service.decide_agent_cognition")
    def test_history_service_uses_original_expression_not_pool_text(
        self,
        mock_cognition,
    ):
        decision = self._decision()
        decision.update(
            {
                "will_comment": True,
                "comment_faction": "观点输出派",
                "expression": {
                    "text": "这是Agent自己的审慎表达。",
                    "emotion": "neutral",
                    "stance": "neutral",
                    "evidence_ids": ["verified_3"],
                },
            }
        )
        mock_cognition.return_value = decision

        class EmptyStateStore:
            @staticmethod
            def get_latest_state(*_args):
                return {}

            @staticmethod
            def build_history_summary(*_args):
                return {"own_comment_history": []}

        result = decide_one_agent(
            PERSONA,
            _context(),
            {},
            [
                {
                    "comment_id": "pool_comment",
                    "text": "评论池原文",
                    "emotion": "negative",
                    "faction": "矛盾激化派",
                    "orientation": "opinion",
                    "stance": "criticism",
                }
            ],
            EmptyStateStore(),
        )

        self.assertEqual(
            result["decision"]["selection_source"],
            "agent_original_expression",
        )
        self.assertEqual(
            result["decision"]["selected_comment"]["text"],
            "这是Agent自己的审慎表达。",
        )
        self.assertNotEqual(
            result["decision"]["selected_comment_id"],
            "pool_comment",
        )


if __name__ == "__main__":
    unittest.main()
