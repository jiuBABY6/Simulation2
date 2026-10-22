# 系统架构与代码地图

## 回应方案对照实验

```text
事件输入与官方策略
        ↓
事件角度规划与初始评论池
        ↓
共享进场前舆情基线
        ↓
动态进场条件判断
        ↓
三个回应方案＋不回应基线从同一状态分叉
        ↓
增量评论 → 邻居传播＋公共补充 → Agent决策 → 状态与指标
        ↓
策略效果、数据质量和性能结果比较
```

## 历史趋势复现

```text
事件初始资料＋第一轮人工评论环境
        ↓
公共事实广播＋个体语境曝光＋真实官方通告
        ↓
Persona稳定画像＋个体证据影响＋上一轮状态迟滞
        ↓
规则层裁决个体情绪转移与官方态度
        ↓
LLM解释既定状态、判断发言并生成原创表达
        ↓
实际表达 → 状态、传播与分层指标
```

历史入口不读取第2轮以后的真实评论或真实情绪比例，不使用本地群体配额、概率转移或坍缩熔断。

历史复现的默认对照对象是 Agent 实际发表的评论。内部情绪用于解释主体状态，生成评论池用于描述信息环境，二者都不替代实际表达。状态改变由 Persona、上一轮状态和该 Agent 当轮可用证据共同约束：证据客观强度与Persona个体影响分离，事件情绪和官方态度也彼此独立。历史路径继续使用`persona_decision_v3 / personalized_hysteresis_v3 / official_attitude_v3`。

回应方案对照使用独立的`strategy_directional_utility_v3`：状态证据先经过Persona个体影响评估，再按`reaction_target`路由到事件情绪、官方态度和公开参与三个通道，评论自身的正负标签不再无条件改写事件情绪。与事件伤害、后果和核实事实直接相关的证据可以进入事件情绪；对调查过程的质疑主要进入官方态度；一般公共讨论主要进入参与行为。同一传播根只计一次，最多三个独立根按`1.0 / 0.5 / 0.25`递减累积。官方通告按已完成行动、已核实事实、追责、关切回应和未决过程等维度组合。未推动变化的权威证据最多跨三轮处理，每轮新增吸收量由Persona事实偏好、质疑倾向、主题关注和状态惯性决定，并随证据轮龄衰减；一旦实际推动该Agent变化即标记为已消费。规则层继续融合Persona情绪先验、上一轮惯性和方向性证据效用，只允许保持或相邻变化。该路径不读取真实趋势、不设置群体配额，也不复用历史复现的状态裁决。

## 核心模块

