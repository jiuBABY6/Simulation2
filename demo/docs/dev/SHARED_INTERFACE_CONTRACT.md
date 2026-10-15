# 数据库、后端与前端统一接口契约

更新日期：2026-09-07  
接口版本：`v1.1-product`

本文是三端唯一公共接口标准。原始仿真文件字段以 `demo/docs/DATA_CONTRACT.md` 为准；后端对外字段以本文为准。

## 一、技术栈与职责边界

| 层级 | 技术 | 对本契约的职责 |
| --- | --- | --- |
| 数据库 | MySQL 8.0 | 按业务含义保存输入、状态和结果 |
| 后端 | FastAPI + Pydantic | 暴露接口，并用Pydantic校验请求和响应 |
| 前端 | Vue 3 + Vite + Element Plus + JavaScript | 调用接口并展示数据，不自行改变字段语义 |

本文定义的是三端共享的数据语义，不要求三端使用相同内部类名。任何公共字段或枚举发生变化时，必须先修改本文，再同步数据库、FastAPI/Pydantic模型和Vue页面。

## 二、公共规则

- API前缀：`/api/v1`；
- 字段名称：英文 `snake_case`；
- 比率：`0～1`数值，由前端格式化为百分比；
- 时间：ISO 8601；
- 不适用或原始数据缺失：`null`；
- 空集合：`[]`；
- 只有实验列表分页；
- 评论、轮次、场景、网络、传播和Agent轨迹不分页；
- API不得返回服务器绝对路径、密码或LLM密钥。

## 三、统一响应

成功：

```json
{
  "code": 0,
  "message": "success",
  "data": {},
  "request_id": "req_example_001"
}
```

失败：

```json
{
  "code": 40402,
  "message": "experiment not found",
  "data": null,
  "request_id": "req_example_002"
}
```

实验列表分页对象：

```json
{
  "items": [],
  "page": 1,
  "page_size": 20,
  "total": 0
}
```

`page`从1开始，`page_size`默认20、最大100。

## 四、状态枚举

### 4.1 后台运行状态 `run_status`

| 值 | 含义 |
| --- | --- |
| `pending` | 已创建，等待唯一工作进程执行 |
| `running` | 正在运行仿真 |
| `succeeded` | 仿真结束且结果已经入库 |
| `failed` | 启动、仿真或结果导入失败 |

### 4.2 仿真结果状态 `result_status`

```text
completed | partial_failed | failed | not_run | null
```

`run_status`描述后台任务是否执行成功；`result_status`对应原始实验结果中的`status`，两者不能混用。实验尚未结束时 `result_status=null`。

### 4.3 其他枚举

| 字段 | 允许值 |
| --- | --- |
| `scenario_id` | `no_response`、`fact_report`、`empathy`、`rumor_clarification`、`handling_progress` |
| `entry_strategy` | `negative_threshold`、`global_worsening`、`combined_policy` |
| `quality_status` | `normal`、`degraded`、`emergency` |
| `trend_direction` | `stable`、`improving`、`worsening` |
| `entry_reason` | `negative_threshold`、`global_worsening`、`stagnation`、`null` |
| `official_statement_status` | `clear`、`incomplete`、`conflict` |

## 五、新建实验输入

`POST /api/v1/experiments`一次提交完整事件和四种官方声明。`no_response`由仿真系统自动增加。

```json
{
  "event": {
    "event_id": "event_example_001",
    "event_content": "事件正文",
    "event_labels": {
      "topic": "社会事件",
      "event_valence": "negative"
    }
  },
  "response_plan": {
    "entry_strategy": "combined_policy",
    "stagnation_rounds": 2,
    "negative_rate_improvement_tolerance": 0.05,
    "content_strategies": [
      {
        "strategy_id": "fact_report",
        "strategy_name": "事实通报",
        "official_statement": "事实通报正文",
        "official_statement_status": "clear"
      },
      {
        "strategy_id": "empathy",
        "strategy_name": "共情安抚",
        "official_statement": "共情安抚正文",
        "official_statement_status": "clear"
      },
      {
        "strategy_id": "rumor_clarification",
        "strategy_name": "辟谣澄清",
        "official_statement": "辟谣澄清正文",
        "official_statement_status": "clear"
      },
      {
        "strategy_id": "handling_progress",
        "strategy_name": "处置进展",
        "official_statement": "处置进展正文",
        "official_statement_status": "clear"
      }
    ]
  }
}
```

后端返回HTTP 202：

```json
{
  "code": 0,
  "message": "experiment accepted",
  "data": {
    "experiment_id": "event_example_001_20260907_100000_000001",
    "run_status": "pending",
    "created_at": "2026-09-07T10:00:00+08:00"
  },
  "request_id": "req_create_001"
}
```

