# 仿真核心接口规范

本文档定义模块之间的输入、输出和职责。实现者应优先遵守字段约定，再选择具体算法。

## 一、统一数据结构

### 1. 固定事件 `event_input`

来源：`event_example.json`。

```json
{
  "event_id": "event_001",
  "event_content": "事件正文",
  "event_labels": {
    "topic": "社会事件",
    "event_valence": "negative"
  }
}
```

### 2. 动态事件状态 `event_state`

来源：`event_state.json`，每轮更新。

```json
{
  "event_id": "event_001",
  "step": 1,
  "official_statement": "当前官方声明",
  "official_statement_status": "incomplete",
  "group_conflict": false,
  "seriousness": "high"
}
```

### 3. Agent 决策结果 `agent_decision`

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
    "selected_comment_id": "comment_003",
    "selected_comment": {},
    "decision_reason": {}
  }
}
```

### 4. Agent 动态状态 `agent_state_record`

保存位置：`demo/state/agent_state_history.jsonl`。

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
    "last_comment_id": "comment_003"
  }
}
```

## 二、已实现接口

### `comment_pool_generator.py`

```python
generate_comment_pool(event_input, pool_size=60, allow_fallback=True)
load_or_generate_comment_pool(event_input, comment_pool_file, force_regenerate=False)
```

输入：事件固定信息、评论池路径和是否强制重建。

输出：包含 `event_id`、生成方式和 `candidates` 的评论池，或候选评论列表。

### `decision_engine.py`

```python
decide_emotion(persona, policy, event_context, topic_match)
decide_official_attitude(persona, policy, event_context)
decide_will_comment(persona, event_context, topic_match, current_emotion)
decide_comment_faction(persona, event_context, current_emotion, topic_match)
select_best_candidate(candidates, event_context, persona, current_emotion, faction)
```

这些函数只处理决策逻辑，不读写文件，不调用网络。

### `agent_state_store.py`

```python
get_latest_state(agent_id, event_id, before_step)
get_history(agent_id, event_id, before_step)
build_history_summary(agent_id, event_id, before_step)
save_decision_states(decision_results)
```

这些函数只负责 Agent 状态历史，不负责事件状态和评论传播。

## 三、待实现接口

### `propagation.py`

```python
build_blackboard(event_input, event_state, agent_decisions)
sample_visible_comments(agent_id, blackboard, visibility_config)
propagate_comments(event_input, event_state, agent_decisions, visibility_config)
create_interaction_record(event_id, step, viewer_agent_id, source_agent_id, action, comment_id)
build_next_decision_context(agent_id, event_input, event_state, agent_state, visible_comments)
```

规则：事件和官方声明对所有 Agent 可见；自己的评论始终可见；其他评论按概率可见。

`propagate_comments()` 至少输出：

```json
{
  "visible_comments_by_agent": {},
  "interaction_records": []
}
```

### `metrics.py`

```python
calculate_emotion_distribution(agent_decisions)
calculate_attitude_distribution(agent_decisions)
calculate_faction_distribution(agent_decisions)
calculate_round_metrics(event_input, event_state, agent_decisions, interaction_records, previous_metrics)
save_round_metrics(round_metrics, output_file)
```

输出至少包括：各种类别的数量、比例、有效 Agent 数、评论数和传播互动数。

### `event_state_updater.py`

```python
update_event_state(event_input, current_state, agent_decisions, interaction_records, official_response)
classify_statement_status(official_statement, event_input, interaction_records)
calculate_event_seriousness(event_input, current_state, agent_decisions, interaction_records)
```

`update_event_state()` 输出下一轮 `event_state`，必须保证 `event_id` 不变、`step` 增加 1。

### `simulation_runner.py`

```python
run_one_simulation_step(event_input, event_state, personas, agent_states, candidate_comments, step_config)
run_multi_round_simulation(event_input, initial_state, personas, candidate_comments, simulation_config)
should_stop_simulation(step, event_state, round_metrics, stop_config)
save_step_result(step_result, output_dir)
```

单轮输出应包含 Agent 决策、互动记录、本轮指标和下一轮事件状态；多轮输出应包含每轮历史。

### `experiment_runner.py`

```python
build_strategy_scenarios(response_times, response_contents, repeat_count, random_seed)
run_strategy_experiment(experiment_config, event_input, personas, initial_state, candidate_comments)
compare_strategy_results(strategy_results, metric_names)
```

该模块依赖 `simulation_runner.py`，不应复制单轮模拟逻辑。

## 四、时间步调用顺序

```text
读取 event_state(t)
→ 读取 Agent 最近状态和历史摘要
→ 批量 Agent 决策
→ 公共黑板传播
→ 保存 Agent 状态和互动记录
→ 统计本轮指标
→ 生成 event_state(t+1)
→ 保存本轮结果
→ 判断是否停止
```

