# 舆情社会模拟 Demo 开发记录

## 一、当前项目状态

### 已完成功能

- 已完成实验批次创建、状态初始化、状态校验和不同策略的数据隔离。
- 已完成事件角度规划、初始评论池生成、五类评论派系覆盖和后续轮次增量评论生成。
- 已完成 Agent 个人可见评论构建、受约束 LLM 认知决策、候选评论评分和最终表达选择。
- 已完成 Agent 动态状态、个人评论历史以及声明和评论证据时间语义保存。
- 已完成官方动态进场、不回应基线和四种官方内容策略对照。
- 已完成负面率、官方态度分布和五项单批次过程指标计算。
- 已完成独立的历史趋势复现模式，可以按照指定轮次投入多次官方信息。
- 已完成历史复现结果、评论池趋势和人工整理真实趋势的只读网页展示。
- 已完成多轮正式联调、评论数量稳定补齐、失败隔离和数据质量分级。
- 已完成 Demo 分阶段耗时、分类 LLM 请求、HTTP 尝试和重试次数统计，并建立首份完整五策略性能基线。
- 已完成核心代码按评论、Agent、仿真、评估和基础设施五个领域分包，主入口和数据结构保持不变。
- 已完成固定社交网络、Agent影响力权重、邻居评论传播、公共评论补充和个人可见范围内表达；五策略共享同一网络快照并独立演化。
- 已完成传播事件持久化、表达谱系、传播层级与权重衰减，以及覆盖人数、继续传播次数和最大传播深度等指标。
- 已完成第二十六次联调社交网络传播专题网页，可只读查看逐轮信息流、Agent节点表现和单评论传播链。

### 暂缓与未完成功能

- 同一事件内和跨事件的适应性画像更新暂缓，基础 Persona 当前不会被仿真过程修改。
- 固定官方回应时机的策略对照实验暂缓；历史趋势复现中的指定轮次投入不等同于该实验。
- “内容策略 × 声明状态”的完整组合实验尚未实施。
- 多批次运行稳定性指标尚未实现，`calculate_run_stability()`继续保留为占位函数。
- 数据库、后端接口、任务队列和生产级并发调度尚未开始建设。
- 动态关注关系和基于真实传播数据的参数校准尚未实施。

### 当前主要问题

- 自适应质量救援已经把优化后实际兜底率控制到 2.0%～11.0%，单个增量轮次耗时保持在 11.647～13.857 秒，当前性能方案已完成同事件三次验证和第二事件首次验证。
- 当前运行结果仍以 JSON 和 JSONL 为主，尚未建立数据库、后端接口、任务队列和生产级并发调度。
- 五个策略仍按顺序运行；总耗时会随官方进场轮次和实际增量轮次数量变化，比较性能时必须使用单位增量轮次耗时。
- 适应性画像、动态社交关系、传播参数校准和固定进场时机实验仍属于后续扩展，不应与数据库和后端第一阶段混合开发。
- 代码交给团队前仍需完成密钥环境变量化和可复现依赖清单，真实密钥不得进入共享代码。
- 第二十六次联调中五个场景传播覆盖率均为100%，且10个Agent每轮均实际表达；当前小规模密集网络下覆盖指标区分度有限，后续需通过更多Agent、网络稀疏度和Agent活跃性参数验证。

### 下一步唯一工作

冻结已经通过第二十六次五策略联调的第二阶段A数据契约，设计数据库表及现有JSON/JSONL到数据库字段的映射；暂不混入动态关注关系和传播参数校准。

## 二、系统核心设计

### 基础设定

官方声明、声明类型、事件内容和事件标签由人工或实验策略模块指定。

当前 Demo 的主要输入包括事件材料、公众人物画像、官方回应方案和实验运行参数。基础 Persona 从 `output/personas` 只读加载；每次实验创建新的批次目录，保存事件、初始评论池、官方回应方案和固定社交网络快照，避免覆盖历史结果。

当前五策略联调默认使用 10 个时间步、10 个 Agent、5 个 Agent 工作线程，每轮目标生成 20 条增量评论。

### 评论生成

当前采用“事件角度任务 + 评论派系 + 人物类型”的评论生成流程：先根据事件正文形成事件专属角度，再为每条评论分配角度任务，由 LLM 在指定角度下生成评论文本并选择合适的派系和人物类型。

初始评论池目标为 60 条评论，并检查五类评论派系覆盖。第 2 轮起，根据事件、当前官方声明、上一轮 Agent 实际表达、上一轮增量评论分布和历史避重文本生成本轮增量评论。

生成结果经过任务编号、人物类型、派系、字段完整性和全历史重复文本校验。有限重试后数量仍不足时，先使用合格历史评论补齐，必要时使用可识别的本地应急评论，并记录 `normal`、`degraded` 或 `emergency` 数据质量状态。

#### 生成评论的三种策略

- QLoRA 微调：缺点：评论没有逻辑性
- 评论池 → 打分
- 提示词工程：缺点：评论覆盖不够丰富

#### 黑板设计

能否根据

我设想是，全局候选评论集合 `comment_pool.json` 是所有 agent 都能看见，然后选择一个最合适的评论作为代表该 agent 的评论。黑板上的评论是所有 agent 选择的那一条评论的集合，而对于黑板上的评论，agent 可以看见自己选择的那一条以及有概率地看见剩下的评论。

公共黑板保存当前平台上的全局候选评论，但不再代表每个Agent都能完整看见。每个Agent按照固定关注关系优先接收邻居上一轮实际表达，再由公共评论补足可见数量。邻居表达按发布者影响力权重抽样；同一实验的五个策略读取同一网络快照，进场后只隔离评论、状态和指标。

### Agent决策

每个 Agent 每轮读取事件内容、当前官方声明及时间信息、个人可见评论、上一轮状态和个人历史评论。LLM只负责形成情绪、官方态度、评论意愿和评论派系等认知判断，最终表达仍由本地决策引擎完成筛选、评分和可复现选择。

个人可见评论默认最多15条，其中基础目标为邻居传播4条、公共评论补充11条；邻居表达不足时由公共评论补足。公共评论仍优先覆盖当前轮新评论，Agent自己此前所有实际表达作为个人历史参与后续判断，但不会再次被选为新的表达。最终候选筛选、评分和Top-K选择严格限制在本轮个人可见评论内。

```text
               agents/decision_engine.py
                    决策核心逻辑
                     ↑      ↑
                    /        \
agents/rule_decision_demo.py  agents/decision_service.py
单Agent本地规则决策          单Agent受约束LLM决策
        ↓                           ↓
example/decision_result.json  example/decision_result_llm.json
        ↓                           ↓
        └────── agents/state_store.py ──────┘
                  保存Agent动态状态

agents/batch_decision.py
批量调用受约束LLM决策
        ↓
decision_history.jsonl
        ↓
agents/state_store.py
```

### 官方动态进场

五策略实验先运行一条共享的官方进场前舆情基线，再根据本轮指标判断官方是否在下一轮进场。当前组合进场规则包括：

1. 负面率达到阈值，进场原因记录为 `negative_threshold`；
2. 全局趋势为恶化，进场原因记录为 `global_worsening`；
3. 舆情连续多轮没有明显改善，进场原因记录为 `stagnation`。

第 1 轮只作为比较基线，不计入连续停滞轮数。系统不设置强制最晚进场轮次；如果所有动态条件始终没有触发，回应场景标记为 `not_run`，不参与策略效果比较。

### 策略对照

当前实验包含不回应、事实通报、共情安抚、辟谣澄清和处置进展五个场景。五个场景共享相同的事件、初始评论池、固定社交网络和进场前状态，在官方触发进场后从同一状态快照分叉，分别保存在独立目录中继续演化。

四个回应场景使用相同的动态进场规则和进场轮次，每个场景只首次写入一次官方声明，后续轮次继续沿用该声明。实验结束后比较最终指标、过程指标和评论数据质量；指标相同时返回全部并列策略，不将排序后的第一个策略错误表示为唯一最佳策略。

### 指标计算

每轮指标同时描述宏观评论环境和微观 Agent 状态。宏观趋势根据初始评论及当前轮增量评论分析舆情变化；微观指标根据 Agent 决策和状态历史统计负面率以及接受、等待、质疑等官方态度分布。没有官方声明时，官方态度为 `not_applicable`，接受率和质疑率不参与比较。

当前单批次过程指标包括：

- 情绪恢复率；
- 效果持续时间；
- 舆情反弹率；
- 负面峰值和累计负面量；
- 相对不回应场景的对照净效果。

社交传播指标独立描述传播过程，不直接判断策略好坏：`exposure_count`表示邻居表达进入个人视野的次数，`reached_agent_count`和`reach_rate`表示覆盖Agent数量及比例，`continued_propagation_count`表示被目标Agent继续表达的次数，`max_propagation_depth`表示最深传播层级。第一跳使用发布者完整影响力权重，后续每增加一层按网络快照中的`propagation_decay_factor`衰减；当前默认值为0.7。

实验结果还保存模型生成评论数、历史兜底数、应急兜底数、质量状态和告警轮次，用于区分“策略效果”和“评论数据质量”。多批次稳定性分析尚未实现。

### 历史趋势复现

历史趋势复现代码独立保存在 `demo/historical_replay`，不修改原有五策略入口，也不使用动态进场规则和内容策略对照。它按照 `official_response_timeline.json` 中指定的轮次依次投入官方信息，只运行一条连续的历史路线。

该模式复用现有评论生成、Agent 决策、状态管理和指标计算核心。每次运行都在 `demo/experiments` 中创建不可覆盖的新批次，并生成 `historical_replay_result.json`。历史复现失败只影响本次批次，不影响 `python demo/main.py` 和已有实验数据。

`visualization` 目录提供独立只读网页：加载历史复现结果和评论池指标，并将其与 `demo/historical_replay/example.xlsx` 处理得到的人工群体趋势进行阶段对照。真实趋势只作为公开材料的人工整理参考，不用于推断个人态度或认定案件事实；原始官方材料集中保存在 `demo/historical_replay/official.md`。

## 三、阶段性成果

### 2026/09/03 公安部门阶段性成果汇报

已完成一次面向公安部门的项目阶段性成果汇报。本次汇报围绕项目背景、技术方案、核心技术、历史案例验证和后续工作展开，主要展示：

1. 事件材料、公众人物画像、官方回应方案和实验参数组成的输入体系；
2. 评论生成、信息可见、Agent 状态判断、候选筛选与表达、环境更新和指标判断组成的仿真闭环；
3. 共享进场前基线、官方动态进场和五种内容策略对照方法；
4. 负面率、质疑率、接受率以及恢复、持续、反弹和累计负面等指标；
5. 历史事件中多次官方信息按指定轮次投入的复现方式；
6. 模拟 Agent 趋势、模拟评论池趋势和人工整理真实趋势的可视化对照结果；
7. 当前 Demo 的能力边界、数据质量问题、运行耗时和数据库及后端建设计划。

本次汇报完成了阶段性成果展示和需求沟通，不等同于项目最终验收。阶段汇报后，项目由继续扩充仿真功能转入性能测量、运行优化和工程化建设准备阶段。

## 四、历史开发记录

### 2026/08/17 评论池读取和 Agent 决策适配

| 文件 | 保存内容 |
| --- | --- |
| `example/decision_result.json` | 最近一次单 Agent 本地规则决策 |
| `example/decision_result_llm.json` | 最近一次单 Agent LLM 决策 |
| `decision_history.jsonl` | 所有 Agent、所有时间步的完整 LLM 决策 |
| `agent_state_history.jsonl` | 给下一轮使用的精简 Agent 状态 |

2026/08/17 建立独立的评论池读取模块 `comment_pool_repository.py` √

修改单 Agent 本地规则决策，当前结果保存在 `example/decision_result.json`，`agent_decision_demo.py` √

修改单 Agent LLM 决策，当前结果保存在 `example/decision_result_llm.json`。

`example/decision_result_llm.json` 的 `decision` 字段：