第一版不允许客户端修改Agent数、轮次和并发参数，继续使用当前Demo已经验证的配置。

## 六、核心响应对象

### 6.1 ExperimentSummary

```json
{
  "experiment_id": "event_example_001_20260907_100000_000001",
  "event_id": "event_example_001",
  "event_summary": "事件正文的前100字",
  "run_status": "succeeded",
  "result_status": "completed",
  "entry_triggered": true,
  "entry_reason": "stagnation",
  "strategy_count": 5,
  "success_count": 5,
  "not_run_count": 0,
  "failed_count": 0,
  "created_at": "2026-09-07T10:00:00+08:00",
  "finished_at": "2026-09-07T10:15:00+08:00"
}
```

### 6.2 ExperimentStatus

```json
{
  "experiment_id": "event_example_001_20260907_100000_000001",
  "run_status": "running",
  "current_stage": "strategy_experiments",
  "current_scenario": "empathy",
  "result_status": null,
  "error_message": null,
  "started_at": "2026-09-07T10:00:01+08:00",
  "finished_at": null
}
```

`current_stage`允许值：`pending`、`initial_comments`、`shared_baseline`、`strategy_experiments`、`importing_result`、`finished`。无法精确识别时可只返回`running`，不能伪造百分比进度。

### 6.3 ExperimentDetail

在 `ExperimentSummary` 基础上增加：

```json
{
  "event": {},
  "response_plan": {},
  "comparison_status": "completed",
  "comparison": {},
  "performance": {},
  "shared_baseline": {}
}
```

### 6.4 ScenarioSummary

```json
{
  "scenario_id": "fact_report",
  "scenario_name": "事实通报",
  "result_status": "completed",
  "entry_triggered": true,
  "entry_reason": "stagnation",
  "comparison_eligible": true,
  "round_count": 10,
  "official_responses": [],
  "final_metrics": {},
  "effect_metrics": {},
  "comment_quality": {},
  "propagation_summary": {},
  "performance": {},
  "error_message": null
}
```

### 6.5 RoundMetric

```json
{
  "step": 1,
  "global_trend": {
    "trend_direction": "stable",
    "reason": "当前只有初始评论，作为后续趋势比较的基线。",
    "evidence_comment_ids": []
  },
  "agent_negative_emotion": {},
  "agent_emotion_distribution": {},
  "official_attitude_distribution": {},
  "propagation_metrics": {}
}
```

### 6.6 Comment

```json
{
  "comment_id": "comment_066",
  "step": 2,
  "text": "评论正文",
  "profile_id": "7",
  "profile_label": "博闻强识的科普君",
  "emotion": "neutral",
  "faction": "观点输出派",
  "orientation": "opinion",
  "stance": "neutral",
  "source_type": "llm_generated",
  "generation_trigger": "official_statement",
  "introduced_step": 2,
  "angle_id": "gender_violence",
  "angle_name": "女性暴力"
}
```

### 6.7 SocialNetwork

```json
{
  "network_version": "1",
  "network_seed": 2026,
  "neighbors_per_agent": 5,
  "propagation_decay_factor": 0.7,
  "visibility": {
    "neighbor_comment_count": 4,
    "public_comment_count": 11
  },
  "nodes": [
    {"agent_id": "agent_1259110474", "influence_weight": 2.2}
  ],
  "edges": [
    {
      "source_agent_id": "agent_1259110474",
      "target_agent_id": "agent_1711530911"
    }
  ]
}
```

关注边含义：`source_agent_id`关注`target_agent_id`。

### 6.8 PropagationEvent

```json
{
  "propagation_event_id": "propagation_example_001",
  "step": 2,
  "comment_id": "comment_066",
  "source_agent_id": "agent_source",
  "target_agent_id": "agent_target",
  "propagation_depth": 1,
  "influence_weight": 2.051,
  "decay_factor": 0.7,
  "effective_weight": 2.051,
  "was_selected": false,
  "resulting_expression_id": null
}
```

传播边含义：`source_agent_id`将信息暴露给`target_agent_id`。

### 6.9 AgentRoundRecord

