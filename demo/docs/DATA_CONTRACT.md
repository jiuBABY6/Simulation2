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

## 历史趋势复现输入

历史事件必须提供 `initial_opinion.json`，将人工第一阶段群体情绪作为初始评论环境，而不是模型预测目标。核心字段为：

```text
schema_version=1, event_id, step=1,
mode=historical_calibration, comment_count,
emotion_targets.negative, emotion_targets.neutral,
emotion_targets.positive,
observed_distribution, source,
evaluation_role=initial_condition
```

三个 `emotion_targets` 必须是非负整数，合计必须等于 `comment_count`。配置只允许作用于第1轮，不得包含 `public_discourse_context` 或第2轮以后的真实趋势。生成任务中的可选字段 `required_emotion` 必须是 `negative`、`neutral` 或 `positive`；存在该字段时，评论的 `emotion` 必须与其完全一致，否则评论被过滤并定向重试。

历史入口始终使用该初始条件，不再支持自由初始化开关。校准后的 `comment_pool.json.initialization` 保存校准轮次、目标数量、实际数量和来源快照；回应方案对照评论池仍不要求该字段。

`public_context_timeline.json` 也是必需输入，必须完整覆盖官方时间线轮次。每轮包含 `step`、`period`、`phase`、`verified_updates`、`public_discourse` 和 `positive_evidence`。单条记录必须有唯一编号、文字内容和非空 `source_refs`；公众议题状态允许 `public_question`、`unverified_claim`、`ongoing_discussion`、`social_action`。`verified_updates`还应声明`update_kind`、`evidence_strength`和`evidence_target`：`update_kind`允许`status_continuation`、`procedural_update`、`confirmed_fact`、`final_conclusion`，客观历史更新的强度使用`background`、`moderate`或`strong`。若更新是同轮官方通告的摘要，使用可选`claim_id=official_statement_step_<轮次>`与通告归为同一事实，防止重复计数。兼容旧输入时缺少元数据的更新按`procedural_update/moderate`处理，绝不自动升级为强证据。

该文件用于提供每轮当时已经存在的公开语境，不是结果标签。校验器递归拒绝 `emotion_targets`、`observed_distribution`、`negative_rate`、`neutral_rate` 和 `positive_rate`，第2轮以后也不得写入真实评论文本。

历史入口没有额外的回放模式字段。`event_input.json.simulation_options` 除 `emotion_choice_mode`、`incremental_comment_count` 和 `active_opinion_window` 外，还可显式保存 `network`、`visibility` 与 `context_exposure`。`network.neighbors_per_agent` 默认5；`visibility`默认邻居4条、公共11条；公众讨论到达率默认0.65，建设性证据到达率默认0.5。两类评论之和必须为15，且 `neighbor_comment_count` 不得大于 `neighbors_per_agent`。逐轮已核实事实直接写入 `public_context_timeline.json.verified_updates`，无需第二条客观事件时间线。

## 官方策略输入

文件：`demo/official_response_options.json`。

必填字段：

- `event_id`：必须与事件输入一致；
- `entry_strategy`：`negative_threshold`、`global_worsening`或`combined_policy`；
- `content_strategies`：必须恰好包含3个回应方案；`strategy_id`必须唯一，方案名称和内容类型不做硬编码限制；
- `official_statement_status`：`clear`、`incomplete`或`conflict`。

不回应场景由系统自动增加，不写入`content_strategies`。因此新批次总共4个场景。旧批次中已保存的5个场景仍按其结果文件动态读取，不做数据迁移。

## 评论记录

核心字段包括：

```text
comment_id, profile_id, text, topic, emotion,
faction, orientation, introduced_step, generation_trigger
```

`generation_trigger`记录该轮评论生成所依据的事件阶段。`source_type`是可选来源字段：当前普通LLM评论通常不写该字段，导入数据库时应将缺失值统一解释为`llm_generated`；`repost_fallback`表示历史评论兜底，`local_emergency_fallback`表示本地应急评论，`neighbor_propagation`表示邻居传播副本，`agent_original_expression`表示Agent在决策调用中生成的原创表达。数据库不得只保存文本而丢失来源、生成触发条件和首次出现轮次。

