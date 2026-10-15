# 数据库开发任务说明

更新日期：2026-09-07  
适用接口：`v1.1-product`

## 一、需要完成什么

数据库负责人需要让MySQL同时支持两类业务：

1. 保存用户新建实验的事件、四种官方声明和后台运行状态；
2. 保存仿真结果，让用户以后能够查询实验、指标、评论、网络和传播。

还需要实现已有 `demo/experiments` 实验结果的只读导入。数据库代码不能修改原始实验文件，也不能调用LLM。

## 二、MySQL技术要求

- 使用MySQL 8.0；
- 存储引擎使用`InnoDB`；
- 字符集使用`utf8mb4`；
- 内部主键可使用`BIGINT UNSIGNED AUTO_INCREMENT`；
- `event_id`、`experiment_id`、`agent_id`和`comment_id`保留字符串类型；
- 长事件和评论正文使用`TEXT`或`LONGTEXT`；
- 原始嵌套数据使用MySQL `JSON`；
- 比率使用`DECIMAL`，不能保存带百分号字符串；
- 时间使用`DATETIME(6)`；
- 状态使用`VARCHAR`，由后端Pydantic负责枚举校验；
- 核心关联建立外键和索引，历史实验第一版不提供级联删除。

数据库负责人需要交付一份可在空MySQL数据库执行的建表SQL，以及一套读取现有JSON/JSONL并写入MySQL的导入功能。文档不限制代码目录。

## 三、需要保存的数据

第一版使用11张表：

| 表名 | 需要保存的内容 |
| --- | --- |
| `events` | 用户输入的事件正文和标签 |
| `official_response_plans` | 进场规则及四种官方声明 |
| `experiments` | 实验运行状态、结果状态、总体比较和性能 |
| `experiment_scenarios` | 不回应及四个回应场景的结果 |
| `simulation_rounds` | 各场景每轮指标 |
| `social_networks` | 实验共享的网络参数 |
| `social_network_nodes` | Agent编号和影响力权重 |
| `social_network_edges` | Agent关注关系 |
| `comments` | 初始评论和各场景增量评论 |
| `agent_round_records` | Agent每轮决策、状态和最终表达 |
| `propagation_events` | 评论沿关系网络传播的证据 |

第一版不单独建立任务表，运行状态直接保存在 `experiments`，避免增加不必要的表。

## 四、核心字段

### 4.1 `events`

```text
event_id（唯一）、event_content、event_labels_json、created_at、updated_at
```

### 4.2 `official_response_plans`

```text
plan_id（唯一）、event_pk、entry_strategy、stagnation_rounds、
improvement_tolerance、content_strategies_json、raw_json、created_at
```

`content_strategies_json`必须完整保留四种声明。`no_response`由仿真系统自动增加，不写入该数组。

### 4.3 `experiments`

```text
experiment_id（唯一）、event_pk、response_plan_pk、
run_status、current_stage、current_scenario、run_error_message、
result_status、entry_strategy、entry_triggered、entry_reason、
strategy_count、success_count、not_run_count、failed_count、
comparison_status、comparison_json、performance_json、shared_baseline_json、
raw_result_json、result_relative_path、created_at、started_at、finished_at、imported_at
```

新建实验时先写入：

```text
run_status=pending
result_status=NULL
raw_result_json=NULL
```

运行过程更新 `run_status/current_stage/current_scenario`；结果成功导入后更新：

```text
run_status=succeeded
result_status=原始experiment_result.json.status
```

启动、运行或导入失败时使用 `run_status=failed`，并保存简短错误。不得把后台任务失败和仿真结果中的 `partial_failed` 混为一类。

### 4.4 `experiment_scenarios`

```text
experiment_pk、scenario_id、scenario_name、result_status、
entry_triggered、entry_reason、comparison_eligible、round_count、
official_responses_json、final_metrics_json、effect_metrics_json、
comment_quality_json、propagation_summary_json、performance_json、
error_message、raw_json
```

唯一约束：`(experiment_pk, scenario_id)`。

### 4.5 `simulation_rounds`

```text
scenario_pk、step、trend_direction、agent_count、negative_count、
negative_rate、question_rate、accept_rate、global_trend_json、
agent_negative_json、emotion_distribution_json、official_attitude_json、
propagation_metrics_json、raw_json
```

