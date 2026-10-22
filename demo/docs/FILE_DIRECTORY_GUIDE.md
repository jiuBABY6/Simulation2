# 项目目录与文件功能说明

本文用于帮助新成员快速理解项目目录、文件职责和使用边界。文档以当前工作区为准，重点覆盖项目自研代码、配置、示例、文档和运行产物。

## 一、说明范围

文件按以下类型标注：

| 类型 | 含义 |
| --- | --- |
| 当前核心 | 当前回应方案对照或历史趋势复现会直接使用的代码、配置和数据 |
| 辅助工具 | 为画像构建、可视化、演示或开发提供支持，不属于主仿真入口 |
| 运行产物 | 由程序生成的结果、状态、缓存或示例数据，通常不应作为业务代码修改 |
| 历史/外部参考 | 早期原型、归档文档或外部参考工程，不是当前 Demo 的执行入口 |

`demo/experiments`、`output/personas` 和 `__pycache__` 中包含大量同构文件，本文按文件命名规则说明，不重复列出每个实验批次、每个 Agent 和每个字节码文件。`agentsociety2`、`oasis-master`、`TrendSim` 是外部参考工程，按顶层模块说明，具体内部文件应以各工程自身文档为准。

## 二、项目根目录

| 路径 | 类型 | 主要功能 | 使用说明 |
| --- | --- | --- | --- |
| `demo/` | 当前核心 | 舆情社会模拟 Demo 主体，包含回应方案对照、历史复现、配置、状态、结果和文档 | 当前开发和运行的主要目录 |
| `comment/` | 历史原型 | 保留早期评论池、评分和分析原型 | 当前 Demo 不再依赖该目录，不作为正式入口 |
| `persona_pipeline/` | 辅助工具 | 从原始社交数据构建 Persona、情绪阈值和派系偏好 | 画像重新生成时使用 |
| `output/` | 当前核心数据 | 保存 Persona 构建结果和全局策略配置 | 当前 Agent 决策会读取 `output/personas` |
| `visualization/` | 辅助工具 | 提供历史趋势对照及第二十六次联调社交网络传播专题网页 | 只读仿真结果，不参与仿真计算 |
| `agentsociety2/` | 外部参考 | AgentSociety 相关框架代码 | 当前 `demo/main.py` 不以它作为运行入口 |
| `oasis-master/` | 外部参考 | OASIS 社交媒体仿真框架和示例 | 用于设计参考，修改前应先确认是否准备正式集成 |
| `TrendSim/` | 外部参考 | 另一套舆情趋势模拟原型 | 与当前 Demo 相互独立 |
| `.agents/` | 工具配置 | 智能编码工具的本地配置目录 | 不属于产品代码，不应加入业务依赖 |
| `.git/` | 版本控制 | Git 仓库元数据、对象和分支信息 | 不手工修改 |
| `__pycache__/` | 运行产物 | 根目录 Python 字节码缓存 | 可由 Python 自动重建，不是源码 |
| `requirements.txt` | 环境配置 | 当前项目运行、可视化和Persona构建所需的Python第三方依赖清单 | 新环境在项目根目录使用`python -m pip install -r requirements.txt`安装 |

## 三、`demo`：当前仿真核心

### 3.1 主入口、配置和输入

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `main.py` | 当前核心 | 回应方案对照总入口；准备初始评论池并调用实验调度器。正常运行命令为 `python demo\main.py` |
| `project_config.py` | 当前核心 | 集中定义项目路径、模型参数、Agent 数量、并发数、评论数量、重试次数、质量阈值和可见评论数量等配置 |
| `experiment_runner.py` | 当前核心 | 回应方案对照总调度器；运行共享进场前基线、判断官方动态进场、分流各场景、汇总质量与性能并比较结果 |
| `event_example.json` | 当前核心输入 | 当前回应方案对照的事件材料，包括 `event_id`、事件描述、标签和初始状态等 |
| `official_response_options.json` | 当前核心输入 | 配置三个可自定义回应方案及官方声明内容、状态与统一进场规则；不回应基线由实验调度器补充 |
| `comment_pool.json` | 运行产物 | 当前调试或最近一次准备得到的初始评论池；正式批次会复制独立快照 |

注意：`event_example.json` 与 `official_response_options.json` 中的 `event_id` 必须一致。`project_config.py` 涉及模型访问配置，敏感凭据应通过安全配置方式管理，不应在文档、日志或提交记录中暴露。

