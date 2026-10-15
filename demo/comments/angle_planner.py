"""生成事件讨论角度，并为初始评论和增量评论分配角度任务。

本模块只负责角度计划和任务分配，不生成评论文本，也不处理评论兜底。
"""

import json
import re

from infrastructure.llm_service import call_deepseek_json
from project_config import COMMENT_POOL_MAX_TOKENS
from simulation.evidence_policy import (
    build_official_statement_evidence,
    objective_event_is_positive_eligible,
)


EVENT_ANGLE_COUNT = 8
ANGLE_PLAN_RETRY_COUNT = 3

# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：统一声明出现后使用的公共评价角度。
OFFICIAL_RESPONSE_ANGLES = (
    {
        "angle_id": "official_completeness",
        "angle_name": "声明信息完整性",
        "focus": "讨论官方声明是否回答了公众关心的关键问题。",
        "source_type": "official_statement",
    },
    {
        "angle_id": "official_credibility",
        "angle_name": "声明可信度",
        "focus": "讨论官方声明的依据、可信程度和仍需核实之处。",
        "source_type": "official_statement",
    },
    {
        "angle_id": "official_follow_up",
        "angle_name": "后续处置",
        "focus": "讨论官方是否给出后续行动、处理进展或持续公开安排。",
        "source_type": "official_statement",
    },
)

# 2026/09/04 评论质量与耗时平衡，新增功能：为重复出现的讨论角度轮换表达方式，降低并行批次生成相同套话的概率。
EXPRESSION_MODES = (
    {
        "expression_mode": "fact_check",
        "expression_instruction": "关注事实、证据或信息是否充分。",
    },
    {
        "expression_mode": "question",
        "expression_instruction": "提出一个仍需回答的具体问题。",
    },
    {
        "expression_mode": "impact",
        "expression_instruction": "关注事件对公众或相关群体的影响。",
    },
    {
        "expression_mode": "judgment",
        "expression_instruction": "基于现有信息表达审慎的态度判断。",
    },
    {
        "expression_mode": "suggestion",
        "expression_instruction": "提出合理的后续处理或信息公开建议。",
    },
)

