# 与SIMULATION_CORE_AUDIT.md SIMULATION_INTERFACE_SPEC.md TEAM_COLLABORATION.md存在部分重复，是早期的接口

> **文档状态：已归档。** 本文列出的多数接口已经实现，仅用于追溯早期规划，不得作为当前未完成任务清单。当前状态请阅读 [`../PROJECT_STATUS.md`](../PROJECT_STATUS.md)。


# 未完成功能协作接口文档

本文档对应 `demo` 中的接口占位代码，目的是让不同开发者可以并行实现不同模块。

## 当前已有模块

目前已经具备：

```text
Persona 读取
单 Agent 受约束 LLM 决策
最多 30 个 Agent 并发决策
agent_state_history.jsonl 状态追加
```

以下模块目前只有接口，没有实现算法：

```text
event_state_updater.py  事件状态更新
propagation.py          评论传播和 Agent 互动
metrics.py              舆情指标统计
experiment_runner.py    官方策略实验
simulation_runner.py    多轮社会演化
```

## 统一数据约定

### 固定事件输入

文件：`event_example.json`

```json
{
  "event_id": "event_001",
  "event_content": "事件具体内容",
  "event_labels": {
    "topic": "社会事件",
    "event_valence": "negative"
  }
}
```

`event_valence` 表示事件本身的固有性质，通常不随时间步变化。

### 当前事件状态

文件：`state/event_state_history.json`

```json
{
  "event_id": "event_001",
  "step": 1,
  "official_statement": "官方当前声明",
  "official_statement_status": "incomplete",
  "group_conflict": false,
  "seriousness": "high"
}
```

每个时间步由 `event_state_updater.py` 生成下一轮状态。

### Agent 决策结果

```json
{
  "event_id": "event_001",
  "step": 1,
  "agent_id": "agent_001",
  "status": "success",
  "decision": {
    "current_emotion": "negative",
    "official_attitude": "question",
    "will_comment": true,
    "comment_faction": "观点输出派",
    "selected_comment_id": "comment_001"
  }
}
```

### Agent 动态状态

文件：`agent_state_history.jsonl`

```json
{
  "event_id": "event_001",
  "step": 1,
  "agent_id": "agent_001",
  "state": {
    "current_emotion": "negative",
    "official_attitude": "question",
    "will_comment": true,
    "last_action": "comment",
    "last_comment_faction": "观点输出派",
    "last_comment_id": "comment_001"
  }
}
```

### 互动记录

文件建议：`interaction_history.jsonl`

```json
{
  "event_id": "event_001",
  "step": 1,
  "source_agent_id": "agent_001",
  "target_agent_id": "agent_002",
  "action": "read",
  "comment_id": "comment_001"
}
```

## 模块接口

### 1. 事件状态更新：`event_state_updater.py`

核心函数：

```python
update_event_state(
    event_input,
    current_state,
    agent_decisions,
    interaction_records,
    official_response
)
```

输入：当前状态、本轮 Agent 决策、互动结果、官方回应。

输出：一条可追加到 `state/event_state_history.json` 的事件状态记录。

主要更新：

```text
official_statement_status
group_conflict
seriousness
```

### 2. 评论传播：`propagation.py`

本项目当前采用公共黑板模型，不建立社交网络：

```text
所有 Agent 都能看到事件和官方声明
每个 Agent 都能看到自己的评论
其他 Agent 的评论按 probability 随机可见
```

核心函数：

```python
propagate_comments(
    event_input,
    event_state,
    agent_decisions,
    visibility_config
)
```

参数说明：

- `event_input`：固定事件内容，所有 Agent 共享；
- `event_state`：当前官方声明和事件状态，所有 Agent 共享；
- `agent_decisions`：本轮所有 Agent 的评论结果；
- `visibility_config`：其他 Agent 评论的可见概率等配置。

输出：`propagation_result`，包含每个 Agent 的可见评论和互动记录。

建议第一版只实现：

```text
read：看到评论
ignore：没有看到或不处理
repost：转发评论
comment：对评论产生回应
```

传播模块的辅助接口是：

```python
build_blackboard(event_input, event_state, agent_decisions)
sample_visible_comments(agent_id, blackboard, visibility_config)
create_interaction_record(event_id, step, viewer_agent_id, source_agent_id, action, comment_id)
build_next_decision_context(agent_id, event_input, event_state, agent_state, visible_comments)
```

这些函数的每个参数和返回值已经写在 `propagation.py` 的中文函数注释中。

### 3. 指标统计：`metrics.py`

核心函数：

```python
calculate_round_metrics(
    event_input,
    event_state,
    agent_decisions,
    interaction_records,
    previous_metrics
)
```

输出建议包含：

```text
emotion_distribution
official_attitude_distribution
faction_distribution
comment_count
interaction_count
active_agent_count
polarization_index
```

### 4. 官方策略实验：`experiment_runner.py`

核心函数：

```python
run_strategy_experiment(
    experiment_config,
    event_input,
    personas,
    initial_state,
    candidate_comments
)
```

实验配置应包含：

```json
{
  "response_times": ["early", "growth", "pre_peak", "post_peak"],
  "response_contents": ["fact", "empathy", "clarification", "progress"],
  "repeat_count": 5,
  "random_seed": 42
}
```

输出：每种策略的多轮指标、均值和比较结果。

### 5. 多轮模拟：`simulation_runner.py`

核心函数：

```python
run_multi_round_simulation(
    event_input,
    initial_state,
    personas,
    candidate_comments,
    simulation_config
)
```

每轮顺序固定为：

```text
读取事件状态
→ 批量 Agent 决策
→ 评论传播
→ 更新 Agent 状态
→ 更新事件状态
→ 统计指标
→ 判断是否停止
```

输出：完整模拟结果，包括每一轮的决策、状态、互动和指标。

## 协作实现顺序

建议不同开发者按以下顺序实现：

1. `metrics.py`：先能统计单轮结果；
2. `event_state_updater.py`：根据单轮结果更新事件状态；
3. `simulation_runner.py`：串联多轮流程；
4. `propagation.py`：加入网络和互动；
5. `experiment_runner.py`：运行官方回应策略对比实验。

所有模块都应保持 `event_id` 和 `step` 字段，避免不同事件或时间步的数据混用。
