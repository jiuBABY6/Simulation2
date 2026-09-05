# 早期触发原因与质量状态备忘

> **文档状态：已归档。** 本文是早期临时备忘，当前解释请阅读 [`../RUNBOOK.md`](../RUNBOOK.md)。

| `entry_reason` | 含义 | 当前触发条件 |
|---|---|---|
| `negative_threshold` | 负面率达到阈值 | `negative_rate >= 0.5` |
| `global_worsening` | 舆情趋势恶化 | `global_trend == "worsening"` |
| `stagnation` | 舆情连续没有明显改善 | 连续2个相邻轮次改善不超过 `0.05`，且趋势为 `stable` |


质量解析
| 状态 | 含义 |
|---|---|
| `normal` | LLM生成数量充足，兜底较少 |
| `degraded` | 实验完成，但历史兜底较多，结果需要谨慎解释 |
| `emergency` | 历史评论仍无法补齐，使用了本地应急评论，数据质量更低 |