### 3.2 `demo/config`：业务配置数据

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `comment_profiles.json` | 当前核心配置 | 定义候选评论生成使用的人物类型、表达特点和信息倾向；它是评论模板，不是参与仿真的 Agent Persona |
| `social_network_config.json` | 当前核心配置 | 定义固定网络种子、每个Agent的邻居数量、邻居评论数量、公共评论补充数量、认证影响力加成和逐层传播衰减系数 |

### 3.3 `demo/comments`：评论生成与评论池

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记评论领域包并说明模块边界 |
| `angle_planner.py` | 当前核心 | 根据事件生成“评论角度计划”，并将角度、评论派系和人物类型组织成初始评论或增量评论生成任务 |
| `generation_service.py` | 当前核心 | 评论生成公共服务；加载人物类型、规范字段、校验评论、统计过滤原因并执行有限次数补齐 |
| `pool_generator.py` | 当前核心 | 生成初始评论池，检查五派覆盖情况并补齐缺少的评论派系 |
| `incremental_generator.py` | 当前核心 | 每轮生成增量评论；负责触发原因、并行首轮请求、补齐、质量救援、历史评论兜底、本地应急兜底和质量统计 |
| `repository.py` | 当前核心 | 统一读取初始评论、增量评论和全部评论，并按 `comment_id` 查询评论 |

### 3.3.1 `demo/application`：跨实验共享应用层

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `runtime_config.py` | 当前核心 | 集中保存单轮参数，并把旧全局配置转换为可注入的路径、决策和仿真配置对象 |
| `error_summary.py` | 当前核心 | 把完整异常整理成适合控制台显示的单行摘要 |
| `scenario_state.py` | 当前核心 | 创建隔离场景状态，必要时从共享基线快照初始化 |
| `step_executor.py` | 当前核心 | 封装仿真子进程、运行环境和结构化结果协议；用户中断时负责终止并回收当前子进程 |
| `round_results.py` | 当前核心 | 读取轮次指标、评论质量和传播摘要，不包含具体实验规则 |

两类实验都依赖该层。历史复现不再通过导入`experiment_runner.py`复用回应方案对照
实现，避免一种业务模式依赖另一种业务模式的顶层编排器。

### 3.3.2 `demo/domain`：跨模块数据契约

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `contracts.py` | 当前核心 | 定义 `SimulationContext`、`AgentDecisionInput` 和 `AgentDecisionResult`，在编排器与Agent核心之间提供稳定输入输出边界 |

领域契约不读取文件或环境变量。现有 JSON 字典只在入口和持久化边界转换，
因此实验结果格式保持兼容。

### 3.4 `demo/agents`：Agent 感知与决策

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记 Agent 决策领域包并说明模块边界 |
| `decision_service.py` | 当前核心 | 串联状态LLM、本地行为门控、按需原创表达或转发，不读取仿真文件 |
| `official_attitude.py` | 当前核心 | 按事实证据、过程回应、Persona门槛和上一轮状态裁决个体官方态度 |
| `decision_engine.py` | 当前核心 | 构建事件、Persona、可见评论和历史摘要；统一校验状态、证据、原创表达和转发动作 |
| `decision_profile.py` | 当前核心 | 从Persona生成稳定决策画像；按个体门槛、上一轮状态、新增证据和效用边际裁决后续情绪转移 |
| `evidence_appraisal.py` | 当前核心 | 将证据客观强度与Persona主题、信息取向和上一轮状态结合，分别给出情绪与官方态度个体影响及变化资格 |
| `evidence_impact_router.py` | 回应方案扩展 | 按评论目标、证据角色和现实来源分离事件情绪、官方态度和参与作用，防止把质疑官方等同于事件负面 |
| `state_evidence.py` | 回应方案扩展 | 从完整可见评论中构建内部状态证据视图；消融过滤后保留最近一轮、根传播去重且最多2条邻居表达，以及按Persona相关性选择的最多5条独立公共评论；完整可见评论仍交给行为层 |
| `strategy_state_transition.py` | 回应方案扩展 | 编排方向性情绪效用裁决、有限证据记忆、官方态度候选、紧凑证据目录和状态审计 |
| `strategy_evidence_integrator.py` | 回应方案扩展 | 按通告语义维度、Persona先验、上一轮惯性和独立传播根递减整合证据，输出唯一相邻状态；不读文件、不调用LLM |
| `strategy_evidence_assimilation.py` | 回应方案扩展 | 按Persona处理速度对权威证据进行最多三轮的渐进吸收、轮龄衰减、消费和有界记忆；不读文件、不调用LLM |
| `strategy_evidence_lifecycle.py` | 兼容层 | 保留旧批次的权威证据消费标记和审计兼容；新状态变化强度由`strategy_evidence_assimilation.py`负责 |
| `strategy_behavior.py` | 回应方案扩展 | 根据Persona、当轮信息、方向性证据相关度、状态效用张力和连续发言疲劳决定沉默、原创或转发，不改写内部状态 |
| `strategy_expression.py` | 回应方案扩展 | 在原创动作确定后独立构造、校验三分类表达，不判断状态或发言资格 |
| `historical_participation.py` | 历史复现扩展 | 根据相关新证据、状态变化、表达重复和连续发言疲劳评估公开表达必要性，不修改Agent内部状态 |
| `batch_decision.py` | 当前核心 | 加载固定网络；回应方案读取邻居最近3轮表达、历史复现读取上一轮表达，并保存曝光诊断 |
| `state_store.py` | 当前核心 | 维护 Agent 每轮状态、个人评论历史和情绪变化摘要，为后续轮次提供最近状态与个人经历 |
| `persona_repository.py` | 当前核心 | 从 `output/personas` 加载 Persona 和指定数量的 Agent |
| `rule_decision_demo.py` | 辅助工具 | 不调用 LLM 的规则版单 Agent 决策示例，用于本地理解和小范围调试，不是回应方案对照主流程 |

