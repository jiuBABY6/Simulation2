# 仿真核心审查报告

> **文档状态：已归档。** 本文是早期阶段性审查，其中传播、指标、多轮模拟和策略实验等缺失项已经完成。当前状态请阅读 [`../PROJECT_STATUS.md`](../PROJECT_STATUS.md)。

## 1. 审查范围

本次审查覆盖 `demo` 目录下的 Python 模块、事件输入、Persona 输入、评论池、Agent 状态文件和结果文件，重点检查：

```text
事件输入 → 候选评论池 → Agent 决策 → 状态保存 → 评论传播
→ 舆情指标 → 事件状态更新 → 下一轮模拟
```

## 2. 已完成部分

| 功能 | 文件 | 状态 |
|---|---|---|
| 事件读取和编号校验 | `event_context.py` | 已实现 |
| Persona 批量读取 | `persona_repository.py` | 已实现 |
| 根据事件生成候选评论池 | `comment_pool_generator.py` | 已实现 |
| DeepSeek JSON 调用 | `llm_service.py` | 已实现 |
| 情绪、官方态度、评论派系决策 | `decision_engine.py` | 已实现 |
| 单 Agent LLM 决策 | `agent_decision_llm_demo.py` | 已实现 |
| 多 Agent 并发决策 | `batch_agent_decision.py` | 已实现单轮版本 |
| Agent 最近状态和历史摘要 | `agent_state_store.py` | 已实现 |
| JSON、JSONL 存储 | `json_storage.py` | 已实现 |
| 事件动态状态基础更新 | `event_state_updater.py` | 已实现规则版，可选接入声明分类回调 |

Agent 状态主要写入：

```text
demo/state/agent_state_history.jsonl
```

## 3. 尚未完成部分

以下模块目前仍会抛出 `NotImplementedError`，因此完整多轮仿真暂时不能运行：

| 功能 | 文件 | 缺失内容 |
|---|---|---|
| 公共黑板和评论可见性 | `propagation.py` | 黑板构建、随机可见、互动记录 |
| 单轮舆情指标 | `metrics.py` | 情绪、官方态度、派系和传播指标 |
| 多轮流程编排 | `simulation_runner.py` | 单轮调用、多轮循环、断点保存 |
| 官方策略实验 | `experiment_runner.py` | 场景组合、重复实验、结果比较 |

## 4. 当前可运行边界

当前可以运行：

```text
事件文件 → 生成或读取评论池 → 单个 Agent 决策
事件文件 → 生成或读取评论池 → 多 Agent 并发决策 → 保存决策和状态
```

当前不能完整运行：

```text
多轮传播 → 指标统计 → 事件状态自动变化 → 下一轮决策 → 官方策略实验
```

## 5. 设计结论

1. `Persona` 是长期稳定输入，不应在每轮被覆盖。
2. `agent_state_history.jsonl` 保存 Agent 跨轮动态状态，不应与 Persona 混合。
3. `event_example.json` 保存固定事件信息，`state/event_state_history.json` 保存动态事件信息。
4. 所有 Agent 必须使用同一份 `event_state(t)` 完成本轮决策。
5. 所有 Agent 决策完成后，才能执行评论传播和互动。
6. 传播和指标统计完成后，才能生成 `event_state(t+1)`。
7. 只有 `simulation_runner.py` 负责编排多轮流程，业务模块不应复制彼此逻辑。

## 6. 建议开发优先级

1. 实现 `propagation.py`；
2. 实现 `metrics.py`；
3. 将 `event_state_updater.py` 接入真实的本轮指标和互动记录；
4. 实现 `simulation_runner.py`；
5. 实现 `experiment_runner.py`；
6. 增加单元测试、断点续跑和数据库持久化。
