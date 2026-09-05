# 每轮执行流程，可以作为参考

> **文档状态：已归档。** 本文包含早期建议字段和流程，可能与当前代码不一致，不得作为当前接口依据。请阅读 [`../ARCHITECTURE.md`](../ARCHITECTURE.md) 和 [`../SIMULATION_INTERFACE_SPEC.md`](../SIMULATION_INTERFACE_SPEC.md)。

# 多轮社会模拟：每轮执行流程

本文档用于协作开发，规定每一个时间步的统一执行顺序、输入数据、输出数据和模块职责。
多轮模拟的总控模块是 `simulation_runner.py`。

## 一、时间步的基本约定

- `event_example.json`：事件的固定信息，整个模拟过程中通常不变。
- `state/event_state_history.json`：保存每个时间步的动态事件状态。
- `persona_*.json`：每个 Agent 的长期人物画像，通常不在模拟过程中改变。
- `agent_state_history.jsonl`：保存每个 Agent 每个时间步的最新状态。
- 所有 Agent 必须使用同一个时间步的事件状态进行决策，避免同一轮出现信息不同步。

## 二、每一轮的统一执行顺序

假设当前时间步为 `t`，每轮严格按下面顺序执行：

```text
读取固定事件信息
        ↓
读取事件状态 state(t)
        ↓
读取所有 Agent 的 Persona
        ↓
读取 Agent 在 t-1 的最近状态和历史摘要
        ↓
准备或生成本轮候选评论
        ↓
批量调用 Agent 决策
        ↓
将评论放入公共黑板并模拟可见性
        ↓
保存本轮 Agent 状态和评论互动记录
        ↓
统计本轮舆情指标
        ↓
根据本轮结果生成事件状态 state(t+1)
        ↓
保存本轮结果，判断是否进入下一轮
```

## 三、步骤 1：读取固定事件信息

读取 `event_example.json`，获得事件的固定字段，例如：

- `event_id`：事件编号。
- `title`：事件标题。
- `description`：事件的详细描述。
- `topic`：事件主题。
- `event_emotion`：事件整体的情绪基调。

固定事件信息作为每个 Agent 的共同背景，不在每轮中被覆盖。

## 四、步骤 2：读取当前事件状态

读取 `state/event_state_history.json`，获得时间步 `t` 的最新动态状态：

- `event_id`：事件编号。
- `step`：当前时间步。
- `official_statement`：当前已经发布的官方声明。
- `official_statement_status`：官方声明状态，如 `none`、`incomplete`、`clear`、`conflict`。

本轮所有 Agent 都读取同一份 `state(t)`。

## 五、步骤 3：读取 Agent 输入

每个 Agent 的决策输入由四部分组成：

1. 固定事件信息 `event_example.json`。
2. 当前事件状态 `state/event_state_history.json` 中的最新记录。
3. 该 Agent 的 Persona 文件。
4. 该 Agent 的动态记忆：
   - 上一个时间步的状态。
   - `agent_history_summary` 历史摘要。

第一轮没有上一个时间步时，最近状态使用空对象，历史摘要使用空文本或默认摘要。

同一轮中先读取所有 Agent 的输入，再统一进行决策，不让前一个 Agent 的新评论影响后一个 Agent 的即时决策。

## 六、步骤 4：准备候选评论

候选评论可以来自微调模型、通用大模型或预先准备的候选池。
候选评论至少包含：

- `comment_id`：候选评论编号。
- `text`：评论文本。
- `topic`：评论对应的事件主题。
- `emotion`：评论情绪。
- `faction`：评论派系。
- `orientation`：信息表达取向。

本轮候选评论应与当前事件相关。候选评论生成与 Agent 决策可以由不同开发者负责，但输出字段必须保持一致。

## 七、步骤 5：批量 Agent 决策

调用 `batch_agent_decision.py`，为每个 Agent 生成一条决策结果。
推荐接口输入：

```text
event_input
event_state
persona
agent_previous_state
agent_history_summary
candidate_comments
```

推荐接口输出：

```text
agent_id
step
should_comment
selected_comment_id
comment_text
emotion
faction
confidence
decision_reason
```

`confidence` 和 `decision_reason` 用于记录 LLM 的辅助判断；最终是否采用评论应由约束后的结构化结果决定。

## 八、步骤 6：公共黑板传播与互动

调用 `propagation.py` 的公共黑板接口：

```python
propagate_comments(
    event_input,
    event_state,
    agent_decisions,
    visibility_config,
)
```

