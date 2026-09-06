"""评论池读取服务。

本模块只负责读取和检查已经存在的 comment_pool.json。
它不生成评论、不调用大模型，也不处理 Agent 决策。
"""

from pathlib import Path

from infrastructure.json_storage import load_json, read_jsonl
from project_config import COMMENT_POOL_FILE, INCREMENTAL_COMMENT_FILE


REQUIRED_COMMENT_FIELDS = (
    "comment_id",
    "text",
    "profile_id",
    "profile_label",
    "topic",
    "emotion",
    "faction",
    "orientation",
    "stance",
    "introduced_step",
    "generation_trigger",
)
ANGLE_COMMENT_FIELDS = (
    "task_id",
    "angle_id",
    "angle_name",
    "angle_focus",
)


def load_comment_pool(comment_pool_file=COMMENT_POOL_FILE):
    """读取并检查完整的评论池对象。

    参数：
        comment_pool_file：comment_pool.json 的文件路径。

    返回：
        经过检查的完整评论池字典。
    """
    file_path = Path(comment_pool_file)
    if not file_path.exists():
        raise FileNotFoundError(f"评论池文件不存在：{file_path}")

    comment_pool = load_json(file_path)
    if not isinstance(comment_pool, dict):
        raise ValueError("comment_pool.json 的顶层结构必须是 JSON 对象。")

    comments = comment_pool.get("comments")
    if not isinstance(comments, list):
        raise ValueError("comment_pool.json 必须包含 comments 数组。")

    requested_count = comment_pool.get("requested_comment_count")
    if not isinstance(requested_count, int) or requested_count < 0:
        raise ValueError("requested_comment_count 必须是非负整数。")
    if requested_count != len(comments):
        raise ValueError(
            "requested_comment_count 与 comments 的实际数量不一致："
            f"声明 {requested_count} 条，实际 {len(comments)} 条。"
        )

    comment_ids = set()
    task_ids = set()
    angle_plan = comment_pool.get("angle_plan")
    planned_angle_ids = set()
    if angle_plan is not None:
        if not isinstance(angle_plan, dict) or not isinstance(
            angle_plan.get("angles"), list
        ):
            raise ValueError("angle_plan 必须包含 angles 数组。")
        if angle_plan.get("event_id") != comment_pool.get("event_id"):
            raise ValueError("angle_plan 与评论池的 event_id 不一致。")
        planned_angle_ids = {
            str(angle.get("angle_id", "")).strip()
            for angle in angle_plan["angles"]
            if isinstance(angle, dict) and angle.get("angle_id")
        }
        if not planned_angle_ids:
            raise ValueError("angle_plan 中没有可用事件角度。")

    for index, comment in enumerate(comments, start=1):
        if not isinstance(comment, dict):
            raise ValueError(f"第 {index} 条评论必须是 JSON 对象。")

        missing_fields = [
            field for field in REQUIRED_COMMENT_FIELDS if field not in comment
        ]
        if missing_fields:
            raise ValueError(
                f"第 {index} 条评论缺少字段：{', '.join(missing_fields)}"
            )

        comment_id = str(comment.get("comment_id", "")).strip()
        text = str(comment.get("text", "")).strip()
        if not comment_id:
            raise ValueError(f"第 {index} 条评论的 comment_id 不能为空。")
        if not text:
            raise ValueError(f"第 {index} 条评论的 text 不能为空。")
        if comment_id in comment_ids:
            raise ValueError(f"发现重复的 comment_id：{comment_id}")

        # 2026/08/26，事件角度+派系+人物类型，解决评论兜底，修改功能：新评论池读取时校验角度任务可追踪且不重复。
        if angle_plan is not None:
            missing_angle_fields = [
                field
                for field in ANGLE_COMMENT_FIELDS
                if not comment.get(field)
            ]
            if missing_angle_fields:
                raise ValueError(
                    f"第 {index} 条评论缺少角度字段："
                    + ", ".join(missing_angle_fields)
                )
            task_id = str(comment["task_id"])
            if task_id in task_ids:
                raise ValueError(f"发现重复的 task_id：{task_id}")
            if comment["angle_id"] not in planned_angle_ids:
                raise ValueError(
                    f"第 {index} 条评论引用了未知角度：{comment['angle_id']}"
                )
            task_ids.add(task_id)

        comment_ids.add(comment_id)

    return comment_pool


def load_comments(comment_pool_file=COMMENT_POOL_FILE):
    """读取评论池并返回其中的评论列表。"""
    comment_pool = load_comment_pool(comment_pool_file)
    return comment_pool["comments"]


def load_incremental_comments(
    event_id,
    current_step=None,
    history_file=INCREMENTAL_COMMENT_FILE,
):
    """读取指定事件在当前时间步以前生成的增量评论。"""
    comments = []
    for record in read_jsonl(history_file):
        if not isinstance(record, dict):
            raise ValueError("增量评论历史中的每一行都必须是 JSON 对象。")
        if record.get("event_id") != event_id:
            continue

        step = record.get("step")
        if not isinstance(step, int) or step < 2:
            raise ValueError("增量评论历史记录包含非法 step。")
        if current_step is not None and step > current_step:
            continue

        batch_comments = record.get("comments")
        if not isinstance(batch_comments, list):
            raise ValueError("增量评论历史记录缺少 comments 数组。")
        if record.get("comment_count") != len(batch_comments):
            raise ValueError("增量评论记录的 comment_count 与实际数量不一致。")

        for comment in batch_comments:
            if not isinstance(comment, dict):
                raise ValueError("增量评论必须是 JSON 对象。")
            missing_fields = [
                field for field in REQUIRED_COMMENT_FIELDS if field not in comment
            ]
            if missing_fields:
                raise ValueError(
                    "增量评论缺少字段：" + ", ".join(missing_fields)
                )
            if comment.get("introduced_step") != step:
                raise ValueError("增量评论的 introduced_step 与所在批次 step 不一致。")
            comments.append(comment)

    return comments


def load_all_comments(
    event_id,
    current_step=None,
    comment_pool_file=COMMENT_POOL_FILE,
    history_file=INCREMENTAL_COMMENT_FILE,
):
    """合并初始评论和当前时间步已经生成的增量评论。"""
    comment_pool = load_comment_pool(comment_pool_file)
    if comment_pool.get("event_id") != event_id:
        raise ValueError("初始评论池与当前事件的 event_id 不一致。")

    comments = list(comment_pool["comments"])
    comments.extend(
        load_incremental_comments(event_id, current_step, history_file)
    )

    comment_ids = [comment.get("comment_id") for comment in comments]
    if len(comment_ids) != len(set(comment_ids)):
        raise ValueError("初始评论和增量评论中存在重复的 comment_id。")
    return comments


def get_comment_by_id(comments, comment_id):
    """根据 comment_id 查询评论；找不到时返回 None。"""
    if not isinstance(comments, list):
        raise ValueError("comments 必须是评论列表。")

    target_id = str(comment_id).strip()
    for comment in comments:
        if isinstance(comment, dict) and comment.get("comment_id") == target_id:
            return comment
    return None
