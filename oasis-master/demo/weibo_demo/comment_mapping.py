from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from .config import ScenarioConfig
from .models import GroupProfile


@dataclass(frozen=True)
class CommentMappingResult:
    total_comments: int
    group_counts: dict[str, int]
    examples: dict[str, list[str]]

    def to_dict(self) -> dict:
        return {
            "total_comments": self.total_comments,
            "group_counts": self.group_counts,
            "examples": self.examples,
        }


class KeywordCommentMapper:
    """可替换的基线分类器；生产版应改为语义聚类并进行人工抽检。"""

    def __init__(
        self,
        groups: tuple[GroupProfile, ...],
        fallback_group_id: str = "low_engagement",
        max_examples_per_group: int = 5,
    ) -> None:
        self.groups = groups
        self.fallback_group_id = fallback_group_id
        self.max_examples_per_group = max_examples_per_group
        if fallback_group_id not in {item.group_id for item in groups}:
            raise ValueError("fallback_group_id 必须存在于群体配置中。")

    def classify(self, text: str) -> str:
        normalized = text.strip().lower()
        scored = []
        for index, group in enumerate(self.groups):
            score = sum(
                1 for keyword in group.keywords if keyword.lower() in normalized
            )
            if score > 0:
                scored.append((score, -index, group.group_id))
        if not scored:
            return self.fallback_group_id
        return max(scored)[2]

    def map_jsonl(
        self,
        path: str | Path,
        *,
        text_field: str = "text",
    ) -> CommentMappingResult:
        counts = {group.group_id: 0 for group in self.groups}
        examples = {group.group_id: [] for group in self.groups}
        total = 0
        with Path(path).open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                record = json.loads(line)
                if text_field not in record:
                    raise ValueError(
                        f"评论文件第 {line_number} 行缺少字段 {text_field!r}。"
                    )
                text = str(record[text_field]).strip()
                if not text:
                    continue
                group_id = self.classify(text)
                counts[group_id] += 1
                total += 1
                if len(examples[group_id]) < self.max_examples_per_group:
                    examples[group_id].append(text)
        return CommentMappingResult(total, counts, examples)


def scenario_with_comment_populations(
    scenario: ScenarioConfig,
    result: CommentMappingResult,
) -> ScenarioConfig:
    """用评论计数替换群体规模；零样本群体保留 1 个占位权重。"""

    groups = tuple(
        replace(
            group,
            population_size=max(1, result.group_counts.get(group.group_id, 0)),
            data_source="comment_keyword_mapping",
        )
        for group in scenario.groups
    )
    updated = replace(scenario, groups=groups)
    updated.validate()
    return updated
