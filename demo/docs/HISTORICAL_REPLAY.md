# 历史趋势复现

历史趋势复现采用一条主线：在真实时间阶段中依次投入当时可见的公众语境和真实官方通告。第一轮情绪由LLM初始化；后续轮次由规则层结合 Persona、个人可见模拟评论与上一轮状态裁决情绪转移和官方态度。LLM解释既定状态、决定是否发言，并在发言时生成原创表达。

当前主线不提供额外的“旧回放”配置，不使用本地概率转移、稳定分层、比例上限或群体坍缩熔断。结果可能自然出现高度一致甚至单一类别；系统如实保存结果，不因分布过于集中而把实验标记为失败。

## 输入边界

回放使用：

- 事件初始资料；
- 第一轮人工情绪比例，仅用于构造初始公共评论池；
- 每轮当时可见的已核实信息、公众议题与建设性证据；
- 官方通告的真实内容及首次发布时间。

第2轮以后不读取真实评论文本，也不读取真实正面、中性、负面比例。真实趋势只在运行完成后用于探索性对照，不进入 Agent 决策，不能把对照指标解释为独立预测准确率。

## 事件目录

```text
demo/historical_replay/events/<event_id>/
├── event_manifest.json
├── event_input.json
├── initial_opinion.json
├── public_context_timeline.json
├── official_response_timeline.json
└── real_trend_source.xlsx（可选，仅用于可视化）
```

- `event_input.json`：第一阶段已经公开的事件信息和通用模拟参数；
- `initial_opinion.json`：第一轮人工情绪比例和整数评论配额；
- `public_context_timeline.json`：逐轮同期公众语境，必须覆盖全部轮次；
- `official_response_timeline.json`：真实阶段、时间范围和官方通告节点；
- `real_trend_source.xlsx`：人工趋势来源，历史回放入口不会读取。

`active_event.json` 只决定省略 `--event-id` 时的默认事件。正式运行建议显式指定事件编号。

## 运行

```powershell
conda activate persona_sim
python demo\historical_replay\main.py --list-events
python demo\historical_replay\main.py --event-id event_huxinyu_2022_001
```

每次运行都会在 `demo/experiments` 新建批次，不覆盖既有实验。

## Agent 响应机制

每轮先更新公众语境和官方通告，再调用共享模拟流程：

```text
初始事件＋第一轮人工评论池
        ↓
公共事实广播＋个体公众语境曝光＋本轮适用的真实官方通告
        ↓
Persona稳定决策画像＋个体证据影响＋上一轮状态迟滞
        ↓
规则层裁决情绪转移和官方态度 → LLM解释状态并判断发言意愿
        ↓
状态转移校验＋发言资格评估
        ↓
原创表达或沉默 → 状态、传播和指标
```

`emotion_choice_mode=evidence_based_all` 表示三种情绪均属于基础状态空间。首次情绪由LLM在完整状态空间内完成语义初始化；后续先由证据门槛开放相邻状态，再按Persona效用和个体切换边际形成唯一情绪结果，LLM不得机械保留或覆盖。首次进入正面或从其他状态转为正面时仍需引用支持建设性表达的证据。官方态度和事件情绪分别判断，接受官方通告不等于情绪自动转为中性或正面。

历史复现还执行以下最小状态约束：