第一轮历史校准评论可以额外包含 `required_emotion`，用于证明文本生成前已经分配情绪任务；不得把生成后的中性文本仅修改标签伪装成负面评论。

2026/10/9，新增功能：历史增量评论任务还可以包含：

```text
reaction_target, evidence_ids, positive_evidence, required_emotion
```

这些字段在历史回放启用 `evidence_based_all` 时使用。正面任务必须携带 `positive_evidence`，有效评论会保留同一证据链。每轮增量记录的 `emotion_coverage.status` 为 `not_required`、`complete` 或 `incomplete`，它只表示证据支持的最小覆盖是否完成，不代表人工目标比例。

## Agent决策和状态

每条记录至少包含：

```text
event_id, step, agent_id, status,
current_emotion, official_attitude, will_comment,
comment_faction, selected_comment_id
```

状态历史和决策历史属于不同数据：决策记录用于解释当轮选择，状态记录用于下一轮输入，不应合并覆盖。

决策记录中的 `visible_comment_ids` 是Agent本轮可见评论范围。新回应方案对照批次的`action_type`可为`silent`、`original`或`reshare`。状态请求只返回内部情绪、官方态度和两项状态理由；`will_comment`与动作由独立本地门控填写，不保存也不依赖`llm_requested_speech`。只有动作确定为`original`时才独立生成`expression`，其`emotion`始终允许`positive / neutral / negative`，且不会反向修改内部状态。转发的`selected_comment_id`必须属于个人可见数组，沉默则不产生表达。回应方案不保存已废弃的`strategy_decision_guard`、`decision_guard`或`emotion_resolution`；`strategy_evidence_memory`仅保存权威证据和已消费传播根的有限元数据，不含评论正文，也不进入LLM提示词。历史原创表达继续使用自己的证据协议。`neighbor_visible_count`和`public_visible_count`记录邻居传播与公共评论补充数量；`neighbor_target_count`、`effective_neighbor_exposure_rate`、`neighbor_expression_age_distribution`和`unique_neighbor_root_count`记录有效邻居曝光诊断。实际表达还包含`expression_id`、`propagation_depth`、`parent_expression_ids`和`root_expression_ids`。

回应方案原创表达目标为120～200字，硬上限为280字符。校验失败时仅重新请求表达，状态和动作保持不变；连续纠错仍超长时允许按句末裁剪，`expression.normalization_audit`记录`code=trimmed_overlong_expression_at_sentence_boundary`、`original_length`、`normalized_length`和`limit`。情绪、立场或证据编号错误不得通过裁剪掩盖。

回应方案对照的`decision_method`保持为`constrained_llm`。决策包含`strategy_state_guard`、`state_transition_diagnostics`和`state_evidence_diagnostics`：分别记录Persona状态约束、实际状态变化来源，以及完整可见评论到状态证据视图的筛选过程。2026/10/20起，`strategy_state_guard.guard_version=strategy_directional_utility_v3`。第一轮没有上一状态时保留政策合法候选；后续轮次的`emotion_options`只包含本地效用裁决出的唯一状态，LLM只负责解释。

方向性效用按`Persona情绪先验×0.16 + 方向性证据支持×0.68 + 上一轮状态惯性×0.16`计算。证据先通过`impact_channels`分流：事件伤害、结果和核实事实主要影响事件情绪；官方主张、调查过程和问责主要影响官方态度；公共讨论和社会行动主要影响参与。普通传播根在每个方向保留最强值，最多三个独立根按`1.0 / 0.5 / 0.25`递减累积；只有社会评论时至少需要两个独立根，官方或客观证据可以单独作用。权威证据的`strategy_evidence_assimilation`保存`absorbed_fraction`、`remaining_potential`、首次出现轮次和消费状态：最多处理三轮，每轮吸收速度由Persona事实偏好、质疑倾向、主题关注和状态惯性决定，并乘以`1.0 / 0.65 / 0.35`轮龄系数；强客观事实允许更快吸收。证据实际推动一次情绪变化后立即消费，不得推动第二次变化。切换边际仍为`0.06 + 0.10×状态惯性 + 0.06×上一情绪先验`，每轮只能保持或转移到相邻情绪。一般调查或控制不具备中性到正面的资格；只有明确完成的修复、风险解除或结果性事实才允许支持该变化。所有系数都是机制参数，不是群体人数或真实曲线目标。