| 文件 | 单一职责 |
| --- | --- |
| `main.py` | 回应方案对照实验统一入口 |
| `project_config.py` | 路径、模型和运行参数 |
| `experiment_runner.py` | 共享基线、动态进场、策略分叉和结果比较 |
| `application/runtime_config.py` | 回应方案对照与历史复现共用的单轮执行参数 |
| `application/error_summary.py` | 回应方案对照与历史复现共用的控制台错误摘要 |
| `application/scenario_state.py` | 创建隔离场景状态并复用基线快照 |
| `application/step_executor.py` | 封装仿真子进程和环境变量协议 |
| `application/round_results.py` | 统一读取轮次指标、评论质量和传播摘要 |
| `domain/contracts.py` | 定义仿真上下文、Agent决策输入和决策结果的数据契约，不包含文件读写和业务规则 |
| `comments/` | 评论角度、生成、校验与评论池访问 |
| `agents/` | Agent认知决策、原创表达、发言门控、批量决策、状态和Persona访问 |
| `agents/strategy_behavior.py` | 回应方案对照的Persona/状态发言门控，不修改内部认知 |
| `agents/strategy_expression.py` | 回应方案选择原创后，独立生成并校验三分类公开表达 |
| `agents/strategy_state_transition.py` | 编排回应方案的方向性情绪裁决、官方态度候选和审计记录 |
| `agents/strategy_evidence_integrator.py` | 纯函数整合语义方向、Persona先验、状态惯性、独立传播根和递减边际，输出唯一相邻情绪状态与诊断 |
| `agents/evidence_impact_router.py` | 根据评论目标、证据角色和信息来源，将证据作用分配到事件情绪、官方态度和公开参与通道 |
| `agents/strategy_evidence_assimilation.py` | 纯函数管理权威证据的Persona渐进吸收、轮龄衰减、消费和有界记忆 |
| `agents/strategy_evidence_lifecycle.py` | 纯函数持久化已见证据组和已消费传播根，并执行过期裁剪与记忆上限控制 |
| `agents/state_evidence.py` | 将完整个人可见评论转换为“最多2条邻居＋5条Persona相关公共评论”的状态证据视图，不改变行为与传播视图 |
| `agents/decision_profile.py` | 将Persona与群体分位数转换为稳定决策画像，并按个体门槛生成情绪迟滞约束 |
| `agents/evidence_appraisal.py` | 将客观证据与Persona主题、信息取向和状态惯性结合，分别生成情绪与官方态度的个体影响 |
| `agents/official_attitude.py` | 按事实证据、过程回应、未解决关切和上一轮状态裁决个体官方态度 |
| `simulation/` | 单轮运行、事件状态、个体语境曝光、传播、实验批次和状态隔离 |
| `simulation/options.py` | 集中校验事件级正式行为配置 |
| `simulation/counterfactual_controls.py` | 规范化共享客观事实，生成共同输入/基线快照哈希并执行场景污染审计 |
| `historical_replay/main.py` | 历史趋势复现入口 |
| `historical_replay/public_context.py` | 逐轮公众语境校验，拒绝数值拟合目标 |
| `historical_replay/replay_runner.py` | 历史时间线编排和结果汇总；只依赖共享应用层，不依赖回应方案对照编排器 |
| `historical_replay/run_manifest.py` | 保存输入、核心代码、模型、随机种子和Persona画像指纹 |
| `evaluation/metrics.py` | Agent内部状态、实际表达、趋势和过程效果指标 |
| `infrastructure/llm_service.py` | HTTP请求、JSON解析、重试和性能统计 |

## 核心目录速查

| 目录 | 当前职责 |
| --- | --- |
| `demo/` | 仿真入口、输入配置和实验编排 |
| `demo/application/` | 两类实验共用的运行配置、场景状态、子进程执行和轮次结果服务 |
| `demo/domain/` | 仿真上下文、决策输入输出和评论语义等共享数据对象 |
| `demo/comments/` | 初始评论、增量评论、角度规划和评论池访问 |
| `demo/agents/` | Persona读取、证据评估、状态裁决、发言门控和表达生成 |
| `demo/simulation/` | 单轮执行、固定网络、传播、场景隔离和运行选项 |
| `demo/evaluation/` | 逐轮与场景级指标 |
| `demo/infrastructure/` | DeepSeek请求和其他基础设施 |
| `demo/historical_replay/` | 历史事件仓库、时间线校验和连续回放 |
| `demo/experiments/` | 不可覆盖的实验输入、状态和结果快照 |
| `persona_pipeline/` | MongoDB数据清洗、分类、Persona和策略配置生成 |
| `output/personas/` | 仿真只读加载的Agent Persona与`policy_config.json` |
| `visualization/` | 历史复现、方案对照和共享网络的只读网页 |

`demo/state/`只用于默认调试状态；正式实验必须使用批次目录中的独立状态。`demo/example/`只提供结构示例，不是正式输入。早期原型和外部参考工程不属于当前运行链路。

## 状态边界

- `output/personas` 是长期画像，只读加载；
- `demo/state` 是默认临时状态，正式实验使用批次内独立状态目录；
- `demo/experiments` 保存不可覆盖的输入、状态和结果快照；
- 三个回应方案与不回应基线共享进场前基线，进场后场景彼此隔离；
- 历史趋势复现拥有独立入口和事件目录，不调用回应方案对照分叉。

## 可视化三层结构

```text
统一入口与模式选择
        ↓
┌──────────────┬──────────────┐
│ 历史复现层   │ 方案对照实验层 │
│ historical/  │ strategy/    │
└──────┬───────┴──────┬───────┘
       └──── shared/network ────┘
        实验适配、社交网络、评论传播链
```