- 为什么产生这种情绪；
- 为什么对官方声明持这种态度；
- 为什么选择这条评论。

`agent_decision_llm_demo.py` √

修改批量 Agent 决策，会产生 `decision_history.jsonl`、`agent_state_history.jsonl`。

`decision_history.jsonl` = 完整事实记录。

`agent_state_history.jsonl` = 决策所需的精简状态。

`batch_agent_decision.py` √

统一 Agent 状态保存：修改 `demo/agent_state_store.py`，删除 `demo/agent_state_history.jsonl` 和 `demo/state/agent_state_history.json`，新建示例文件 `demo/state/agent_state_history.jsonl` √

### 2026/08/17 21:47 计划

1. 重写 `propagation.py`
2. 将 Agent 可见评论接入批量决策
3. 清理旧 `candidate_comments.json` 和预览历史
4. 实现增量评论生成
5. 实现 `metrics.py`
6. 实现 `simulation_runner.py`
7. 实现 `experiment_runner.py`
8. 最后统一更新 README 和接口文档

### 2026/08/18 9:20

1. 重写 `propagation.py`

   公共黑板基础数据

   - 事件
   - 当前官方声明
   - 当前声明类型
   - 全局候选评论

   ↓ 可见性筛选

   Agent 个人黑板视图

   - 事件
   - 当前官方声明
   - 当前声明类型
   - Agent 自己上一轮的评论
   - 随机可见的其他评论

### 2026/08/20

1. 重写 `propagation.py`，修改 `propagation.py`、`project_config.py`

   - 随机可见机制：当前版本
   - 偏好推荐机制：后续扩展

   评论抽取不依赖 Persona、情绪、地域等身份特征，但建议使用 `agent_id` 生成随机种子。

   Agent_001 得到一组随机评论。

   Agent_002 得到另一组随机评论。

   相同实验重复运行时结果保持不变

   主要功能：

   - 构建当前轮公共黑板；
   - 为每个 Agent 生成个人可见视图。

2. 将 Agent 可见评论接入批量决策，修改 `batch_agent_decision.py`

   主要功能：

   - 读取基础数据；
   - 构建公共黑板；
   - 为每个 agent 构建个人视图；
   - 把可见评论交给 LLM；
   - 并发执行多个 agent；
   - 失败重试；
   - 保存可见评论 id
   - 保存历史数据：`decision_history.jsonl`、`agent_state_history.jsonl`

3. 清理旧 `candidate_comments.json` 和预览历史

   删除：

   - `demo/candidate_comments.json`

   清空：

   - `demo/state/decision_history.jsonl`
   - `demo/state/agent_state_history.jsonl`

   Python 代码：

   - 不需要修改

   暂时没有执行清空，执行删除 `demo/candidate_comments.json`

4. 实现增量评论生成

   新建：

   - `demo/incremental_comment_generator.py`
   - `state/incremental_comment_history.jsonl`

   修改：

   - `demo/project_config.py`
   - `comment_pool_repository.py`
   - `batch_agent_decision.py`

5. 实现 `metrics.py`

   - `demo/metrics.py`
   - `demo/state/metrics_history.jsonl`

   `metrics_history.jsonl` 字段含义：

   - `event_id`：事件编号；
   - `step`：指标所属时间步；
   - `is_example`：表示这是一条示例记录；
   - `global_trend`：LLM 对全局评论变化的判断；
   - `trend_direction`：改善、稳定或恶化；
   - `reason`：LLM 给出的趋势原因；
   - `evidence_comment_ids`：支持判断的评论 ID；
   - `agent_count`：成功参与统计的 Agent 数；
   - `negative_count`：负面 Agent 数量；
   - `negative_rate`：负面 Agent 比例；
   - `accept`：接受官方声明；
   - `wait`：等待更多信息；
   - `question`：质疑官方声明

   宏观层：全局评论变化。

   数据来源：`comment_pool.json`、`incremental_comment_history.jsonl`

   微观层：Agent 个体变化。

   数据来源：`agent_state_history.jsonl`、`decision_history.jsonl`

   `introduced_step` 表示一条评论第一次进入全局评论环境的时间步。

   外层 `step`：这一批增量评论在哪个仿真轮次生成；

   内层 `introduced_step`：某条评论从哪个时间步开始进入公共黑板。

   全局评论池
   ↓
   本地统计每轮情绪、立场、派系
   ↓
   LLM 分析主题变化和官方声明效果
   ↓
   得到宏观舆情趋势

   Agent 历史状态
   ↓
   本地统计情绪与态度转移
   ↓
   选择典型 Agent 进行个体轨迹分析
   ↓
   得到微观反应差异

   初期 demo：

   1. 统计全局舆情趋势，LLM 分析初始评论和增量评论
   2. Agent 负面情绪率
   3. Agent 对官方态度分布

   后续扩充：

   - 情绪恢复率：多少 Agent 从负面转为中性或正面；
   - 效果持续时间：安抚效果能维持多少轮；
   - 舆情反弹率：短暂缓和后重新转为负面的比例；
   - 负面峰值与累计负面量：用于比较不同回应时机；
   - 对照实验净效果：比较“有官方声明”和“无官方声明”的差异；
   - 多次运行稳定性：不同随机种子下结果是否稳定。

6. 实现 `simulation_runner.py`

   - `demo/simulation_runner.py`
   - `demo/state/metrics_history.jsonl`

   执行一个完整的时间步：

   1. 读取当前事件状态
   2. 检查当前时间步
   3. 第 1 轮不生成增量评论，第 2 轮以后生成增量评论
   4. 运行批量 Agent 决策
   5. 保存 Agent 决策和动态状态
   6. 计算本轮舆情指标
   7. 返回本轮汇总结果

7. 实现 `experiment_runner.py`

   首次回应

   - 不回应策略
   - 负面率阈值策略
   - 全局判断

   补充回应

   - 官方质疑率阈值策略
   - 不回应策略
   - 负面率阈值策略
   - 全局判断

   重构 `experiment_runner.py`
   新增 `experiment_config_example.json`（考虑是否删除）
   删除 `experiment_config_example.json`（太复杂）

### 2026/08/20 21:12 端到端联调与统一入口

输入事件
→ 生成初始评论池
→ 初始化事件状态
→ 生成 Agent 可见评论
→ Agent 批量决策
→ 保存 Agent 状态
→ 生成下一轮增量评论
→ 统计舆情指标
→ 动态触发官方回应
→ 比较不同实验策略

先做统一入口，新增 `main.py` 作为统一入口

再进行联调

### 2026/08/21 决策逻辑修改

修改 agent 对评论的打分逻辑，按照如下形式进行一个确定：

第一阶段：LLM 形成认知

第二阶段：对全局候选评论打分

个人可见评论影响 Agent 的认知和态度，Agent 从全局候选评论池中选择自己的表达。

> 这是2026/08/21的历史设计，已在2026/09/05社交网络传播第一阶段中改为“最终表达只能从个人可见评论中选择”。

| 文件 | 是否必须手工修改 |
| --- | --- |
| `example/decision_result_llm.json` | 否，可作为示例同步更新 |
| `decision_history.jsonl` | 否，运行时自动生成 |
| `batch_agent_decision.py` | 是 |
| `agent_decision_llm_demo.py` | 是 |
| `decision_engine.py` | 是 |

### 2026/08/21 15:50 联调

验证技术链路，再验证多轮策略逻辑

联调，读取 agent 文件名排序的前 3 个

联调修改下面的功能：

- DeepSeek 统一请求重试；
- 部分 Agent 失败时停止指标计算；
- 评论主题强制使用事件主题；
- 初始评论和增量评论的批次重试。

进场策略

- 不回应
- 负面率达到阈值
- 全局舆情恶化
- 官方质疑率达到阈值
- 多个指标组合触发

内容策略

- 事实通报
- 共情安抚
- 辟谣澄清
- 处置进展

后续可以同时进行不同的策略，观察哪种策略效果最好

官方回应策略

- 进场规则：什么时候回应
- 内容策略：回应什么

目前实现进场规则

### 2026/08/22 增量评论累积对齐

当前问题：

- 目标生成 5 条
- 第一次得到 4 条有效评论
- 4 条全部放弃
- 再重新生成 5 条
- 最终仍可能失败

修改为：

- 目标生成 5 条
- 第一次得到 4 条
- 暂存 4 条
- 第二次只补充剩余 1 条
- 合并并去重
- 达到 5 条后返回

重构评论模块：

```text
comment_generation_service.py
  ↑
  │ 公共评论生成能力
  │
  ┌────────┴─────────┐
  │                  │
  `comment_pool_`     `incremental_comment_`
  `generator.py`      `generator.py`
  │                  │
  生成初始评论池       生成后续轮次增量评论
```

- 新增 `comment_generation_service.py`
- 修改 `comment_pool_generator.py`
- 修改 `incremental_comment_generator.py`

完成“联调可靠性收尾”，涉及：

- `batch_agent_decision.py`：全部 Agent 成功后再保存。
- `simulation_runner.py`：避免半轮数据卡死，并支持安全恢复。
- `experiment_runner.py`：修复 UTF-8

### 2026/08/24 增量评论生成容错/增量评论第二次修改实施方案

当前状态：已完成代码修改和不联网行为验证；第三次联调已验证冗余生成和部分兜底有效。

首次联调问题：每轮需要生成 20 条增量评论，程序将其拆分为两个 10 条批次。DeepSeek 返回结果经过重复文本、人物类型和分类字段校验后，部分批次只剩 8～9 条有效评论。原批次经过三次尝试仍未达到 10 条时会抛出异常，导致整个实验策略提前终止。

目标：保持每轮最终生成 20 条有效增量评论，不降低评论数量要求；通过冗余生成、增加补齐次数、字段规范化和过滤原因统计，提高完整联调的稳定性，同时保证五个实验组的评论数量具有可比性。

| 类型 | 文件 | 主要目标 |
| --- | --- | --- |
| 修改 | `project_config.py` | 将评论批次尝试次数由 3 次提高到 5 次，并新增每批冗余生成 2 条的配置。 |
| 修改 | `comment_generation_service.py` | 缺少 N 条时请求 N+2 条；安全转换字符串形式的 `profile_id`；统计空文本、重复文本、无效人物类型和分类字段错误等过滤原因。 |
| 修改 | `incremental_comment_generator.py` | 每批目标仍为 10 条，但首次向模型请求 12 条，校验后只接收所需数量；每轮最终仍保持 20 条。 |
| 不需要修改 | `experiment_runner.py`、`main.py`、`official_response_options.json` | 不改变实验分组、官方进场规则、内容策略和统一启动入口。 |
| 不新增 | 测试代码文件 | 使用现有模块语法检查、导入检查和新实验批次进行验证。 |

涉及的功能函数：

| 函数 | 操作 | 功能 |
| --- | --- | --- |
| `normalize_profile_id()` | 新增 | 将字符串形式的 `"1"` 安全转换为整数 `1`，不能转换的仍判为无效。 |
| `normalize_comments()` | 修改 | 增加过滤原因统计，同时保持严格字段校验。 |
| `build_comment_retry_prompt()` | 修改 | 缺少 N 条时请求 `N + 2` 条。 |
| `generate_valid_comment_batch()` | 修改 | 最多尝试 5 次、累计有效结果，并输出过滤原因。 |
| `generate_incremental_comments()` | 修改 | 每批按“目标 10 条、实际请求 12 条”生成。 |

实现约束：

- 保留已经生成的有效评论，只补充缺少的数量。
- 不使用随机抽取旧评论作为常规补足方式。
- 五个实验组每轮的目标增量评论数量保持一致。
- 达到最大尝试次数后仍缺少 1～3 条时启用有限兜底；缺少更多或没有合格候选时停止当前策略。
- 修复后的联调创建新的实验批次，不覆盖首次失败结果。

验收标准：