`state_evidence_diagnostics`记录邻居和公共评论的可见数、保留数、上限与去重/限流数；`state_transition_diagnostics`记录方向支持、效用边际、独立根、转移原因、`evidence_lifecycle`和`evidence_assimilation`。逐轮`strategy_state_diagnostics`进一步汇总新增、恢复、到期、消费证据组数量及平均已吸收比例。`not_applicable`首次进入`wait / accept / question`只表示通告开始适用，不计为心理状态变化。完整规则守卫留在结果审计中，发送给LLM的守卫不包含官方态度推荐、证据记忆或逐条内部映射。这些字段只用于机制审计，不是群体配额或拟合目标。自主发言门控和三类公开动作仍作为独立字段保存；历史复现继续使用自己的完整证据裁决字段，二者不得混用。

官方方案可选填`evidence_dimensions`，键限定为`verified_fact`、`completed_action`、`accountability`、`empathy`、`unresolved_process`和`rumor_control`，值必须为布尔值。该字段只声明通告正文中确实存在的可观察语义，不得填写期望情绪、目标人数或拟合比例。`official_statement_status=clear`仅表示表述清楚；仍在调查、没有完整处置结果的方案应标为`incomplete`。

历史回放决策额外要求：

```text
emotion_target, emotion_evidence_ids,
official_attitude_evidence_ids, persona_factors,
expression.{text, emotion, stance, evidence_ids},
persona_decision_profile, decision_guard, official_attitude_resolution,
claim_position, process_evaluation, evidence_appraisal
```

`emotion_evidence_ids` 必须来自同期公众语境、官方声明或模拟可见评论；首次进入正面情绪或从其他情绪转为正面时，至少引用一个支持建设性表达的证据编号。延续上一轮正面状态时可以引用本轮实际影响判断的其他证据，避免连续状态被旧的“每轮重新证明”规则强制打断。`official_attitude_evidence_ids` 单独记录官方态度依据，只能引用官方通告、已核实更新、客观事件或与官方响应直接相关的语境证据；没有官方声明时必须为空。`persona_factors` 只能引用允许的长期倾向类型。官方通告证据编号绑定首次发布轮次，持续通告不伪装成新的历史事实。通告分项使用`official_statement_step_<轮次>_part_<序号>`，同一通告的分项和原文共享`evidence_group_id=official_statement_step_<轮次>`。邻居评论证据可以携带`network_influence_weight`、`source_agent_ids`和`propagation_depth`，这些字段只描述实际传播来源，不改变公共评论的数据契约。

上一轮状态是默认基线。`persona_decision_profile.profile_version=persona_decision_v3`，由Persona原始比例和群体P25/P75单调推导；画像保存主题关注度、相对信息取向、情绪先验、状态惯性、情绪变化门槛、情绪切换边际、官方态度变化门槛、官方接受门槛、未解决关切门槛、过程满意门槛、公共意见敏感度和表达门槛。相同输入必须生成相同画像。系统再为每条证据分别计算情绪与官方态度的`personal_impact`。

`decision_guard.guard_version=personalized_hysteresis_v3`。它保存情绪和官方态度唯一合法结果、两类相对效用、证据合并影响、个体变化门槛和状态惯性。第一轮没有上一状态时仍由LLM初始化；后续情绪由`emotion_resolution.resolution_version=emotion_transition_v1`按个体效用边际最终裁决，官方态度由`official_attitude_resolution.resolution_version=official_attitude_v3`最终裁决，LLM不得覆盖。该机制不设置人口配额或目标曲线。

