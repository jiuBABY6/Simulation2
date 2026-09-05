"""提供最小化的 JSON 和 JSONL 文件存储功能。"""

import json
from pathlib import Path


def load_json(file_path):
    """读取 UTF-8 编码的 JSON 文件。"""
    with Path(file_path).open("r", encoding="utf-8") as file:
        return json.load(file)


def save_json(file_path, data):
    """以易读格式保存 JSON 文件，并自动创建父目录。"""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def append_jsonl(file_path, record):
    """向 JSONL 文件追加一条记录。"""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_jsonl_many(file_path, records):
    """向 JSONL 文件连续追加多条记录。"""
    path = Path(file_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False) + "\n")


def read_jsonl(file_path):
    """读取 JSONL 文件，自动跳过空行和损坏行。"""
    path = Path(file_path)
    if not path.exists():
        return []

    records = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"跳过损坏的 JSONL 第 {line_number} 行：{path}")
    return records


# 2026/08/22 系统重置与状态初始化 新增功能：严格校验JSONL并报告损坏文件的具体行号。
def validate_jsonl(file_path):
    """严格检查JSONL文件；文件缺失或某一行损坏时直接抛出异常。"""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"JSONL 文件不存在：{path}")

    record_count = 0
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(
                    f"JSONL 文件 {path.name} 第 {line_number} 行不是合法 JSON。"
                ) from error
            if not isinstance(record, dict):
                raise ValueError(
                    f"JSONL 文件 {path.name} 第 {line_number} 行必须是 JSON 对象。"
                )
            record_count += 1
    return record_count