# 2026/10/8，新增功能：历史校准任务可声明硬情绪要求；普通角度任务仍可省略该字段。
TASK_EMOTIONS = ("negative", "neutral", "positive")


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：构造事件角度规划提示词。
def build_event_angle_prompt(event_input, angle_count=EVENT_ANGLE_COUNT):
    """构造只依据事件正文生成讨论角度的提示词。"""
    return f"""
你是社会舆情模拟系统的事件讨论角度规划器。请只根据给定事件正文，提取公众可能讨论的不同角度。

【事件正文】
{event_input.get('event_content', '')}

【生成要求】
1. 生成恰好 {angle_count} 个彼此不同的讨论角度。
2. angle_id 使用简短且唯一的英文小写字母、数字或下划线。
3. angle_name 使用简短中文名称，focus 说明该角度关注什么。
4. evidence_text 必须逐字摘自事件正文，并能支持该角度。
5. 不得编造事件正文中没有提供的事实，不得加入官方声明评价角度。

【输出格式】
只能返回一个 JSON 对象，不要返回 Markdown 或额外解释：
{{
  "angles": [
    {{
      "angle_id": "product_safety",
      "angle_name": "产品安全",
      "focus": "讨论产品本身是否存在安全风险",
      "evidence_text": "事件正文中的原文片段"
    }}
  ]
}}
""".strip()


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：校验事件角度数量、编号和正文依据。
def validate_event_angle_plan(raw_result, event_input, expected_count=None):
    """返回规范化角度计划，拒绝无正文依据或重复的角度。"""
    if not isinstance(raw_result, dict):
        raise ValueError("事件角度计划必须是 JSON 对象。")
    raw_angles = raw_result.get("angles")
    if not isinstance(raw_angles, list) or not raw_angles:
        raise ValueError("事件角度计划必须包含非空 angles 数组。")
    if expected_count is not None and len(raw_angles) != expected_count:
        raise ValueError(
            f"事件角度数量必须为 {expected_count}，实际为 {len(raw_angles)}。"
        )

    event_content = str(event_input.get("event_content", "")).strip()
    if not event_content:
        raise ValueError("事件正文不能为空。")

    angles = []
    angle_ids = set()
    angle_names = set()
    for index, item in enumerate(raw_angles, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个事件角度必须是 JSON 对象。")

        angle_id = str(item.get("angle_id", "")).strip()
        angle_name = str(item.get("angle_name", "")).strip()
        focus = str(item.get("focus", "")).strip()
        evidence_text = str(item.get("evidence_text", "")).strip()
        if not re.fullmatch(r"[a-z0-9_]+", angle_id):
            raise ValueError(f"第 {index} 个 angle_id 格式不合法：{angle_id}")
        if not angle_name or not focus or not evidence_text:
            raise ValueError(f"第 {index} 个事件角度字段不完整。")
        if angle_id in angle_ids or angle_name in angle_names:
            raise ValueError(f"事件角度重复：{angle_id} / {angle_name}")
        if evidence_text not in event_content:
            raise ValueError(
                f"事件角度 {angle_id} 的 evidence_text 不是事件正文原文。"
            )

        angle_ids.add(angle_id)
        angle_names.add(angle_name)
        angles.append(
            {
                "angle_id": angle_id,
                "angle_name": angle_name,
                "focus": focus,
                "evidence_text": evidence_text,
                "source_type": "event",
            }
        )

    return {
        "event_id": event_input.get("event_id"),
        "generation_method": "llm_event_angle_plan",
        "angles": angles,
    }


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：为每个事件生成一次可复用的讨论角度计划。
def generate_event_angle_plan(event_input, angle_count=EVENT_ANGLE_COUNT):
    """调用大模型生成事件角度，校验失败时只重试角度计划。"""
    if not isinstance(event_input, dict) or not event_input.get("event_id"):
        raise ValueError("event_input 必须包含有效的 event_id。")
    if not isinstance(angle_count, int) or angle_count < 1:
        raise ValueError("angle_count 必须是正整数。")

    prompt = build_event_angle_prompt(event_input, angle_count)
    last_error = None
    for attempt in range(1, ANGLE_PLAN_RETRY_COUNT + 1):
        request_prompt = prompt
        if last_error is not None:
            request_prompt = f"""
{prompt}

【上一次结果问题】
{last_error}
请修正后重新返回完整角度计划。
""".strip()
        raw_result = call_deepseek_json(
            prompt=request_prompt,
            system_prompt="你只能返回合法 JSON 对象，并且必须包含 angles 数组。",
            temperature=0.3,
            max_tokens=min(COMMENT_POOL_MAX_TOKENS, 4000),
            # 2026/09/04 Demo性能基线，新增功能：标记事件角度规划请求类型。
            request_type="comment_angle",
        )
        try:
            return validate_event_angle_plan(
                raw_result,
                event_input,
                expected_count=angle_count,
            )
        except ValueError as error:
            last_error = str(error)
            print(
                f"事件角度计划校验失败，第 {attempt}/{ANGLE_PLAN_RETRY_COUNT} 次："
                f"{last_error}"
            )
    raise RuntimeError(f"事件角度计划生成失败：{last_error}")


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：统一校验初始和增量评论角度任务。
# 2026/09/04 评论质量与耗时平衡，修改功能：校验并补充任务表达方式，同时兼容旧任务结构。
def validate_comment_tasks(comment_tasks, expected_count=None):
    """检查评论任务编号和角度字段，并返回规范化任务。"""
    if not isinstance(comment_tasks, list) or not comment_tasks:
        raise ValueError("comment_tasks 必须是非空数组。")
    if expected_count is not None and len(comment_tasks) != expected_count:
        raise ValueError(
            f"评论任务数量必须为 {expected_count}，实际为 {len(comment_tasks)}。"
        )

    tasks = []
    task_ids = set()
    expression_mode_map = {
        item["expression_mode"]: item["expression_instruction"]
        for item in EXPRESSION_MODES
    }
    for index, item in enumerate(comment_tasks, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"第 {index} 个评论任务必须是 JSON 对象。")
        task_id = str(item.get("task_id", "")).strip()
        angle_id = str(item.get("angle_id", "")).strip()
        angle_name = str(item.get("angle_name", "")).strip()
        focus = str(item.get("focus", "")).strip()
        default_expression = EXPRESSION_MODES[(index - 1) % len(EXPRESSION_MODES)]
        expression_mode = str(
            item.get("expression_mode")
            or default_expression["expression_mode"]
        ).strip()
        expression_instruction = str(
            item.get("expression_instruction")
            or expression_mode_map.get(expression_mode, "")
        ).strip()
        required_emotion = item.get("required_emotion")
        if required_emotion is not None:
            required_emotion = str(required_emotion).strip().lower()
        source_type = str(item.get("source_type", "event")).strip() or "event"
        reaction_target = item.get("reaction_target")
        if reaction_target is not None:
            reaction_target = str(reaction_target).strip()
            if not reaction_target:
                raise ValueError(f"第 {index} 个评论任务的 reaction_target 为空。")
        evidence_ids = item.get("evidence_ids", [])
        if not isinstance(evidence_ids, list) or any(
            not isinstance(evidence_id, str) or not evidence_id.strip()
            for evidence_id in evidence_ids
        ):
            raise ValueError(f"第 {index} 个评论任务的 evidence_ids 不合法。")
        evidence_ids = list(
            dict.fromkeys(evidence_id.strip() for evidence_id in evidence_ids)
        )
        positive_evidence = item.get("positive_evidence", [])
        if not isinstance(positive_evidence, list) or any(
            not isinstance(evidence, dict)
            or not str(evidence.get("evidence_id", "")).strip()
            or not str(evidence.get("content", "")).strip()
            for evidence in positive_evidence
        ):
            raise ValueError(
                f"第 {index} 个评论任务的 positive_evidence 不合法。"
            )
        if not task_id or task_id in task_ids:
            raise ValueError(f"评论任务编号为空或重复：{task_id}")
        if not angle_id or not angle_name or not focus:
            raise ValueError(f"第 {index} 个评论任务缺少角度字段。")
        if expression_mode not in expression_mode_map:
            raise ValueError(
                f"第 {index} 个评论任务的表达方式不合法："
                f"{expression_mode}"
            )
        if not expression_instruction:
            raise ValueError(f"第 {index} 个评论任务缺少表达要求。")
        if (
            required_emotion is not None
            and required_emotion not in TASK_EMOTIONS
        ):
            raise ValueError(
                f"第 {index} 个评论任务的 required_emotion 不合法："
                f"{required_emotion}"
            )
        if (
            required_emotion == "positive"
            and reaction_target is not None
            and not positive_evidence
        ):
            raise ValueError(
                f"第 {index} 个正面评论任务缺少 positive_evidence。"
            )
        task_ids.add(task_id)
        normalized_task = {
            "task_id": task_id,
            "angle_id": angle_id,
            "angle_name": angle_name,
            "focus": focus,
            "expression_mode": expression_mode,
            "expression_instruction": expression_instruction,
            "source_type": source_type,
        }
        if required_emotion is not None:
            normalized_task["required_emotion"] = required_emotion
        if reaction_target is not None:
            normalized_task["reaction_target"] = reaction_target
        if evidence_ids:
            normalized_task["evidence_ids"] = evidence_ids
        if positive_evidence:
            normalized_task["positive_evidence"] = positive_evidence
        tasks.append(normalized_task)
    return tasks


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：确定性均匀分配评论角度。
# 2026/09/04 评论质量与耗时平衡，修改功能：为每个角度任务确定性分配不同表达方式。
def build_angle_tasks(angles, comment_count, task_prefix, start_offset=0):
    """按轮转顺序将评论数量均匀分配给不同角度。"""
    if not isinstance(comment_count, int) or comment_count < 1:
        raise ValueError("comment_count 必须是正整数。")
    if not isinstance(angles, list) or not angles:
        raise ValueError("angles 必须是非空数组。")
    if not isinstance(start_offset, int) or start_offset < 0:
        raise ValueError("start_offset 必须是非负整数。")

    tasks = []
    for index in range(comment_count):
        angle = angles[(start_offset + index) % len(angles)]
        expression = EXPRESSION_MODES[
            (start_offset + index) % len(EXPRESSION_MODES)
        ]
        tasks.append(
            {
                "task_id": f"{task_prefix}_{index + 1:03d}",
                "angle_id": angle["angle_id"],
                "angle_name": angle["angle_name"],
                "focus": angle["focus"],
                "source_type": angle.get("source_type", "event"),
                **expression,
            }
        )
    return validate_comment_tasks(tasks, expected_count=comment_count)


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：均匀分配初始评论的事件角度任务。
def build_initial_angle_tasks(angle_plan, comment_count):
    """根据事件角度计划生成初始评论任务。"""
    return build_angle_tasks(
        angle_plan.get("angles", []),
        comment_count,
        "initial",
    )


# 2026/10/8，新增功能：将历史初始条件的情绪配额确定性且均匀地附加到评论任务。
def apply_required_emotion_targets(comment_tasks, emotion_targets):
    """返回带 required_emotion 的任务副本，不影响没有配额的普通任务。"""
    tasks = validate_comment_tasks(comment_tasks)
    if not isinstance(emotion_targets, dict):
        raise ValueError("emotion_targets 必须是JSON对象。")

    targets = {}
    for emotion in TASK_EMOTIONS:
        value = emotion_targets.get(emotion, 0)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"emotion_targets.{emotion} 必须是非负整数。")
        targets[emotion] = value
    total = sum(targets.values())
    if total != len(tasks):
        raise ValueError(
            "情绪配额总数与评论任务数不一致："
            f"{total} != {len(tasks)}"
        )

    assigned = {emotion: 0 for emotion in TASK_EMOTIONS}
    calibrated_tasks = []
    for position, task in enumerate(tasks, start=1):
        candidates = [
            emotion
            for emotion in TASK_EMOTIONS
            if assigned[emotion] < targets[emotion]
        ]
        selected = max(
            candidates,
            key=lambda emotion: (
                position * targets[emotion] / total - assigned[emotion],
                -TASK_EMOTIONS.index(emotion),
            ),
        )
        calibrated_tasks.append({**task, "required_emotion": selected})
        assigned[selected] += 1
    return validate_comment_tasks(calibrated_tasks, expected_count=len(tasks))


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：声明出现后补充公共评价角度。
def select_active_angles(angle_plan, current_state):
    """返回本轮使用的事件角度和可选的官方声明评价角度。"""
    event_angles = list(angle_plan.get("angles", []))
    if not event_angles:
        raise ValueError("angle_plan 缺少可用事件角度。")

    statement = str(current_state.get("official_statement", "")).strip()
    statement_status = current_state.get("official_statement_status", "none")
    if not statement or statement_status == "none":
        return event_angles

    event_angle_ids = {angle.get("angle_id") for angle in event_angles}
    official_angles = [
        {
            **angle,
            "evidence_text": statement,
        }
        for angle in OFFICIAL_RESPONSE_ANGLES
        if angle["angle_id"] not in event_angle_ids
    ]
    return [*event_angles, *official_angles]


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：按当前状态分配每轮增量评论角度任务。
def build_incremental_angle_tasks(
    angle_plan,
    current_state,
    comment_count,
    *,
    evidence_based=False,
    previous_comments=None,
):
    """根据本轮活跃角度生成增量评论任务。"""
    step = current_state.get("step")
    if not isinstance(step, int) or step < 2:
        raise ValueError("增量评论任务的 step 必须大于或等于 2。")
    active_angles = select_active_angles(angle_plan, current_state)
    tasks = build_angle_tasks(
        active_angles,
        comment_count,
        f"step_{step}",
        start_offset=step - 2,
    )
    if not evidence_based:
        return tasks
    return apply_evidence_based_emotion_coverage(
        tasks,
        current_state,
        previous_comments or [],
    )