历史状态保存离散的`current_emotion`、兼容字段`official_attitude`以及`claim_position`、`process_evaluation`，不保存`latent_emotion_score`或`response_memory`。状态改变必须引用本轮新增证据；一个个体充分证据或两个独立普通新增证据才能支持变化，非相邻情绪跳转还必须引用允许完整重判的强证据。

当官方声明从无到有时，上一轮`official_attitude=not_applicable`不属于三态惯性。规则层按当前Persona、事实证据、过程回应和未解决关切直接形成首次态度；已有`accept/wait/question`状态后才应用个体变化门槛和相邻状态迟滞。

情绪标签变化必须至少引用一条本轮新增且确实作用于情绪的证据，并继续执行“两条独立普通证据或一条个体充分证据”的离散充分性校验。官方态度由规则裁决使用的`supporting_evidence_ids`自动进入审计记录；同一`evidence_group_id`的通告原文、分句和摘要不能重复增加影响。`evidence_appraisal`只保存本次决策实际引用证据的强度、目标、证据组和个体影响，不代表系统预设群体结论。个人评论证据只能来自该 Agent 的 `visible_comment_ids`，公共评论池中未进入个人视图的评论不能作为决策依据。

历史决策还可以包含`participation_assessment`与`silence_reason`。前者记录LLM原始发言意愿、参与分、阈值、相关新证据、强证据、最大个体证据影响、状态变化、连续发言轮数和表达相似度；后者在沉默时使用`agent_chose_silence`、`no_relevant_new_evidence`、`repeated_view_without_state_change`或`consecutive_comment_fatigue`。强证据只按Persona相关性增加参与分，不再无条件绕过沉默门控。该评估只决定是否公开表达，不得改写`current_emotion`或`official_attitude`。

决策可包含`output_normalizations`，记录不改变实际公开行为语义的格式补全：`filled_null_expression_for_silence`、`discarded_expression_for_silence`、`filled_null_comment_faction_for_silence`和`filled_empty_attitude_evidence_without_statement`。系统以`will_comment=false`为权威行为选择，丢弃不会进入评论池的多余表达；决定发言时缺少表达或派系不得自动补全。`expression_similarity_audit`只用于分析表达重复程度，不改变Agent明确选择的原创或转发动作。内部状态使用`emotion_options`，公开表达使用`expression_emotion_options`，二者可以不同，但都必须遵守证据边界和正面证据资格。

历史第一轮情绪由LLM初始化，后续情绪和官方态度由受证据约束的本地离散个体规则裁决，LLM只解释结果、判断发言并生成表达。系统不保存`conditioned_response`，也不使用本地概率、稳定Agent分层或人口配额。接受通告不等于事件情绪自动转为中性或正面；`claim_position=accepted`也可以同时出现`process_evaluation=dissatisfied`。`unresolved_concern=true`的过程材料只计入未解决关切，不得同时计作官方已覆盖的过程回应。`process_evaluation`在没有新过程证据时保持上一轮结果，有新证据时按个体过程门槛与迟滞更新。

事件状态保存原始 `public_context`、`public_context_timing` 和 `simulation_mode`。决策前，已核实事实保留在公共语境，公众讨论与建设性证据被拆分到 `individual_public_context`；该个体视图只存在于本轮决策上下文，不回写公共状态。

## 社交网络快照

回应方案对照实验文件：`demo/experiments/<experiment_id>/social_network_snapshot.json`。历史复现或独立调试入口缺少外部网络文件时，会在各自状态目录创建确定性的同格式快照。

```text
network_version, network_seed, neighbors_per_agent,
propagation_decay_factor,
visibility.neighbor_comment_count, visibility.public_comment_count,
nodes[].agent_id, nodes[].influence_weight,
edges[].source_agent_id, edges[].target_agent_id
```

