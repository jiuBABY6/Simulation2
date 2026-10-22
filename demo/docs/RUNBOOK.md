# 运行与排错手册

## 环境准备

当前验证环境使用Conda环境`persona_sim`。在项目根目录执行：

```powershell
conda create -n persona_sim python=3.10 -y
conda activate persona_sim
python -m pip install -r requirements.txt
$env:DEEPSEEK_API_KEY = "填写本机使用的API Key"
python demo\main.py
```

根目录`requirements.txt`是当前项目的可复现依赖清单。LLM密钥只在本机环境变量中设置，不得写入配置文件、日志、实验数据或代码仓库；程序检测不到密钥时会直接给出环境变量配置提示。

## 更换测试事件

1. 修改`demo/event_example.json`。
2. 修改`demo/official_response_options.json`。
3. 确认两个文件的`event_id`完全一致。
4. 保持Agent数、轮数、增量评论数和随机种子不变，再进行跨事件性能比较。

## 输出位置

每次运行会创建新的：

```text
demo/experiments/<event_id>_<timestamp>/
```

重点查看：

- `experiment_result.json`：总体结果、策略比较和性能摘要；
- 各策略目录中的状态和逐轮指标；
- `comment_quality`和`data_quality`：LLM评论及兜底情况；
- `performance`：阶段耗时和分类LLM请求。
- `propagation_history.jsonl`：邻居曝光、传播层级、衰减权重和是否继续表达；
- `propagation_summary`：场景累计覆盖人数、继续传播次数和最大传播深度。

回应方案新批次还应抽查逐轮`strategy_state_diagnostics`：`public_state_evidence_retention_rate`用于确认公共评论状态限流；`average_directional_support`、`average_utility_margin`和`average_required_switch_margin`用于判断证据方向是否真正进入Persona裁决；`directional_evidence_group_count`用于确认传播根去重后的有效证据数量；`assimilation_new_evidence_group_count`、`assimilation_restored_evidence_group_count`、`assimilation_expired_evidence_group_count`、`assimilation_consumed_evidence_group_count`和`average_authoritative_absorbed_fraction`用于核对权威证据是否按Persona在三轮内渐进吸收。决策中的`strategy_state_guard.guard_version`应为`strategy_directional_utility_v3`，`emotion_options`在第一轮以后应只有规则层裁决出的唯一相邻状态。`strategy_evidence_assimilation`可以出现在本地状态与完整审计中，但不得进入LLM提示词。`experiment_result.json.simulation_options.incremental_comment_count`默认应为8；历史复现的默认值仍为20。

## 历史趋势复现

事件目录必须同时包含 `initial_opinion.json`、`public_context_timeline.json` 和官方时间线，然后直接运行：

```powershell
python demo\historical_replay\main.py --event-id <event_id>
```

当前可运行事件可用`--list-events`查看。北国先天下新数据应使用`event_beiguo_xiantianxia_crash_20260920_002`；旧`001`只保留真实趋势快照和旧批次兼容，不再作为事件源运行。

新批次根目录应同时包含 `initial_opinion.json`、`public_context_timeline.json` 和 `comment_pool.json`，且 `comment_pool.json.initialization.target_emotion_counts` 与 `actual_emotion_counts` 完全一致。第一轮作为历史初始条件，不计入MAE和峰值指标；第2轮以后不读取真实评论或真实情绪比例。

## 历史复现输入检查

运行前应确认：

1. `event_input.json`、公众语境和官方时间线的 `event_id` 一致；
2. `public_context_timeline.json` 完整覆盖全部历史轮次；
3. 同期公众语境中没有真实情绪比例、目标分布或真实评论文本；
4. 每条公众语境信息有可审计的来源引用；
5. 后续调查结论没有提前进入早期轮次。
6. `verified_updates`已区分`status_continuation`、`procedural_update`、`confirmed_fact`或`final_conclusion`，且“调查继续、等待结果、结论后的讨论”没有误标为`strong`。