- `visualization/historical/` 只负责历史结果、真实趋势与探索性对照；
- `visualization/strategy/` 只负责回应方案对照的逐轮和横向指标；
- `visualization/shared/` 负责实验目录适配以及两种模式共用的网络能力；
- `visualization/shared/artifact_io.py` 统一只读加载和校验 JSON/JSONL；
- `visualization/shared/event_resources.py` 统一事件资源编号和安全路径规则，避免共享层反向依赖历史业务层；
- `visualization/api_router.py` 负责 API 参数校验和三层服务分发；
- `visualization/app.py` 是唯一 HTTP 入口，不包含业务指标计算。

## 依赖方向与解耦原则

```text
命令行或HTTP入口
        ↓
实验编排或API路由
        ↓
共享应用服务与领域服务
        ↓
文件、子进程、LLM等基础设施
```

- 上层可以依赖下层，下层不能反向导入某一种具体实验的顶层入口；
- `demo/application/` 是方案对照与历史复现的共享应用层，历史复现不反向依赖 `experiment_runner.py`；
- `demo/domain/contracts.py` 定义 `SimulationContext`、`AgentDecisionInput` 和 `AgentDecisionResult`，决策核心通过参数接收上下文，不自行定位仿真文件；
- `project_config.py` 仍是兼容配置源，应用层通过运行配置对象逐步减少全局配置依赖；
- 可视化共享层只提供只读数据和网络能力，`historical/` 与 `strategy/` 依赖共享层，共享层不反向导入业务层；
- Persona流水线的清洗、策略汇总和DeepSeek JSON客户端分别位于 `text_processing.py`、`policy_builder.py` 和 `deepseek_json_client.py`；
- 旧函数名和JSON/JSONL字段在兼容门面处保留，重构不能隐式改变实验口径。

后续继续解耦时，应先迁移剩余全局配置和存储访问，再拆分超长编排函数；不要在同一个提交中同时调整模块边界与Agent业务机制。

## LLM与本地逻辑边界

LLM负责事件角度、评论文本、历史首轮情绪初始化、历史既定状态解释和全局趋势判断。历史模式保留原有完整决策请求；回应方案对照拆成状态请求和按需原创表达请求：状态请求不包含发言意愿、动作或文本，行为门控与原创/转发选择由本地代码独立完成，只有选择原创时才调用表达生成。本地代码还负责证据边界校验、根传播链去重、时间/深度衰减、兜底、进场规则、指标公式和结果存储；这些约束不设置群体比例或拟合目标。所有网络请求经过 `infrastructure/llm_service.py`。

## 2026/10/19 六项现实机制的模块边界

本轮改造没有再建立一套平行决策系统，而是在现有分层上增加四个单一职责组件：

- `domain/comment_semantics.py`：统一评论目标、证据角色、现实来源和内生/外生属性，只做纯数据规范化。
- `agents/strategy_attitude_lifecycle.py`：维护官方态度专用的有限证据记忆，不负责最终态度裁决。
- `simulation/social_network.py`：保留原始影响力并生成认知层归一化权重；传播层只消费查询接口。
- `simulation/counterfactual_controls.py`：只固化事件、初始评论、固定网络、客观事实时间线和进场前快照；不生成公众反应。
- `experiment_runner.py`：从同一进场前快照分叉四个场景，通告投入后分别运行并执行污染审计。

策略实验的单轮数据流为：

```text
共同事件、初始评论、网络与客观事实
  -> 个人网络曝光（最近 3 轮）
  -> 当前场景官方通告与独立公众反应
  -> 评论语义规范化
  -> 情绪证据生命周期 / 官方态度证据生命周期
  -> Persona 个体裁决
  -> 沉默、原创或转发
  -> Agent 内生表达进入后续网络传播
```

共同输入只包含不受方案影响的客观信息。公众反应不是共同外生输入：它必须读取当前场景已经公开的通告和上一轮Agent实际表达，并保存在本场景目录。四个场景仍使用相同客观事实、Persona、网络、初始评论和进场前快照；因此差异来自官方干预及其后续个体、公众和网络反应，而不会出现“通告已经发布，评论仍声称没有官方信息”的上下文冲突。

情绪状态与官方态度仍是两条独立状态链。情绪证据允许在有限吸收期内推动一次相邻状态变化；官方态度记忆则允许事实结论持续存在，同时要求新证据才可触发 `accept / wait / question` 的变化。公众支持不能证明官方事实，公众质疑可以作为弱关切信号。