1. 每个成功轮次均保存 20 条增量评论。
2. `incremental_comment_history.jsonl` 中的 `comment_count` 与实际评论数组长度一致。
3. 五个实验组能够完成 10 个时间步。
4. `experiment_result.json` 中 `success_count` 为 5、`failed_count` 为 0。
5. `comparison` 包含五个实验组的最终指标对照结果。

### 2026/08/24 增量评论兜底机制实施方案

当前状态：第三次联调已验证 1～2 条历史评论兜底可以生效；根据第 6 轮缺少 3 条的实际结果，当前上限已调整为 3 条，待下一次正式联调验证。

目标：模型经过 5 次尝试后，每轮仅缺少 1～3 条评论时，从初始评论池和本轮之前的增量评论中确定性抽取合格评论补足到 20 条；缺少超过 3 条时继续报错，避免大量旧评论影响内容策略对照。

| 类型 | 文件 | 主要目标 |
| --- | --- | --- |
| 修改 | `project_config.py` | 新增每轮最多允许 3 条历史兜底评论的配置。 |
| 修改 | `comment_generation_service.py` | 增量场景达到最大尝试次数后可返回部分有效评论，初始评论池继续保持严格数量校验。 |
| 修改 | `incremental_comment_generator.py` | 读取已选择评论编号，筛选初始评论和历史增量评论，使用固定种子抽取并保存兜底来源。 |
| 不需要修改 | `experiment_runner.py`、`main.py`、`official_response_options.json` | 不改变实验分组、统一入口、官方进场规则和内容策略。 |
| 不新增 | 代码文件和测试文件 | 在现有模块中实现，并使用不联网行为检查和新实验批次验证。 |

涉及的功能函数：

| 函数 | 操作 | 功能 |
| --- | --- | --- |
| `generate_valid_comment_batch()` | 修改 | 新增 `allow_partial=False` 参数，仅在增量调用传入 `True` 时返回部分有效评论。 |
| `load_selected_comment_ids()` | 新增 | 从决策历史读取本轮之前已经被 Agent 选择的评论编号。 |
| `select_fallback_comments()` | 新增 | 排除已选择、已兜底和字段不完整的评论，按最近轮次优先并使用固定种子抽取。 |
| `generate_incremental_comments()` | 修改 | 模型结果只缺 1～3 条时调用历史评论兜底并补足目标数量。 |
| `run_incremental_generation()` | 修改 | 加载已选择评论编号，并在本轮记录中保存 `fallback_count`。 |
| `validate_incremental_record()` | 修改 | 校验兜底数量和来源字段，同时兼容没有 `fallback_count` 的旧记录。 |

兜底评论新增字段：

```json
{
  "source_type": "repost_fallback",
  "source_comment_id": "comment_025"
}
```

每轮增量评论记录新增 `fallback_count`；旧记录缺少该字段时按 0 处理。

实现约束：

- 候选范围包括初始评论池和当前轮次之前的全部增量评论。
- 优先抽取上一轮评论，再按时间步从近到远抽取，最后使用初始评论。
- 排除已经被 Agent 选择、已经作为兜底来源、已经标记为兜底、字段不完整或与本轮新评论文本重复的评论。
- 候选评论先按 `comment_id` 排序，再使用事件编号、当前时间步和固定随机种子抽取，保证结果可复现。
- 每轮最多使用 3 条兜底评论；缺少超过 3 条或候选不足时停止当前策略。
- 兜底评论生成新的 `comment_id`，并通过 `source_comment_id` 保留原始来源。
- 初始评论池不启用部分结果和历史兜底。

验收标准：

1. 正常生成 20 条时，`fallback_count` 为 0。
2. 模型只生成 17～19 条时，能够补足到 20 条。
3. 模型生成少于 17 条时，仍然明确报错。
4. 不会抽取此前已被 Agent 选择或已经作为兜底来源的评论。
5. 相同事件、时间步、候选数据和随机种子得到相同的兜底结果。
6. `fallback_count` 与实际 `source_type` 为 `repost_fallback` 的评论数量一致。
7. 没有 `fallback_count` 的历史增量评论记录仍然可以读取。

### 2026/08/24 第三次联调问题修复


| 类型 | 文件 | 主要目标 |
| --- | --- | --- |
| 修改 | `metrics.py` | 趋势分析只比较初始评论和当前轮增量评论；限制说明为 100 字、证据编号最多 5 个，并使用紧凑 JSON 提示词。 |
| 修改 | `llm_service.py` | JSON 解析失败时记录 `finish_reason` 和输出字符数，明确识别达到 `max_tokens` 后的截断。 |
| 修改 | `project_config.py` | 将每轮历史评论兜底上限从 2 条调整为 3 条。 |
| 修改 | `incremental_comment_generator.py` | 继续复用现有兜底函数，并按新的 3 条配置上限校验和补足。 |
| 新增文档 | `INTEGRATION_TEST_HISTORY.md` | 按日期记录三次联调的配置、结果、失败原因和后续处理。 |
| 不需要修改 | `experiment_runner.py`、`main.py`、官方内容策略文件 | 不改变实验分组、运行入口、动态进场和声明内容。 |


### 2026/08/24 第四次联调问题修复

当前状态：已完成代码修改和不联网行为验证，待第五次正式联调验证。第四次联调的完整实验结果见 [`INTEGRATION_TEST_HISTORY.md`](./INTEGRATION_TEST_HISTORY.md)。

第四次联调问题：`rumor_clarification` 第 8 轮只得到 15 条有效评论，缺少 5 条；`handling_progress` 第 3 轮只得到 16 条有效评论，缺少 4 条。两个缺口均超过当时每轮最多 3 条的历史评论兜底上限，导致对应策略提前终止。

目标：取消“缺口超过固定数量就终止策略”的处理，将 3 条改为数据质量告警阈值；模型有限重试后，先使用合格历史评论补足全部缺口，历史候选仍不足时使用可识别的本地中性应急评论，保证每轮最终仍有 20 条评论。同时保存模型生成、字段过滤、两级兜底和数据质量信息，避免为了完成联调而掩盖数据质量下降。

| 类型 | 文件 | 主要目标 |
| --- | --- | --- |
| 修改 | `project_config.py` | 将原来的 3 条固定失败上限改为数据质量告警阈值，不再因缺口超过 3 条直接终止策略。 |
| 修改 | `comment_generation_service.py` | 在保持原评论返回结构兼容的前提下，返回批次尝试次数、模型返回数量、有效数量、过滤原因和生成错误；增量请求失败时允许交由本地补齐。 |
| 修改 | `incremental_comment_generator.py` | 取消固定兜底上限，统一执行历史评论补齐和本地应急补齐，保存评论来源统计与质量状态，并兼容旧增量评论记录。 |
| 修改 | `experiment_runner.py` | 失败时同时保留子进程标准输出和异常栈；在轮次、场景及最终对照结果中汇总评论数据质量。 |
| 不需要修改 | `main.py`、`simulation_runner.py`、官方内容策略文件 | 不改变统一入口、单轮执行顺序、官方进场规则和声明内容。 |
| 不新增 | Python 模块和测试文件 | 继续在现有模块中实现，并通过语法、导入、历史兼容和不联网定向测试验证。 |

涉及的功能函数：

| 函数 | 操作 | 功能 |
| --- | --- | --- |
| `update_comment_generation_stats()` | 新增 | 将单个评论子批次的目标数量、尝试次数、模型返回数量、有效数量和过滤原因写入统计字典。 |
| `generate_valid_comment_batch()` | 修改 | 支持可选生成统计；增量场景的模型请求失败或重试结束后可以返回部分有效结果。 |
| `select_fallback_comments()` | 修改 | 删除固定 3 条上限，按照实际缺口尽量抽取符合原有排除规则的历史评论。 |
| `build_emergency_fallback_comments()` | 新增 | 历史候选不足时使用确定性中性模板生成剩余评论，并标记应急来源和原因。 |
| `complete_incremental_comments()` | 新增 | 先使用历史评论，再使用本地应急评论，统一保证本轮达到目标数量。 |
| `merge_batch_generation_stats()` | 新增 | 合并两个增量评论子批次的尝试次数、模型返回数量、过滤原因和生成错误。 |
| `generate_incremental_comments()` | 修改 | 调用统一补齐函数，并向上层返回本轮模型生成统计。 |
| `validate_incremental_record()` | 修改 | 允许兜底数量超过 3 条，校验模型、历史兜底、应急兜底数量及质量状态，同时兼容旧记录。 |
| `determine_comment_quality()` | 新增 | 根据历史兜底告警阈值和应急兜底数量返回 `normal`、`degraded` 或 `emergency`。 |
| `run_incremental_generation()` | 修改 | 保存模型生成数、两类兜底数、生成尝试、过滤原因、错误和质量状态。 |
| `run_simulation_step()` | 修改 | 子进程失败时同时保留标准输出中的过滤统计和标准错误中的异常栈。 |
| `load_step_comment_quality()` | 新增 | 从增量评论历史读取指定轮次的评论来源和质量信息。 |
| `summarize_comment_quality()` | 新增 | 汇总一个场景全部轮次的兜底数量、质量等级和告警轮次。 |
| `run_one_content_strategy()` | 修改 | 将每轮评论生成质量和场景质量汇总写入策略结果。 |
| `compare_strategy_results()` | 修改 | 在最终对照中增加 `data_quality` 和 `quality_warning_strategies`。 |

每轮增量评论记录新增或明确以下字段：

```json
{
  "comment_count": 20,
  "llm_comment_count": 15,
  "history_fallback_count": 5,
  "emergency_fallback_count": 0,
  "fallback_count": 5,
  "quality_status": "degraded",
  "generation_attempts": 10,
  "model_returned_comment_count": 30,
  "rejection_counts": {},
  "validation_errors": []
}
```

质量状态规则：

- `normal`：没有本地应急评论，且历史兜底不超过 3 条。
- `degraded`：没有本地应急评论，但历史兜底超过 3 条。
- `emergency`：使用了至少 1 条本地应急评论。

实现约束：

- DeepSeek 请求和评论批次继续使用有限重试，不使用无限重试。
- 历史兜底继续排除已被 Agent 选择、已经作为兜底来源、字段不完整以及与本轮新评论文本重复的评论。
- 历史候选不足时才使用本地应急评论；应急评论使用中性模板，不编造新的事件事实。
- 历史兜底评论继续保存 `source_type` 和 `source_comment_id`；本地应急评论保存 `source_type` 和 `fallback_reason`。
- 大量兜底只改变数据质量状态，不再导致策略因评论数量不足而退出。
- 初始评论池继续保持严格数量校验，不使用增量评论的本地应急补齐。

验收标准：

1. 模型只返回 15～16 条有效评论时，仍能将本轮补足到 20 条并继续运行策略。
2. 合格历史候选不足时，能够使用本地应急评论补足剩余数量。
3. `llm_comment_count + fallback_count` 等于 `comment_count`，两类兜底数量与实际评论来源一致。
4. 第四次联调之前没有新增质量字段的历史增量评论记录仍然可以读取。
5. `scenario_result.json` 和 `experiment_result.json` 能显示场景质量状态和告警轮次。
6. 子进程发生其他异常时，结果中同时保留评论过滤输出和异常栈。
7. 五个策略不会再因增量评论缺少 4 条、5 条或更大缺口而直接退出。


### 2026/08/25 第五次联调问题修复

当前状态：已完成代码修改和不联网函数级验证，待下一次正式联调验证。第五次联调已经完成全部 5 个策略、每个策略 10 个时间步，评论数量稳定补齐功能验证通过；但最终指标长期固定，导致内容策略效果无法被有效区分。完整联调结果见 [`INTEGRATION_TEST_HISTORY.md`](./INTEGRATION_TEST_HISTORY.md)。

第五次联调问题：五个策略最终负面率均为 `1.0`，四个回应策略质疑率均为 `1.0`、接受率均为 `0.0`，四种官方内容策略最终结果完全相同；并列指标仍只返回排序后的第一个策略，使“不回应”被误显示为唯一最佳策略。