当前 Demo 不使用社交网络，采用以下规则：

- 所有 Agent 都能看到事件信息和当前官方声明。
- Agent 一定能看到自己的评论。
- 其他 Agent 的评论按 `visibility_config` 中的概率随机可见。
- 传播结果只影响下一轮 Agent 的可见信息和状态，不改变本轮已经完成的决策。

该步骤输出 `interaction_records`，记录评论被谁看到、看到哪条评论以及可见性结果。

## 九、步骤 7：保存 Agent 状态

每轮决策和传播完成后，为每个 Agent 追加一条状态记录到 `agent_state_history.jsonl`。

建议状态字段保持精简：

```json
{
  "agent_id": "agent_001",
  "step": 1,
  "emotion": "negative",
  "faction": "观点输出派",
  "should_comment": true,
  "selected_comment_id": "comment_003",
  "visible_comment_count": 5,
  "confidence": 0.82
}
```

下一轮只读取该 Agent 最近一条状态，并结合历史摘要使用。

## 十、步骤 8：统计本轮舆情指标

调用 `metrics.py`，根据本轮 Agent 决策和互动结果统计：

- 各类情绪的 Agent 数量和比例。
- 各类评论派系的数量和比例。
- `should_comment` 的比例。
- 官方声明发布后的接受、质疑和等待倾向。
- 评论可见数量、互动数量等传播指标。

统计结果追加到 `metrics_history.jsonl`，每条记录必须包含 `event_id` 和 `step`。

## 十一、步骤 9：保存当前时间步事件状态

人工或实验策略模块先确定官方声明文本和声明类型，再调用
`event_state_updater.py`：

```python
append_event_state_record(
    event_input,
    official_statement="当前官方声明",
    official_statement_status="incomplete",
)
```

该函数只保存当前已经确定的官方声明状态，不判断声明类型，也不预测下一轮状态。
它会根据该事件历史记录的最大 `step` 自动加一，并追加到
`state/event_state_history.json` 数组中。
至少需要保证：

- `event_id` 从 `event_example.json` 读取并保持不变。
- `step` 自动递增。
- `official_statement_status` 必须是 `none`、`clear`、`incomplete` 或 `conflict`。
- 不修改 `event_example.json` 中的固定事件信息。

`state/event_state_history.json` 直接保存所有时间步状态记录，数组中每个对象对应一个时间步。

## 十二、步骤 10：保存本轮结果

建议按文件追加保存，避免程序中断后全部丢失：

| 文件 | 保存内容 |
|---|---|
| `decision_history.jsonl` | 每个 Agent 的本轮决策 |
| `agent_state_history.jsonl` | 每个 Agent 的本轮动态状态 |
| `interaction_history.jsonl` | 公共黑板可见性和互动记录 |
| `metrics_history.jsonl` | 本轮舆情统计指标 |
| `state/event_state_history.json` | 保存每轮事件状态数组 |

每条记录都应包含 `event_id`、`step`，Agent 记录还应包含 `agent_id`。

## 十三、步骤 11：判断是否继续

每轮结束后调用 `simulation_runner.py` 的停止判断函数。
可以使用以下停止条件之一：

- 达到预设最大时间步。
- 连续若干轮情绪和派系分布变化很小。
- 事件严重程度降到 `low` 且评论活动低于阈值。
- 用户或实验配置主动终止。

如果不满足停止条件，则令 `t = t + 1`，读取刚生成的 `state(t+1)`，开始下一轮。

## 十四、协作开发边界

- `batch_agent_decision.py`：负责 Agent 批量输入和决策，不负责修改事件状态。
- `propagation.py`：负责公共黑板、评论可见性和互动记录，不负责生成评论。
- `metrics.py`：负责统计，不负责改变 Agent 或事件状态。
- `event_state_updater.py`：负责保存每个时间步事件状态，不负责保存 Persona。
- `simulation_runner.py`：负责串联所有模块，控制时间步和保存顺序。
- `experiment_runner.py`：负责多种官方回应场景的实验，不改变单轮接口约定。

## 十五、必须遵守的同步规则

1. 所有 Agent 在时间步 `t` 使用同一个 `event_state(t)`。
2. 所有 Agent 的决策完成后，才能执行公共黑板传播。
3. 当前时间步状态确定后，才能写入 `state/event_state_history.json`。
4. 下一时间步决策读取该数组中 `step` 最大的最新状态。
5. 任意模块失败时，应保留已经写入的 JSONL 中间结果，并记录 `event_id` 和 `step`，便于断点续跑。
