

from __future__ import annotations

import argparse
import html
import json
import os
import re
import time
from collections import Counter, defaultdict
from pathlib import Path

import requests
from pymongo import MongoClient


TOPICS = ("社会事件", "新闻时事", "娱乐", "其他")
ORIENTATIONS = ("fact", "opinion", "questioning")
EMOTIONS = ("positive", "neutral", "negative")
REPOST_PLACEHOLDERS = {"转发微博", "转发", "repost"}

# ---------------------------------------------------------------------------
# 项目配置
# ---------------------------------------------------------------------------
# 在这里填写数据库和 DeepSeek 配置后，可直接运行本脚本。
# 命令行参数仅用于临时覆盖默认配置。
MONGODB_URI = "mongodb://localhost:27017"
MONGODB_DATABASE = "weibo"
USERS_COLLECTION = "user"
POSTS_COLLECTION = "weibo"

DEEPSEEK_API_KEY = "API_key"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"

DEMO_USER_LIMIT = 16  # 设为 0 时处理 users 集合中的所有用户。
CLASSIFICATION_BATCH_SIZE = 10
MAX_TEXT_CHARS = 800
OUTPUT_DIR = "output/personas"


def clean_weibo_text(value):
    """主要功能：清洗微博文本，将空值与“转发微博”占位符视为无效文本。"""
    if not isinstance(value, str):
        return ""
    value = html.unescape(value)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if value.lower() in REPOST_PLACEHOLDERS:
        return ""
    return value


def get_nested_value(doc, *keys, default=None):
    # 主要功能：按照多层字段路径安全读取字典值。
    value = doc
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def extract_user_record(doc):
    """主要功能：兼容平铺用户文档与包含 wb.user 的嵌套文档。"""
    candidate = get_nested_value(doc, "wb", "user")
    if isinstance(candidate, dict):
        return candidate
    candidate = doc.get("user")
    if isinstance(candidate, dict) and "id" in candidate:
        return candidate
    return doc


def iterate_post_records(doc):
    """主要功能：兼容单条微博文档与 wb.weibo 列表存储结构。"""
    candidates = (get_nested_value(doc, "wb", "weibo"), doc.get("weibo"))
    for candidate in candidates:
        if isinstance(candidate, list):
            for post in candidate:
                if isinstance(post, dict):
                    yield post
            return
    yield doc


def normalize_user_id(value):
    # 主要功能：将用户 ID 统一转换为用于关联的字符串。
    return str(value).strip() if value is not None else ""


def split_post_texts(post):
    """主要功能：拆分主题分类文本、用户自身表达文本和转发标记。"""
    own_text = clean_weibo_text(post.get("text"))
    retweet = post.get("retweet")
    is_repost = isinstance(retweet, dict)

    if not is_repost:
        return own_text, own_text, False

    original_text = clean_weibo_text(retweet.get("text"))
    # 纯转发使用原微博正文判断主题；转发附言仍是用户自己的表达。
    content_text = original_text or own_text
    return content_text, own_text, True


def should_skip_post(post):
    """主要功能：判断微博正文为空或只是“转发微博”时，是否应整体跳过。"""
    return not clean_weibo_text(post.get("text"))


def calculate_quantile(values, q):
    # 主要功能：使用线性插值计算数值列表的分位数。
    if not values:
        return None
    ordered = sorted(values)
    position = q * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def calculate_rate(numerator, denominator):
    # 主要功能：计算比例并避免分母为零。
    return round(float(numerator) / denominator, 6) if denominator else 0.0



def show_progress(task_name, current, total):
    """主要功能：在终端显示当前任务的文本处理进度条。"""
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



def load_progress_records(progress_path):
    """主要功能：读取已保存的分类结果和已跳过微博，用于断点续跑。"""
    saved_labels = {}
    skipped_ids = set()
    if not progress_path.exists():
        return saved_labels, skipped_ids

    with progress_path.open("r", encoding="utf-8") as file:
        for line in file:
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            item_id = str(record.get("id", ""))
            if not item_id:
                continue
            if record.get("status") == "success" and isinstance(record.get("label"), dict):
                saved_labels[item_id] = record["label"]
            elif record.get("status") == "skipped":
                skipped_ids.add(item_id)
    return saved_labels, skipped_ids


def save_progress_records(progress_path, records):
    """主要功能：将一批分类结果立即追加写入文件，防止中断后丢失。"""
    if not records:
        return
    with progress_path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")
        file.flush()
        os.fsync(file.fileno())


class DeepSeekBadRequestError(RuntimeError):
    """主要功能：保存 DeepSeek 返回的 400 请求错误信息。"""