```json
{
  "step": 2,
  "agent_id": "agent_1259110474",
  "decision_method": "constrained_llm",
  "record_status": "success",
  "current_emotion": "negative",
  "official_attitude": "question",
  "will_comment": true,
  "comment_faction": "表态判断派",
  "selected_comment_id": "comment_066",
  "selected_comment_score": 0.906667,
  "expression_id": "expression_example",
  "propagation_depth": 1,
  "visible_comment_ids": ["comment_066"],
  "visible_neighbor_comment_ids": ["agent_comment_previous"],
  "visible_public_comment_ids": ["comment_066"],
  "public_sampling_method": "persona_weighted_seeded",
  "silence_reason": null,
  "participation_assessment": {
    "llm_will_comment": true,
    "eligible_to_comment": true,
    "state_changed": false,
    "consecutive_comment_rounds": 1
  },
  "visibility_counts": {
    "current_step": 10,
    "historical": 1,
    "neighbor": 4,
    "public": 11
  },
  "decision": {},
  "state": {}
}
```

`decision`和`state`分别来自决策历史与状态历史，不能互相覆盖。`participation_assessment`和`silence_reason`只要求历史复现新批次提供；五策略或旧批次可以为空。

## 七、第一版API清单

| ID | 方法 | 路径 | `data`内容 |
| --- | --- | --- | --- |
| A01 | GET | `/health` | 服务和数据库状态 |
| A02 | POST | `/experiments` | 创建并排队运行实验 |
| A03 | GET | `/experiments?page=1&page_size=20&keyword=&run_status=&result_status=` | 分页实验列表 |
| A04 | GET | `/experiments/{experiment_id}/status` | 实验运行状态 |
| A05 | GET | `/experiments/{experiment_id}` | 实验详情 |
| A06 | GET | `/experiments/{experiment_id}/scenarios` | `ScenarioSummary[]` |
| A07 | GET | `/experiments/{experiment_id}/scenarios/{scenario_id}/rounds` | `{rounds: RoundMetric[]}` |
| A08 | GET | `/experiments/{experiment_id}/scenarios/{scenario_id}/comments?step=` | `{comments: Comment[]}` |
| A09 | GET | `/experiments/{experiment_id}/network` | `SocialNetwork` |
| A10 | GET | `/experiments/{experiment_id}/scenarios/{scenario_id}/propagation?step=&comment_id=` | `{summary,events: PropagationEvent[]}` |
| A11 | GET | `/experiments/{experiment_id}/scenarios/{scenario_id}/agents/{agent_id}/rounds` | `{records: AgentRoundRecord[]}` |
| A12 | POST | `/imports/experiments` | 导入已有实验 |

除A03外，其他接口不使用`page/page_size`。

## 八、关键完整响应

### A03 实验列表

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "items": [],
    "page": 1,
    "page_size": 20,
    "total": 0
  },
  "request_id": "req_list_001"
}
```

### A07 逐轮指标

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "experiment_id": "example",
    "scenario_id": "fact_report",
    "rounds": []
  },
  "request_id": "req_rounds_001"
}
```

### A08 评论弹幕数据

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "experiment_id": "example",
    "scenario_id": "fact_report",
    "step": null,
    "comments": []
  },
  "request_id": "req_comments_001"
}
```

### A10 传播数据

```json
{
  "code": 0,
  "message": "success",
  "data": {
    "experiment_id": "example",
    "scenario_id": "fact_report",
    "summary": {},
    "events": []
  },
  "request_id": "req_propagation_001"
}
```

### A12 导入旧实验

请求：

```json
{"experiment_id": "event_gaoyang_assault_001_20260906_143939_040535"}
```

`status`返回`imported`或`already_imported`，重复导入不能新增数据。

## 九、错误码

| 业务码 | HTTP | 含义 |
| --- | --- | --- |
| `40001` | 400 | 输入或查询参数错误 |
| `40402` | 404 | 实验不存在 |
| `40403` | 404 | 场景不存在 |
| `40404` | 404 | Agent不存在 |
| `40901` | 409 | `event_id`或业务标识冲突 |
| `40902` | 409 | 已有实验正在运行 |
| `42201` | 422 | 四种官方回应不完整或不合法 |
| `50001` | 500 | 数据库错误 |
| `50002` | 500 | 仿真运行失败 |
| `50003` | 500 | 结果导入失败 |

## 十、数据库/API/页面对应关系

| 数据 | 数据库 | API | 页面 |
| --- | --- | --- | --- |
| 运行状态 | `experiments.run_status` | A03/A04 | 新建实验状态、历史列表 |
| 总体结果 | `experiments` | A05 | 实验总览 |
| 五策略 | `experiment_scenarios` | A06 | 策略卡片 |
| 逐轮指标 | `simulation_rounds` | A07 | 趋势图 |
| 评论 | `comments` | A08 | 固定区域弹幕 |
| 网络 | 三张网络表 | A09 | 关注网络 |
| 传播 | `propagation_events` | A10 | 评论传播图 |
| Agent轨迹 | `agent_round_records` | A11 | Agent详情 |

三端不得在不更新本文的情况下改变以上映射。