### 3.5 `demo/simulation`：仿真运行与状态

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记仿真运行领域包并说明模块边界 |
| `event_context.py` | 当前核心 | 读取事件及当前状态，构建官方声明时间语义，并验证事件输入 |
| `context_exposure.py` | 当前核心 | 将历史公众语境拆分为共享事实和按Agent稳定抽样的个体讨论曝光 |
| `evidence_policy.py` | 历史复现扩展 | 统一历史更新、客观事件和官方通告的证据强度、新旧状态、稳定编号及正面资格；避免所有公开更新被默认升级为强证据 |
| `event_state_updater.py` | 当前核心 | 追加、读取和校验事件状态历史，获取某事件的最新状态 |
| `state_manager.py` | 当前核心 | 创建、复制、校验和重置仿真状态目录，防止不同实验场景相互污染 |
| `counterfactual_controls.py` | 回应方案对照 | 规范化共享客观事实时间线，生成共同输入与进场前快照SHA-256，并检查通告后数据是否发生跨场景污染 |
| `batch_manager.py` | 当前核心 | 生成实验批次 ID，创建批次目录并保存事件、官方策略和初始评论池快照 |
| `runner.py` | 当前核心 | 执行单个时间步或多轮仿真；校验轮次顺序，串联增量评论、Agent 决策、状态更新和指标计算 |
| `propagation.py` | 当前核心 | 按轮龄优先、根链去重、时间与传播深度衰减抽取近期邻居表达，再由公共评论补足个人视图 |
| `social_network.py` | 当前核心 | 根据实际参与Agent构建和校验固定有向关系网络，计算影响力权重并查询关注邻居 |
| `propagation_tracking.py` | 当前核心 | 为Agent实际表达补充谱系，构建邻居曝光事件并防重保存传播历史 |

`demo/experiment_runner.py` 继续保留在根目录，作为回应方案对照总调度器，负责共享基线、动态进场、场景分流、质量与性能汇总和方案比较。

### 3.6 `demo/evaluation`：指标评估

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记指标评估包并说明模块边界 |
| `metrics.py` | 当前核心 | 计算负面率、情绪分布、质疑率、接受率、全局趋势，以及负面峰值、负面面积、恢复率、持续时间、反弹率和净效果等指标 |
| `propagation_metrics.py` | 当前核心 | 读取传播事件并计算曝光次数、覆盖人数、继续传播次数、传播深度和有效传播权重 |

### 3.7 `demo/infrastructure`：公共基础设施

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记公共基础设施包并说明模块边界 |
| `llm_service.py` | 当前核心 | DeepSeek JSON 请求的统一出口；负责响应解析、有限重试、异常封装和请求耗时/次数统计 |
| `json_storage.py` | 当前核心 | 提供 JSON、JSONL 的读取、保存、追加和格式校验，避免各模块重复实现文件操作 |

### 3.8 `demo/example`：数据结构示例