class DeepSeekResponseFormatError(RuntimeError):
    """主要功能：保存 DeepSeek 返回内容无法解析为有效 JSON 的错误信息。"""


class DeepSeekTextClassifier:
    def __init__(self, api_key, model, endpoint, batch_size, max_chars):
        # 主要功能：初始化 DeepSeek 文本分类客户端的连接参数。
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.batch_size = batch_size
        self.max_chars = max_chars

    def classify_batch_texts(self, items):
        # 主要功能：批量调用 DeepSeek，获取微博主题、表达方式和情绪标签。
        if not items:
            return {}
        compact_items = [
            {"id": item["id"], "text": item["text"][: self.max_chars]}
            for item in items
        ]
        prompt = f"""你是微博文本分类器。逐条分类，不要解释。

主题 topic 只能是：社会事件、新闻时事、娱乐、其他。
表达方式 orientation 只能是：fact、opinion、questioning。
情绪 emotion 只能是：positive、neutral、negative。

定义：
- fact：以转述事实、通报、报道或信息为主；
- opinion：以个人判断、评价、态度为主；
- questioning：以提问、求证、怀疑或要求说明为主。

只输出合法 JSON，严格使用以下结构：
{{"items":[{{"id":"原id","topic":"...","orientation":"...","emotion":"..."}}]}}

待分类微博：
{json.dumps(compact_items, ensure_ascii=False)}"""
        payload = {
            "model": self.model,
            "thinking": {
                "type": "disabled"
            },
            "temperature": 0,
            "response_format": {
                "type": "json_object"
            },
            "max_tokens": 800,
            "messages": [
                {"role": "system", "content": "你只返回 JSON，不添加 Markdown。"},
                {"role": "user", "content": prompt},
            ],
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        last_error = None
        for attempt in range(3):
            try:
                response = requests.post(self.endpoint, headers=headers, json=payload, timeout=90)
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
                    topic = item.get("topic")
                    orientation = item.get("orientation")
                    emotion = item.get("emotion")
                    if item_id and topic in TOPICS and orientation in ORIENTATIONS and emotion in EMOTIONS:
                        labels[item_id] = {
                            "topic": topic,
                            "orientation": orientation,
                            "emotion": emotion,
                        }
                return labels
            except DeepSeekBadRequestError:
                raise
            except (requests.RequestException, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                last_error = exc
                time.sleep(2**attempt)
        if isinstance(last_error, (KeyError, TypeError, ValueError, json.JSONDecodeError)):
            raise DeepSeekResponseFormatError(f"DeepSeek response cannot be parsed: {last_error}")
        raise RuntimeError(f"DeepSeek classification failed after retries: {last_error}")


def classify_all_texts(classifier, pending, task_name, progress_path, saved_labels, skipped_ids):
    """主要功能：分批分类文本，保存中间结果，并逐条处理返回 400 的异常微博。"""
    pending_ids = {item["id"] for item in pending}
    resolved = {item_id: saved_labels[item_id] for item_id in pending_ids if item_id in saved_labels}
    completed_ids = set(resolved) | (pending_ids & skipped_ids)
    pending = [item for item in pending if item["id"] not in completed_ids]
    completed_count = len(completed_ids)
    total_texts = completed_count + len(pending)

    if completed_count:
        print(f"\n{task_name} 已从中间结果恢复 {completed_count} 条。")
    show_progress(task_name, completed_count, total_texts)

    for start in range(0, len(pending), classifier.batch_size):
        batch = pending[start : start + classifier.batch_size]
        api_items = [{"id": item["id"], "text": item["text"]} for item in batch]
        progress_records = []
        try:
            result = classifier.classify_batch_texts(api_items)
            for item in batch:
                label = result.get(item["id"])
                if label:
                    resolved[item["id"]] = label
                    saved_labels[item["id"]] = label
                    progress_records.append({"id": item["id"], "status": "success", "label": label})
                else:
                    skipped_ids.add(item["id"])
                    progress_records.append({"id": item["id"], "status": "skipped", "reason": "未返回有效分类标签"})
        except (DeepSeekBadRequestError, DeepSeekResponseFormatError) as error:
            print(f"\n\u6279\u6b21\u8bf7\u6c42\u5f02\u5e38\uff0c\u5f00\u59cb\u9010\u6761\u5b9a\u4f4d\u3002\u9519\u8bef\u4fe1\u606f\uff1a{error}")
            for item in batch:
                try:
                    single_result = classifier.classify_batch_texts(
                        [{"id": item["id"], "text": item["text"]}]
                    )
                    label = single_result.get(item["id"])
                    if label:
                        resolved[item["id"]] = label
                        saved_labels[item["id"]] = label
                        progress_records.append({"id": item["id"], "status": "success", "label": label})
                    else:
                        skipped_ids.add(item["id"])
                        progress_records.append({"id": item["id"], "status": "skipped", "reason": "未返回有效分类标签"})
                except (DeepSeekBadRequestError, DeepSeekResponseFormatError) as single_error:
                    print(f"\n已跳过异常微博：{item['id']}。错误信息：{single_error}")
                    skipped_ids.add(item["id"])
                    progress_records.append({"id": item["id"], "status": "skipped", "reason": str(single_error)})

        save_progress_records(progress_path, progress_records)
        current_count = completed_count + min(start + len(batch), len(pending))
        show_progress(task_name, current_count, total_texts)
    return resolved


def build_user_persona(user, posts, content_labels, expression_labels):
    # 主要功能：根据单个用户的微博和分类标签聚合生成 Persona。
    user_id = normalize_user_id(user.get("id"))
    topic_counts = Counter()
    orientation_counts = Counter()
    emotion_counts = Counter()
    original_count = 0
    repost_count = 0
    content_sample_count = 0
    expression_sample_count = 0

    for post in posts:
        if should_skip_post(post):
            continue

        post_id = normalize_user_id(post.get("id"))
        content_text, expression_text, is_repost = split_post_texts(post)
        if is_repost:
            repost_count += 1
        else:
            original_count += 1

        content_id = f"{post_id}:content"
        if content_text and content_id in content_labels:
            topic_counts[content_labels[content_id]["topic"]] += 1
            content_sample_count += 1

        expression_id = f"{post_id}:expression"
        if expression_text and expression_id in expression_labels:
            label = expression_labels[expression_id]
            orientation_counts[label["orientation"]] += 1
            emotion_counts[label["emotion"]] += 1
            expression_sample_count += 1

    # 使用拉普拉斯平滑，避免小样本出现 0 或 1 的极端比例。
    topic_denominator = content_sample_count + len(TOPICS)
    expression_denominator = expression_sample_count + len(ORIENTATIONS)
    emotion_denominator = expression_sample_count + len(EMOTIONS)
    action_denominator = original_count + repost_count

    return {
        "agent_id": f"agent_{user_id}",
        "source_user_id": user_id,
        "identity": {
            "gender": user.get("gender", ""),
            "location": user.get("location", ""),
            "verified": bool(user.get("verified", False)),
            "followers_count": user.get("followers_count", 0),
        },
        "action_preference": {
            "original_preference": calculate_rate(original_count, action_denominator),
            "repost_preference": calculate_rate(repost_count, action_denominator),
        },
        "topic_preference": {
            topic: round((topic_counts[topic] + 1) / topic_denominator, 6)
            for topic in TOPICS
        },
        "information_orientation": {
            f"{orientation}_rate": round((orientation_counts[orientation] + 1) / expression_denominator, 6)
            for orientation in ORIENTATIONS
        },
        "emotion_expression": {
            f"{emotion}_rate": round((emotion_counts[emotion] + 1) / emotion_denominator, 6)
            for emotion in EMOTIONS
        },
        "data_info": {
            "total_posts": action_denominator,
            "topic_sample_count": content_sample_count,
            "expression_sample_count": expression_sample_count,
        },
    }


def calculate_quantile_summary(values):
    # 主要功能：计算一组数值的 P25、P50 和 P75。
    return {"p25": calculate_quantile(values, 0.25), "p50": calculate_quantile(values, 0.50), "p75": calculate_quantile(values, 0.75)}


def build_global_policy_config(personas):
    # 主要功能：使用所有 Persona 计算全局分位数与候选决策规则。
    topic_quantiles = {
        topic: calculate_quantile_summary([persona["topic_preference"][topic] for persona in personas])
        for topic in TOPICS
    }
    orientation_quantiles = {
        f"{orientation}_rate": calculate_quantile_summary(
            [persona["information_orientation"][f"{orientation}_rate"] for persona in personas]
        )
        for orientation in ORIENTATIONS
    }
    action_gaps = [
        abs(persona["action_preference"]["repost_preference"] - persona["action_preference"]["original_preference"])
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
                "none": {"default": ["wait"]},
                "clear": {"fact_high": ["accept", "wait"], "default": ["wait"]},
                "incomplete": {
                    "questioning_high_or_medium": ["wait", "question"],
                    "default": ["wait"],
                },
                "conflict": {"questioning_high": ["question"], "default": ["wait", "question"]},
            },
        },
    }


