"""回应方案Persona状态转换约束测试。"""

import sys
import unittest
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parents[1]
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

from agents.strategy_state_transition import (  # noqa: E402
    attach_strategy_state_audit,
    build_strategy_state_prompt_guard,
    build_strategy_state_guard,
)
from agents.state_store import (  # noqa: E402
    AgentStateStore,
    create_empty_agent_state,
)
from agents.decision_engine import (  # noqa: E402
    build_allowed_choices,
    build_strategy_state_prompt,
)
from simulation.options import normalize_simulation_options  # noqa: E402


def make_persona(*, fact, opinion, questioning, repost, eat_melon):
    return {
        "agent_id": f"agent_{fact}_{opinion}",
        "topic_preference": {"社会事件": 1.0},
        "information_orientation": {
            "fact_rate": fact,
            "opinion_rate": opinion,
            "questioning_rate": questioning,
        },
        "emotion_expression": {
            "positive_rate": 0.33,
            "neutral_rate": 0.34,
            "negative_rate": 0.33,
        },
        "action_preference": {
            "original_preference": 1.0 - repost,
            "repost_preference": repost,
        },
        "comment_faction_preference": {"吃瓜派": eat_melon},
    }


def make_event(statement_status="none"):
    return {
        "event_id": "event_test",
        "event_content": "测试事件",
        "event_labels": {
            "topic": "社会事件",
            "event_valence": "negative",
        },
        "current_state": {
            "step": 2,
            "official_statement_status": statement_status,
        },
    }


def neighbor_evidence(
    evidence_id,
    weight=0.8,
    emotion="negative",
    target="public_discourse",
):
    return {
        "evidence_id": evidence_id,
        "evidence_group_id": evidence_id,
        "evidence_type": "simulated_comment",
        "comment_source": "current_repost",
        "evidence_target": target,
        "evidence_strength": "weak",
        "is_new_this_step": True,
        "network_influence_weight": weight,
        "source_agent_ids": [f"source_{evidence_id}"],
        "emotion": emotion,
        "positive_eligible": emotion == "positive",
    }