| 文件 | 主要功能 |
| --- | --- |
| `agent_state_history.jsonl` | 展示每轮 Agent 状态记录，包括情绪、官方态度、评论意愿和个人评论历史等字段 |
| `comment_pool_angle_task_example.json` | 展示事件角度计划与“角度＋派系＋人物类型”评论任务的数据结构 |
| `decision_history.jsonl` | 展示 Agent 每轮最终决策和所选评论的记录格式 |
| `event_state_history.json` | 展示事件状态随轮次变化以及官方声明注入后的保存格式 |
| `incremental_comment_history.jsonl` | 展示每轮增量评论、生成来源、兜底数量和质量状态的记录格式 |
| `metrics_history.jsonl` | 展示每轮舆情指标的保存格式 |
| `comment_pool_example.json` | 展示初始评论池的数据结构，不参与正式实验 |
| `metrics_result_example.json` | 展示单轮指标和扩展效果指标的数据结构，不参与正式实验 |
| `decision_result.json` | 保存规则版单 Agent 最近一次调试结果，不是回应方案对照结果 |
| `decision_result_llm.json` | 保存 LLM 版单 Agent 最近一次调试结果，不是回应方案对照结果 |
| `social_network_snapshot_example.json` | 展示网络节点、Agent影响力权重和有向关注边的数据结构 |
| `propagation_history_example.jsonl` | 展示邻居曝光、表达谱系、传播层级、衰减权重和继续表达标记 |

该目录同时保存静态结构示例和单 Agent 调试输出。它们用于理解字段或局部调试，不是正式实验输入和正式实验结果。

### 3.9 `demo/state`：默认调试状态

| 文件 | 主要功能 |
| --- | --- |
| `.gitkeep` | 让空状态目录能够被 Git 保留 |

直接调试核心模块时，默认状态文件会写入本目录。正式回应方案对照主要使用 `demo/experiments/<experiment_id>/<scenario>/state`，避免不同场景共享运行中状态。

### 3.10 `demo/experiments`：实验批次结果

该目录是运行产物目录。每个 `<experiment_id>` 表示一个独立实验批次，不建议手工修改其中内容。

#### 回应方案对照批次

```text
demo/experiments/<experiment_id>/
├─ event_input.json
├─ official_response_options.json
├─ comment_pool.json
├─ social_network_snapshot.json
├─ experiment_result.json
├─ _shared_baseline/state/
├─ no_response/
├─ response_plan_1/
├─ response_plan_2/
└─ response_plan_3/
```

| 文件或目录 | 主要功能 |
| --- | --- |
| `event_input.json` | 本批次实际使用的事件输入快照 |
| `official_response_options.json` | 本批次实际使用的官方策略快照 |
| `comment_pool.json` | 三个回应方案与不回应基线共同使用的初始评论池快照 |
| `social_network_snapshot.json` | 四个场景共同只读的固定社交网络与影响力权重快照 |
| `experiment_result.json` | 批次总结果，包括完成状态、进场原因、策略比较、数据质量、性能统计，以及共同输入哈希和跨场景污染检查 |
| `_shared_baseline/state/` | 官方进场前的共享基线状态，保证四个场景从同一舆情条件分流 |
| `<scenario>/scenario_result.json` | 单个策略场景的轮次结果、最终指标、质量与性能摘要 |
| `<scenario>/state/event_state_history.json` | 该场景每轮事件和官方声明状态 |
| `<scenario>/state/agent_state_history.jsonl` | 该场景各 Agent 的状态历史 |
| `<scenario>/state/decision_history.jsonl` | 该场景各 Agent 的决策历史 |
| `<scenario>/state/incremental_comment_history.jsonl` | 该场景每轮增量评论及生成质量记录 |
| `<scenario>/state/metrics_history.jsonl` | 该场景每轮舆情指标 |
| `<scenario>/state/propagation_history.jsonl` | 该场景逐轮邻居曝光、传播路径、层级、衰减权重和继续表达记录 |

2026/10/20 起，四个场景只共享客观输入和进场前快照。通告投入后的公众评论与Agent表达分别写入各自场景目录；`experiment_result.json.counterfactual_controls` 用于证明共同输入一致，并检查是否误用了其他场景的运行数据。

#### 历史复现批次

历史回放批次包含输入快照、`historical_replay_result.json` 和 `historical_replay/state`。输入快照用于复现配置，状态目录保存逐轮决策、指标和传播数据。它不进行回应方案比较，而是按真实时间线投入同期公众语境和官方信息。