边的语义是 `source_agent_id` 关注 `target_agent_id`，因此source可以接收target的实际表达。回应方案按最近1、2、3轮的顺序补足邻居曝光，历史复现保持上一轮口径；同一根传播链只占一个邻居曝光名额，邻居不足后才使用公共评论补齐。影响力权重决定同一轮龄内的抽样概率；三个回应方案与一组不回应基线必须读取同一快照，但不得共享进场后的决策、表达、公众反应和状态文件。

## 传播事件

文件：`demo/experiments/<experiment_id>/<scenario>/state/propagation_history.jsonl`。

```text
propagation_event_id, event_id, step, event_type,
comment_id, source_expression_id, root_expression_ids,
source_agent_id, target_agent_id, propagation_depth,
influence_weight, decay_factor, effective_weight,
was_selected, resulting_expression_id
```

`event_type=neighbor_exposure`表示邻居表达进入目标Agent的个人可见范围。回应方案对照中，Agent转发该评论，或原创表达的 `evidence_ids` 引用该评论时，`was_selected=true`。原创表达引用邻居评论时必须继承直接父表达、根表达和传播深度；公共评论池抽样不是沿关注关系发生的传播，因此不写入该文件。回应方案近期曝光的有效权重为`influence_weight × depth_decay^(propagation_depth-1) × 0.72^(expression_age-1)`；历史上一轮表达的时间项恒为1。

## 指标记录

每轮指标至少包含`agent_emotion_distribution`、`agent_expression_distribution`、`agent_action_distribution`、`official_attitude_distribution`、`official_attitude_diagnostics`、`neighbor_exposure_diagnostics`、`strategy_state_diagnostics`、全局趋势和`propagation_metrics`。`neighbor_exposure_diagnostics`聚合目标/实际邻居曝光数、有效填充率、达到目标与零曝光Agent比例、平均唯一根表达数和轮龄分布，只用于诊断网络是否真正进入个人视图。`strategy_state_diagnostics`聚合三方向支持、效用差、切换边际、独立证据根和转移原因，用来区分“证据未到达、证据无方向、Persona保持或证据推动变化”。`agent_action_distribution`保存沉默、原创、转发数量与原创文本去重率；`official_attitude_diagnostics`只诊断群体趋同而不触发熔断。历史复现的 `policy_metrics.negative_rate_basis=agent_expression`，回应方案对照默认为 `agent_internal`；两种口径不得无标记混用。最终结果继续保存传播、峰值、累计负面量、恢复率、持续时间、反弹率、对照净效果、数据质量和性能统计。

完整历史批次根目录新增`run_manifest.json`，至少保存事件输入、初始评论池、官方时间线、公众语境、初始人工条件和核心机制代码的SHA-256，以及模型名称、Agent决策温度、随机种子、实际Agent编号和Persona决策画像指纹。该文件不得包含API Key或其他密钥。

历史结果不执行群体坍缩熔断。如果全部 Agent 在某轮选择同一情绪或同一适用官方态度，结果仍会保存为已完成；该现象应作为模型输出进行分析，而不是由运行框架改写或拒绝。

`global_trend`中的`trend_direction`和`reason`是核心趋势字段，继续执行严格校验。`evidence_comment_ids`只是支持趋势说明的辅助证据：系统会去除首尾空格、去重、限制为最多5条，并过滤不属于本轮允许集合的编号。证据字段格式异常或出现越界编号时，不中断已经完成的Agent决策、传播和核心指标计算，而是在同一对象的`evidence_validation`中保存审计结果：

```text
status: valid | filtered
issues: 证据字段格式或过滤原因数组
invalid_ids: 最多5个被过滤的原始编号
```

`status=filtered`只表示证据引用质量下降，不表示`trend_direction`已经通过外部事实验证，也不改变负面率、官方态度或传播指标。趋势方向非法或`reason`为空仍会使本轮指标失败。

## 实验结果

