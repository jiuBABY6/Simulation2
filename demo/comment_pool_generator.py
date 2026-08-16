"""根据事件直接生成覆盖型候选评论池。

评论池不再依赖 QLoRA 或其他微调模型。默认调用 DeepSeek 一次生成多样化候选，
并要求覆盖五类评论派系、三种情绪和三种信息取向。API 不可用时提供一个
可运行的模板兜底池，便于先验证整个决策流程。
"""

import argparse
import json
from pathlib import Path

from event_context import validate_event_input
from json_storage import load_json, save_json
from llm_service import call_deepseek_json
from project_config import (
    COMMENT_POOL_FILE,
    COMMENT_POOL_MAX_TOKENS,
    COMMENT_POOL_SIZE,
    COMMENT_POOL_TEMPERATURE,
    EVENT_FILE,
)


FACTIONS = [
    "观点输出派",
    "表态判断派",
    "情绪激进派",
    "矛盾激化派",
    "吃瓜派",
]
EMOTIONS = ["positive", "neutral", "negative"]
ORIENTATIONS = ["fact", "opinion", "questioning"]


def build_comment_pool_prompt(event_input, pool_size):
    """构造评论池生成提示词，明确要求覆盖不同组合。"""
    return f"""
你是社会舆情模拟系统的候选评论生成器。
请根据下面的事件生成 {pool_size} 条互不重复、自然、符合中文社交平台表达习惯的候选评论。
评论只围绕给定事件，不得编造事件中没有出现的具体事实、人物或数字。

事件：
{json.dumps(event_input, ensure_ascii=False, indent=2)}

覆盖要求：
1. 尽量均衡覆盖以下五类派系：{FACTIONS}
2. 尽量覆盖以下三类情绪：{EMOTIONS}
3. 尽量覆盖以下三类信息取向：{ORIENTATIONS}
4. 评论长度控制在 15 到 80 个汉字。
5. 不输出违法、仇恨、歧视、个人隐私或未经事件提供的事实指控。

只返回一个 JSON 对象，格式如下：
{{
  "candidates": [
    {{
      "comment_id": "comment_001",
      "text": "评论文本",
      "topic": "事件主题",
      "emotion": "positive|neutral|negative",
      "faction": "五类派系之一",
      "orientation": "fact|opinion|questioning"
    }}
  ]
}}
""".strip()


def normalize_candidates(raw_data, event_input):
    """校验并规范模型返回的候选评论字段。"""
    raw_candidates = raw_data.get("candidates", [])
    if not isinstance(raw_candidates, list):
        raise ValueError("评论池的 candidates 必须是列表。")

    topic = event_input.get("event_labels", {}).get("topic", "其他")
    candidates = []
    for index, item in enumerate(raw_candidates, start=1):
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "")).strip()
        faction = item.get("faction")
        emotion = item.get("emotion")
        orientation = item.get("orientation")
        if not text or faction not in FACTIONS:
            continue
        if emotion not in EMOTIONS:
            emotion = "neutral"
        if orientation not in ORIENTATIONS:
            orientation = "opinion"
        candidates.append(
            {
                "comment_id": f"comment_{index:03d}",
                "text": text,
                "topic": item.get("topic") or topic,
                "emotion": emotion,
                "faction": faction,
                "orientation": orientation,
            }
        )

    if not candidates:
        raise ValueError("模型没有返回可用的候选评论。")
    return candidates