#### 其他文件

| 文件 | 主要功能 |
| --- | --- |
| `.gitkeep` | 保留实验输出根目录 |
| `integration_test_001/` | 早期或小范围集成测试产生的固定测试批次，主要用于问题追溯 |

### 3.11 `demo/historical_replay`：历史趋势复现

该模块与回应方案对照隔离，但复用同一套 Persona、评论生成、Agent 决策和指标计算核心。

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `main.py` | 当前核心入口 | 按 `--event-id` 运行指定历史事件；省略参数时读取 `active_event.json` |
| `replay_runner.py` | 当前核心 | 按时间步投入公众语境和官方通告，运行 LLM 直接历史回放并汇总结果 |
| `timeline_service.py` | 当前核心 | 读取和校验官方信息时间线，返回指定轮次的官方状态和历史阶段 |
| `batch_manager.py` | 当前核心 | 创建隔离的历史复现批次目录，保存输入快照并准备初始评论池 |
| `runtime_paths.py` | 当前核心 | 设置模块搜索路径和运行时路径，使历史复现可以复用 `demo` 核心模块 |
| `event_repository.py` | 事件索引 | 安全解析 `events/<event_id>`，校验事件输入、初始条件、公众语境和官方时间线完整性 |
| `public_context.py` | 同期语境输入 | 校验逐轮公众语境，拒绝逐轮真实情绪比例和隐藏的数值拟合目标 |
| `initial_opinion.py` | 历史初始化 | 校验第一轮人工群体情绪配额；只服务历史回放必需输入 |
| `active_event.json` | 默认选择 | 记录无参数运行使用的默认事件，不保存事件正文 |
| `events/<event_id>/` | 当前输入 | 分事件保存清单、事件输入、第一轮比例、同期公众语境、官方时间线和可选真实趋势Excel |
| `official.md` | 原始资料 | 历史案例官方通告材料，供人工整理输入和来源追溯 |
| `__init__.py` | 包文件 | 将目录标记为 Python 包 |
| `example/event_input_example.json` | 示例 | 历史复现事件输入格式示例 |
| `example/official_response_timeline_example.json` | 示例 | 多次官方信息按指定轮次投入的时间线格式示例 |
| `__pycache__/` | 运行产物 | Python 字节码缓存，可自动重建 |

### 3.12 `demo/docs`：统一文档中心

| 文件 | 主要功能 |
| --- | --- |
| `README.md` | 文档总入口和推荐阅读顺序 |
| `FILE_DIRECTORY_GUIDE.md` | 本文；说明项目每个主要目录、文件的职责和使用边界 |
| `PROJECT_HANDOFF_20261022.md` | 当前交接现场、验证边界、风险、下一步和Destination sentinel |
| `PROJECT_STATUS.md` | 当前完成情况、主要问题和下一步唯一工作 |
| `ARCHITECTURE.md` | 系统流程、模块边界和代码地图 |
| `DATA_CONTRACT.md` | 事件、评论、状态、决策、指标和实验结果的字段契约 |
| `RUNBOOK.md` | 环境准备、替换事件、运行实验、查看结果和常见排错步骤 |
| `SIMULATION_INTERFACE_SPEC.md` | 当前仿真核心接口、调用约束和禁止事项 |
| `TASK_BREAKDOWN.md` | 面向多人协作的任务拆分、输入输出和验收标准 |
| `TEAM_COLLABORATION.md` | 团队协作、分支、修改边界和交付规范 |
| `GIT_WORKFLOW.md` | 从GitHub获取或更新项目、创建姓名分支、提交、推送和Pull Request的操作说明 |
| `LLM_SERVICE.md` | 系统各处 LLM 调用点、用途和调用边界 |
| `HISTORICAL_REPLAY.md` | 历史趋势复现模式的配置和运行说明 |
| `VISUALIZATION.md` | 回应方案对照、历史复现、人工真实趋势和传播追踪的统一网页展示说明 |
| `INTEGRATION_TEST_HISTORY.md` | 历次正式联调的日期、输入、结果、失败原因和修复记录 |
| `detail.md` | 长期开发记录，保存方案演变、阶段成果、历史计划和扩展方向 |

#### `demo/docs/dev`