根因：负面事件虽然允许 Agent 在 `neutral` 和 `negative` 之间选择，但决策提示没有明确要求根据本轮新证据重新判断，最近状态容易被连续沿用；`incomplete` 声明只允许 `wait` 和 `question`，从规则上排除了 `accept`；无声明场景被记录为 `wait`，使不适用的接受率和质疑率被错误计算为 `0.0`；最终评论选择未考虑官方态度和评论 `stance`，Agent 的认知态度不能稳定传递到下一轮舆情；策略比较没有显式处理并列和不适用指标。

目标：解除官方态度指标的结构性锁死，明确无声明场景的指标语义，要求 Agent 依据当前声明重新判断，并使最终表达与认知态度保持基本一致；同时如实返回所有并列策略。修复不强迫不同内容策略产生不同结果，真实相同结果仍然允许保留。

| 类型 | 文件 | 主要目标 |
| --- | --- | --- |
| 修改 | `decision_engine.py` | 统一官方态度选项；增加 `not_applicable`；强化本轮证据判断；按官方态度优先选择语义一致的评论。 |
| 修改 | `agent_decision_llm_demo.py` | 将认知决策中的官方态度传给最终评论选择函数。 |
| 修改 | `agent_decision_demo.py` | 同步本地规则示例的评论选择参数，保持接口一致。 |
| 修改 | `metrics.py` | 增加完整情绪分布；官方态度按适用 Agent 计算，无声明时接受率和质疑率为 `null`。 |
| 修改 | `experiment_runner.py` | 保留 `null` 指标；比较时跳过不适用场景；返回全部并列策略和 `is_tie`。 |
| 修改 | `persona_pipeline/build_personas.py` | 同步官方态度候选规则，避免重新生成 Persona 配置后恢复旧规则。 |
| 修改 | `output/personas/policy_config.json` | 更新当前 Demo 实际读取的官方态度候选规则。 |
| 暂不修改 | `propagation.py`、情绪候选规则 | 先验证最小语义修复；如后续仍不敏感，再单独处理当前轮评论被累计历史评论稀释的问题。 |
| 不新增 | Python 模块和测试文件 | 在现有模块中完成，并使用语法、导入和不联网函数级检查验证。 |

涉及的功能函数：

| 函数 | 操作 | 功能 |
| --- | --- | --- |
| `get_official_attitude_options()` | 新增 | 从声明状态和统一策略配置取得官方态度选项；无声明只返回 `not_applicable`，有声明允许 `accept`、`wait` 和 `question`。 |
| `decide_official_attitude()` | 修改 | 复用统一态度选项，并保持本地规则决策兼容。 |
| `build_allowed_choices()` | 修改 | 复用统一态度选项，删除正式 LLM 决策中的重复硬编码。 |
| `build_decision_prompt()` | 修改 | 明确态度含义，要求依据当前声明和当前可见评论重新判断，历史状态只作为参考。 |
| `validate_cognition_decision()` | 修改 | 校验三项决策理由均为非空字符串，并校验 `not_applicable` 与声明状态一致。 |
| `get_attitude_stances()` | 新增 | 将 `accept`、`wait`、`question` 映射到语义相符的评论立场。 |
| `select_best_candidate()` | 修改 | 优先在态度相符的评论中沿用现有评分；没有相符候选时回退到全部候选，避免人为增加数值权重。 |
| `calculate_emotion_distribution()` | 新增 | 输出正面、中性和负面 Agent 的完整数量与比例，便于诊断负面率变化。 |
| `calculate_attitude_distribution()` | 修改 | 区分总 Agent 数和适用 Agent 数，`not_applicable` 不进入接受率、等待率和质疑率分母。 |
| `calculate_round_metrics()` | 修改 | 写入完整情绪分布，并根据当前声明状态计算官方态度指标。 |
| `extract_policy_metrics()` | 修改 | 允许接受率和质疑率为 `null`，不将无声明误解释为零。 |
| `compare_strategy_results()` | 修改 | 跳过 `null` 指标，返回全部最佳并列策略、并列状态和值。 |

官方态度语义：

- `accept`：总体认可当前声明的可信度和回应价值，不代表声明已经包含全部信息。
- `wait`：当前证据不足，暂时无法形成明确接受或质疑态度。
- `question`：主要态度是质疑声明的真实性、完整性或处理方式。
- `not_applicable`：当前没有官方声明，官方态度指标不适用。

实现约束：

- 不为了得到策略差异而在提示词中预设某种内容策略必然更好。
- 不设置“怀疑度加减固定数值”等缺少依据的人工影响系数。
- 暂不将负面事件的情绪候选扩大到 `positive`；先验证 Agent 能否在已有 `neutral` 和 `negative` 之间根据新证据变化。
- `official_statement_status=incomplete` 只表示信息尚不完整，不直接等同于声明不可信，也不再排除 `accept`。
- 评论态度对齐采用候选集合优先级，不修改现有评论评分公式；没有匹配评论时必须安全回退。
- 无声明场景仍参与负面率比较，但不参与接受率和质疑率比较。
- 并列结果必须如实保留，不以排序后的第一个策略暗示唯一最佳策略。
- 不运行 DeepSeek 完整联调；完成代码后先进行不联网验证，再由新的正式实验批次验证实际效果。

验收标准：

1. 无声明时 Agent 只能输出 `not_applicable`，接受率、等待率和质疑率均为 `null`，适用 Agent 数为 0。
2. 有声明时 `accept`、`wait` 和 `question` 均不是被代码结构排除的选项。
3. Agent 决策理由包含非空的情绪、官方态度和评论依据，历史态度不会被提示词描述为必须延续。
4. 最终评论优先与官方态度对应的 `stance` 一致；不存在匹配评论时仍能正常选出候选评论。
5. 指标结果同时保留负面率和完整情绪分布。
6. 接受率、质疑率比较不包含值为 `null` 的场景；全部场景均不适用时返回 `null` 比较结果。
7. 最佳指标相同时返回全部并列策略，并显式记录 `is_tie: true`；唯一最佳时记录 `is_tie: false`。
8. 不要求四种官方内容策略必须得到不同指标，只要求差异不再被硬编码规则阻断。

不联网验证结果：6 个相关 Python 文件通过 AST 语法检查，当前策略配置通过 JSON 解析；5 个运行模块通过导入检查；官方态度候选、声明适用性、决策理由校验、评论立场优先与回退、情绪分布、官方态度分母、空指标跳过和并列策略返回均通过函数级行为检查。验证过程未调用 DeepSeek，也未创建新的测试文件。

### 2026/08/25 第六次联调问题修复

#### 第一阶段：修复 Agent 判断输入

| 文件和函数 | 所做的更改 |
| --- | --- |
| `decision_engine.py`：新增 `build_agent_event_view()` | 构造 Agent 专用事件视图，只保留事件原文、主题和当前官方声明，不向提示词直接提供 `event_valence`。 |
| `decision_engine.py`：新增 `build_persona_decision_summary()` | 将 `emotion_expression`、`information_orientation`、主题偏好和派系偏好转换为可解释的决策摘要。 |
| `decision_engine.py`：新增 `summarize_visible_comments()` | 汇总 Agent 本轮可见评论的情绪和立场分布。 |
| `decision_engine.py`：修改 `build_allowed_choices()`、`build_decision_prompt()` | 将 Persona 摘要和可见评论摘要写入正式决策提示词，要求 Agent 根据事件原文、声明内容和本轮证据重新判断，不得直接使用负面标签得出结论。 |

离线检查结果：事件预设情绪标签不再出现在 Agent 提示词中，Persona 摘要、评论摘要、官方声明及原有候选约束均能正常传递。

#### 第二阶段：修复评论选择和重复传播

| 文件和函数 | 所做的更改 |
| --- | --- |
| `incremental_comment_generator.py`：修改 `load_previous_round_comments()` | 同一条上一轮 Agent 实际评论只保留一份，并用 `selection_count` 记录选择该评论的 Agent 数量。 |
| `incremental_comment_generator.py`：新增 `summarize_previous_incremental_comments()` | 汇总上一轮全部增量评论的数量、情绪、立场和派系分布，不把 20 条完整原文重复写入提示词。 |
| `incremental_comment_generator.py`：修改 `build_incremental_prompt()`、`generate_incremental_comments()`、`run_incremental_generation()` | 向评论生成器传递重复选择次数和上一轮分布摘要；提示词只提供事件主题，不直接提供 `event_valence`。 |
| `decision_engine.py`：新增 `select_from_top_candidates()`，修改 `select_best_candidate()` | 先保留官方态度对应的候选评论，再从评分最高的 3 条中根据“固定种子、事件、轮次、Agent”进行可复现选择。 |
| `decision_engine.py`：修改 `build_final_decision()` | 保存实际被选中评论的评分，不再固定保存评分列表第一条的分数。 |
| `project_config.py`、`agent_decision_llm_demo.py`、`agent_decision_demo.py` | 增加并接入 `COMMENT_SELECTION_TOP_K=3` 和评论选择随机种子配置。 |

离线检查结果：重复评论能够正确归并，选择次数和上一轮分布统计正确；相同输入可复现，不同 Agent 可以从前三名中选择不同评论，实际评论评分记录正确。

#### 第三阶段：当前轮和历史评论分层可见

| 文件和函数 | 所做的更改 |
| --- | --- |
| `project_config.py` | 保持每个 Agent 每轮最多可见 15 条评论，新增 `CURRENT_STEP_VISIBLE_COUNT=10`。 |
| `propagation.py`：修改 `sample_visible_comments()` | 优先随机抽取当前轮评论 10 条和历史评论 5 条；任一层数量不足时由另一层补足，总量不足时使用全部可用评论，全程不重复抽取。 |
| `propagation.py`：修改 `build_agent_blackboard_view()` | 在 Agent 黑板视图中记录 `current_step_visible_count` 和 `historical_visible_count`。 |
| `batch_agent_decision.py` | 接入分层可见配置，并将两层评论的实际可见数量保存到成功或失败的决策记录中。 |

离线检查结果：正常情况下每个 Agent 可见当前轮 10 条、历史 5 条；当前轮或历史评论不足时可以相互补足，第一轮无历史评论时可见 15 条初始评论，相同随机种子结果可复现且没有重复评论。



### 2026/08/25 第七次联调后续处理：Agent个人评论历史

完成Agent个人评论历史功能：该Agent此前所有轮次实际选择的评论

将个人评论历史加入后续决策

| 文件 | 函数 | 修改内容 |
| --- | --- | --- |
| `demo/agent_state_store.py` | `DEFAULT_AGENT_STATE` | 增加 `last_comment` 默认字段 |
| `demo/agent_state_store.py` | `build_state_record()` | 保存Agent本轮实际选择的完整评论，而不仅是评论编号和派系 |
| `demo/agent_state_store.py` | `build_history_summary()` | 按时间顺序汇总当前轮之前的全部个人评论，生成 `own_comment_history` |
| `demo/decision_engine.py` | `build_decision_prompt()` | 将个人评论历史明确展示给LLM，并说明历史可以维持或改变本轮判断 |


### 2026/08/26 第八次联调问题修复与官方声明组合实验扩展

当前状态：前三项代码修改和不联网验证已完成，待下一次正式联调验证；小范围状态实验和完整组合实验暂未实施。

#### 已完成：策略对照实验可信度修复

1. 统一五个场景的官方进场前基线。
2. 控制Agent重复选择自己的历史评论。
3. 降低增量评论生成的重复率。

