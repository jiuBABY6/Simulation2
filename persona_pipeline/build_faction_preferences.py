"""根据历史微博文本，计算每个 Agent 的评论派系偏好。"""

import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests
from pymongo import MongoClient

from build_personas import (
    CLASSIFICATION_BATCH_SIZE,
    DEEPSEEK_API_KEY,
    DEEPSEEK_ENDPOINT,
    DEEPSEEK_MODEL,
    MONGODB_DATABASE,
    MONGODB_URI,
    POSTS_COLLECTION,
    clean_weibo_text,
    iterate_post_records,
    normalize_user_id,
    should_skip_post,
)


# 主要功能：定义五种可选评论派系。
FACTIONS = (
    "观点输出派",
    "表态判断派",
    "情绪激进派",
    "矛盾激化派",
    "吃瓜派",
)

# 主要功能：定义每次 DeepSeek 请求处理的文本数量和单条文本最大长度。
BATCH_SIZE = CLASSIFICATION_BATCH_SIZE
MAX_TEXT_CHARS = 800

# 主要功能：定位已有 Persona 的输出目录和派系分类断点文件。
PERSONA_DIR = Path(__file__).resolve().parent.parent / "output" / "personas"
PROGRESS_PATH = PERSONA_DIR / "faction_classification_progress.json"


class DeepSeekBadRequestError(RuntimeError):
    """主要功能：保存 DeepSeek 返回的 400 请求错误信息。"""


class DeepSeekResponseFormatError(RuntimeError):
    """主要功能：保存 DeepSeek 返回内容无法解析为有效 JSON 的错误信息。"""


def show_progress(task_name, current, total):
    """主要功能：在终端显示派系分类任务的进度条。"""
    if total == 0:
        return
    bar_length = 30
    ratio = current / total
    filled_length = int(bar_length * ratio)
    progress_bar = "#" * filled_length + "-" * (bar_length - filled_length)
    print(
        f"\r{task_name} [{progress_bar}] {current}/{total} ({ratio:.1%})",
        end="",
        flush=True,
    )
    if current >= total:
        print()


def load_agent_files():
    """主要功能：读取已有 Agent Persona 文件，并按真实用户 ID 建立索引。"""
    agents = {}
    for agent_path in PERSONA_DIR.glob("agent_*.json"):
        with agent_path.open("r", encoding="utf-8") as file:
            agent = json.load(file)
        user_id = normalize_user_id(agent.get("source_user_id"))
        if user_id:
            agents[user_id] = {"path": agent_path, "data": agent}

    if not agents:
        raise RuntimeError(f"未在 {PERSONA_DIR} 找到 agent_*.json 文件。")
    return agents


def load_progress():
    """主要功能：读取已完成和已跳过的派系分类结果，用于断点续跑。"""
    if not PROGRESS_PATH.exists():
        return {"labels": {}, "skipped": {}}

    with PROGRESS_PATH.open("r", encoding="utf-8") as file:
        progress = json.load(file)

    labels = progress.get("labels", {})
    skipped = progress.get("skipped", {})
    if not isinstance(labels, dict) or not isinstance(skipped, dict):
        raise RuntimeError(f"派系断点文件格式错误：{PROGRESS_PATH}")

    valid_labels = {
        item_id: faction
        for item_id, faction in labels.items()
        if faction in FACTIONS
    }
    return {"labels": valid_labels, "skipped": skipped}


def save_progress(progress):
    """主要功能：原子写入派系分类中间结果，避免中断时损坏文件。"""
    PERSONA_DIR.mkdir(parents=True, exist_ok=True)
    temp_path = PROGRESS_PATH.with_suffix(".tmp")
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(progress, file, ensure_ascii=False, indent=2)
        file.write("\n")
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp_path, PROGRESS_PATH)


