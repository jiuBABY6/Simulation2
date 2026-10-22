"""使用现有有效 Persona 原子重建全局策略配置。"""

import json
import shutil
from datetime import datetime
from pathlib import Path

if __package__:
    from .emotion import build_emotion_quantiles, EMOTION_FIELDS
    from .policy_builder import build_global_policy_config
else:  # pragma: no cover - 保留既有直接脚本命令
    from emotion import build_emotion_quantiles, EMOTION_FIELDS
    from policy_builder import build_global_policy_config


PROJECT_DIR = Path(__file__).resolve().parent.parent
PERSONA_DIR = PROJECT_DIR / "output" / "personas"
POLICY_PATH = PERSONA_DIR / "policy_config.json"


def main():
    personas = []

    for path in sorted(PERSONA_DIR.glob("agent_*.json")):
        persona = json.loads(path.read_text(encoding="utf-8"))

        total_posts = persona.get("data_info", {}).get("total_posts", 0)
        if not isinstance(total_posts, int) or total_posts <= 0:
            print(f"跳过无有效微博的 Persona：{path.name}")
            continue

        personas.append(persona)

    if not personas:
        raise RuntimeError("没有找到有效 Persona。")

    # 重新计算主题、信息取向、行动偏好和参考人数
    policy_config = build_global_policy_config(personas)

    # 重新计算情绪分位数
    emotion_values = {
        field: [
            float(persona["emotion_expression"][field])
            for persona in personas
        ]
        for field in EMOTION_FIELDS
    }
    policy_config["emotion_quantiles"] = build_emotion_quantiles(
        emotion_values
    )

    # 备份旧配置
    if POLICY_PATH.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = POLICY_PATH.with_name(
            f"policy_config.backup_{timestamp}.json"
        )
        shutil.copy2(POLICY_PATH, backup_path)
        print(f"旧配置已备份：{backup_path}")

    # 原子替换，避免写入中断损坏正式文件
    temporary_path = POLICY_PATH.with_suffix(".json.tmp")
    temporary_path.write_text(
        json.dumps(policy_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(POLICY_PATH)

    print(
        f"已使用 {len(personas)} 份有效 Persona "
        f"重新生成：{POLICY_PATH}"
    )


if __name__ == "__main__":
    main()