| 功能 | 文件 | 函数操作 |
|---|---|---|
| 共享进场前基线 | `experiment_runner.py` | 新增`load_round_result()`和`run_shared_pre_entry_baseline()`；修改`run_experiment()`、`run_one_content_strategy()`和`prepare_scenario_state()`，动态阈值触发前只运行一条公共路径，触发后再分叉。 |
| 复制基线状态 | `simulation_state_manager.py` | 新增`initialize_state_from_snapshot()`，复制并校验事件状态、Agent状态、决策、增量评论和指标五类文件。 |
| Agent历史评论排重 | `agent_decision_llm_demo.py` | 修改`decide_one_agent()`，提取个人历史评论编号和文本；没有新候选时改为本轮不评论，不回退到个人旧评论。 |
| Agent候选评论过滤 | `decision_engine.py` | 新增`filter_unseen_candidates()`；修改`select_best_candidate()`，评分前硬排除当前Agent已经选择过的评论编号和相同文本。 |
| 增量评论多样性 | `incremental_comment_generator.py` | 新增`select_recent_avoid_texts()`；修改`build_incremental_prompt()`和`generate_incremental_comments()`，最多提供最近30条避重文本，并要求更换表达角度。 |
| 评论补齐提示 | `comment_generation_service.py` | 修改`build_comment_retry_prompt()`，要求补齐评论避免少量换词复述已有观点。 |
| 评论生成温度 | `experiment_runner.py` | 将评论生成温度从`0`调整为`0.5`；Agent认知决策仍保持确定性配置。 |

不联网验证结果：6个相关模块通过语法和导入检查；共享基线可在非固定轮次由指标触发，状态快照复制后五类文件内容一致；个人历史编号和标准化后的相同文本均会被排除；没有新候选时不会导致Agent或策略失败；增量提示词只携带有限近期文本。验证过程未调用DeepSeek，也未新增测试文件。

#### 待完成：官方声明组合实验扩展

4. 进行小范围声明状态实验。
5. 小范围验证通过后，扩展为完整的“内容策略 × 声明状态”组合实验。


### 2026/08/26 第十次联调问题修复，增量评论大量重复
当前问题：第十次联调虽然五个场景全部完成，但900条增量评论中有468条来自兜底，总兜底率为52%。主要原因是LLM反复生成历史中已经存在的评论，共有3853条候选因重复文本被过滤。

问题原因：增量评论提示词只提供最近30条避重文本，但本地校验会检查全部历史评论。模型不知道更早的历史文本，重试时也没有收到本次被过滤的具体重复内容，因此可能连续返回旧评论。

目标：保留全历史严格去重和现有两级兜底，在每次重试时向LLM反馈本批次被过滤的具体重复文本，减少重复生成和兜底评论数量。

| 文件 | 函数 | 修改内容 |
| --- | --- | --- |
| `comment_generation_service.py` | `normalize_comments()` | 记录因重复被过滤的具体评论文本。 |
| `comment_generation_service.py` | `build_comment_retry_prompt()` | 将本批次已经接收的评论和被过滤的重复文本加入下一次补齐提示词。 |
| `comment_generation_service.py` | `generate_valid_comment_batch()` | 累积本批次的重复文本，并在后续重试时传给补齐提示词。 |

实现要求：

1. 重复文本列表去重，并限制最多50条，避免提示词过长。
2. 保留全历史严格文本校验，不允许重复评论作为新的模型评论进入评论池。
3. 保留历史评论兜底和紧急兜底，避免评论不足导致策略退出。
4. 不增加现有重试次数，不修改Agent决策、指标计算和实验编排模块。

验收标准：

1. 相关模块通过语法和导入检查。
2. 重试提示词包含本批次实际被过滤的重复文本。
3. 每轮仍能稳定补齐20条增量评论。
4. 下一次联调的重复文本过滤数量和总兜底率明显低于第十次联调。

### 2026/08/26 第十一次联调问题修复

当前状态：事件角度任务代码和不联网验证已完成，待第十二次正式联调验证重复过滤数量、兜底率及评论角度分布。

当前问题：第十一次联调的五个场景均完成10轮，但900条增量评论中仍有302条来自历史兜底，总兜底率约33.6%，模型候选仍有3239条因重复文本被过滤，五个场景的数据质量均为`degraded`。仅扩大历史避重文本范围可以减少直接重复，但不能解决模型长期集中生成少数论点的问题。

问题原因：评论生成器目前只笼统要求“从不同角度表达”，没有先形成事件专属角度，也没有为每条评论分配明确角度。LLM容易反复选择最直观的论点，随后被全历史重复校验过滤并触发历史兜底。人物类型和评论派系虽然大多组合合理，但当前完全由LLM自由选择，缺少可观察的组合统计。

解决目标：保留现有全历史严格去重、分层避重和两级兜底，在此基础上增加“事件角度任务”。程序为每条评论分配角度，LLM在指定角度下自行选择语义合适的人物类型和评论派系并生成文本，从源头增加论点差异，降低重复过滤和兜底率。

| 文件 | 函数 | 修改内容 |
| --- | --- | --- |
| `comment_angle_planner.py` | `generate_event_angle_plan()`、`validate_event_angle_plan()` | 新增事件角度生成与校验；角度必须有事件正文依据。 |
| `comment_angle_planner.py` | `build_initial_angle_tasks()`、`build_incremental_angle_tasks()` | 新增初始评论和增量评论的确定性角度任务分配。 |
| `comment_angle_planner.py` | `select_active_angles()` | 有官方声明时加入信息完整性、可信度和后续处置三个公共评价角度。 |
| `comment_generation_service.py` | `normalize_comments()`、`generate_valid_comment_batch()` | 校验`task_id`，由程序写入对应`angle_id`；补齐时只请求尚未完成的角度任务。 |
| `comment_generation_service.py` | `summarize_profile_faction_combinations()` | 新增人物类型与派系组合数量统计，只作诊断，不设置硬性组合限制。 |
| `comment_pool_generator.py` | `build_generation_prompt()`、`generate_comment_pool()` | 先生成事件角度，再按角度任务生成60条初始评论，并将角度计划和组合统计保存在`comment_pool.json`。 |
| `comment_pool_repository.py` | `load_comment_pool()` | 新格式存在角度计划时，校验评论角度任务字段、任务编号唯一性和角度引用。 |
| `incremental_comment_generator.py` | `build_incremental_prompt()`、`generate_incremental_comments()` | 每轮20条增量评论按活跃角度生成；继续输入官方声明、上一轮Agent实际评论、分布摘要和避重文本。 |
| `llm_service.md` | LLM调用说明 | 记录新增事件角度规划调用及调整后的最低调用量。 |
| `example/comment_pool_angle_task_example.json`、`example/incremental_comment_history.jsonl` | 示例数据 | 展示角度计划、任务字段、角度统计和人物类型与派系统计。 |

技术方案：

1. 每个事件只生成一次事件专属角度计划，所有官方策略场景复用初始评论池中的同一份计划。
2. LLM生成的初始评论和增量评论都携带`task_id`与`angle_id`；程序负责角度覆盖，LLM负责评论文本、人物类型、派系、情绪、立场和信息取向。历史和应急兜底仍通过来源字段单独识别。
3. 人物类型和派系不做完整笛卡尔积，也不增加严格`allowed_factions`；保存`profile_id × faction`统计，后续根据联调结果再判断是否需要软偏好。
4. 角度任务补齐只重试缺失任务，不再笼统补数量；继续保留全历史文本校验、同轮重复反馈、历史评论兜底和本地应急兜底。
5. 不修改Agent决策、指标计算和实验编排模块，不新增无网络测试文件，不运行DeepSeek完整联调。

验收标准：

1. 相关模块通过语法、导入和不联网功能检查。
2. 初始评论池保存合法且不重复的事件角度计划，所有评论均可追踪到角度任务。
3. 增量评论按本轮活跃角度分配任务，重试提示词只包含尚未完成的任务。
4. 旧的非任务化调用仍保持兼容，历史和应急兜底仍能保证每轮20条评论。
5. 第十二次联调的重复过滤数量和总兜底率低于第十一次联调，紧急兜底保持为0。


### 2026/08/27 第十二次联调修复

当前问题：第十二次联调中负面率始终为`0.4`、趋势始终为`stable`，原有阈值和恶化条件均未触发。共享基线运行到第10轮后，四个回应场景没有发布声明或继续运行，却仍被标记为`success`并参与策略比较。

解决目标：不增加最晚进场轮次，在原有负面阈值和趋势恶化条件上增加“连续没有明显改善”动态触发；若全部动态条件始终不满足，四个回应场景必须标记为`not_run`，实验结果明确为不可比较。

| 文件 | 函数 | 修改内容 |
| --- | --- | --- |
| `official_response_options.json` | 动态进场配置 | 增加`stagnation_rounds`和`negative_rate_improvement_tolerance`。 |
| `experiment_runner.py` | `validate_official_response_options()` | 校验停滞轮数和负面率改善容差。 |
| `experiment_runner.py` | `count_consecutive_stagnant_rounds()` | 新增功能：第1轮只作基线，从第2轮起统计趋势稳定且负面率未明显下降的连续轮数。 |
| `experiment_runner.py` | `evaluate_response_entry()` | 新增功能：统一返回是否进场、`entry_reason`和当前停滞轮数。 |
| `experiment_runner.py` | `run_shared_pre_entry_baseline()` | 修改功能：应用连续停滞规则并保存`entry_triggered`、`entry_reason`。 |
| `experiment_runner.py` | `run_one_content_strategy()` | 修改功能：未触发进场时将回应场景保存为`not_run`。 |
| `experiment_runner.py` | `compare_strategy_results()`、`run_experiment()` | 修改功能：只比较真实进场的场景，并分别统计成功、未运行和失败数量。 |
| `main.py` | `run_complete_simulation()` | 修改功能：控制台明确提示内容策略对照未执行。 |

动态进场规则：

1. `negative_rate >= 0.5`时按`negative_threshold`进场。
2. `global_trend == worsening`时按`global_worsening`进场。
3. `combined_policy`下，连续达到配置轮数的`stable`且负面率下降不超过容差时，按`stagnation`进场。
4. 第1轮是比较基线，不计入停滞轮数；负面率明显下降会重置连续停滞统计。
5. 不配置或配置`stagnation_rounds=0`时保持旧行为，不设置最晚进场轮次。

未进场结果：

1. 不回应场景保留为成功的自然基线。
2. 四个回应场景标记为`not_run`，原因是`official_response_not_triggered`。
3. 实验状态为`completed_no_entry`，`comparison_status`为`not_evaluable`，`comparison`为空对象。
4. 未运行场景不计入`failed_count`，单独写入`not_run_count`。

验收标准：

1. 第十二次相同的`0.4 + stable`指标序列在连续2轮没有改善后返回`stagnation`，并确定下一轮进场。
2. 负面率明显下降时停滞累计重置。
3. 未触发进场时四个回应场景均为`not_run`且不产生策略比较。
4. 原有负面阈值、趋势恶化和`no_response`规则保持兼容。
5. 相关模块通过语法、导入和不联网功能验证，不运行DeepSeek完整联调。

### 2026/08/27 第十三次联调修复

修改official_response_options.json，验证声明状态为clear的时候，是否有accept

解决目标：clear声明确实能够触发Agent的accept，接受分支不存在功能故障。


### 2026/08/27 第十四次联调修复

修改official_response_options.json，统一四个回应场景的声明完整度，消除第十四次实验中的状态混杂。
控制变量：
相同：售价、配置、交付时间、售后信息、声明状态
不同：表达方式和沟通重点

目标：检查四个场景是否都出现accept、接受率是否因表达策略产生差异



### 2026/08/27 舆情指标计算扩充

当前问题：现有实验主要比较最终一轮负面率、质疑率、接受率和趋势，无法反映声明发布后的恢复过程、改善持续时间、后续反弹、累计负面程度以及相对不回应场景的净效果。

解决目标：不增加多批次稳定性分析，只使用单个实验批次中已有的`rounds`和`agent_state_history.jsonl`计算五项过程指标，并写入现有场景结果和实验汇总。

| 类型 | 文件 | 主要工作 |
|---|---|---|
| 修改 | `metrics.py` | 实现5个单批次过程指标，增加情绪历史和负面率序列整理函数 |
| 修改 | `experiment_runner.py` | 每个场景结束后调用新指标，并以`no_response`为对照计算净效果 |
| 修改 | `detail.md` | 记录指标定义、技术方案和验收标准 |
| 修改 | `example/metrics_result_example.json` | 增加过程指标示例；不影响系统运行 |