| 文件 | 主要功能 |
| --- | --- |
| `README.md` | 数据库、后端和前端任务分工、完成效果及本地测试后推送规则 |
| `SHARED_INTERFACE_CONTRACT.md` | 新建实验和历史查询共同使用的状态、API响应、对象和方向语义 |
| `DATABASE_DEVELOPMENT.md` | 数据库任务、11张MVP表、导入要求、完成效果和本地验收 |
| `BACKEND_DEVELOPMENT.md` | FastAPI串行实验运行、历史查询、业务校验和本地验收 |
| `FRONTEND_DEVELOPMENT.md` | Vue 3与JavaScript的新建实验、历史查询、弹幕和结果展示任务 |
| `INTEGRATION_CHECKLIST.md` | 三端使用固定样本在本地测试，通过后再推送和合并的执行清单 |

#### `demo/docs/archive`

| 文件 | 主要功能 |
| --- | --- |
| `README.md` | 历史文档索引，说明归档材料的使用边界 |
| `README_early.md` | 早期 Demo 目录和团队参考说明 |
| `REFERENCE_NOTES_early.md` | 早期触发原因与质量状态备忘 |
| `SIMULATION_CORE_AUDIT_early.md` | 早期仿真核心审查记录 |
| `SIMULATION_INTERFACE_SPEC_early.md` | 已被当前接口规范替代的早期版本 |
| `SIMULATION_WORKFLOW_early.md` | 早期每轮仿真流程说明 |
| `TEAM_COLLABORATION_early.md` | 已被当前协作规范替代的早期版本 |
| `UNIMPLEMENTED_INTERFACES_early.md` | 早期未实现接口清单，用于追溯，不代表当前状态 |

### 3.13 `demo/ppt_assets`

用于统一保存汇报所需的可编辑幻灯片和大纲，不参与程序运行。当前保留第一次汇报`研发进展汇报.pptx`、当前第二次汇报`第二次研发成果汇报.pptx`、系统实现校正版以及第二次汇报大纲；这些文件属于交付材料，不按运行缓存清理。后续如需归档校正版，应先确认最终汇报文件已完整吸收其内容。

### 3.14 Python 字节码缓存

`demo/__pycache__` 以及各业务包内部的 `__pycache__` 保存 Python 自动生成的 `.pyc` 字节码。它们不是源码，可以重新生成。若出现已经没有对应 `.py` 文件的旧字节码，也不应据此恢复或调用旧模块。

## 四、`comment`：早期评论原型

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `data.json` | 历史原型数据 | 早期原型使用的事件和官方通告数据 |
| `main.py` | 历史原型 | 串联早期评论池生成、Agent 打分和舆情分析；引用旧模块路径并包含旧式配置，不是当前可用入口 |
| `pool.py` | 历史原型 | 早期基于 LLM 生成事件评论和通告评论的实现 |
| `score.py` | 历史原型 | 早期按用户画像对评论进行认同度评分，并完成分数转换 |
| `analyse.py` | 历史原型 | 早期根据评论及其权重生成舆情分析文本 |
| `request.py` | 历史原型 | 早期 LLM 客户端和对话历史封装 |
| `utils.py` | 历史原型 | 读取早期事件、`demo/config/comment_profiles.json` 人物定义以及选择高分评论的工具函数 |
| `readme.md` | 历史说明 | 对早期 `comment` 原型各模块的简要说明；存在旧编码痕迹，仅用于追溯 |
| `__pycache__/` | 运行产物 | 早期原型的 Python 字节码缓存 |

当前 Demo 已不再依赖该目录。需要保留早期实现时可归档；确认无需追溯后可以整体删除。

## 五、`persona_pipeline`：Persona 构建流水线

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `README.md` | 使用说明 | 说明MongoDB数据要求、Persona构建顺序、运行命令、输出文件、断点续跑和安全要求 |
| `build_personas.py` | 辅助工具 | 清洗原始微博文本，调用 LLM 分类内容与表达特征，构建每个用户的 Persona，并生成全局量化策略 |
| `build_faction_preferences.py` | 辅助工具 | 对用户历史表达进行评论派系分类，将派系偏好写回 Persona |
| `emotion.py` | 辅助工具 | 汇总 Persona 情绪值并计算情绪分位点，辅助检查或生成情绪阈值 |
| `__pycache__/` | 运行产物 | Python 字节码缓存 |

该目录负责“生成画像”，而 `demo/agents/persona_repository.py` 负责“读取画像”；二者职责不同。

## 六、`output`：Persona 与策略输出

