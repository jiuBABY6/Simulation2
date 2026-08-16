"""读取 Persona 文件，计算情绪表达比例的全局分位数。"""

import json
from pathlib import Path


# 主要功能：定位当前项目实际使用的 Persona 输出目录。
PERSONA_DIR = Path(__file__).resolve().parent.parent / "output" / "personas"
POLICY_CONFIG_PATH = PERSONA_DIR / "policy_config.json"
EMOTION_FIELDS = ("positive_rate", "neutral_rate", "negative_rate")


def calculate_quantile(values, quantile):
    """主要功能：使用线性插值计算一组数值的分位数。"""
    if not values:
        return None
    ordered_values = sorted(values)
    position = quantile * (len(ordered_values) - 1)
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(ordered_values) - 1)
    fraction = position - lower_index
    return round(
        ordered_values[lower_index] + (ordered_values[upper_index] - ordered_values[lower_index]) * fraction,
        6,
    )


def read_persona_emotions():
    """主要功能：读取每个 Agent Persona 中的三项个人情绪表达比例。"""
    emotion_values = {field: [] for field in EMOTION_FIELDS}

    for persona_path in PERSONA_DIR.glob("agent_*.json"):
        with persona_path.open("r", encoding="utf-8") as file:
            persona = json.load(file)

        emotions = persona.get("emotion_expression", {})
        if not all(isinstance(emotions.get(field), (int, float)) for field in EMOTION_FIELDS):
            print(f"跳过情绪字段不完整的 Persona：{persona_path.name}")
            continue

        for field in EMOTION_FIELDS:
            emotion_values[field].append(float(emotions[field]))

    return emotion_values


def build_emotion_quantiles(emotion_values):
    """主要功能：分别计算正面、中性、负面情绪比例的 P25、P50、P75。"""
    return {
        field: {
            "p25": calculate_quantile(values, 0.25),
            "p50": calculate_quantile(values, 0.50),
            "p75": calculate_quantile(values, 0.75),
        }
        for field, values in emotion_values.items()
    }


def main():
    """主要功能：计算情绪分位数，并更新全局策略配置文件。"""
    if not PERSONA_DIR.exists():
        raise RuntimeError(f"未找到 Persona 输出目录：{PERSONA_DIR}")
    if not POLICY_CONFIG_PATH.exists():
        raise RuntimeError(f"未找到全局策略配置文件：{POLICY_CONFIG_PATH}")

    emotion_values = read_persona_emotions()
    persona_count = len(emotion_values["positive_rate"])
    if persona_count == 0:
        raise RuntimeError("未读取到包含完整情绪字段的 Persona 文件。")

    with POLICY_CONFIG_PATH.open("r", encoding="utf-8") as file:
        policy_config = json.load(file)

    emotion_quantiles = build_emotion_quantiles(emotion_values)
    updated_policy_config = {}
    for key, value in policy_config.items():
        if key == "emotion_quantiles":
            continue
        updated_policy_config[key] = value
        if key == "orientation_quantiles":
            updated_policy_config["emotion_quantiles"] = emotion_quantiles

    if "emotion_quantiles" not in updated_policy_config:
        updated_policy_config["emotion_quantiles"] = emotion_quantiles

    with POLICY_CONFIG_PATH.open("w", encoding="utf-8") as file:
        json.dump(updated_policy_config, file, ensure_ascii=False, indent=2)
        file.write("\n")

    print(f"已使用 {persona_count} 份 Persona 更新情绪分位数：{POLICY_CONFIG_PATH}")


if __name__ == "__main__":
    main()