唯一约束：`(scenario_pk, step)`。不适用的质疑率和接受率保存为`NULL`，不能存为0。

### 4.6 社交网络三张表

```text
social_networks
experiment_pk（唯一）、network_version、network_seed、neighbors_per_agent、
propagation_decay_factor、neighbor_comment_count、public_comment_count、
visibility_json、raw_json

social_network_nodes
network_pk、agent_id、influence_weight、raw_json

social_network_edges
network_pk、source_agent_id、target_agent_id、raw_json
```

关注关系含义固定为：`source_agent_id`关注`target_agent_id`。

### 4.7 `comments`

```text
experiment_pk、scenario_pk、scenario_scope、step、comment_id、text、
profile_id、profile_label、topic、emotion、faction、orientation、stance、
source_type、generation_trigger、introduced_step、task_id、angle_id、
angle_name、raw_json
```

初始评论使用 `scenario_scope=shared`；增量评论使用具体场景编号。评论接口不分页，但仍需建立 `(scenario_pk, step)` 查询索引。

### 4.8 `agent_round_records`

```text
scenario_pk、step、agent_id、decision_method、record_status、
current_emotion、official_attitude、will_comment、comment_faction、
selected_comment_id、selected_comment_score、expression_id、
propagation_depth、visible_comment_ids_json、visibility_counts_json、
decision_json、state_json
```

唯一约束：`(scenario_pk, step, agent_id)`。决策和状态可存入同一行，但两个JSON必须分别保留。

### 4.9 `propagation_events`

```text
scenario_pk、propagation_event_id、step、event_type、comment_id、
source_expression_id、root_expression_ids_json、source_agent_id、
target_agent_id、propagation_depth、influence_weight、decay_factor、
effective_weight、was_selected、resulting_expression_id、raw_json
```

传播含义固定为：`source_agent_id`将信息暴露给`target_agent_id`。建立 `(scenario_pk, step, comment_id)` 查询索引。

## 五、新建实验时数据库需要做什么

1. 保存或复用相同 `event_id` 的事件；
2. 保存本次四策略回应方案快照；
3. 创建实验记录并设置 `run_status=pending`；
4. 后端开始运行后更新为 `running`；
5. 仿真结束后在事务中写入场景、轮次、评论、Agent、网络和传播；
6. 全部写入成功后设置 `run_status=succeeded`；
7. 任一步骤失败时回滚结果写入，并设置 `run_status=failed`。

事件编号相同但正文或标签不同，应返回冲突，不能静默覆盖旧事件。

## 六、已有实验如何导入

| 原文件 | 导入内容 |
| --- | --- |
| `event_input.json` | 事件 |
| `official_response_options.json` | 官方回应方案 |
| `experiment_result.json` | 实验和五场景摘要 |
| `comment_pool.json` | 初始评论 |
| `social_network_snapshot.json` | 网络、节点和关注边 |
| `metrics_history.jsonl` | 逐轮指标 |
| `incremental_comment_history.jsonl` | 增量评论 |
| `decision_history.jsonl` | Agent决策 |
| `agent_state_history.jsonl` | Agent状态 |
| `propagation_history.jsonl` | 传播事件 |

已完成的旧实验导入后统一设置 `run_status=succeeded`。重复导入相同 `experiment_id` 时返回 `already_imported`，不能增加记录。

## 七、做好之后是什么样

- 用户提交实验后，数据库立即出现一条`pending`实验；
- 运行页面可以持续查询实验状态；
- 实验完成后可以查询5个场景及各轮结果；
- 评论可以按场景和轮次一次返回给弹幕区域；
- 能查询关注网络和评论传播路径；
- 服务重启后，运行结果和历史实验仍然存在；
- 重复导入不会产生重复数据；
- 数据库不依赖前端读取本地JSON。

## 八、本地测试后再推送

数据库负责人必须在本地验证：

1. 空数据库可以成功建表；
2. 手工创建一条`pending`实验并依次更新为`running/succeeded`；
3. 完整导入统一本地样本；
4. 场景、轮次、评论、Agent、节点、边和传播数量与原文件一致；
5. 重复导入不新增数据；
6. 中途失败能够回滚；
7. 中文、Emoji和JSON没有乱码；
8. 能支持 `SHARED_INTERFACE_CONTRACT.md` 所有查询。

以上测试通过后再提交并推送个人分支，Pull Request中附测试过程和结果。
