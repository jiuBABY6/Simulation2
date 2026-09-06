# 历史舆情趋势复现

本目录提供独立的历史趋势复现入口。它按照真实时间节点在指定轮次更新官方信息，只运行一条连续历史路线，不调用动态进场规则，也不运行五种内容策略对照。

## 运行方式

在项目根目录和原有 Conda 环境中运行：

```powershell
python demo\historical_replay\main.py
```

## 输入文件

- `event_input.json`：只保存事件第一阶段已经公开的信息，不能提前写入后续调查结论。
- `official_response_timeline.json`：保存时间步与现实时间段的对应关系，以及指定轮次首次投入的官方信息。
- `official.md`：人工保存的官方通告原始材料，仅作为配置时间线时的参考，不由程序自动读取。
- `example.xlsx`：人工整理的真实舆情阶段变化，供 `visualization/real_data_processor.py` 处理和对照展示。

没有新通告的轮次会继续沿用最近一次声明。为保持现有状态结构不变，后续声明应在突出本轮新增信息的同时，简要保留此前已经确认的官方事实。

## 输出位置

每次运行都会在 `demo/experiments` 下创建不可覆盖的新批次，主要文件包括：

```text
event_input.json
official_response_timeline.json
comment_pool.json
historical_replay_result.json
historical_replay/state/
```

`historical_replay_result.json` 按轮保存模拟指标、传播指标、现实时间段、官方信息首次投入轮次和评论数据质量；`historical_replay/state/propagation_history.jsonl`保存邻居传播明细。两类数据均可与人工整理的真实舆情阶段记录进行对照。

## 隔离边界

- 不修改或调用原有五策略入口 `demo/main.py`。
- 不读取 `official_response_options.json`。
- 复用现有评论生成、Agent决策、状态管理和指标计算模块。
- 历史复现失败只会影响本次新建批次，不会修改既有实验数据。