- Persona 是长期决策先验，LLM 必须记录本轮实际使用的 Persona 因素；
- 系统利用`policy_config.json`中的群体分位数，把主题偏好、信息取向、情绪表达和行动偏好转换为稳定的`persona_decision_profile`；不添加随机人格标签，也不强制群体分散；
- 每名Agent具有独立的情绪变化门槛、状态惯性、官方态度变化门槛、通告接受门槛、未解决关切门槛、过程满意门槛、公共意见敏感度和表达门槛；系统不从人口属性虚构“官方来源信任”等Persona中不存在的特征；
- 上一轮情绪和官方态度是默认基线，改变状态必须引用本轮新增证据；
- 事件首次出现官方声明时，上一轮`not_applicable`不作为态度惯性；规则层直接按个体证据和门槛形成首次态度，不再把三个相同候选交给LLM自由选择；
- `verified_updates`按`background`、`moderate`、`strong`区分状态延续、阶段进展和关键事实；缺少元数据的旧记录按`moderate`处理，不再默认全部为强证据；
- 同一客观证据会分别计算情绪影响和官方态度影响。事实型、观点型和质疑型Persona按证据对象进行加权组合，不再用最大取向抹平差异；同一事实的通告与摘要通过`claim_id`归为一组，并按递减边际合并，避免重复计数和数量饱和；
- 情绪证据和官方态度证据分别记录，不能由情绪反推官方态度；
- 规则层先生成`decision_guard`。后续情绪由`emotion_resolution`形成唯一合法结果；官方态度由`official_attitude_resolution`形成唯一合法结果，并同时保存`claim_position`与`process_evaluation`。过程评价没有新过程证据时保持上一轮值，有新证据时按迟滞更新。两条路径互不代替；
- 新官方通告会按句子拆成至多6个可引用证据点，并按事实核实、调查过程、责任处理、社会行动等对象标注。各片段仍共享同一`evidence_group_id`，不能被重复计算为多条独立证据；
- 社交评论证据严格限制在该 Agent 的个人可见评论集合中，未曝光评论不能用于决策；评论影响受该Agent的公共意见敏感度约束，邻居传播边权最多作有限调节，不能取代客观事实证据。
- 已核实事实和官方通告对所有 Agent 广播；公众讨论和建设性证据按固定种子进行个体曝光，决策记录保存实际可见的语境证据编号；
- Agent 发言时不再从评论池挑选文本，而是生成不超过280字的原创表达；表达情绪可以与内部情绪不同，表达证据必须属于该 Agent 的可用证据；
- 内部情绪与公开表达使用独立字段；公开表达使用完整基础情绪空间，因此Agent可以保持中性内部状态但发表有证据支持的负面或正面表达；
- 历史模式默认让每名 Agent 固定关注5名邻居，每轮目标曝光为4条邻居表达和11条公共评论。第一轮没有上一轮 Agent 表达，因此实际为0条邻居表达和15条公共评论；后续轮次如果邻居沉默或可用表达不足，由公共评论补足，总上限仍为15条；
- 历史公共评论按主题、信息取向、情绪表达和派系偏好进行固定种子加权抽样，同时保留探索基线，低偏好内容仍可能被看见；
- 内部状态与公开表达分开处理。LLM决定发言后，系统再根据相关新证据、状态变化、个体证据影响、近三次表达相似度和连续发言轮数评估公开表达必要性；状态变化只增加动机、不保证发言，强证据也不绕过疲劳和重复约束。评分不读取当前情绪类别对应的历史表达率，三种情绪使用相同的相关性、新颖性和疲劳标准；

这些约束不指定群体比例，也不强制某个 Agent 改变状态；其作用是防止公共评论多数机械覆盖 Persona 和个人历史。

## 输出

```text
demo/experiments/<experiment_id>/
├── event_input.json
├── initial_opinion.json
├── public_context_timeline.json
├── official_response_timeline.json
├── comment_pool.json
├── run_manifest.json
├── historical_replay_result.json
└── historical_replay/
    ├── historical_replay_result.json
    └── state/
        ├── social_network_snapshot.json
        ├── propagation_history.jsonl
        ├── decision_history.jsonl
        ├── metrics_history.jsonl
        └── ...
```

新结果使用 `mode=historical_replay` 与 `public_context_enabled=true`。逐轮 `public_context` 保存当轮原始输入快照；每条决策的 `visible_context_evidence_ids` 保存个体实际曝光，`visible_neighbor_comment_ids`、`visible_public_comment_ids` 与 `public_sampling_method`记录评论来源。历史决策的`persona_decision_profile`保存`persona_decision_v3`稳定画像；`decision_guard`保存`personalized_hysteresis_v3`约束；`emotion_resolution`保存`emotion_transition_v1`裁决、个体效用边际与实际证据；`official_attitude_resolution`保存`official_attitude_v3`裁决、事实立场、过程评价、门槛与实际证据。`evidence_appraisal`保存实际引用证据的客观强度、作用对象和Persona个体影响。状态中不保存连续情绪值或跨轮准备度。发言评估保存在`participation_assessment`，其中`emotion_independent_scoring=true`表示发言评分不奖励特定情绪。`run_manifest.json`记录输入、代码、模型、温度、种子和Persona画像哈希，不记录API Key。

根目录保存输入快照和汇总结果，`historical_replay/state` 保存逐轮状态。二者职责不同，不是重复数据。

## 真实趋势与可视化

如果事件提供人工 Excel，单独执行：

```powershell
python visualization\historical\real_data_processor.py --event-id <event_id>
```

输出位于 `visualization/data/real_trends/<event_id>.json`。历史页面默认使用“Agent实际表达”与真实评论比较：只有 `will_comment=true` 且存在最终 `selected_comment` 的决策进入分布，分母为具有合法三分类标签的实际表达。Agent内部情绪、当前轮生成评论、最近若干轮活跃评论和模拟评论池累计均保留为诊断口径，但不作为默认拟合口径。

## 与回应方案对照实验的隔离

