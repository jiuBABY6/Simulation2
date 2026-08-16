"""单个 Agent 的本地规则决策示例。

该文件用于不调用大模型时验证 Persona、事件状态和评论池的组合逻辑。
正式批量运行可使用 batch_agent_decision.py。
"""

import argparse
import json

from agent_state_store import AgentStateStore
from comment_pool_generator import load_or_generate_comment_pool
from decision_engine import (
    decide_comment_faction,
    decide_emotion,
    decide_official_attitude,
    decide_will_comment,
    get_topic_match,
    select_best_candidate,
)
from event_context import load_event_context
from json_storage import load_json, save_json
from persona_repository import load_first_persona
from project_config import (
    EVENT_FILE,
    EVENT_STATE_FILE,
    PERSONA_DIR,
    POLICY_FILE,
    SINGLE_DECISION_RESULT_FILE,
)


def run_rule_decision(persona=None):
    """运行单个 Agent 的本地规则决策并保存结果。"""
    persona = persona or load_first_persona(PERSONA_DIR)
    event_context = load_event_context(EVENT_FILE, EVENT_STATE_FILE)
    policy = load_json(POLICY_FILE)
    candidates = load_or_generate_comment_pool(event_context)
    topic_match = get_topic_match(persona, event_context)
    current_emotion, emotion_scores = decide_emotion(
        persona, policy, event_context, topic_match
    )
    official_attitude, attitude_scores = decide_official_attitude(
        persona, policy, event_context
    )
    will_comment, intention_score = decide_will_comment(
        persona, event_context, topic_match, current_emotion
    )

    result = {
        "event_id": event_context["event_id"],
        "step": event_context["current_state"]["step"],
        "agent_id": persona["agent_id"],
        "decision_method": "local_rule",
        "topic_match_score": round(topic_match, 6),
        "current_emotion": current_emotion,
        "emotion_scores": emotion_scores,
        "official_attitude": official_attitude,
        "official_attitude_scores": attitude_scores,
        "will_comment": will_comment,
        "comment_intention_score": intention_score,
        "comment_faction": None,
        "faction_scores": {},
        "selected_comment": None,
        "candidate_comment_scores": [],
    }

    if will_comment:
        faction, faction_scores = decide_comment_faction(
            persona, event_context, current_emotion, topic_match
        )
        selected, scored_candidates = select_best_candidate(
            candidates, event_context, persona, current_emotion, faction
        )
        result["comment_faction"] = faction
        result["faction_scores"] = faction_scores
        result["selected_comment"] = selected
        result["candidate_comment_scores"] = scored_candidates

    AgentStateStore().save_decision_states(
        [
            {
                "event_id": result["event_id"],
                "step": result["step"],
                "agent_id": result["agent_id"],
                "status": "success",
                "decision": result,
            }
        ]
    )
    save_json(SINGLE_DECISION_RESULT_FILE, result)
    print("本地规则决策完成。")
    print(f"结果文件：{SINGLE_DECISION_RESULT_FILE}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    """提供本地规则决策的命令行入口。"""
    parser = argparse.ArgumentParser(description="运行单个 Agent 的本地规则决策")
    parser.add_argument("--agent-file", default="", help="可选的 Persona JSON 文件路径")
    args = parser.parse_args()
    persona = load_json(args.agent_file) if args.agent_file else None
    run_rule_decision(persona)


if __name__ == "__main__":
    main()
