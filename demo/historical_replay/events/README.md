# 历史趋势复现事件目录

每个子目录保存一个 `event_id` 的完整输入：

```text
events/<event_id>/
├── event_manifest.json
├── event_input.json
├── initial_opinion.json
├── public_context_timeline.json
├── official_response_timeline.json
└── real_trend_source.xlsx（可选）
```

## 文件职责

- `event_manifest.json`：事件名称和源文件信息；
- `event_input.json`：第一阶段已公开的事件信息和通用模拟参数；
- `initial_opinion.json`：第一轮人工情绪比例及整数评论配额；
- `public_context_timeline.json`：每轮当时可见的公众议题、已核实更新和建设性证据；
- `official_response_timeline.json`：阶段、时间范围和官方通告首次发布时间；
- `real_trend_source.xlsx`：只用于生成运行后对照曲线，不进入 Agent 决策。

## 数据约束

- JSON 的 `event_id` 必须与目录名一致；
- 三类初始评论配额之和必须等于初始评论总数；
- 公众语境必须覆盖全部轮次，并为每条信息提供来源引用；
- 公众语境不得包含正面率、中性率、负面率、观测分布或目标分布；
- 第2轮以后不得输入真实评论文本；
- 后续调查结论不能提前写入早期阶段；
- 不得为了贴合真实曲线重复发布同一官方通告或改写时间边界。

## 命令

```powershell
python demo\historical_replay\main.py --event-id <event_id>
python visualization\historical\real_data_processor.py --event-id <event_id>
```

第一条命令创建新的历史回放批次；第二条只在存在人工 Excel 时生成运行后的真实趋势对照。完整说明见 [`../../docs/HISTORICAL_REPLAY.md`](../../docs/HISTORICAL_REPLAY.md)。

## 当前事件与兼容边界

- 北国先天下当前可运行事件为`event_beiguo_xiantianxia_crash_20260920_002`，使用新数据的三阶段输入；
- 旧`event_beiguo_xiantianxia_crash_20260920_001`事件源已经退出运行入口；
- `visualization/data/real_trends`中的旧`001`趋势JSON以及引用它的旧实验批次继续只读保留，以保证历史结果仍可查看；
- 新运行、新测试和新文档不得再把`001`当作现行事件源。
