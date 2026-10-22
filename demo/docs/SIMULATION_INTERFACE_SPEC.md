# 当前仿真接口规范

## 稳定入口

| 入口 | 职责 |
| --- | --- |
| `main.run_complete_simulation()` | 创建批次、生成初始评论并执行三种回应方案和一组不回应基线 |
| `experiment_runner.run_experiment(...)` | 运行共享基线、策略场景和结果比较 |
| `ablation_runner.run_ablation_experiment(...)` | 在共享输入和首轮状态下运行反馈链路消融 |
| `simulation.runner.run_one_simulation_step(...)` | 执行一个时间步 |
| `historical_replay/main.py` | 执行指定轮次投入官方信息的历史路线 |

后端应调用稳定入口或命令行子进程，不应逐个拼接内部函数。

## 模块接口边界

- 评论生成模块输入事件上下文、历史评论和目标数量，输出经过校验并带来源的评论；不修改Agent状态。
- 可见性模块输入公共评论、固定网络和邻居表达，输出“近期邻居传播＋公共补充”的个人可见评论；回应方案读取最近3轮、历史复现保持上一轮，模块本身不读写文件、不调用LLM。
- 传播追踪模块为Agent表达补充谱系，构建并保存邻居曝光事件；不生成评论、不修改Agent认知结果。
- Agent决策模块输入Persona、事件、声明、个人可见评论和个人历史。回应方案先从完整可见范围构造受限的内部状态证据视图，再输出纯状态；本地门控和原创/转发行为仍使用完整可见评论。状态证据按目标分别进入事件情绪、官方态度和参与通道，权威证据由Persona在最多三轮内渐进吸收；内部状态与表达情绪均允许三分类，状态每轮只能保持或相邻变化。通告分句共享同一证据组，规则层推荐态度和证据记忆不得进入模型输入。转发编号必须属于本轮完整可见范围，模块不更新事件状态。
- 指标模块只读决策和历史状态，输出统计结果；不修改Persona、评论或决策。
- 传播指标只描述覆盖、继续传播和层级，不将传播越广或越深直接解释为策略越好。
- 实验编排模块负责状态隔离和调用顺序，不复制业务算法。
- 消融编排只能通过`simulation_options.ablation`关闭单条反馈路径；不得改写正式事件文件、Persona或决策常量。未配置时必须保持完整机制。
- 存储模块负责序列化，不推导业务结论。

## 数据库与后端接入约束

1. 第一阶段以现有JSON和JSONL为事实来源。
2. 数据库必须保留`event_id`、`experiment_id`、`strategy_id`、`step`和`agent_id`等关联键。
3. 实验目录在运行期间只由仿真进程写入，展示和导入程序只读。
4. 后端不得通过并发请求让两个任务共用同一状态目录。
5. 任务异常必须保留控制台错误和实验目录，不能通过删除目录伪装成功。
6. 新的存储实现应放在独立模块，通过适配器接入，当前仿真文件接口在迁移完成前继续保留。

## 禁止事项

- 在多个模块分别实现DeepSeek HTTP请求；
- 在前端重新计算业务指标；
- 把`clear`直接等同于Agent必然接受；
- 用场景摘要中的重复共享基线数据计算实际兜底率；
- 为方便数据库设计而修改现有历史实验文件。
- 让不同策略场景读取不同的初始社交网络，或在场景间共享进场后的决策状态。
- 把公共评论抽样误记为邻居传播，或把“进入个人视野”直接当作Agent已经继续表达。
## 2026/10/19 接口增量

所有新字段均为向后兼容增量，旧 JSON/JSONL 无需迁移即可读取。新写入的评论建议完整提供：

```json
{
  "reaction_target": "official_claim",
  "evidence_role": "question",
  "information_source_type": "public",
  "information_origin": "exogenous",
  "provenance_type": "llm_incremental_public",
  "claim_id": "optional-claim-id",
  "root_id": "comment-or-expression-root"
}
```

`simulation_options.expression_window_rounds` 为正整数，默认 `3`，同时约束策略实验的邻居传播读取窗口和状态认知保留窗口。网络快照的 `nodes[]` 新增 `normalized_influence_weight`；邻居传播评论新增 `normalized_propagation_weight`。原始权重字段继续保留，前端不得用归一化字段替代节点影响力展示。

策略实验总结果使用因果对照清单：

```json
{
  "counterfactual_controls": {
    "shared_input_sha256": "...",
    "components": {
      "event_input_sha256": "...",
      "initial_comment_pool_sha256": "...",
      "social_network_sha256": "...",
      "objective_fact_timeline_sha256": "..."
    },
    "pre_entry_snapshot_sha256": "...",
    "public_reactions_shared": false,
    "scenario_reactions_independent": true,
    "cross_scenario_audit": {"status": "passed"}
  }
}
```

共同输入哈希必须在四个场景中一致；每个场景的 `scenario_input_sha256` 必须不同，且同时覆盖通告正文、声明状态和`official_evidence_dimensions`。通告投入后的公众反应读取当前场景通告和上一轮实际表达，并写入本场景自己的状态目录。任何旧式共享公众评论、错误 `scenario_id`、不同共同输入哈希、语义维度串场或状态目录复用都会使污染检查失败。`state_evidence_diagnostics` 额外输出外生/内生证据数；此处内生证据包括Agent表达以及受到本场景通告和讨论影响的公众反应。
