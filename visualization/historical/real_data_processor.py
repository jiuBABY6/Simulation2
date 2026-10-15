"""将人工整理的 Excel 群体趋势转换为可审计的展示 JSON。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

# 保留从项目根目录直接运行脚本的体验，同时让实现留在 historical 包内。
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from visualization.config import HISTORICAL_EVENTS_DIR
from visualization.historical.real_trend_repository import (
    get_active_event_id,
    normalize_event_id,
    real_trend_path,
)
from visualization.historical.xlsx_reader import read_sheet_rows


SENTIMENT_LABELS = {
    "negative": "负面",
    "neutral": "中性",
    "positive": "正面",
}


def _find_column(
    headers: dict[str, str], keyword: str, *, exact: bool = False
) -> str:
    for column, value in headers.items():
        if value.strip() == keyword:
            return column
    if exact:
        raise ValueError(f"真实数据缺少必需列：{keyword}")
    for column, value in headers.items():
        if keyword in value:
            return column
    raise ValueError(f"真实数据缺少必需列：{keyword}")


def _find_header_row(rows: list[dict[str, str]]) -> tuple[int, dict[str, str]]:
    """定位真实趋势表头，避免依赖固定的 Excel 行号。"""

    required_keywords = ("关键节点", "时间线", "社会情绪")
    for index, row in enumerate(rows):
        values = tuple(str(value) for value in row.values())
        has_required_keywords = all(
            any(keyword in value for value in values)
            for keyword in required_keywords
        )
        has_sampling_column = any(value.strip() == "当前" for value in values)
        if has_required_keywords and has_sampling_column:
            return index, row
    raise ValueError(
        "真实数据缺少可识别的表头：关键节点、时间线、当前、社会情绪"
    )


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


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _load_event_id(event_file: Path) -> str:
    if not event_file.is_file():
        raise ValueError(f"事件配置不存在：{event_file}")
    try:
        event_input = json.loads(event_file.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"无法读取事件配置 {event_file}：{error}") from error
    event_id = str(event_input.get("event_id") or "").strip()
    if not event_id:
        raise ValueError(f"事件配置缺少 event_id：{event_file}")
    return event_id


def _resolve_event_id(event_id: str | None, event_file: Path | None) -> str:
    configured_event_id = _load_event_id(event_file) if event_file else None
    explicit_event_id = str(event_id or "").strip() or None
    if (
        explicit_event_id
        and configured_event_id
        and explicit_event_id != configured_event_id
    ):
        raise ValueError(
            "参数 event_id 与事件配置不一致："
            f"{explicit_event_id} != {configured_event_id}"
        )
    resolved = explicit_event_id or configured_event_id
    if not resolved:
        raise ValueError("必须通过 --event-id 或 --event-file 提供 event_id")
    return resolved


def _build_real_trend_from_rows(
    rows: list[dict[str, str]],
    *,
    event_id: str,
    source_name: str,
    sheet_name: str,
) -> dict[str, object]:
    """从工作表行构建真实趋势；只接受有时间段和情绪估计的阶段行。"""

    if not event_id.strip():
        raise ValueError("event_id 不能为空")

    header_index, headers = _find_header_row(rows)
    phase_column = _find_column(headers, "关键节点")
    period_column = _find_column(headers, "时间线")
    sampling_column = _find_column(headers, "当前", exact=True)
    sentiment_column = _find_column(headers, "社会情绪")
    opinion_column = _find_column(headers, "网络当前舆论")

    stage_rows: list[tuple[int, dict[str, str]]] = []
    for row_index, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(str(value).strip() for value in row.values()):
            continue
        if not row.get(period_column, "").strip():
            continue
        if not row.get(sentiment_column, "").strip():
            continue
        stage_rows.append((row_index, row))

    if len(stage_rows) < 2:
        raise ValueError(
            f"真实数据至少需要 2 个有效阶段，当前只识别到 {len(stage_rows)} 个"
        )

    periods: list[dict[str, object]] = []
    last_phase = ""
    for step, (row_index, row) in enumerate(stage_rows, start=1):
        sentiment_text = row.get(sentiment_column, "")
        sentiments = {
            key: _extract_sentiment_estimate(sentiment_text, label)
            for key, label in SENTIMENT_LABELS.items()
        }
        if sentiments["negative"]["estimate"] is None:
            raise ValueError(
                f"Excel 第 {row_index} 行（阶段 {step}）缺少可识别的负面情绪比例"
            )

        phase = _compact_text(row.get(phase_column, ""))
        if phase:
            last_phase = phase
        else:
            phase = last_phase

        available_estimates = [
            item["estimate"]
            for item in sentiments.values()
            if item["estimate"] is not None
        ]
        periods.append(
            {
                "step": step,
                "period": _compact_text(row.get(period_column, "")),
                "phase": phase,
                "sampling_method": _compact_text(
                    row.get(sampling_column, "")
                ),
                "sentiment": sentiments,
                "estimate_sum": round(sum(available_estimates), 4),
                "group_summary": _shorten_text(sentiment_text),
                "public_opinion_summary": _shorten_text(
                    row.get(opinion_column, "")
                ),
                "source_row": row_index,
            }
        )

    first_data_row = stage_rows[0][0]
    last_data_row = stage_rows[-1][0]
    limitations = [
        "数据只能反映群体层面的阶段性变化，不能用于验证单个 Agent 的判断。",
        "数据来自人工整理和有限历史材料，不是完整平台样本或严格抽样结果。",
        "当前只对照可共同定义的情绪趋势，不把真实材料推导为接受率或质疑率。",
    ]
    if len(periods) == 2:
        limitations.append(
            "当前只有两个观测阶段，只能描述一次上升、下降或持平方向；"
            "差异指标仅供探索，不计算峰值轮次差或趋势拟合优度。"
        )

    return {
        "event_id": event_id,
        "data_type": "manual_group_trend_reference",
        "stage_count": len(periods),
        "source": {
            "file": source_name,
            "sheet": sheet_name,
            "range": f"A{first_data_row}:H{last_data_row}",
            "header_row": header_index + 1,
        },
        "scope": "人工整理材料中的群体舆情阶段变化",
        "methodology": [
            "动态读取表头之后所有同时包含时间段和社会情绪的非空阶段行。",
            "“关键节点”作为阶段名称，“当前”作为采样方法说明保存。",
            "保留材料中明确写出的约值和区间，不把人工判断视为精确抽样统计。",
            "区间仅为绘图生成中点，同时保留下限、上限和原始表达。",
            "“近乎为零”仅按展示值 0 处理，不代表统计意义上的绝对为零。",
            "各情绪比例不强制归一化，避免改写原材料中的人工估计。",
        ],
        "limitations": limitations,
        "periods": periods,
    }


# 2026/09/02 历史趋势可视化，新增功能：仅提取群体趋势估计并保留不确定性说明。
def build_real_trend(
    source_path: Path,
    event_id: str,
    sheet_name: str = "Sheet1",
    source_name: str | None = None,
) -> dict[str, object]:
    """读取人工整理表，生成动态阶段群体趋势参考，不推断个体态度。"""

    rows = read_sheet_rows(source_path, sheet_name)
    return _build_real_trend_from_rows(
        rows,
        event_id=event_id,
        source_name=source_name or source_path.name,
        sheet_name=sheet_name,
    )


def _source_display_name(event_dir: Path, source_path: Path) -> str:
    """从事件清单恢复原始Excel名称，保留来源可追溯性。"""

    manifest_path = event_dir / "event_manifest.json"
    archived_source = (event_dir / "real_trend_source.xlsx").resolve()
    if source_path.resolve() != archived_source or not manifest_path.is_file():
        return source_path.name
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return source_path.name
    if not isinstance(manifest, dict):
        return source_path.name
    return str(
        manifest.get("real_trend_source_original_name") or source_path.name
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="处理真实群体趋势 Excel")
    parser.add_argument(
        "--source",
        type=Path,
        help="真实趋势Excel；默认读取 events/<event_id>/real_trend_source.xlsx",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="输出路径；默认写入 data/real_trends/<event_id>.json",
    )
    parser.add_argument("--sheet", default="Sheet1")
    parser.add_argument("--event-id")
    parser.add_argument(
        "--event-file",
        type=Path,
        help="包含 event_id 的事件配置；默认读取对应事件目录中的文件",
    )
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    explicit_event_file = args.event_file.resolve() if args.event_file else None
    if args.event_id:
        requested_event_id = normalize_event_id(args.event_id)
    elif explicit_event_file:
        requested_event_id = _resolve_event_id(None, explicit_event_file)
    else:
        requested_event_id = get_active_event_id()
    event_dir = HISTORICAL_EVENTS_DIR / requested_event_id
    event_file = (
        explicit_event_file
        if explicit_event_file
        else (event_dir / "event_input.json").resolve()
    )
    event_id = _resolve_event_id(requested_event_id, event_file)
    source_path = (
        args.source.resolve()
        if args.source
        else (event_dir / "real_trend_source.xlsx").resolve()
    )
    output_path = (
        args.output.resolve() if args.output else real_trend_path(event_id)
    )
    result = build_real_trend(
        source_path,
        event_id=event_id,
        sheet_name=args.sheet,
        source_name=_source_display_name(event_dir, source_path),
    )
    content = json.dumps(result, ensure_ascii=False, indent=2)
    if args.stdout:
        print(content)
        return

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(f"{content}\n", encoding="utf-8")
    print(f"真实群体趋势已处理：{output_path.resolve()}")


if __name__ == "__main__":
    main()