def collect_expression_items(agent_user_ids):
    """主要功能：读取目标 Agent 的微博，仅保留有实际正文的用户自身表达文本。"""
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=10_000)
    client.admin.command("ping")
    database = client[MONGODB_DATABASE]

    items_by_user = defaultdict(list)
    for raw_post in database[POSTS_COLLECTION].find({}):
        for post in iterate_post_records(raw_post):
            user_id = normalize_user_id(post.get("user_id"))
            if user_id not in agent_user_ids or should_skip_post(post):
                continue

            text = clean_weibo_text(post.get("text"))
            post_id = normalize_user_id(post.get("id"))
            if not post_id:
                post_id = f"row_{len(items_by_user[user_id])}"

            item = {
                "id": f"{user_id}:{post_id}:faction",
                "user_id": user_id,
                "text": text,
            }
            items_by_user[user_id].append(item)
    return items_by_user


class DeepSeekFactionClassifier:
    """主要功能：调用 DeepSeek，为微博文本标注五类派系之一。"""

    def classify_batch(self, items):
        """主要功能：批量请求 DeepSeek 并返回微博 ID 对应的派系标签。"""
        compact_items = [
            {"id": item["id"], "text": item["text"][:MAX_TEXT_CHARS]}
            for item in items
        ]
        prompt = f"""你是微博表达派系分类器。逐条分类，不要解释。

faction 只能是以下五类之一：
1. 观点输出派：输出明确的看法/态度/评价/质疑等，评论围绕事件本身展开，具备相对完整的论证或依据（即使论据不一定严谨）。
2. 表态判断派：输出明确的看法/态度/评价/质疑等，但缺乏具体依据或论证支撑，属于直觉式表态而非说理。不带强烈情绪色彩，也不针对群体挑起对立。
3. 情绪激进派：无事实或逻辑论证的观点/质疑，作为愤怒、同情、讽刺等情感的宣泄口。情绪浓度远高于论证内容，以情绪化措辞为主要表现形式，缺少具体理由或仅有简单归因。
4. 矛盾激化派：从性别、地域、阶级等角度挑起群体对立，策略性的放大群体差异。常通过反串、挑衅、扣帽子、地图炮、身份对立、断章取义、故意曲解他人观点等方式引发骂战。
5. 吃瓜派：无意深究的态度，无强立场，不为事件提供有效信息，不主动下结论。评论多使用谐音梗、反讽、网络梗或段子、emoji、隐喻调侃等。

只输出合法 JSON，严格使用以下结构：
{{"items":[{{"id":"原id","faction":"..."}}]}}

待分类微博：
{json.dumps(compact_items, ensure_ascii=False)}"""
        payload = {
            "model": DEEPSEEK_MODEL,
            "thinking": {"type": "disabled"},
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "max_tokens": 800,
            "messages": [
                {"role": "system", "content": "你只返回 JSON，不添加 Markdown。"},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json",
        }

        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(DEEPSEEK_ENDPOINT, headers=headers, json=payload, timeout=90)
                if response.status_code == 400:
                    try:
                        error_detail = json.dumps(response.json(), ensure_ascii=False)
                    except ValueError:
                        error_detail = response.text
                    raise DeepSeekBadRequestError(error_detail[:1000])
                response.raise_for_status()

                content = response.json()["choices"][0]["message"]["content"].strip()
                json_start = content.find("{")
                if json_start < 0:
                    raise ValueError("DeepSeek returned no JSON object.")
                parsed, _ = json.JSONDecoder().raw_decode(content[json_start:])
                if not isinstance(parsed, dict):
                    raise ValueError("The first JSON value returned by DeepSeek is not an object.")

                labels = {}
                for item in parsed.get("items", []):
                    item_id = str(item.get("id", ""))
                    faction = item.get("faction")
                    if item_id and faction in FACTIONS:
                        labels[item_id] = faction
                return labels
            except DeepSeekBadRequestError:
                raise
            except (requests.RequestException, KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
                last_error = error
                time.sleep(2**attempt)

        if isinstance(last_error, (KeyError, TypeError, ValueError, json.JSONDecodeError)):
            raise DeepSeekResponseFormatError(f"DeepSeek 返回内容无法解析：{last_error}")
        raise RuntimeError(f"DeepSeek 分类重试后仍失败：{last_error}")


def classify_items(items, progress):
    """主要功能：分类全部待处理微博，遇到异常批次时逐条定位并保存进度。"""
    pending = [
        item
        for item in items
        if item["id"] not in progress["labels"] and item["id"] not in progress["skipped"]
    ]
    completed_count = len(items) - len(pending)
    if completed_count:
        print(f"已从中间结果恢复 {completed_count} 条派系标签。")

    show_progress("派系分类", completed_count, len(items))
    classifier = DeepSeekFactionClassifier()
    for start in range(0, len(pending), BATCH_SIZE):
        batch = pending[start : start + BATCH_SIZE]
        try:
            labels = classifier.classify_batch(batch)
            for item in batch:
                faction = labels.get(item["id"])
                if faction:
                    progress["labels"][item["id"]] = faction
                else:
                    progress["skipped"][item["id"]] = "未返回有效派系标签"
        except (DeepSeekBadRequestError, DeepSeekResponseFormatError) as error:
            print(f"\n批次请求异常，开始逐条定位。错误信息：{error}")
            for item in batch:
                try:
                    labels = classifier.classify_batch([item])
                    faction = labels.get(item["id"])
                    if faction:
                        progress["labels"][item["id"]] = faction
                    else:
                        progress["skipped"][item["id"]] = "未返回有效派系标签"
                except (DeepSeekBadRequestError, DeepSeekResponseFormatError) as single_error:
                    print(f"\n已跳过异常微博：{item['id']}。错误信息：{single_error}")
                    progress["skipped"][item["id"]] = str(single_error)

        save_progress(progress)
        current_count = completed_count + min(start + len(batch), len(pending))
        show_progress("派系分类", current_count, len(items))


def update_agent_files(agents, items_by_user, progress):
    """主要功能：将每位 Agent 的五类派系概率写回对应 Persona 文件。"""
    for user_id, agent_info in agents.items():
        faction_counts = Counter()
        sample_count = 0
        for item in items_by_user.get(user_id, []):
            faction = progress["labels"].get(item["id"])
            if faction in FACTIONS:
                faction_counts[faction] += 1
                sample_count += 1

        denominator = sample_count + len(FACTIONS)
        faction_preference = {
            faction: round((faction_counts[faction] + 1) / denominator, 6)
            for faction in FACTIONS
        }

        agent = agent_info["data"]
        agent["comment_faction_preference"] = faction_preference
        data_info = agent.get("data_info", {})
        data_info["faction_sample_count"] = sample_count
        agent["data_info"] = data_info

        with agent_info["path"].open("w", encoding="utf-8") as file:
            json.dump(agent, file, ensure_ascii=False, indent=2)
            file.write("\n")


def main():
    """主要功能：计算全部已有 Agent 的评论派系概率并写入 Persona 文件。"""
    if MONGODB_DATABASE.startswith("REPLACE_WITH_"):
        raise RuntimeError("请先在 build_personas.py 中填写 MongoDB 数据库配置。")
    if DEEPSEEK_API_KEY.startswith("REPLACE_WITH_"):
        raise RuntimeError("请先在 build_personas.py 中填写 DeepSeek API Key。")

    agents = load_agent_files()
    items_by_user = collect_expression_items(set(agents))
    items = [item for user_items in items_by_user.values() for item in user_items]
    if not items:
        raise RuntimeError("未找到可用于派系分类的有效微博文本。")

    progress = load_progress()
    print(f"共需处理 {len(items)} 条有效用户表达文本。")
    classify_items(items, progress)
    update_agent_files(agents, items_by_user, progress)
    print(f"已更新 {len(agents)} 份 Agent Persona：{PERSONA_DIR}")
    print(f"派系分类中间结果：{PROGRESS_PATH}")


if __name__ == "__main__":
    main()