def build_template_comment_pool(event_input, pool_size=COMMENT_POOL_SIZE):
    """生成不依赖网络的基础评论池，用于 API 失败时继续运行 Demo。"""
    topic = event_input.get("event_labels", {}).get("topic", "其他")
    content = event_input.get("event_content", "该事件")
    short_content = content[:35]
    templates = [
        ("观点输出派", "negative", "fact", f"关于{short_content}，建议尽快公开核查依据和后续处理进展。"),
        ("观点输出派", "neutral", "fact", f"这件事的关键还是事实链条，期待看到完整、可核验的信息。"),
        ("观点输出派", "positive", "fact", f"如果后续信息透明、处置及时，公众对{topic}的信任有机会恢复。"),
        ("表态判断派", "negative", "opinion", f"这事确实让人不舒服，希望相关方面认真对待。"),
        ("表态判断派", "neutral", "opinion", "目前先看后续通报，再决定怎么判断吧。"),
        ("表态判断派", "positive", "opinion", "希望最后能有一个让大家信服的结果。"),
        ("情绪激进派", "negative", "opinion", f"看到{short_content}真的很生气，不能就这样算了。"),
        ("情绪激进派", "neutral", "opinion", "信息越看越乱，心里多少有点焦虑。"),
        ("情绪激进派", "positive", "opinion", "希望别再互相指责了，大家都先冷静下来。"),
        ("矛盾激化派", "negative", "questioning", "为什么每次都要把责任推给某一类人？就不能正面回应吗？"),
        ("矛盾激化派", "neutral", "questioning", "又开始给人贴标签了，真正的问题反而没人讨论。"),
        ("矛盾激化派", "positive", "questioning", "别拿地域和身份制造对立，先把事实说清楚。"),
        ("吃瓜派", "negative", "opinion", "先吃瓜，等一个后续。"),
        ("吃瓜派", "neutral", "opinion", "信息量有点大，搬个小板凳看后续。"),
        ("吃瓜派", "positive", "opinion", "希望最后能平稳解决，散了散了。"),
    ]

    candidates = []
    index = 1
    while len(candidates) < pool_size:
        for faction, emotion, orientation, text in templates:
            if len(candidates) >= pool_size:
                break
            suffix = "" if index <= len(templates) else f"（第{index}条）"
            candidates.append(
                {
                    "comment_id": f"comment_{index:03d}",
                    "text": text + suffix,
                    "topic": topic,
                    "emotion": emotion,
                    "faction": faction,
                    "orientation": orientation,
                }
            )
            index += 1
    return candidates


def generate_comment_pool(event_input, pool_size=COMMENT_POOL_SIZE, allow_fallback=True):
    """根据事件生成候选评论池，优先使用 DeepSeek，必要时使用模板兜底。"""
    validate_event_input(event_input)
    prompt = build_comment_pool_prompt(event_input, pool_size)
    try:
        raw_data = call_deepseek_json(
            prompt,
            "你必须只返回合法 JSON，不要输出 Markdown 或额外说明。",
            temperature=COMMENT_POOL_TEMPERATURE,
            max_tokens=COMMENT_POOL_MAX_TOKENS,
        )
        candidates = normalize_candidates(raw_data, event_input)
        return {
            "event_id": event_input["event_id"],
            "generation_method": "deepseek_event_generation",
            "requested_size": pool_size,
            "candidates": candidates,
        }
    except Exception as error:
        if not allow_fallback:
            raise
        print(f"评论池大模型生成失败，使用模板兜底：{error}")
        return {
            "event_id": event_input["event_id"],
            "generation_method": "local_template_fallback",
            "requested_size": pool_size,
            "candidates": build_template_comment_pool(event_input, pool_size),
        }


def generate_and_save_comment_pool(event_file=EVENT_FILE, output_file=COMMENT_POOL_FILE):
    """读取事件文件、生成评论池并保存。"""
    event_input = load_json(event_file)
    pool = generate_comment_pool(event_input)
    save_json(output_file, pool)
    return pool


def load_or_generate_comment_pool(
    event_input,
    comment_pool_file=COMMENT_POOL_FILE,
    force_regenerate=False,
):
    """读取与当前事件匹配的评论池，不存在或要求重建时自动生成并保存。"""
    comment_pool_file = Path(comment_pool_file)
    if comment_pool_file.exists() and not force_regenerate:
        pool = load_json(comment_pool_file)
        if pool.get("event_id") == event_input.get("event_id"):
            return pool.get("candidates", [])

    pool = generate_comment_pool(event_input)
    save_json(comment_pool_file, pool)
    return pool["candidates"]


def main():
    """提供命令行入口，支持直接指定事件 JSON 文件。"""
    parser = argparse.ArgumentParser(description="根据事件生成覆盖型候选评论池")
    parser.add_argument("--event-file", default=str(EVENT_FILE), help="事件 JSON 文件路径")
    parser.add_argument("--output-file", default=str(COMMENT_POOL_FILE), help="评论池输出路径")
    parser.add_argument("--regenerate", action="store_true", help="忽略旧评论池并重新生成")
    args = parser.parse_args()
    if args.regenerate:
        event_input = load_json(args.event_file)
        pool = generate_comment_pool(event_input)
        save_json(args.output_file, pool)
    else:
        pool = generate_and_save_comment_pool(args.event_file, args.output_file)
    print(f"评论池生成完成，共 {len(pool['candidates'])} 条。")
    print(f"输出文件：{args.output_file}")


if __name__ == "__main__":
    main()
