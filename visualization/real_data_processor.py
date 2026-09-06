"""将人工整理的 Excel 群体趋势转换为可审计的展示 JSON。"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from config import REAL_DATA_PATH, REAL_SOURCE_PATH
from xlsx_reader import read_sheet_rows


SENTIMENT_LABELS = {
    "negative": "负面",
    "neutral": "中性",
    "positive": "正面",
}


def _find_column(headers: dict[str, str], keyword: str) -> str:
    for column, value in headers.items():
        if keyword in value:
            return column
    raise ValueError(f"真实数据缺少必需列：{keyword}")


def _extract_sentiment_estimate(text: str, label: str) -> dict[str, object]:
    range_match = re.search(
        rf"{label}[^\n]{{0,40}}?(\d+(?:\.\d+)?)\s*%\s*[-—~至]\s*(\d+(?:\.\d+)?)\s*%",
        text,
    )
    if range_match:
        lower = float(range_match.group(1)) / 100
        upper = float(range_match.group(2)) / 100
        return {
            "lower": lower,
            "upper": upper,
            "estimate": round((lower + upper) / 2, 4),
            "method": "range_midpoint",
            "source_expression": range_match.group(0).strip(),
        }

    exact_match = re.search(
        rf"{label}[^\n]{{0,40}}?(\d+(?:\.\d+)?)\s*%", text
    )
    if exact_match:
        value = float(exact_match.group(1)) / 100
        return {
            "lower": value,
            "upper": value,
            "estimate": value,
            "method": "stated_approximation",
            "source_expression": exact_match.group(0).strip(),
        }

    near_zero_match = re.search(rf"{label}[^\n]{{0,40}}?近乎为零", text)
    if near_zero_match:
        return {
            "lower": 0.0,
            "upper": None,
            "estimate": 0.0,
            "method": "qualitative_near_zero",
            "source_expression": near_zero_match.group(0).strip(),
        }

    return {
        "lower": None,
        "upper": None,
        "estimate": None,
        "method": "not_available",
        "source_expression": "",
    }


def _shorten_text(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if len(compact) <= limit:
        return compact
    return f"{compact[:limit].rstrip()}……"


# 2026/09/02 历史趋势可视化，新增功能：仅提取群体趋势估计并保留不确定性说明。
def build_real_trend(source_path: Path) -> dict[str, object]:
    """读取人工整理表，生成八阶段群体趋势参考，不推断个体级态度。"""

    rows = read_sheet_rows(source_path, "Sheet1")
    if len(rows) < 10:
        raise ValueError("真实数据应至少包含表头和八个阶段")

    headers = rows[1]
    period_column = _find_column(headers, "时间线")
    phase_column = _find_column(headers, "当前")
    sentiment_column = _find_column(headers, "社会情绪")
    opinion_column = _find_column(headers, "网络当前舆论")

    periods: list[dict[str, object]] = []
    for step, row in enumerate(rows[2:10], start=1):
        sentiment_text = row.get(sentiment_column, "")
        sentiments = {
            key: _extract_sentiment_estimate(sentiment_text, label)
            for key, label in SENTIMENT_LABELS.items()
        }
        if sentiments["negative"]["estimate"] is None:
            raise ValueError(f"第 {step} 阶段缺少可识别的负面情绪比例")

        available_estimates = [
            item["estimate"]
            for item in sentiments.values()
            if item["estimate"] is not None
        ]
        periods.append(
            {
                "step": step,
                "period": row.get(period_column, ""),
                "phase": _shorten_text(row.get(phase_column, ""), 60),
                "sentiment": sentiments,
                "estimate_sum": round(sum(available_estimates), 4),
                "group_summary": _shorten_text(sentiment_text),
                "public_opinion_summary": _shorten_text(
                    row.get(opinion_column, "")
                ),
            }
        )

    return {
        "event_id": "event_huxinyu_2022_001",
        "data_type": "manual_group_trend_reference",
        "source": {
            "file": source_path.name,
            "sheet": "Sheet1",
            "range": "B3:H10",
        },
        "scope": "人工整理材料中的群体舆情阶段变化",
        "methodology": [
            "保留材料中明确写出的约值和区间，不把人工判断视为精确抽样统计。",
            "区间仅为绘图生成中点，同时保留下限、上限和原始表达。",
            "“近乎为零”仅按展示值 0 处理，不代表统计意义上的绝对为零。",
            "各情绪比例不强制归一化，避免改写原材料中的人工估计。",
        ],
        "limitations": [
            "数据只能反映群体层面的阶段性变化，不能用于验证单个 Agent 的判断。",
            "数据来自人工整理和有限历史材料，不是完整平台样本或严格抽样结果。",
            "当前只对照可共同定义的情绪趋势，不把真实材料推导为接受率或质疑率。",
        ],
        "periods": periods,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="处理真实群体趋势 Excel")
    parser.add_argument("--source", type=Path, default=REAL_SOURCE_PATH)
    parser.add_argument("--output", type=Path, default=REAL_DATA_PATH)
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    result = build_real_trend(args.source.resolve())
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.stdout:
        print(content)
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(f"{content}\n", encoding="utf-8")
    print(f"真实群体趋势已处理：{args.output.resolve()}")


if __name__ == "__main__":
    main()