| 函数 | 操作 | 功能 |
|---|---|---|
| `build_agent_emotion_timeline()` | 新增 | 将Agent状态历史整理为按Agent和时间步排序的情绪序列 |
| `extract_negative_rate_series()` | 新增 | 兼容场景轮次与原始指标记录，提取逐轮负面率 |
| `calculate_emotion_recovery_rate()` | 修改 | 计算进场前为负面、进场后至少一次转为中性或正面的Agent比例 |
| `calculate_effect_duration()` | 修改 | 计算声明后负面率首次低于基线的连续轮数 |
| `calculate_rebound_rate()` | 修改 | 计算已经恢复、随后再次转为负面的Agent比例 |
| `calculate_negative_peak_and_area()` | 修改 | 计算负面率峰值、峰值轮次和逐轮负面率累计量 |
| `calculate_control_net_effect()` | 修改 | 使用不回应指标减去回应指标，正数表示回应有所改善 |
| `calculate_strategy_effect_metrics()` | 新增 | 汇总单个场景的五项过程指标 |
| `attach_control_net_effect_metrics()` | 新增 | 场景全部完成后附加相对不回应基线的净效果 |
| `compare_strategy_results()` | 修改 | 增加峰值、累计量、恢复率、持续时间、反弹率和净效果比较 |

计算口径：

1. 官方进场前一轮作为恢复率和持续时间的基线。
2. 恢复率分母是基线轮为`negative`的Agent；进场后至少一次变为`neutral`或`positive`即视为恢复。
3. 反弹率分母是已恢复Agent；恢复后再次变为`negative`即视为反弹。
4. 效果持续时间从首次低于基线负面率开始，连续统计到重新达到或超过基线为止。
5. 负面累计量为实验各轮负面率之和；各轮时间间隔相同，不额外引入复杂积分算法。
6. 对照净效果使用`no_response - response`，结果大于0表示回应场景改善。
7. `calculate_run_stability()`继续保留为占位函数，本阶段不计算多批次稳定性。

结果保存：

- 每个成功场景在`scenario_result.json`中新增`effect_metrics`。
- `experiment_result.json`中的每个`strategy_result`同步保存`effect_metrics`。
- `comparison`新增最低负面峰值、最低累计负面量、最高恢复率、最长持续时间、最低反弹率和最高累计负面量减少值。
- 没有触发官方进场时，只计算峰值和累计量；恢复、持续和反弹指标为`null`，未运行回应场景不参与比较。

验收标准：

1. 纯函数可以正确识别恢复、反弹、首次改善持续时间、并列峰值和累计负面量。
2. 不回应场景作为唯一对照，净效果正负方向与定义一致。
3. 无可适用Agent时比例返回`null`，不使用`0`误表示没有恢复或反弹。
4. 不改变现有每轮`metrics_history.jsonl`结构和原有最终指标比较。
5. 相关模块通过语法、导入和不联网回归验证，不运行DeepSeek完整联调。


### 2026/08/27 第十六次联调修复-Agent情绪状态转换

当前问题：第十六次联调的指标计算已正常工作，但相同4个Agent从第1轮到第10轮始终保持`negative`，其余6个Agent始终保持`neutral`。官方态度能够变化，情绪却没有发生任何转换，导致恢复率、持续时间、反弹率和净效果均无法体现策略差异。

主要原因：Persona主导情绪、上一轮情绪和最近三轮重复情绪同时进入提示词，旧情绪被重复强化；当前轮评论与历史评论又被合并统计，使本轮信息变化不够突出。

解决目标：保留Persona、上一轮状态和个人完整评论历史，但明确它们只是长期倾向或历史参考；优先使用当前事件、当前声明和当前轮评论判断本轮情绪。情绪可以维持或转换，但两种结果都必须有当前证据，不强制`accept`后转为`neutral`。

| 文件 | 函数 | 修改内容 |
|---|---|---|
| `decision_engine.py` | `build_persona_decision_summary()` | 将情绪表达改为长期弱先验，移除直接提供的主导情绪结论。 |
| `decision_engine.py` | `summarize_comment_group()`、`summarize_visible_comments()` | 分开统计当前轮评论与历史评论的情绪和立场。 |
| `decision_engine.py` | `build_allowed_choices()`、`build_decision_prompt()` | 明确当前证据优先级、情绪转换依据，以及官方态度与个人情绪的区别。 |
| `agent_state_store.py` | `summarize_emotion_transitions()` | 新增上一轮情绪、累计转换次数和最近转换时间步摘要。 |
| `agent_state_store.py` | `build_history_summary()` | 用紧凑转换摘要替代连续三轮重复情绪列表，保留完整个人评论历史。 |

验收标准：

1. Persona不再直接向LLM提供本轮主导情绪结论。
2. 当前轮10条评论与历史5条评论在摘要中分层呈现。
3. 情绪维持和情绪转换都要求说明当前证据，不随机或强制改变情绪。
4. 官方态度和情绪分别判断，`accept`不强制为`neutral`，`question`不强制为`negative`。
5. 相关模块通过语法、导入和不联网纯函数验证，不运行DeepSeek完整联调。

### 2026/08/28 第十七次联调问题修复-证据时间语义

当前问题：第十七次联调已经解决Agent情绪完全固化，但四个回应场景的负面Agent大多在声明发布当轮立即恢复，之后即使仍有负面增量评论也没有反弹。持续存在的旧声明缺少发布时间信息；`repost_fallback`虽然来自旧轮次，却使用当前`introduced_step`，会被当前轮摘要误认为新评论。

解决目标：不增加人为情绪惯性，不改变现有状态文件格式，根据事件状态历史计算声明时间，并按照时间和来源区分可见评论，让Agent正确识别本轮新证据、持续背景和历史观点再次传播。

| 文件 | 函数 | 修改内容 |
|---|---|---|
| `event_context.py` | `build_official_statement_timing()` | 新增功能：计算当前声明首次发布轮次、持续轮数和本轮新发布标记。 |
| `event_context.py` | `load_event_context()` | 修改功能：向当前事件上下文加入只读声明时间信息，不写回状态文件。 |
| `decision_engine.py` | `build_agent_event_view()` | 修改功能：将声明时间信息提供给Agent。 |
| `decision_engine.py` | `classify_visible_comment_source()` | 新增功能：区分本轮LLM评论、历史转发、应急评论和历史评论。 |
| `decision_engine.py` | `summarize_visible_comments()` | 修改功能：形成四层评论摘要，同时保留当前轮总体摘要。 |
| `decision_engine.py` | `build_allowed_choices()`、`build_decision_prompt()` | 修改功能：明确不同时间和来源证据的优先级与用途。 |

验收标准：

1. 声明发布轮`is_new=true`且持续轮数为1，后续轮次`is_new=false`并递增持续轮数。
2. `repost_fallback`不计入本轮LLM新评论，`local_emergency_fallback`单独统计。
3. 旧声明继续有效，但不再被解释为每轮重新发布的新声明。
4. 新负面评论能够支持已恢复Agent合理反弹，不强制任何情绪转换。
5. 不修改事件状态JSON格式，不增加LLM调用，不运行DeepSeek完整联调。




### 2026/09/04 Demo性能基线与运行耗时统计

当前问题：当前配置下，10 个 Agent、10 个时间步和 5 个策略完整运行约需 40 分钟。此前只能根据调用链推测 Agent 决策、增量评论生成和策略串行是主要耗时来源，实验结果没有保存分阶段墙钟耗时、分类 LLM 调用数和实际 HTTP 重试数，无法形成可量化的优化前基线。

解决目标：不修改仿真规则、评论生成规则、Agent 决策逻辑、实验规模和并发参数，为初始评论池、共享基线、策略、时间步以及三类单轮阶段增加性能统计；将主进程和各时间步子进程的统计汇总到现有 `experiment_result.json`，不新增运行状态文件。

| 类型 | 文件 | 主要工作 |
| --- | --- | --- |
| 修改 | `llm_service.py` | 线程安全地统计逻辑调用、实际 HTTP 尝试、重试、最终失败和累计耗时，并支持跨进程结果汇总。 |
| 修改 | `comment_angle_planner.py` | 将事件角度规划调用标记为 `comment_angle`。 |
| 修改 | `comment_generation_service.py` | 将初始和增量评论生成调用标记为 `comment_generation`。 |
| 修改 | `agent_decision_llm_demo.py` | 将 Agent 认知调用标记为 `agent_decision`。 |
| 修改 | `metrics.py` | 将全局趋势调用标记为 `global_trend`。 |
| 修改 | `simulation_runner.py` | 记录单轮总耗时、增量评论生成、Agent 决策和指标计算耗时，并向父进程返回结构化统计。 |
| 修改 | `experiment_runner.py` | 解析单轮子进程结果，分别汇总共享基线、各策略、各阶段和全部子进程 LLM 统计。 |
| 修改 | `main.py` | 记录初始评论池和完整入口耗时，合并初始评论阶段与实验阶段的 LLM 统计并写回最终结果。 |
| 修改 | `detail.md` | 记录性能统计目标、技术方案、结果字段和验收要求。 |
| 不新增 | 运行状态文件 | 性能数据写入现有场景结果和 `experiment_result.json`，不改变状态初始化和快照文件集合。 |

涉及的主要功能函数：

| 函数 | 操作 | 功能 |
| --- | --- | --- |
| `reset_llm_performance_stats()` | 新增 | 清空当前进程的 LLM 性能统计。 |
| `get_llm_performance_stats()` | 新增 | 返回经过耗时精度处理的线程安全统计快照。 |
| `merge_llm_performance_stats()` | 新增 | 合并初始评论、共享基线和不同时间步子进程的统计。 |
| `call_deepseek_json()` | 修改 | 增加可选 `request_type`，记录一次逻辑调用的 HTTP 尝试、重试、失败和完整等待时间。 |
| `run_one_simulation_step()` | 修改 | 记录本轮三类阶段耗时和 LLM 统计。 |
| `parse_simulation_step_result()` | 新增 | 从子进程标准输出中提取带固定标记的结构化单轮结果。 |
| `summarize_step_performance()` | 新增 | 汇总一个共享基线或策略实际执行的全部时间步。 |
| `build_experiment_performance()` | 新增 | 生成实验级策略耗时、阶段耗时和 LLM 请求汇总。 |
| `run_shared_pre_entry_baseline()` | 修改 | 保存共享基线墙钟耗时和分轮性能。 |
| `run_one_content_strategy()` | 修改 | 保存策略自身墙钟耗时和进场后实际执行时间步性能。 |
| `run_experiment()` | 修改 | 生成实验阶段性能汇总，并随最终实验结果保存。 |
| `run_complete_simulation()` | 修改 | 补充初始评论池和完整程序耗时，写回最终性能结果并输出简要统计。 |

最终 `experiment_result.json` 新增或补充：

```json
{
  "performance": {
    "total_duration_seconds": 0.0,
    "initial_comment_pool_duration_seconds": 0.0,
    "experiment_duration_seconds": 0.0,
    "shared_baseline_duration_seconds": 0.0,
    "strategy_duration_seconds": {},
    "stage_duration_seconds": {
      "initial_comment_pool": 0.0,
      "incremental_comment_generation": 0.0,
      "agent_decision": 0.0,
      "metrics": 0.0
    },
    "llm_requests": {
      "logical_request_count": 0,
      "http_attempt_count": 0,
      "retry_count": 0,
      "failed_request_count": 0,
      "total_duration_seconds": 0.0,
      "by_type": {}
    }
  }
}
```

统计口径：

1. `logical_request_count`表示业务代码调用 `call_deepseek_json()` 的次数。
2. `http_attempt_count`包含首次 HTTP 请求和失败后的实际重试请求。
3. `retry_count`等于同一次逻辑调用中首次请求之后的附加 HTTP 尝试数。
4. LLM累计耗时是各请求等待时间之和；Agent并发时可能大于实验墙钟耗时，不能直接相加解释为程序运行时间。
5. 共享基线只统计一次，复制到五个场景的历史轮次不重复计入实验性能。
6. 各策略耗时只统计从共享基线分叉后由该策略实际执行的部分。

