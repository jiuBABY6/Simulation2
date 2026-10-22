"""根据 Persona 集合构建全局决策策略配置。"""

from __future__ import annotations

from collections.abc import Iterable


TOPICS = ("社会事件", "新闻时事", "娱乐", "其他")
ORIENTATIONS = ("fact", "opinion", "questioning")


def calculate_quantile(values: Iterable[float], quantile: float) -> float | None:
    """使用线性插值计算分位数，保持既有算法和输出精度。"""

    ordered = sorted(values)
    if not ordered:
        return None
    position = quantile * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def calculate_quantile_summary(values: Iterable[float]) -> dict:
    values = list(values)
    return {
        "p25": calculate_quantile(values, 0.25),
        "p50": calculate_quantile(values, 0.50),
        "p75": calculate_quantile(values, 0.75),
    }


def build_global_policy_config(personas: list[dict]) -> dict:
    """用全部 Persona 计算分位数与候选决策规则。"""

    topic_quantiles = {
        topic: calculate_quantile_summary(
            persona["topic_preference"][topic] for persona in personas
        )
        for topic in TOPICS
    }
    orientation_quantiles = {
        f"{orientation}_rate": calculate_quantile_summary(
            persona["information_orientation"][f"{orientation}_rate"]
            for persona in personas
        )
        for orientation in ORIENTATIONS
    }
    action_gaps = [
        abs(
            persona["action_preference"]["repost_preference"]
            - persona["action_preference"]["original_preference"]
        )
        for persona in personas
    ]
    return {
        "version": "policy_v0.1",
        "reference_population_size": len(personas),
        "band_definition": {
            "low": "value < p25",
            "medium": "p25 <= value < p75",
            "high": "value >= p75",
        },
        "topic_quantiles": topic_quantiles,
        "orientation_quantiles": orientation_quantiles,
        "action_preference_rule": {
            "strong_preference_gap": calculate_quantile(action_gaps, 0.75)
        },
        "candidate_rules": {
            "emotion": {
                "positive": ["neutral", "positive"],
                "neutral": ["neutral"],
                "negative": ["neutral", "negative"],
            },
            "official_statement": {
                "none": {"default": ["not_applicable"]},
                "clear": {"default": ["accept", "wait", "question"]},
                "incomplete": {
                    "default": ["accept", "wait", "question"]
                },
                "conflict": {"default": ["accept", "wait", "question"]},
            },
        },
    }
