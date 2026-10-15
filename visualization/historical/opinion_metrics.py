"""历史复现专用：评论舆情口径计算。

本模块只接受已经读取的评论，不访问实验目录。当前轮、累计和滚动活跃口径
在同一处计算，避免后端比较与前端展示使用不同分母。
"""

from __future__ import annotations

from typing import Any, Iterable


COMMENT_EMOTIONS = ("positive", "neutral", "negative")


# 2026/10/9，新增功能：统一评论分布分母为具有合法三分类标签的评论数。
def calculate_comment_distribution(
    comments: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """计算评论三分类分布，并明确总量、有效量和未分类量。"""

    comment_list = list(comments)
    counts = {
        emotion: sum(
            1 for item in comment_list if item.get("emotion") == emotion
        )
        for emotion in COMMENT_EMOTIONS
    }
    classified_count = sum(counts.values())
    return {
        "comment_count": len(comment_list),
        "classified_count": classified_count,
        "unclassified_count": len(comment_list) - classified_count,
        "distribution": {
            emotion: {
                "count": counts[emotion],
                "rate": (
                    round(counts[emotion] / classified_count, 6)
                    if classified_count
                    else None
                ),
            }
            for emotion in COMMENT_EMOTIONS
        },
    }


def calculate_active_comment_distribution(
    round_comment_groups: list[list[dict[str, Any]]],
    window_size: int,
) -> dict[str, Any]:
    """按最近若干轮评论计算滚动活跃舆情，不使用未来轮次。"""

    if (
        isinstance(window_size, bool)
        or not isinstance(window_size, int)
        or window_size < 1
    ):
        raise ValueError("活跃舆情窗口必须是正整数。")
    selected_groups = round_comment_groups[-window_size:]
    active_comments = [
        comment for group in selected_groups for comment in group
    ]
    distribution = calculate_comment_distribution(active_comments)
    distribution.update(
        {
            "window_size": window_size,
            "included_round_count": len(selected_groups),
            "method": "rolling_round_window",
        }
    )
    return distribution
