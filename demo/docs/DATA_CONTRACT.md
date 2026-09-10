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

### Web 事件输入

事件默认从`demo/event_example.json`读取。后续 web 页面通过
`resolve_event_input()`接收事件输入，只传需要覆盖的字段即可，例如：

```json
{
  "event_content": "网页填写的事件正文",
  "event_labels": {
    "event_valence": "negative"
  }
}
```

`event_labels`使用浅层合并：没有传入的标签保留默认值。只覆盖事件正文时沿用
默认`event_id`；若传入与默认不同的`event_id`，必须同时传入`event_content`，
避免新事件编号误配旧正文。

## 官方策略输入

文件：`demo/official_response_options.json`。

必填字段：

- `event_id`：必须与事件输入一致；
- `entry_strategy`：`negative_threshold`、`global_worsening`或`combined_policy`；
- `content_strategies`：必须完整包含事实通报、共情安抚、辟谣澄清、处置进展和
  `custom`；内置策略的声明不能为空；
- `official_statement_status`：`clear`、`incomplete`、`conflict`或`none`；
  `none`仅允许用于公告内容为空的`custom`占位。

`custom`策略是框架的自定义公告入口，默认不随依次触发模式运行。通过
`run_single_strategy_experiment(..., strategy_id="custom")`显式触发时：
公告为空且状态为`none`会保存为`not_run`，原因`custom_statement_empty`；
填入`official_statement`并将状态改为`clear`、`incomplete`或`conflict`后，
该策略会按同一套规则运行并参与该批次结果记录。

不回应场景由系统自动增加，不写入`content_strategies`。

### Web 公告输入

后续 web 页面通过 `resolve_official_response_options()`接收公告内容。默认值来自
`official_response_options.json`；输入可以只覆盖需要修改的策略，例如：

```json
{
  "custom": {
    "official_statement": "网页填写内容",
    "official_statement_status": "clear"
  }
}
```

也可以传入策略列表或完整的`{"content_strategies": [...]}`结构。未知策略编号、
缺少`strategy_id`、空公告配非`none`状态等情况都会在校验阶段直接报错。

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

## 指标记录

每轮指标至少包含Agent负面率、官方态度分布、评论派系分布和全局趋势。最终实验结果还包含峰值、累计负面量、恢复率、持续时间、反弹率、对照净效果、数据质量和性能统计。

## 实验结果

主文件：`demo/experiments/<experiment_id>/experiment_result.json`。

顶层稳定字段包括：

```text
experiment_id, status, strategy_count, success_count,
not_run_count, failed_count, entry_triggered, entry_reason,
strategy_trigger_mode, selected_strategy_id,
custom_included, custom_triggered,
comparison_status, strategy_results, comparison,
performance, performance_summary
```

数据库第一版应完整保留原始JSON，同时把实验、策略、轮次、指标和性能摘要拆成可查询表，避免迁移时丢失尚未结构化的扩展字段。