# 2026/10/9，修改功能：条件化历史回放使用本阶段公众语境、客观事件、
# 官方声明和模拟评论设置最小情绪覆盖，避免增量评论单类坍缩。
def apply_evidence_based_emotion_coverage(
    comment_tasks,
    current_state,
    previous_comments,
):
    """为有内部证据的情绪各分配一个任务，其余任务由模型自由判断。"""

    tasks = validate_comment_tasks(comment_tasks)
    if not isinstance(current_state, dict):
        return tasks

    objective_context = current_state.get("objective_event_context", {})
    objective_events = (
        objective_context.get("events", [])
        if isinstance(objective_context, dict)
        else []
    )
    official_evidence = build_official_statement_evidence(current_state)
    public_context = current_state.get("public_context", {})
    public_discourse = (
        public_context.get("public_discourse", [])
        if isinstance(public_context, dict)
        else []
    )
    verified_updates = (
        public_context.get("verified_updates", [])
        if isinstance(public_context, dict)
        else []
    )
    conditioned_positive = (
        public_context.get("positive_evidence", [])
        if isinstance(public_context, dict)
        else []
    )
    simulated_comments = [
        item
        for item in previous_comments
        if isinstance(item, dict) and item.get("comment_id")
    ]

    positive_candidates = []
    positive_candidates.extend(
        {
            "evidence_id": item.get("evidence_id"),
            "content": item.get("content", ""),
            "target": item.get("target", "public_discourse"),
        }
        for item in conditioned_positive
        if item.get("evidence_id")
    )
    positive_candidates.extend(
        {
            "evidence_id": item.get("context_id"),
            "content": item.get("content", ""),
            "target": "social_action",
        }
        for item in public_discourse
        if item.get("status") == "social_action" and item.get("context_id")
    )
    for item in objective_events:
        if not objective_event_is_positive_eligible(item.get("event_type")):
            continue
        positive_candidates.append(
            {
                "evidence_id": item.get("objective_event_id"),
                "content": item.get("content", ""),
                "target": "social_action",
            }
        )
    if (
        official_evidence is not None
        and official_evidence["positive_eligible"]
    ):
        positive_candidates.append(
            {
                "evidence_id": official_evidence["evidence_id"],
                "content": official_evidence["content"],
                "target": "official_response",
            }
        )
    positive_candidates.extend(
        {
            "evidence_id": item.get("comment_id"),
            "content": item.get("text", ""),
            "target": "public_discourse",
        }
        for item in simulated_comments
        if item.get("emotion") == "positive"
    )

    neutral_candidates = [
        {
            "evidence_id": item.get("objective_event_id"),
            "content": item.get("content", ""),
        }
        for item in objective_events
    ]
    neutral_candidates.extend(
        {
            "evidence_id": item.get("evidence_id"),
            "content": item.get("content", ""),
        }
        for item in verified_updates
        if item.get("evidence_id")
    )
    if official_evidence is not None:
        neutral_candidates.append(
            {
                "evidence_id": official_evidence["evidence_id"],
                "content": official_evidence["content"],
            }
        )
    neutral_candidates.extend(
        {
            "evidence_id": item.get("comment_id"),
            "content": item.get("text", ""),
        }
        for item in simulated_comments
        if item.get("emotion") == "neutral"
    )
    negative_candidates = [
        {
            "evidence_id": item.get("comment_id"),
            "content": item.get("text", ""),
        }
        for item in simulated_comments
        if item.get("emotion") == "negative"
    ]
    negative_candidates.extend(
        {
            "evidence_id": item.get("context_id"),
            "content": item.get("content", ""),
        }
        for item in public_discourse
        if item.get("status")
        in {"public_question", "unverified_claim", "ongoing_discussion"}
        and item.get("context_id")
    )

    assignments = []
    if positive_candidates:
        evidence = positive_candidates[0]
        assignments.append(
            {
                "emotion": "positive",
                "reaction_target": evidence.get("target", "public_discourse"),
                "evidence_ids": [evidence.get("evidence_id")],
                "positive_evidence": [evidence],
                "prefer_official": evidence.get("target")
                in {"official_response", "fact_clarification"},
            }
        )
    if neutral_candidates:
        evidence = neutral_candidates[0]
        assignments.append(
            {
                "emotion": "neutral",
                "reaction_target": "event_outcome",
                "evidence_ids": [evidence.get("evidence_id")],
                "prefer_official": True,
            }
        )
    if negative_candidates:
        evidence = negative_candidates[0]
        assignments.append(
            {
                "emotion": "negative",
                "reaction_target": "public_discourse",
                "evidence_ids": [evidence.get("evidence_id")],
                "prefer_official": False,
            }
        )

    assigned_indexes = set()
    for assignment in assignments:
        preferred_indexes = [
            index
            for index, task in enumerate(tasks)
            if index not in assigned_indexes
            and (
                not assignment["prefer_official"]
                or task.get("source_type") == "official_statement"
            )
        ]
        fallback_indexes = [
            index for index in range(len(tasks)) if index not in assigned_indexes
        ]
        candidate_indexes = preferred_indexes or fallback_indexes
        if not candidate_indexes:
            break
        selected_index = candidate_indexes[0]
        assigned_indexes.add(selected_index)
        tasks[selected_index] = {
            **tasks[selected_index],
            "required_emotion": assignment["emotion"],
            "reaction_target": assignment["reaction_target"],
            "evidence_ids": [
                evidence_id
                for evidence_id in assignment["evidence_ids"]
                if evidence_id
            ],
            **(
                {"positive_evidence": assignment["positive_evidence"]}
                if assignment.get("positive_evidence")
                else {}
            ),
        }
    return validate_comment_tasks(tasks, expected_count=len(tasks))


# 2026/08/26，事件角度+派系+人物类型，解决评论兜底，新增功能：统一格式化提示词中的角度任务。
def format_comment_tasks(comment_tasks):
    """将评论任务转换为适合提示词使用的 JSON 文本。"""
    return json.dumps(comment_tasks, ensure_ascii=False, indent=2)