class StrategyStateTransitionTests(unittest.TestCase):
    def test_strategy_evidence_memory_is_persisted_without_shared_defaults(self):
        memory = {
            "official_step_4": {
                "first_seen_step": 4,
                "emotion_consumed": True,
            }
        }
        assimilation = {
            "official_step_4": {
                "first_seen_step": 4,
                "absorbed_fraction": 0.42,
                "remaining_potential": 0.58,
            }
        }
        record = AgentStateStore().build_state_record(
            "event_test",
            4,
            "agent_test",
            {
                "current_emotion": "neutral",
                "official_attitude": "wait",
                "will_comment": False,
                "strategy_evidence_memory": memory,
                "strategy_evidence_assimilation": assimilation,
            },
        )
        first_empty = create_empty_agent_state()
        second_empty = create_empty_agent_state()
        first_empty["strategy_evidence_memory"]["x"] = {}

        self.assertEqual(
            record["state"]["strategy_evidence_memory"],
            memory,
        )
        self.assertEqual(
            record["state"]["strategy_evidence_assimilation"],
            assimilation,
        )
        self.assertNotIn("x", second_empty["strategy_evidence_memory"])

    def test_state_only_decision_uses_strategy_guard(self):
        persona = make_persona(
            fact=0.9,
            opinion=0.05,
            questioning=0.05,
            repost=0.1,
            eat_melon=0.0,
        )
        event = make_event()
        event["simulation_options"] = normalize_simulation_options({})
        policy = {
            "candidate_rules": {
                "emotion": {"negative": ["neutral", "negative"]},
                "official_statement": {
                    "none": {"default": ["not_applicable"]}
                },
            }
        }

        choices = build_allowed_choices(
            event,
            policy,
            [],
            persona,
            {
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
            },
            state_only=True,
        )

        self.assertEqual(choices["emotion_options"], ["neutral"])
        self.assertIn("strategy_state_guard", choices)
        self.assertEqual(
            choices["strategy_state_guard"]["guard_version"],
            "strategy_directional_utility_v3",
        )
        self.assertEqual(
            choices["_strategy_state_guard_audit"]["emotion_options"],
            ["neutral"],
        )

    def test_state_prompt_hides_rule_recommendation_but_keeps_legal_options(self):
        persona = make_persona(
            fact=0.9,
            opinion=0.05,
            questioning=0.05,
            repost=0.1,
            eat_melon=0.0,
        )
        event = make_event("clear")
        event["simulation_options"] = normalize_simulation_options({})
        event["current_state"].update(
            {
                "official_statement": "警方已控制涉事人员，正在调查。",
                "official_statement_is_new": True,
            }
        )
        choices = build_allowed_choices(
            event,
            {"candidate_rules": {"official_statement": {}}},
            [],
            persona,
            {
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
            },
            state_only=True,
        )

        prompt = build_strategy_state_prompt(event, choices, [], {}, {})

        self.assertIn('"official_attitude_options"', prompt)
        self.assertNotIn("recommended_official_attitude", prompt)
        self.assertNotIn('"utilities"', prompt)
        self.assertNotIn("strategy_evidence_memory", prompt)

    def test_single_peer_root_holds_previous_emotion(self):
        persona = make_persona(
            fact=0.9,
            opinion=0.05,
            questioning=0.05,
            repost=0.1,
            eat_melon=0.0,
        )

        guard = build_strategy_state_guard(
            persona=persona,
            policy={},
            event_context=make_event(),
            previous_state={"current_emotion": "neutral"},
            current_evidence=[neighbor_evidence("n1")],
            base_emotion_options=["neutral", "negative"],
            base_attitude_options=["not_applicable"],
        )

        self.assertEqual(guard["emotion_options"], ["neutral"])
        self.assertEqual(
            guard["emotion_transition"]["state_change_basis"],
            "held_without_directional_evidence",
        )

    def test_high_peer_susceptibility_can_open_adjacent_state(self):
        persona = make_persona(
            fact=0.0,
            opinion=0.95,
            questioning=0.05,
            repost=0.95,
            eat_melon=0.9,
        )

        guard = build_strategy_state_guard(
            persona=persona,
            policy={},
            event_context=make_event(),
            previous_state={"current_emotion": "neutral"},
            current_evidence=[
                neighbor_evidence("n1", 1.0, target="event_harm"),
                neighbor_evidence("n2", 1.0, target="event_harm"),
            ],
            base_emotion_options=["neutral", "negative"],
            base_attitude_options=["not_applicable"],
        )

        self.assertEqual(guard["emotion_options"], ["negative"])
        self.assertEqual(
            guard["emotion_transition"]["state_change_basis"],
            "changed_by_peer_directional_evidence",
        )

    def test_initial_official_options_differ_by_persona(self):
        official_evidence = {
            "evidence_id": "official_2",
            "evidence_group_id": "official_2",
            "evidence_type": "official_statement",
            "evidence_target": "fact_clarification",
            "evidence_strength": "strong",
            "is_new_this_step": True,
        }
        high_fact = make_persona(
            fact=0.95,
            opinion=0.04,
            questioning=0.01,
            repost=0.1,
            eat_melon=0.0,
        )
        low_fact = make_persona(
            fact=0.05,
            opinion=0.9,
            questioning=0.05,
            repost=0.8,
            eat_melon=0.5,
        )

        high_guard = build_strategy_state_guard(
            high_fact,
            {},
            make_event("clear"),
            {"current_emotion": "neutral", "official_attitude": None},
            [official_evidence],
            ["neutral", "negative"],
            ["accept", "wait", "question"],
        )
        low_guard = build_strategy_state_guard(
            low_fact,
            {},
            make_event("clear"),
            {"current_emotion": "neutral", "official_attitude": None},
            [official_evidence],
            ["neutral", "negative"],
            ["accept", "wait", "question"],
        )

        self.assertEqual(
            high_guard["official_attitude_options"],
            ["wait", "accept"],
        )
        self.assertEqual(low_guard["official_attitude_options"], ["wait"])

    def test_weak_public_comment_cannot_bypass_persona_hold(self):
        persona = make_persona(
            fact=0.9,
            opinion=0.05,
            questioning=0.05,
            repost=0.1,
            eat_melon=0.0,
        )
        weak_public = {
            "evidence_id": "public_1",
            "evidence_group_id": "public_1",
            "evidence_type": "simulated_comment",
            "comment_source": "current_generated",
            "evidence_target": "public_discourse",
            "evidence_strength": "weak",
            "is_new_this_step": True,
        }

        guard = build_strategy_state_guard(
            persona,
            {},
            make_event(),
            {
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
            },
            [weak_public],
            ["positive", "neutral", "negative"],
            ["not_applicable"],
        )

        self.assertEqual(guard["emotion_options"], ["neutral"])
        transition = guard["emotion_transition"]
        self.assertEqual(
            transition["state_change_basis"],
            "held_without_directional_evidence",
        )
        self.assertEqual(transition["effective_non_peer_evidence_count"], 0)
        self.assertEqual(transition["held_non_peer_evidence_count"], 0)

    def test_personally_sufficient_objective_evidence_opens_adjacent_state(self):
        persona = make_persona(
            fact=0.95,
            opinion=0.03,
            questioning=0.02,
            repost=0.1,
            eat_melon=0.0,
        )
        objective = {
            "evidence_id": "verified_1",
            "evidence_group_id": "verified_1",
            "evidence_type": "objective_event",
            "evidence_target": "fact_clarification",
            "evidence_strength": "strong",
            "is_new_this_step": True,
        }

        guard = build_strategy_state_guard(
            persona,
            {},
            make_event(),
            {
                "current_emotion": "negative",
                "official_attitude": "not_applicable",
            },
            [objective],
            ["positive", "neutral", "negative"],
            ["not_applicable"],
        )

        self.assertEqual(guard["emotion_options"], ["neutral"])
        self.assertEqual(
            guard["emotion_transition"]["state_change_basis"],
            "changed_by_non_peer_directional_evidence",
        )

    def test_prompt_guard_does_not_expose_recommended_attitude(self):
        prompt_guard = build_strategy_state_prompt_guard(
            {
                "guard_version": "strategy_directional_utility_v3",
                "emotion_transition": {"state_change_basis": "held"},
                "official_attitude_resolution": {
                    "official_attitude": "wait",
                    "utilities": {"wait": 1.0},
                },
                "decision_rule": "test",
            }
        )

        self.assertNotIn("official_attitude_resolution", prompt_guard)
        self.assertNotIn("utilities", prompt_guard)

    def test_official_statement_parts_are_one_prompt_evidence_group(self):
        persona = make_persona(
            fact=0.9,
            opinion=0.05,
            questioning=0.05,
            repost=0.1,
            eat_melon=0.0,
        )
        items = [
            {
                "evidence_id": f"official_2_part_{index}",
                "evidence_group_id": "official_2",
                "evidence_type": "official_statement_unit",
                "evidence_target": target,
                "evidence_strength": "strong",
                "is_new_this_step": True,
            }
            for index, target in enumerate(
                ("fact_clarification", "investigation_process"),
                start=1,
            )
        ]

        guard = build_strategy_state_guard(
            persona,
            {},
            make_event("clear"),
            {
                "current_emotion": "neutral",
                "official_attitude": "not_applicable",
            },
            items,
            ["positive", "neutral", "negative"],
            ["accept", "wait", "question"],
        )

        self.assertEqual(len(guard["state_evidence_catalog"]), 1)
        catalog_item = guard["state_evidence_catalog"][0]
        self.assertEqual(catalog_item["evidence_group_id"], "official_2")
        self.assertEqual(catalog_item["evidence_member_count"], 2)
        self.assertEqual(
            set(catalog_item["evidence_targets"]),
            {"fact_clarification", "investigation_process"},
        )

    def test_audit_keeps_emotion_and_attitude_dimensions_separate(self):
        guard = {
            "previous_emotion": "negative",
            "previous_official_attitude": "wait",
            "emotion_transition": {
                "state_change_basis": "new_non_peer_evidence"
            },
            "official_attitude_resolution": {
                "official_attitude": "wait",
                "process_evaluation": "partial",
                "transition_reason": "held_without_new_evidence",
            },
        }

        audited = attach_strategy_state_audit(
            {
                "current_emotion": "neutral",
                "official_attitude": "wait",
            },
            guard,
        )

        self.assertTrue(
            audited["state_transition_diagnostics"]["emotion_changed"]
        )
        self.assertFalse(
            audited["state_transition_diagnostics"][
                "official_attitude_changed"
            ]
        )
        self.assertEqual(audited["claim_position"], "unresolved")


if __name__ == "__main__":
    unittest.main()