### `output/personas`

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `agent_<user_id>.json` | 当前核心数据 | 每个文件保存一个 Agent 的 Persona，包括内容偏好、表达倾向、情绪特征、派系偏好等；当前共有多份不同用户画像 |
| `policy_config.json` | 当前核心数据 | 保存全体 Persona 统计得到的分位点和决策阈值，供 Agent 决策时进行相对分层 |
| `classification_progress.jsonl` | 构建过程产物 | 保存 Persona 文本分类进度，支持中断后继续构建，避免重复调用 LLM |
| `faction_classification_progress.json` | 构建过程产物 | 保存评论派系分类进度和结果缓存 |

`agent_<user_id>.json` 的具体文件名对应不同 Agent，但文件职责相同。正式修改画像生成规则时应修改 `persona_pipeline`，不建议批量手工改写生成结果。

## 七、`visualization`：结果展示网页

### 7.1 统一入口与共享基础层

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `app.py` | 辅助工具入口 | 唯一的本地 HTTP 服务入口，只负责分层路由、错误返回和静态资源托管 |
| `api_router.py` | API路由 | 校验只读请求参数，并把请求分发到历史、回应方案对照或共享网络服务 |
| `config.py` | 辅助工具配置 | 定义实验目录、真实数据源、处理结果和静态资源路径 |
| `portal/` | 前端入口 | 提供“回应方案对照/历史趋势复现”模式和实验批次选择 |
| `shared/artifact_io.py` | 共享读取 | 统一读取和校验 JSON、JSONL 实验产物 |
| `shared/event_resources.py` | 共享路径 | 校验事件资源编号并安全定位真实趋势文件；共享层不反向导入历史业务层 |
| `shared/experiment_catalog.py` | 共享索引 | 自动识别已完成的两类实验，并报告页面所需能力 |
| `shared/experiment_adapter.py` | 共享适配 | 把两类实验的场景、轮次、网络和传播文件转换为统一只读接口 |
| `shared/network/repository.py` | 网络数据层 | 读取并验证网络快照、传播记录和决策记录 |
| `shared/network/summary.py` | 网络摘要 | 汇总实验级网络、传播和评论质量指标 |
| `shared/network/network_view.py` | 网络构图 | 分别计算指定轮次和累计传播的节点与边状态 |
| `shared/network/cascade.py` | 评论追踪 | 构建评论目录和单评论传播 DAG |
| `shared/network/service.py` | 服务门面 | 向 HTTP 层公开稳定的共享网络接口 |
| `shared/network/static/` | 共享前端 | 展示固定关注关系、逐轮传播、节点聚焦和评论传播链 |
| `data/real_trends/<event_id>.json` | 处理产物 | 每个事件独立保存的标准化真实趋势，网页按实验编号自动选择 |
| `__init__.py` | 包文件 | 将目录标记为 Python 包 |

### 7.2 历史趋势复现层

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `historical/service.py` | 历史服务 | 封装历史实验详情、真实趋势和探索性对照 |
| `historical/simulation_data_loader.py` | 历史数据装配 | 汇总历史 Agent 指标和三种评论池情绪口径 |
| `historical/real_trend_repository.py` | 真实趋势索引 | 按 `event_id` 安全读取多事件真实趋势 |
| `historical/real_data_processor.py` | 转换工具 | 把人工整理 Excel 转换为事件级真实趋势 JSON |
| `historical/xlsx_reader.py` | Excel读取 | 使用标准库只读解析 `.xlsx` 内部 XML |
| `historical/comparison_service.py` | 探索性对照 | 对齐同一事件的模拟与人工趋势，并输出适用指标 |
| `historical/opinion_metrics.py` | 口径计算 | 统一当前轮、累计和活跃舆情的分母与三分类统计 |
| `historical/static/` | 历史前端 | 展示真实趋势、模拟趋势、公开语境和官方时间线 |

### 7.3 回应方案对照层

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `strategy/service.py` | 方案对照服务 | 只读整理四个场景的逐轮指标、最终状态、传播摘要和数据质量 |
| `strategy/static/` | 方案对照前端 | 展示回应方案逐轮负面率、方案摘要和横向比较，并进入共享网络页面 |

旧版 `data/real_trend.json`、`social_network_report/` 独立服务器、兼容转发模块和重复配置已删除。当前只保留 `python visualization\app.py` 这一服务入口。

该模块只展示已有数据。修改它不会改变 Agent 决策、官方进场或指标原始计算结果。

## 八、外部参考工程

### 8.1 `agentsociety2`

