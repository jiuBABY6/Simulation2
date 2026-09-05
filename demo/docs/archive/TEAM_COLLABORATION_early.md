# 仿真项目团队协作说明

> **文档状态：已归档。** 本文是传播、指标和实验模块尚未完成时的早期分工。当前任务请阅读 [`../TASK_BREAKDOWN.md`](../TASK_BREAKDOWN.md) 和 [`../TEAM_COLLABORATION.md`](../TEAM_COLLABORATION.md)。

## 一、当前状态

当前已经完成：事件输入、候选评论池生成、单 Agent 决策、多 Agent 单轮决策和 Agent 状态保存。

当前尚未完成：评论传播、舆情指标、多轮模拟和官方策略实验。
`event_state_updater.py` 已有基础规则版，后续需要接入真实指标和互动记录。

## 二、建议分工

### A 组：传播模块

负责 `propagation.py`：公共黑板、评论可见性、互动记录和下一轮决策上下文。

验收条件：给定固定 Agent 决策，能够生成每个 Agent 的可见评论和互动记录。

### B 组：指标模块

负责 `metrics.py`：情绪分布、官方态度分布、评论派系分布、评论率、传播量和 JSONL 保存。

验收条件：使用人工构造的 Agent 决策，可以得到可复核的数量和比例。

### C 组：事件状态模块

负责完善 `event_state_updater.py`：接入真实指标、官方声明分类回调、群体对立、严重程度和下一轮 `step`。

验收条件：输入一轮结果后，输出合法的下一轮 `event_state`。

### D 组：模拟编排模块

负责 `simulation_runner.py`：串联模块、控制时间步、保存断点、判断停止条件和支持续跑。

验收条件：至少完成两轮模拟，并能读取上一轮 Agent 状态和事件状态。

### E 组：实验模块

负责 `experiment_runner.py`：官方回应时机、官方回应内容、重复实验和指标比较。

该组应在模拟编排模块稳定后开始开发。

## 三、实现顺序

```text
传播模块 → 指标模块 → 事件状态更新模块 → 多轮模拟编排模块 → 官方策略实验模块
```

## 四、协作接口规则

1. 函数参数和字段名称以 `SIMULATION_INTERFACE_SPEC.md` 为准。
2. 每条结果必须带有 `event_id` 和 `step`。
3. 每条 Agent 结果必须带有 `agent_id`。
4. 模块不应在内部写死其他模块的路径。
5. 传播模块不得修改 Persona。
6. 指标模块不得修改 Agent 状态或事件状态。
7. `simulation_runner.py` 不得复制决策规则。
8. 大模型调用只能通过 `llm_service.py`，不得重复实现 HTTP 请求。

## 五、每轮结果保存约定

建议使用 JSONL 追加写入以下文件：

- `demo/state/agent_state_history.jsonl`
- `demo/state/decision_history.jsonl`
- `demo/state/interaction_history.jsonl`
- `demo/state/metrics_history.jsonl`
- `demo/state/event_state_history.json`：直接保存所有时间步事件状态数组

程序中断后不能删除已有记录。续跑时应根据 `event_id` 和 `step` 判断已完成的时间步。

## 六、提交前检查

每个模块提交前必须完成：

1. 执行 `python -m compileall -q demo`；
2. 使用最小字典输入运行一次；
3. 检查空 Agent、空评论和无官方声明的情况；
4. 检查 JSONL 输出是否可以重新读取；
5. 检查重复运行是否不会破坏已有状态；
6. 保持函数的中文注释和参数说明完整。

## 七、模块完成定义

一个模块只有同时满足以下条件，才视为完成：

- 函数不再抛出 `NotImplementedError`；
- 输入和输出字段符合接口规范；
- 有至少一个最小可运行示例；
- 能处理空输入和异常输入；
- 不依赖其他模块的内部变量；
- 不修改接口范围之外的数据。