主文件：`demo/experiments/<experiment_id>/experiment_result.json`。

顶层稳定字段包括：

```text
experiment_id, status, strategy_count, success_count,
not_run_count, failed_count, entry_triggered, entry_reason,
comparison_status, strategy_results, comparison,
social_network_file, performance
```

`performance_summary`是`demo/main.py`运行结束时构造的控制台摘要字段，不写入`experiment_result.json`，因此不作为持久化数据契约。数据库第一版应完整保留原始JSON，同时把实验、策略、轮次、指标和`performance`拆成可查询表，避免迁移时丢失尚未结构化的扩展字段。
## 2026/10/19 评论语义、证据与实验对照契约

为避免把“负面情绪”“质疑官方”“讨论事件损害”和“转发来源”混为同一个标签，评论与证据新增以下互相独立的字段：

```text
reaction_target:
  event_harm | official_claim | investigation_process | accountability |
  victim_support | public_discourse | social_action | 兼容的历史目标
evidence_role:
  support | contradict | question | opinion | background | clarify
information_source_type:
  official | media | expert | witness | public | agent | event
information_origin:
  exogenous | endogenous
provenance_type: 技术生成或传播路径
claim_id: 可选的事实主张编号
root_id: 传播根编号
```

`source_type` 保留为旧接口兼容字段，不再承担现实信息来源语义；例如 `neighbor_propagation` 是技术传播路径，规范化后同时保存 `provenance_type=neighbor_propagation`、`information_source_type=agent` 和 `information_origin=endogenous`。旧批次缺少新字段时由 `domain/comment_semantics.py` 保守补齐：公众支持性表达仍是公众意见，不能自动升级为事实证据。

官方态度使用独立的 `strategy_attitude_memory`，与情绪证据的“推动一次后消费”机制分开。权威事实、过程回应和未解决关切分别保留；历史记忆只能形成当前认知背景，只有本轮新增证据可以触发态度变化。逐轮诊断中的 `attitude_memory_active_evidence_count`、`attitude_memory_new_evidence_count` 和 `attitude_memory_restored_evidence_count` 用于审计该过程。

网络节点同时保存：

```text
influence_weight                 # 原始权重，用于展示和传播排序
normalized_influence_weight      # 同批网络内归一化到 0～1，用于认知计算
```

邻居评论同理保存 `propagation_weight` 与 `normalized_propagation_weight`。多名邻居传播同一根表达时，归一化权重使用饱和并集合并，结果不会超过 1。策略实验的传播窗口和状态认知窗口统一由 `simulation_options.expression_window_rounds` 控制，默认均为最近 3 轮。

## 2026/10/20 策略对照的因果隔离契约

三种回应方案与不回应基线只共享不会被方案改变的输入：事件快照、初始评论池、固定网络、官方进场前状态和可选的 `objective_event_timeline` 客观事实时间线。官方进场后的公众反应不再从不回应场景复制；每个场景根据自己的官方声明、共同客观事实和上一轮Agent实际表达独立生成，记录为 `generation_mode=scenario_reactive_public`、`information_source_type=public`、`information_origin=endogenous`。

事件状态、增量评论批次和评论均携带 `scenario_id` 与 `shared_input_sha256`。实验结果的 `counterfactual_controls` 保存事件、初始评论、网络、客观事实时间线和进场前快照的SHA-256，并保存逐场景及跨场景污染检查。新批次不得再出现 `generation_mode=shared_exogenous_context` 或 `shared_external_context=true`；出现时实验标记为 `failed_isolation_audit`。

可选客观事实时间线格式：

```json
{
  "objective_event_timeline": [
    {
      "step": 3,
      "objective_event_context": {
        "events": [{"objective_event_id": "fact-3", "text": "客观进展"}]
      },
      "objective_event_timing": {"phase": "阶段三"}
    }
  ]
}
```

该时间线只能包含不依赖回应方案即可成立的客观事实，不得填入真实情绪比例、方案评价或某个场景生成的公众评论。
