"""回应方案实验的独立原创表达生成协议。

2026/10/17，新增功能：内部状态与公开文本分两次形成。只有本地行为
门控已经选择 ``original`` 时才调用本模块；因此表达文本不会反向决定
Agent 是否发言，也不会反向改写内部情绪或官方态度。
"""

from __future__ import annotations

import json

from domain.comment_semantics import (
    EVIDENCE_ROLES,
    REACTION_TARGETS,
    normalize_comment_semantics,
)


EXPRESSION_EMOTIONS = ("positive", "neutral", "negative")
EXPRESSION_STANCES = ("support", "neutral", "questioning", "criticism")
MAX_EXPRESSION_LENGTH = 280
TARGET_EXPRESSION_LENGTH = 200


def _truncate_at_sentence_boundary(text, max_length=MAX_EXPRESSION_LENGTH):
    """在硬上限内优先按句末裁剪，避免直接截断出半句话。"""

    normalized = str(text or "").strip()
    if len(normalized) <= max_length:
        return normalized
    prefix = normalized[:max_length]
    sentence_endings = "。！？!?；;"
    cut_positions = [
        index
        for index, character in enumerate(prefix)
        if character in sentence_endings
    ]
    # 过短的第一个句子不足以代表原表达时，保留更多正文并使用省略号。
    if cut_positions and cut_positions[-1] >= max_length // 3:
        return prefix[: cut_positions[-1] + 1].strip()
    return prefix[: max_length - 1].rstrip("，,、;； ") + "…"


def normalize_overlong_strategy_expression(expression):
    """只修复超长文本，并留下可审计的原始/规范化长度。"""

    if not isinstance(expression, dict):
        return expression
    text = expression.get("text")
    if not isinstance(text, str) or len(text.strip()) <= MAX_EXPRESSION_LENGTH:
        return expression
    normalized = dict(expression)
    normalized_text = _truncate_at_sentence_boundary(text)
    normalized["text"] = normalized_text
    normalized["normalization_audit"] = {
        "code": "trimmed_overlong_expression_at_sentence_boundary",
        "original_length": len(text.strip()),
        "normalized_length": len(normalized_text),
        "limit": MAX_EXPRESSION_LENGTH,
    }
    return normalized


def _build_evidence_catalog(event_context, visible_comments):
    """整理原创表达可引用的个人证据，保持编号可审计。"""

    catalog = []
    for comment in visible_comments:
        if not isinstance(comment, dict) or not comment.get("comment_id"):
            continue
        catalog.append(
            {
                "evidence_id": str(comment["comment_id"]),
                "type": comment.get("source_type", "visible_comment"),
                "text": str(comment.get("text", "")).strip(),
                "introduced_step": comment.get("introduced_step"),
                "reaction_target": comment.get(
                    "reaction_target", "public_discourse"
                ),
                "evidence_role": comment.get("evidence_role", "opinion"),
                "claim_id": comment.get("claim_id"),
            }
        )

    current_state = event_context.get("current_state", {})
    statement = (
        current_state.get("official_statement")
        or event_context.get("official_statement")
        or ""
    )
    if str(statement).strip():
        catalog.append(
            {
                "evidence_id": (
                    f"official_statement_step_{current_state.get('step', 0)}"
                ),
                "type": "official_statement",
                "text": str(statement).strip(),
                "introduced_step": current_state.get("step"),
                "reaction_target": "official_claim",
                "evidence_role": "clarify",
                "claim_id": f"official_claim_step_{current_state.get('step', 0)}",
            }
        )

    if not catalog:
        # 极端情况下仍允许围绕事件本身表达，但编号明确指向事件输入，
        # 不把模型自行补充的事实伪装成个人已见证据。
        catalog.append(
            {
                "evidence_id": "event_input",
                "type": "event_input",
                "text": str(event_context.get("event_content", "")).strip(),
                "introduced_step": current_state.get("step"),
                "reaction_target": "event_harm",
                "evidence_role": "background",
                "claim_id": "event_input",
            }
        )
    return catalog