验收标准：

1. 不联网语法、导入和模拟请求检查通过，不运行 DeepSeek 完整联调。
2. 一次成功和一次重试成功的模拟请求能够正确区分逻辑调用数、HTTP 尝试数和重试数。
3. 单轮结果包含三类阶段耗时、单轮总耗时和按类型划分的 LLM 统计。
4. 场景结果包含自身实际执行时间步及汇总，不重复统计共享基线。
5. 最终实验结果包含初始评论池、实验、共享基线、各策略、各阶段和 LLM 请求统计。
6. 原有实验状态、策略比较、指标结构和启动命令保持兼容。
7. 下一次正式联调保持原有参数不变，以该次结果作为后续性能优化的第一份基线。

性能基线结果：实验 `event_wenjie_001_20260904_191412_750213` 总耗时 1425.342 秒，增量评论生成耗时 1185.290 秒，占 83.2%；全部 748 次 LLM 逻辑调用中，评论生成 330 次、Agent 决策 380 次、趋势分析 37 次、角度规划 1 次。评论生成是首要瓶颈，HTTP 重试次数为 0，本地增量处理耗时不足 1 秒。


### 2026/09/04 增量评论生成架构优化

当前问题：每轮 20 条增量评论被拆成两个 10 条子批次，每个子批次最多串行尝试 5 次，一轮最多产生 10 次串行评论请求。性能基线显示，大量时间消耗在业务层重复补齐，而不是 HTTP 重试、本地校验或文件读写。

解决方案：两个首轮子批次并行且各请求一次；程序合并校验结果，统一收集跨批次重复文本和缺失角度任务；仍有缺口时只执行一次定向补齐，之后沿用现有历史评论和本地应急兜底，不改变每轮 20 条评论、评论字段、Agent 决策和指标计算结构。

| 类型 | 文件 | 主要工作 |
| --- | --- | --- |
| 修改 | `project_config.py` | 新增增量评论首轮批次并发数和统一补齐次数配置。 |
| 修改 | `comment_generation_service.py` | 批次生成支持由调用方限制请求次数；本地规范化可明确识别的枚举写法，避免仅因空格、大小写或中英文别名重新请求。 |
| 修改 | `incremental_comment_generator.py` | 并行执行首轮批次、处理跨批次重复、合并缺失任务并只补齐一次；保存首轮请求数、补齐请求数和生成波次数。 |
| 修改 | `experiment_runner.py` | 将新增的业务请求和生成波次统计传递到场景单轮结果，便于联调对比。 |
| 修改 | `detail.md` | 记录首份性能基线、架构瓶颈、技术方案和验证标准。 |

涉及的主要功能函数：

| 函数 | 操作 | 功能 |
| --- | --- | --- |
| `normalize_comment_value()` | 新增 | 规范化评论枚举字段中可明确识别的合法写法。 |
| `generate_valid_comment_batch()` | 修改 | 新增 `max_attempts` 参数；未传入时继续使用原来的 5 次配置。 |
| `generate_incremental_comment_batch()` | 新增 | 单次生成并校验一个增量评论子批次，为并行首轮提供独立输入和统计。 |
| `merge_parallel_comment_batches()` | 新增 | 按稳定顺序合并并行结果，并过滤跨批次重复文本和任务。 |
| `generate_incremental_comments()` | 修改 | 两个首轮批次并行生成，全部缺失任务统一补齐一次，最后进入原有兜底。 |
| `validate_incremental_record()` | 修改 | 校验新增的首轮请求、补齐请求和生成波次字段。 |
| `run_incremental_generation()` | 修改 | 将新增业务请求统计写入每轮增量评论历史。 |
| `load_step_comment_quality()`、`summarize_comment_quality()` | 修改 | 将新增统计写入场景单轮结果并汇总到策略数据质量结果。 |

验证标准：

1. 初始评论池继续使用原来的批次重试设置，不受增量评论并发方案影响。
2. 默认每轮 20 条增量评论首轮产生 2 个并行请求，统一补齐最多增加 1 个请求。
3. 两个并行批次使用互不重叠的角度任务，并在合并时再次检查文本和任务重复。
4. 一次统一补齐后仍不足时沿用历史评论和本地应急兜底，场景不因评论数量不足退出。
5. 增量评论记录新增 `initial_request_count`、`refill_request_count`和`generation_wave_count`，原字段保持兼容。
6. 不修改Agent决策、动态进场、策略比较、指标计算和五策略串行方式。
7. 先完成不联网语法、导入和模拟请求测试，不由代码修改过程运行DeepSeek完整联调。


### 2026/09/04 评论质量与总耗时平衡优化

当前问题：并行首轮加统一补齐将完整实验耗时从 1425.342 秒降至 710.698 秒，评论生成请求从 330 次降至 118 次；但 900 条增量评论中有 458 条来自历史兜底，总兜底率约 50.9%。每个增量轮次都触发一次普通补齐，完整结果中的主要过滤原因为重复文本，说明固定三次请求只是提前结束生成，没有同时解决模型复述历史评论和并行批次表达趋同的问题。

解决方案：保留两个首轮批次并行和一次普通补齐；将上一轮 Agent 实际评论全部加入首轮禁止重复文本；为角度任务轮换事实核验、具体质疑、影响分析、态度判断和处理建议五种表达方式；普通补齐改用精简上下文。普通补齐后至少获得 17 条 LLM 有效评论时直接兜底，少于 17 条时最多追加一次质量救援，救援允许为部分缺失任务提供备选表达，最后继续使用原有两级兜底。

| 类型 | 文件 | 主要工作 |
| --- | --- | --- |
| 修改 | `project_config.py` | 新增质量救援次数和备选表达数量配置，维持每轮最多四次评论请求。 |
| 修改 | `comment_angle_planner.py` | 为评论任务确定性轮换五种表达方式，并兼容没有表达字段的旧任务。 |
| 修改 | `comment_generation_service.py` | 将任务表达方式写入有效评论，供后续诊断和补齐复用。 |
| 修改 | `comment_pool_generator.py` | 初始评论提示词遵循表达方式，并在派系补齐和结果保存时保留相关字段。 |
| 修改 | `incremental_comment_generator.py` | 上一轮实际评论强制避重；补齐提示词精简；增加17条质量门槛和最多一次质量救援。 |
| 修改 | `experiment_runner.py` | 将质量目标、救援请求数及其汇总写入场景结果。 |
| 修改 | `example/comment_pool_angle_task_example.json`、`example/incremental_comment_history.jsonl` | 补充表达方式、质量门槛和救援请求统计示例。 |
| 修改 | `detail.md` | 记录加速结果、质量代价、平衡方案和验证标准。 |

涉及的主要功能函数：

| 函数 | 操作 | 功能 |
| --- | --- | --- |
| `validate_comment_tasks()` | 修改 | 校验表达方式，并为旧任务补充默认表达方式。 |
| `build_angle_tasks()` | 修改 | 在角度轮转基础上同步轮换五种表达方式。 |
| `build_incremental_prompt()` | 修改 | 明确上一轮评论只用于理解、不得复述，并支持精简补齐上下文和备选表达。 |
| `select_missing_comment_tasks()` | 新增 | 统一计算普通补齐和质量救援仍需完成的任务。 |
| `generate_incremental_comments()` | 修改 | 按17条质量门槛决定是否追加一次救援请求，并保存质量目标和请求统计。 |
| `validate_incremental_record()`、`run_incremental_generation()` | 修改 | 校验并保存 `rescue_request_count`和`quality_target_count`。 |
| `load_step_comment_quality()`、`summarize_comment_quality()` | 修改 | 将质量救援数据传递并汇总到最终实验结果。 |

验证标准：

1. 每轮首轮保持两个并行请求，普通补齐最多一次，质量救援最多一次，总请求不超过四次。
2. LLM 有效评论达到17条后不触发质量救援，剩余最多3条使用现有兜底。
3. LLM 有效评论少于17条时触发质量救援，救援完成后无论结果如何都不再继续请求。
4. 上一轮 Agent 实际评论进入禁止重复列表，但仍以结构化形式作为首轮讨论背景。
5. 补齐和救援不重复发送完整人物定义及上一轮讨论内容，只保留事件、声明、缺失任务和避重文本。
6. 初始评论池、Agent决策、动态进场、策略比较和指标计算接口保持兼容。
7. 完成不联网语法、导入、快路径、临界路径和救援路径测试，不由修改过程运行DeepSeek完整联调。

### 2026/09/05 核心代码结构重构

在性能优化结果完成固化后，将原本平铺在 `demo` 根目录的核心文件按业务职责分包。此次重构只调整目录、文件名、导入路径和仿真子进程启动方式，不修改算法、运行参数、JSON结构、输入文件位置及 `python demo\main.py` 启动命令。

| 目录 | 主要职责 | 迁入内容 |
| --- | --- | --- |
| `demo/comments` | 评论领域 | 角度规划、公共生成服务、初始评论、增量评论和评论池访问 |
| `demo/agents` | Agent领域 | LLM认知决策、本地决策引擎、批量决策、Agent状态和Persona访问 |
| `demo/simulation` | 仿真领域 | 单轮运行、事件状态、传播、批次管理和状态隔离 |
| `demo/evaluation` | 评估领域 | 单轮指标、过程指标和对照净效果计算 |
| `demo/infrastructure` | 基础设施 | LLM请求、性能统计和JSON/JSONL存储 |

`main.py`、`experiment_runner.py` 和 `project_config.py` 继续保留在 `demo` 根目录，分别承担稳定入口、五策略总调度和集中配置。历史复现继续使用原入口并复用重构后的核心包。`comment_pool_example.json`、`metrics_result_example.json` 和两个单 Agent 调试结果统一移入 `demo/example`，其中调试结果的默认保存路径已同步调整。评论生成人物类型由 `comment/user.json` 移至 `demo/config/comment_profiles.json`，现行评论生成器与早期评论原型的读取路径已同步更新，并与正式 Agent Persona 明确分离。无网络语法、核心导入、仿真模块入口及历史复现导入检查均通过。

### 2026/09/05 社交网络传播第一阶段

完成固定社交网络、Agent影响力权重和个人可见范围内传播。每个实验批次根据固定种子与实际参与Agent生成一份 `social_network_snapshot.json`；关注边表示一个Agent能够接收其邻居上一轮的实际表达，邻居评论按发布者影响力加权抽取，数量不足时继续由公共评论池补足。

| 操作 | 文件 | 完成功能 |
| --- | --- | --- |
| 新增 | `simulation/social_network.py` | 构建、校验和查询固定有向网络，并根据粉丝规模和认证状态计算相对影响力权重。 |
| 新增 | `config/social_network_config.json` | 配置网络种子、邻居数、邻居评论数、公共补充数和认证加权。 |
| 修改 | `simulation/propagation.py` | 提取邻居上一轮表达，按影响力加权抽样，并与公共评论合并为个人可见范围。 |
| 修改 | `agents/batch_decision.py` | 加载网络快照和上一轮表达，记录邻居传播与公共补充的实际数量。 |
| 修改 | `agents/decision_service.py`、`agents/decision_engine.py` | 最终表达只能从个人可见评论中筛选、评分和选择。 |
| 修改 | `experiment_runner.py`、`project_config.py` | 为五策略生成并传递同一网络快照，同时兼容独立入口和历史复现。 |
| 新增 | `example/social_network_snapshot_example.json` | 展示网络节点、影响力权重和关注边的数据结构。 |

本阶段不包含传播事件持久化、传播层级与衰减、覆盖人数和传播深度指标、动态关注关系及参数校准。已完成语法、核心导入、固定网络可复现性、邻居与公共评论数量、最终表达可见范围等无网络检查，并由第二十五次正式联调验证完整运行结果。