def main():
    # 主要功能：读取 MongoDB 数据、调用分类、输出 Persona 和全局策略配置。
    parser = argparse.ArgumentParser(description="从 MongoDB 读取微博数据，生成 Persona 和全局策略配置。")
    parser.add_argument("--mongo-uri", default=MONGODB_URI, help="临时覆盖 MONGODB_URI 配置")
    parser.add_argument("--database", default=MONGODB_DATABASE, help="临时覆盖 MONGODB_DATABASE 配置")
    parser.add_argument("--users-collection", default=USERS_COLLECTION)
    parser.add_argument("--posts-collection", default=POSTS_COLLECTION)
    parser.add_argument("--deepseek-api-key", default=DEEPSEEK_API_KEY, help="临时覆盖 DEEPSEEK_API_KEY 配置")
    parser.add_argument("--deepseek-model", default=DEEPSEEK_MODEL)
    parser.add_argument("--deepseek-endpoint", default=DEEPSEEK_ENDPOINT)
    parser.add_argument("--limit-users", type=int, default=DEMO_USER_LIMIT, help="首轮 Demo 处理的用户数量，0 表示所有用户")
    parser.add_argument("--batch-size", type=int, default=CLASSIFICATION_BATCH_SIZE)
    parser.add_argument("--max-text-chars", type=int, default=MAX_TEXT_CHARS)
    parser.add_argument("--output-dir", default=OUTPUT_DIR)
    args = parser.parse_args()

    if not args.mongo_uri or args.database.startswith("REPLACE_WITH_"):
        parser.error("请在脚本顶部填写 MONGODB_URI 和 MONGODB_DATABASE 后再运行。")
    if not args.deepseek_api_key or args.deepseek_api_key.startswith("REPLACE_WITH_"):
        parser.error("请在脚本顶部填写 DEEPSEEK_API_KEY 后再运行。")

    client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=10_000)
    client.admin.command("ping")
    database = client[args.database]

    users = []
    for raw_user in database[args.users_collection].find({}):
        payload = extract_user_record(raw_user)
        if normalize_user_id(payload.get("id")):
            users.append(payload)
        if args.limit_users and len(users) >= args.limit_users:
            break
    if not users:
        raise RuntimeError("未找到用户数据，请检查 users 集合和字段映射。")

    user_ids = {normalize_user_id(user["id"]) for user in users}
    posts_by_user = defaultdict(list)
    for raw_post in database[args.posts_collection].find({}):
        for post in iterate_post_records(raw_post):
            user_id = normalize_user_id(post.get("user_id"))
            if user_id in user_ids:
                posts_by_user[user_id].append(post)

    classifier = DeepSeekTextClassifier(
        api_key=args.deepseek_api_key,
        model=args.deepseek_model,
        endpoint=args.deepseek_endpoint,
        batch_size=args.batch_size,
        max_chars=args.max_text_chars,
    )

    content_pending = []
    expression_pending = []
    for user_id, posts in posts_by_user.items():
        for index, post in enumerate(posts):
            if should_skip_post(post):
                continue

            post_id = normalize_user_id(post.get("id")) or f"{user_id}:row:{index}"
            content_text, expression_text, _ = split_post_texts(post)
            if content_text:
                content_pending.append(
                    {
                        "id": f"{post_id}:content",
                        "post_id": post_id,
                        "kind": "content",
                        "text": content_text,
                    }
                )
            if expression_text:
                expression_pending.append(
                    {
                        "id": f"{post_id}:expression",
                        "post_id": post_id,
                        "kind": "expression",
                        "text": expression_text,
                    }
                )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = output_dir / "classification_progress.jsonl"
    saved_labels, skipped_ids = load_progress_records(progress_path)

    print(f"正在分类 {len(content_pending)} 条内容文本和 {len(expression_pending)} 条用户表达文本...")
    content_labels = classify_all_texts(
        classifier, content_pending, "内容文本分类", progress_path, saved_labels, skipped_ids
    )
    expression_labels = classify_all_texts(
        classifier, expression_pending, "用户表达文本分类", progress_path, saved_labels, skipped_ids
    )


    personas = [
        build_user_persona(user, posts_by_user[normalize_user_id(user["id"])], content_labels, expression_labels)
        for user in users
    ]
    for persona in personas:
        output_path = output_dir / f"{persona['agent_id']}.json"
        output_path.write_text(json.dumps(persona, ensure_ascii=False, indent=2), encoding="utf-8")

    policy_config = build_global_policy_config(personas)
    (output_dir / "policy_config.json").write_text(
        json.dumps(policy_config, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"已在 {output_dir.resolve()} 生成 {len(personas)} 份 Persona 和 policy_config.json。")


if __name__ == "__main__":
    main()