def build_strategy_expression_prompt(
    persona,
    event_context,
    state_decision,
    visible_comments,
    history_summary,
    correction_feedback=None,
):
    """在状态和动作均已确定后构造原创表达提示词。"""

    evidence_catalog = _build_evidence_catalog(
        event_context,
        visible_comments,
    )
    persona_view = {
        "agent_id": persona.get("agent_id"),
        "topic_preference": persona.get("topic_preference", {}),
        "information_orientation": persona.get(
            "information_orientation", {}
        ),
        "emotion_expression": persona.get("emotion_expression", {}),
        "comment_faction_preference": persona.get(
            "comment_faction_preference", {}
        ),
    }
    prompt = f"""
你是社会舆情模拟系统中的Agent公开表达生成器。
状态判断和是否发言已经完成；你只能生成一条原创表达，不能改变既定状态或动作。

【既定内部状态】
{json.dumps({
    "current_emotion": state_decision.get("current_emotion"),
    "official_attitude": state_decision.get("official_attitude"),
    "comment_faction": state_decision.get("comment_faction"),
}, ensure_ascii=False, indent=2)}

【Persona表达倾向】
{json.dumps(persona_view, ensure_ascii=False, indent=2)}

【近期个人表达历史】
{json.dumps(history_summary.get("own_comment_history", [])[-5:], ensure_ascii=False, indent=2)}

【本轮可引用证据】
{json.dumps(evidence_catalog, ensure_ascii=False, indent=2)}

【生成规则】
1. expression.emotion可独立选择positive、neutral、negative，不要求等于内部情绪。
2. positive只表示对救助、依法处置、事实澄清、互助或改进的认可，不能赞同伤害后果。
3. 文本应体现当前Persona的关注方式，避免机械重复自己的历史表达。
4. 只能引用本轮证据目录中的编号，不得编造人物、时间、因果或调查结论。
5. 文本目标为120至{TARGET_EXPRESSION_LENGTH}字，绝不能超过{MAX_EXPRESSION_LENGTH}字；只返回JSON对象，不输出Markdown。
6. reaction_target必须表示这条表达真正评价的对象；evidence_role必须区分个人观点、提问、支持和矛盾信息，不能把普通观点伪装成已核实事实。

JSON字段格式：
{{
  "text": "原创表达",
  "emotion": "positive | neutral | negative",
  "stance": "support | neutral | questioning | criticism",
  "evidence_ids": ["至少一个可用证据编号"],
  "reaction_target": "event_harm | official_claim | investigation_process | accountability | victim_support | public_discourse | social_action",
  "evidence_role": "support | contradict | question | opinion | background | clarify",
  "claim_id": "可选，引用具体事实声明时填写，否则为null"
}}
""".strip()
    if correction_feedback:
        prompt += (
            "\n\n【上一次输出的纠错要求】\n"
            f"{str(correction_feedback).strip()[:300]}\n"
            "请只修正原创表达，不改变已经确定的内部状态和动作。"
        )
    return prompt, evidence_catalog


def validate_strategy_expression(expression, evidence_catalog):
    """校验独立原创表达，返回可直接写入决策的规范对象。"""

    if not isinstance(expression, dict):
        raise ValueError("原创表达必须是JSON对象。")
    text = expression.get("text")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("原创表达text必须是非空文本。")
    text = text.strip()
    if len(text) > MAX_EXPRESSION_LENGTH:
        raise ValueError(
            f"原创表达text不能超过{MAX_EXPRESSION_LENGTH}个字符。"
        )
    emotion = expression.get("emotion")
    if emotion not in EXPRESSION_EMOTIONS:
        raise ValueError("原创表达emotion必须是positive、neutral或negative。")
    stance = expression.get("stance")
    if stance not in EXPRESSION_STANCES:
        raise ValueError("原创表达stance不在允许选项中。")

    evidence_ids = expression.get("evidence_ids")
    if not isinstance(evidence_ids, list) or not evidence_ids:
        raise ValueError("原创表达evidence_ids必须是非空数组。")
    normalized_ids = list(
        dict.fromkeys(
            str(item).strip()
            for item in evidence_ids
            if str(item).strip()
        )
    )
    allowed_ids = {item["evidence_id"] for item in evidence_catalog}
    if not normalized_ids or not set(normalized_ids).issubset(allowed_ids):
        raise ValueError("原创表达引用了个人不可用的证据编号。")
    normalized = normalize_comment_semantics({
        "text": text,
        "emotion": emotion,
        "stance": stance,
        "evidence_ids": normalized_ids,
        "reaction_target": expression.get("reaction_target"),
        "evidence_role": expression.get("evidence_role"),
        "claim_id": expression.get("claim_id"),
        "information_source_type": "agent",
        "information_origin": "endogenous",
        "provenance_type": "agent_original_expression",
    }, default_information_source="agent", default_provenance="agent_original_expression")
    if normalized["reaction_target"] not in REACTION_TARGETS:
        raise ValueError("原创表达reaction_target不在允许选项中。")
    if normalized["evidence_role"] not in EVIDENCE_ROLES:
        raise ValueError("原创表达evidence_role不在允许选项中。")
    if isinstance(expression.get("normalization_audit"), dict):
        normalized["normalization_audit"] = dict(
            expression["normalization_audit"]
        )
    return normalized