- 回应方案对照入口是 `demo/main.py`，历史入口是 `demo/historical_replay/main.py`；
- 回应方案对照不读取 `historical_replay/events`、人工初始比例或逐轮公众语境；
- 历史入口不读取 `official_response_options.json`，也不执行三种回应方案与基线的场景分叉；
- 两条入口共享评论生成、Agent 决策、传播和指标基础设施，因此共享模块的通用修复会同时生效，但历史事件输入不会进入回应方案对照实验。

## 2026/10/10 修改说明

在当前主线上恢复 LLM 直接历史回放：删除条件化本地响应、概率限制和群体坍缩熔断；移除额外的历史响应模式配置和独立客观事件时间线；保留第一轮人工初始化、逐轮公众语境及真实官方通告。既有实验目录保持不变。

## 2026/10/12 修改说明

历史复现主对照改为 Agent 实际发表的评论，并保存表达数量、沉默人数、有效分类分母和三分类分布。Persona、上一轮状态和个人曝光由提示约束提升为可校验契约：状态变化需要本轮新增证据，正负跨级需要对当前Persona足以支持完整重新判断的证据，情绪与官方态度分别引用依据。Agent 在同一次决策调用中生成原创表达；公共事实与个体语境分离。

历史事件可以通过 `simulation_options.network.neighbors_per_agent` 单独覆盖关注人数，默认5人；`visibility`默认目标为4条邻居表达与11条公共评论。系统在启动前拒绝“邻居评论目标大于关注人数”的不可能配置。原创表达若在 `evidence_ids` 中明确引用个人可见的邻居表达，会继承父表达、根表达和传播深度，使第二跳及后续传播能够被正确追踪。发言资格评估只抑制缺少新动机的重复公开表达，不修改Agent内部状态，也不设置沉默配额。回应方案对照继续使用全局网络配置、均匀公共评论抽样和候选评论选择，不执行历史发言资格评估。

2026/10/12进一步修正证据机制：新官方声明不再天然等于强证据，`incomplete`默认按阶段性证据处理，持续声明按背景信息处理；历史已核实更新必须使用可审计的`update_kind`和`evidence_strength`。Persona个体影响只决定状态变化许可，不直接指定情绪、官方态度或群体比例。

## 2026/10/13 修改说明

2026/10/14 已按实验`event_huxinyu_2022_001_20261013_181206_806798`恢复稳定Persona画像与离散迟滞机制。公共评论影响受个体公共意见敏感度限制，同一事实组只保留个人影响更强的一项。第一轮由LLM完成初始判断，后续轮次先由规则层根据Persona门槛和新增证据开放候选，再由LLM在候选内判断并生成表达。该机制只接入`evidence_based_all`历史路径，回应方案对照的候选评论选择保持不变。离线契约和回归测试已通过；自然演化效果仍需重新运行完整DeepSeek历史批次后验证。

同日增加无语义损失的LLM输出规范化：`will_comment=false`时自动丢弃多余表达并补全空派系；没有官方通告时可补全空态度证据数组。每次修复写入`output_normalizations`。决定发言却缺少表达或派系、存在通告却缺少态度依据等实质错误仍会重试并在最终失败时终止本轮。

## 2026/10/14 修改说明

官方态度改由本地个体规则最终裁决，LLM只解释裁决并生成表达。事实结论立场与回应过程评价分别保存，`clear`不再自动等同强证据；标记为未解决关切的材料只进入关切通道，不会同时虚增“过程已覆盖”程度，因此允许出现“接受事实结论但不满处置过程”。证据亲和度采用目标相关加权组合，同一事实组按递减边际聚合，邻居边权只有限调节个人评论影响。发言门控不再因状态变化而保证公开表达。

逐轮指标新增官方态度熵、最大群体占比、同步转向率、事实立场分布和过程评价分布。这些字段只用于诊断，不是群体配额或熔断条件。完整实验另存`run_manifest.json`用于比较输入和机制是否真正一致。新机制只在历史`evidence_based_all`路径启用，回应方案对照继续使用自身的官方态度和候选评论路径。

同日进一步升级为`persona_evidence_replay_v3`：第一轮情绪仍由LLM初始化，后续情绪在证据越过个人门槛后由个体效用边际最终裁决，解决候选开放后仍机械保持的问题；发言评分移除当前情绪对应表达率，避免负面状态天然更易发言；过程评价在无新过程证据时跨轮保持，并使用迟滞抵抗弱噪声；质疑门槛按Persona重新校准，且不再被更高的通用态度门槛重复否决。以上修改不读取真实趋势、不设置群体目标比例，也不进入回应方案对照决策路径。