### 2026/09/05 社交网络传播第二阶段A

在第一阶段固定网络和邻居传播基础上，补充可追溯的传播记录、表达谱系、层级衰减和传播指标。邻居评论进入Agent个人视野记为一次`neighbor_exposure`；只有目标Agent最终选中该评论时，才标记`was_selected=true`并形成下一轮可继续传播的新表达。公共评论补充不属于关系网络传播，不写入邻居传播事件文件。

| 操作 | 文件 | 完成功能 |
| --- | --- | --- |
| 新增 | `simulation/propagation_tracking.py` | 为Agent表达生成稳定编号，保存父表达和根表达谱系，构建并防重写入邻居曝光事件。 |
| 新增 | `evaluation/propagation_metrics.py` | 计算曝光次数、覆盖人数、覆盖率、继续传播次数、传播深度和有效权重。 |
| 修改 | `simulation/propagation.py`、`simulation/social_network.py` | 逐跳传递表达谱系，并按`影响力 × 衰减系数^(层级-1)`计算有效传播权重。 |
| 修改 | `agents/batch_decision.py` | 全部Agent决策成功后保存本轮传播事件和表达谱系。 |
| 修改 | `evaluation/metrics.py`、`experiment_runner.py` | 将传播指标加入逐轮指标、场景摘要和五策略并列结果。 |
| 修改 | `simulation/state_manager.py`、`project_config.py` | 初始化、复制、校验并集中配置`propagation_history.jsonl`。 |
| 修改 | `historical_replay/replay_runner.py` | 历史复现继续复用相同传播核心，并输出累计传播摘要。 |
| 新增 | `example/propagation_history_example.jsonl` | 展示第一跳、第二跳、衰减权重和是否继续表达的数据结构。 |

已完成全量Python语法检查、核心与历史复现导入检查、两跳谱系与衰减、传播事件构建、指标计算和示例JSON/JSONL格式验证。第二十六次正式五策略联调进一步验证了传播事件文件、4～6层表达谱系、0.7逐层衰减，以及逐轮、场景和实验三级传播指标，第二阶段A正式通过验收。动态关注关系和真实数据参数校准不属于本阶段，继续暂缓。

### 2026/09/06 第二十六次联调社交网络传播专题展示

在 `visualization/social_network_report` 中新增独立只读网页，固定展示第二十六次联调。页面支持五场景切换、1～10轮传播播放、Agent影响力与曝光统计、单评论传播链追踪、五策略传播指标对照及验收边界说明；不调用大模型，不修改实验结果，也不影响原有五策略和历史复现入口。



## 五、历史规划及完成情况

### 2026/08/22 原阶段规划

#### 计划一：系统重置与状态初始化

- 已完成：新增 `simulation_state_manager.py`，统一创建、检查和重置运行状态，保护历史实验和基础 Persona。

##### 系统重置与状态初始化实施方案

当前状态：已实现，并已完成初始化、拒绝覆盖、严格校验、安全重置和非法路径拦截测试。

目标：统一创建、检查和重置运行状态，同时保护历史实验、基础 Persona、事件输入和初始评论池。  

| 类型 | 文件 |
| --- | --- |
| 新增 | `simulation_batch_manager.py` |
| 修改 | `main.py` |
| 修改 | `experiment_runner.py` |
| 修改 | `project_config.py` |
| 修改 | `simulation_state_manager.py` |
| 不需要修改 | 其余仿真业务模块 |

修改后的实验目录
demo/experiments/
└── event_001_20260822_200500/
    ├── event_input.json
    ├── comment_pool.json
    ├── experiment_result.json
    ├── no_response/
    │   ├── scenario_result.json
    │   └── state/
    ├── negative_threshold/
    ├── global_worsening/
    └── combined_policy/

####  <span style="color:#0969DA;">计划二：同一事件内的适应性画像（暂缓）</span>
- 新增 `adaptive_persona.py` 和 `adaptive_persona_history.jsonl`，让 Agent 在多轮模拟中缓慢变化，但不修改基础 Persona。

#### 计划三：评论派系覆盖补齐 2026/08/23

- 检查初始评论池五类派系分布，对缺失派系进行定向补充。

##### 评论五派覆盖补齐实施方案

目标：检查初始评论池中观点输出派、表态判断派、情绪激进派、矛盾激化派和吃瓜派的数量，对未达到最低数量的派系定向补充，同时保持评论池总数量不变。

| 类型 | 文件 | 主要目标 |
| --- | --- | --- |
| 修改 | `project_config.py` | 新增每个评论派系的最低数量配置，并保证五派最低数量之和不超过初始评论池总数。 |
| 修改 | `comment_generation_service.py` | 扩展评论规范化和批次生成函数，支持限制本次只接收指定派系，并复用现有累积、去重和重试逻辑。 |
| 修改 | `comment_pool_generator.py` | 统计五派数量、计算缺口、构造定向补充提示词、替换数量过多派系的部分评论，并在分配评论编号前完成最终覆盖校验。 |
| 不需要修改 | `incremental_comment_generator.py` | 当前只保证初始评论池覆盖五派，后续轮次的增量评论暂不强制覆盖。 |
| 不需要修改 | `comment_pool_repository.py`、`decision_engine.py`、`batch_agent_decision.py`、`main.py` | 继续复用现有评论读取、Agent 评分、批量决策和统一入口，不改变已有业务边界。 |



#### <span style="color:#0969DA;">计划四：固定官方回应时机实验（暂缓）</span>

- 使用相同声明，分别测试不回应、第 2 轮、第 3 轮、第 4 轮回应。

#### 计划五：官方内容策略对照  2026/08/23

- 以不回应作为独立基线，四种回应场景固定使用相同的动态进场规则，分别测试事实通报、共情安抚、辟谣澄清和处置进展。

##### 官方内容策略对照实施方案

目标：由人工在 JSON 文件中配置当前事件的四类官方声明，保留不回应作为独立基线；四个内容场景使用相同的动态进场规则且最多回应一次，比较不回应和不同声明内容对舆情指标的影响。

| 类型 | 文件 | 主要目标 |
| --- | --- | --- |
| 新增数据文件 | `official_response_options.json` | 保存事件编号、统一动态进场规则、四种内容策略、具体声明和声明状态。 |
| 修改 | `project_config.py` | 新增人工官方内容策略文件路径。 |
| 修改 | `simulation_batch_manager.py` | 创建实验批次时保存独立的官方内容策略快照。 |
| 修改 | `main.py` | 启动时读取官方内容策略，并将批次快照路径传给实验执行器。 |
| 修改 | `experiment_runner.py` | 校验外部内容策略，先运行不回应基线，再使用同一动态规则分别运行四个内容场景，每个内容场景最多回应一次并汇总五个场景的对照结果。 |
| 不需要修改 | `event_state_updater.py`、`simulation_runner.py`、`batch_agent_decision.py`、`decision_engine.py` | 继续使用现有官方声明状态、单轮仿真、Agent 决策和评论评分接口。 |




#### 计划六：小规模功能联调

- 使用 3 个 Agent、3 个时间步，检查新增模块是否正确接入。

#### 计划七：正式 Demo 联调

- 使用 10 个 Agent、10 个时间步，运行不回应基线和四种官方内容策略对照实验。
- 2026/08/24 首次正式联调已完成运行，但五个实验组均因增量评论有效数量不足而提前终止。
- 系统重置、实验状态隔离、官方策略读取、动态进场和声明写入功能正常。
- 2026/08/24 第三次联调完成 3 个场景，另有 2 个场景分别因趋势 JSON 截断和缺少 3 条评论超过兜底上限而失败。
- 当前已缩小趋势分析输入并将有限历史评论兜底上限调整为 3 条，待下一次正式联调验证。
- 三次联调的实验编号、结果和问题处理记录见 [`INTEGRATION_TEST_HISTORY.md`](./INTEGRATION_TEST_HISTORY.md)。

#### 计划八：结果整理和文档更新

- 更新 README、接口文档、流程图和汇报材料。

#### 计划九：9 月 1 日最终验收

- 确认一键启动、策略全部成功、状态完整、实验结果可比较。




## 六、报警和报错处理规范

### 已经解决的问题

| 问题 | 当前处理方式 |
| :-- | --- |
| DeepSeek 临时网络错误、限流或服务端错误 | `llm_service.py` 统一有限重试 |
| DeepSeek 返回内容包含多余文本 | 只解析第一个完整 JSON 对象 |
| 评论批次少于目标数量 | 保留有效评论，按缺少数量增加冗余请求并最多尝试 5 次；仍不足时输出各项过滤原因并停止当前策略 |
| 单个 Agent 决策失败 | 本轮决策和 Agent 状态均不落盘，可重新运行 |
| 决策已经完成但指标中断 | 复用完整决策，继续计算指标 |
| Agent 状态写入不完整 | 根据完整决策补写缺失状态 |
| 子进程中文异常信息乱码 | 设置 `PYTHONIOENCODING=utf-8` |
| 实验目录已经存在 | 停止运行，保护已有实验结果 |

### 状态管理模块新增的明确报错

| 情况 | 处理方式 |
| --- | --- |
| 状态目录缺失 | 提示先运行状态初始化 |
| 必要状态文件缺失 | 列出缺失文件名并停止运行 |
| 事件编号不一致 | 提示事件文件与状态历史不匹配 |
| JSONL 某一行损坏 | 报告文件名和具体行号，不允许静默跳过 |
| 状态目录已经有正式数据 | 拒绝初始化，提示更换实验编号 |
| 重置目标不是 `demo/state` | 拒绝重置，防止误删历史实验 |
| 同一事件存在重复时间步 | 报告重复的 `event_id` 和 `step` |

空的 JSONL 文件属于合法初始状态，不应产生报警。

## 七、后续扩展方向

### 后续画像工作

基础 Persona 继续保存在 `output/personas`，不得被仿真过程覆盖。适应性画像将在系统状态管理完成后，以独立的 `adaptive_persona_history.jsonl` 保存，并加入统一状态初始化流程。

适应性画像后续用于记录 Agent 在多个事件中的近期经历和长期变化。单个事件只形成事件经历，不直接永久修改基础 Persona；积累多个事件后，再根据一致、重复出现的行为证据缓慢更新长期画像。

### Demo性能与单机并发

先建立分阶段耗时和 LLM 请求统计，再根据实测结果优化增量评论生成、Agent 请求并发和策略调度。Demo 阶段只实现可配置、可恢复的单机受控并发，不建设复杂的分布式任务系统。

### 数据库与后端

将当前分散在 JSON 和 JSONL 文件中的实验配置、轮次状态、Agent 决策、指标和结果逐步映射到数据库。后端提供实验创建、任务启动、进度查询、结果读取和失败信息查询接口，同时保留原始实验快照和历史结果不可覆盖原则。

### 生产级任务调度

在后端阶段统一实现实验队列、策略并发、全局 LLM 限流、超时重试、任务取消、断点恢复和多用户资源隔离。生产级调度不直接复用 Demo 中简单增加线程数的方式。

### 实验与指标扩展

- 在需要时开展固定官方回应时机实验，比较相同声明在不同轮次进场的效果。
- 小范围验证声明状态后，再决定是否扩展“内容策略 × 声明状态”组合实验。
- 增加同一配置的多批次运行，统计均值、波动范围和策略排序稳定性。
- 继续将评论生成质量与策略效果分别报告，避免高兜底数据直接用于策略结论。

### 社交传播深化

- 保存逐轮传播事件，记录评论从哪个Agent传播到哪个Agent。
- 增加传播层级与衰减，以及覆盖人数、传播深度等指标。
- 在固定网络结果稳定后，再实现动态关注关系和参数校准。

最后统一更新 README、接口文档、流程图和汇报材料。

## 杂项

### 修改要求

修改要求：尽可能的简单，不需要很复杂，实现主要功能，代码具有可读性，遵循高内聚低耦合，不要与已有的工作产生冲突。