| 顶层目录或文件 | 主要功能 |
| --- | --- |
| `agent/` | Agent 基类、行为、记忆和相关能力 |
| `backend/` | 模型或服务后端适配 |
| `config/` | 框架配置结构 |
| `contrib/` | 社交媒体环境等扩展组件 |
| `custom/` | 自定义扩展示例 |
| `env/` | 仿真环境抽象 |
| `logger/` | 日志设施 |
| `registry/` | 组件注册机制 |
| `skills/` | Agent 可调用技能 |
| `society/` | 多 Agent 社会组织与运行逻辑 |
| `storage/` | 框架存储层 |
| `trace/` | 执行链路追踪 |
| `__init__.py`、`py.typed` | Python 包入口和类型提示标记 |

### 8.2 `oasis-master`

| 顶层目录或文件 | 主要功能 |
| --- | --- |
| `clock/` | 仿真时钟与时间推进 |
| `environment/` | 仿真环境 |
| `social_agent/` | 社交 Agent 行为与模型 |
| `social_platform/` | 社交平台及传播机制 |
| `demo/` | OASIS 自带示例、数据、输出和依赖说明 |
| `docs/` | OASIS 自带文档 |
| `testing/` | OASIS 自带测试代码 |
| `.agents/`、`.git/` | 外部工程自己的工具配置与版本控制元数据 |
| `__init__.py` | Python 包入口 |

### 8.3 `TrendSim`

| 文件或目录 | 主要功能 |
| --- | --- |
| `Agent.py` | TrendSim 的 Agent 定义 |
| `Attacker.py` | 对抗或攻击行为模拟 |
| `Config.py` | TrendSim 配置 |
| `Exception.py` | 自定义异常 |
| `LLM.py` | TrendSim 的 LLM 调用封装 |
| `mechanism.py` | 趋势传播或交互机制 |
| `Recorder.py` | 运行记录与结果保存 |
| `Simulator.py` | TrendSim 仿真调度核心 |
| `run.py` | 命令行运行入口 |
| `run_api.py` | API 方式运行入口 |
| `utils.py` | 通用工具函数 |
| `requirements.txt` | 依赖列表 |
| `data/` | TrendSim 输入和输出数据 |
| `__pycache__/` | Python 字节码缓存 |

以上三个目录均不是当前回应方案对照 Demo 的直接依赖。若要借鉴其中的社交网络、传播或存储能力，应通过新接口逐步接入，不能直接改写当前核心的数据结构。

## 九、新成员快速判断表

| 需要完成的工作 | 优先查看的文件 |
| --- | --- |
| 运行现有回应方案对照 | `demo/docs/RUNBOOK.md`、`demo/main.py`、`demo/project_config.py` |
| 更换事件和官方声明 | `demo/event_example.json`、`demo/official_response_options.json` |
| 修改评论生成 | `demo/comments/angle_planner.py`、`demo/comments/generation_service.py`、`demo/comments/incremental_generator.py` |
| 修改 Agent 决策 | `demo/agents/decision_service.py`、`demo/agents/decision_engine.py`、`demo/agents/state_store.py` |
| 修改评论可见性或传播 | `demo/simulation/propagation.py`、`demo/agents/batch_decision.py` |
| 修改动态进场或策略比较 | `demo/experiment_runner.py` |
| 修改舆情指标 | `demo/evaluation/metrics.py`、`demo/experiment_runner.py` |
| 运行历史趋势复现 | `demo/docs/HISTORICAL_REPLAY.md`、`demo/historical_replay/main.py` |
| 修改网页展示 | `demo/docs/VISUALIZATION.md`、`visualization/` |
| 重建 Persona | `persona_pipeline/`、`output/personas/` |
| 查看历史决策和修复背景 | `demo/docs/detail.md`、`demo/docs/INTEGRATION_TEST_HISTORY.md` |

## 十、维护规则

1. 新增代码、配置、示例或输出目录后，应同步更新本文。
2. 当前规范以 `demo/docs` 下的非 `archive` 文档为准；归档材料不作为开发依据。
3. 不把 `__pycache__`、实验批次结果或分类进度文件误认为手写源代码。
4. 评论生成人物类型统一维护在 `demo/config/comment_profiles.json`，不要与 `output/personas` 中的 Agent Persona 混用。
5. 外部参考工程与当前 Demo 保持隔离；接入前先明确接口、数据契约和验收方法。
6. 正式实验结果保存在独立批次目录中，不依赖 `demo/state` 的临时调试状态。