运行完成后检查结果为 `mode=historical_replay`、`public_context_enabled=true`，且每轮含 `public_context`。`policy_metrics.negative_rate_basis` 应为 `agent_expression`，同时检查 `negative_count`、`negative_denominator`、`expression_count` 和 `silent_agent_count`。决策记录还应满足：发言Agent使用 `selection_source=agent_original_expression`，原创表达有合法 `evidence_ids`，`visible_context_evidence_ids`只包含个体实际曝光；`persona_decision_profile.profile_version`应为`persona_decision_v3`，`decision_guard.guard_version`应为`personalized_hysteresis_v3`，`emotion_resolution.resolution_version`应为`emotion_transition_v1`，`official_attitude_resolution.resolution_version`应为`official_attitude_v3`，并保存`claim_position`、`process_evaluation`与过程转移原因。`participation_assessment.emotion_independent_scoring`应为`true`。`evidence_appraisal`只包含该Agent实际引用证据的个体影响。状态文件不应出现`latent_emotion_score`或`response_memory`。实验根目录应存在`run_manifest.json`且`mechanism_version=persona_evidence_replay_v3`，其输入和代码哈希可用于判断两批实验是否可直接比较。历史网络快照默认应为每名Agent关注5人、目标曝光4条邻居表达和11条公共评论；第1轮没有上一轮表达，实际0+15属于正常结果。第2轮以后检查 `neighbor_visible_count`、`public_visible_count`、两类实际评论编号与`public_sampling_method=persona_weighted_seeded`，邻居沉默时允许公共评论补足。引用邻居评论的原创表达应具有非空 `parent_expression_ids`，连续引用时 `propagation_depth` 应能大于1。沉默决策应检查`silence_reason`、`participation_assessment.max_personal_evidence_impact`和连续发言轮数；状态变化只提高动机，不保证发言。当前主线没有群体坍缩熔断；分布过度集中时检查`official_attitude_diagnostics`中的最大群体占比、态度熵和同步转向率。页面默认显示 Agent 实际表达，也可以切换其他诊断口径。胡某宇事件每轮增量评论为50条，会增加DeepSeek调用费用和运行时间。

## 常见状态

| 状态 | 含义 |
| --- | --- |
| `completed` | 应运行的策略均成功完成 |
| `partial_failed` | 部分策略失败 |
| `failed` | 所有策略失败或关键流程失败 |
| `failed_isolation_audit` | 共同输入哈希、场景编号、状态目录或公众反应发现跨场景污染 |
| `not_run` | 动态进场条件始终未触发，回应策略未实际运行 |
| `normal` | 评论兜底未触发质量告警 |
| `degraded` | 实验完成，但部分轮次历史兜底较多 |
| `emergency` | 使用了本地应急评论，结果需谨慎解释 |

## 进场原因

| 值 | 含义 |
| --- | --- |
| `negative_threshold` | Agent负面率达到当前阈值 |
| `global_worsening` | LLM全局趋势判断为恶化 |
| `stagnation` | 舆情连续多轮没有明显改善 |

## 最小交接检查

新成员首次接手时先执行[`PROJECT_HANDOFF_20261022.md`](./PROJECT_HANDOFF_20261022.md)中的Destination sentinel。哨兵匹配后，再依次完成：

1. 运行Demo、Persona和可视化离线测试；
2. 校验两个输入JSON的`event_id`；
3. 在API Key有效且余额充足时使用小规模参数完成一次运行；
4. 确认生成新实验目录且没有覆盖旧批次；
5. 确认结果中包含策略状态、数据质量、传播摘要和性能摘要。
## 2026/10/20 因果隔离机制运行后检查

运行命令不变：

```powershell
python demo\main.py
```

新批次完成后优先核对：

1. `experiment_result.json.counterfactual_controls.cross_scenario_audit.status` 为 `passed`；
2. 四个场景的 `shared_input_sha256` 完全一致、`scenario_input_sha256` 各不相同，状态目录彼此独立；
3. 通告投入后的 `incremental_comment_history.jsonl` 使用 `generation_mode=scenario_reactive_public`，并携带当前场景 `scenario_id`；不得出现旧式 `shared_exogenous_context`；
4. 抽查回应场景评论，不得在通告已经公开后无依据地声称“尚无任何官方信息”；
5. `state_evidence_diagnostics` 同时出现 `exogenous_state_evidence_count` 与 `endogenous_state_evidence_count`，后者会包含Agent表达和场景反应；
6. 网络快照同时包含原始与归一化影响力，传播记录同时包含两类传播权重；
7. `strategy_state_diagnostics` 能看到官方态度记忆的新增与跨轮恢复，但没有新证据时不应出现态度变化；
8. 评论目标和证据角色有缺失时可以由兼容层补齐，但新生成批次不应大量依赖 `public_discourse/opinion` 默认值。

本轮只完成离线语法、契约和单元回归，不等同于完成新的DeepSeek全量实验。正式比较方案前仍需新建批次运行，旧批次不会被新机制重写。
