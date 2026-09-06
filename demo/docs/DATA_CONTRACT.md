# 核心数据契约

本文档给数据库、后端和可视化开发提供稳定字段边界。新增字段应保持向后兼容，删除或重命名字段必须先更新接口文档并完成回归验证。

## 事件输入

文件：`demo/event_example.json`。

```json
{
  "event_id": "event_example_001",
  "event_content": "事件正文",
  "event_labels": {
    "topic": "社会事件",
    "event_valence": "negative"
  }
}
```

当前Persona可匹配的主题包括`新闻时事`、`社会事件`和`其他`等已有键值。新事件不得临时创造Persona中不存在的主题标签。

## 官方策略输入

文件：`demo/official_response_options.json`。

必填字段：

- `event_id`：必须与事件输入一致；
- `entry_strategy`：`negative_threshold`、`global_worsening`或`combined_policy`；
- `content_strategies`：必须完整包含事实通报、共情安抚、辟谣澄清和处置进展；
- `official_statement_status`：`clear`、`incomplete`或`conflict`。

不回应场景由系统自动增加，不写入`content_strategies`。

## 评论记录

核心字段包括：

```text
comment_id, profile_id, text, topic, emotion,
faction, orientation, introduced_step, generation_source
```

`generation_source`用于区分LLM新评论、历史转发兜底和本地应急评论。数据库不得只保存文本而丢失来源和首次出现轮次。

## Agent决策和状态

每条记录至少包含：

```text
event_id, step, agent_id, status,
current_emotion, official_attitude, will_comment,
comment_faction, selected_comment_id
```

状态历史和决策历史属于不同数据：决策记录用于解释当轮选择，状态记录用于下一轮输入，不应合并覆盖。

决策记录中的 `visible_comment_ids` 是Agent本轮可见范围，`selected_comment_id` 必须属于该数组。`neighbor_visible_count` 和 `public_visible_count` 分别记录邻居传播与公共评论补充数量，`selection_source` 当前固定为 `personal_visible_comments`。实际表达还包含`expression_id`、`propagation_depth`、`parent_expression_ids`和`root_expression_ids`，用于跨轮追踪表达谱系；未表达时这些字段为空值或空数组。

## 社交网络快照

五策略实验文件：`demo/experiments/<experiment_id>/social_network_snapshot.json`。历史复现或独立调试入口缺少外部网络文件时，会在各自状态目录创建确定性的同格式快照。

```text
network_version, network_seed, neighbors_per_agent,
propagation_decay_factor,
visibility.neighbor_comment_count, visibility.public_comment_count,
nodes[].agent_id, nodes[].influence_weight,
edges[].source_agent_id, edges[].target_agent_id
```

边的语义是 `source_agent_id` 关注 `target_agent_id`，因此source可以接收target上一轮的实际表达。影响力权重只调整邻居表达被抽中的概率，不直接改变Agent情绪或官方态度。五个策略必须读取同一快照，但不得共享进场后的决策和状态文件。

## 传播事件

文件：`demo/experiments/<experiment_id>/<scenario>/state/propagation_history.jsonl`。

```text
propagation_event_id, event_id, step, event_type,
comment_id, source_expression_id, root_expression_ids,
source_agent_id, target_agent_id, propagation_depth,
influence_weight, decay_factor, effective_weight,
was_selected, resulting_expression_id
```

`event_type=neighbor_exposure`表示邻居表达进入目标Agent的个人可见范围；`was_selected=true`才表示目标Agent继续表达该评论。公共评论池抽样不是沿关注关系发生的传播，因此不写入该文件。第一跳`propagation_depth=1`，后续按最短已知谱系逐层增加；有效权重公式为`influence_weight × decay_factor^(propagation_depth-1)`。

## 指标记录

每轮指标至少包含Agent负面率、官方态度分布、评论派系分布、全局趋势和`propagation_metrics`。传播指标包括曝光次数、覆盖人数、覆盖率、来源Agent数、传播评论数、继续传播次数、继续传播Agent数、继续传播率、最大/平均传播深度和有效权重总量。最终实验结果还包含`propagation_summary`以及峰值、累计负面量、恢复率、持续时间、反弹率、对照净效果、数据质量和性能统计。

## 实验结果

主文件：`demo/experiments/<experiment_id>/experiment_result.json`。

顶层稳定字段包括：

```text
experiment_id, status, strategy_count, success_count,
not_run_count, failed_count, entry_triggered, entry_reason,
comparison_status, strategy_results, comparison,
social_network_file, performance, performance_summary
```

数据库第一版应完整保留原始JSON，同时把实验、策略、轮次、指标和性能摘要拆成可查询表，避免迁移时丢失尚未结构化的扩展字段。
