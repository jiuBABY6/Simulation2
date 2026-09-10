# 项目目录与文件功能说明

本文用于帮助新成员快速理解项目目录、文件职责和使用边界。文档以当前工作区为准，重点覆盖项目自研代码、配置、示例、文档和运行产物。

## 一、说明范围

文件按以下类型标注：

| 类型 | 含义 |
| --- | --- |
| 当前核心 | 当前五策略实验或历史趋势复现会直接使用的代码、配置和数据 |
| 辅助工具 | 为画像构建、可视化、演示或开发提供支持，不属于主仿真入口 |
| 运行产物 | 由程序生成的结果、状态、缓存或示例数据，通常不应作为业务代码修改 |
| 历史/外部参考 | 早期原型、归档文档或外部参考工程，不是当前 Demo 的执行入口 |

`demo/experiments`、`output/personas` 和 `__pycache__` 中包含大量同构文件，本文按文件命名规则说明，不重复列出每个实验批次、每个 Agent 和每个字节码文件。`agentsociety2`、`oasis-master`、`TrendSim` 是外部参考工程，按顶层模块说明，具体内部文件应以各工程自身文档为准。

## 二、项目根目录

| 路径 | 类型 | 主要功能 | 使用说明 |
| --- | --- | --- | --- |
| `demo/` | 当前核心 | 舆情社会模拟 Demo 主体，包含五策略实验、历史复现、配置、状态、结果和文档 | 当前开发和运行的主要目录 |
| `comment/` | 历史原型 | 保留早期评论池、评分和分析原型 | 当前 Demo 不再依赖该目录，不作为正式入口 |
| `persona_pipeline/` | 辅助工具 | 从原始社交数据构建 Persona、情绪阈值和派系偏好 | 画像重新生成时使用 |
| `output/` | 当前核心数据 | 保存 Persona 构建结果和全局策略配置 | 当前 Agent 决策会读取 `output/personas` |
| `visualization/` | 辅助工具 | 读取历史复现实验与人工真实趋势，提供网页可视化和对比 | 只读仿真结果，不参与仿真计算 |
| `agentsociety2/` | 外部参考 | AgentSociety 相关框架代码 | 当前 `demo/main.py` 不以它作为运行入口 |
| `oasis-master/` | 外部参考 | OASIS 社交媒体仿真框架和示例 | 用于设计参考，修改前应先确认是否准备正式集成 |
| `TrendSim/` | 外部参考 | 另一套舆情趋势模拟原型 | 与当前 Demo 相互独立 |
| `.agents/` | 工具配置 | 智能编码工具的本地配置目录 | 不属于产品代码，不应加入业务依赖 |
| `.git/` | 版本控制 | Git 仓库元数据、对象和分支信息 | 不手工修改 |
| `__pycache__/` | 运行产物 | 根目录 Python 字节码缓存 | 可由 Python 自动重建，不是源码 |
| `HANDOFF.md` | 交接控制 | 记录仓库交接条件、状态校验和下一步动作 | 保留在根目录，执行交接任务前优先读取 |

## 三、`demo`：当前仿真核心

### 3.1 主入口、配置和输入

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `main.py` | 当前核心 | 五策略实验总入口；准备初始评论池并调用实验调度器。正常运行命令为 `python demo\main.py` |
| `project_config.py` | 当前核心 | 集中定义项目路径、模型参数、Agent 数量、并发数、评论数量、重试次数、质量阈值和可见评论数量等配置 |
| `experiment_runner.py` | 当前核心 | 五策略实验总调度器；运行共享进场前基线、判断官方动态进场、分流各策略、汇总质量与性能并比较策略结果；提供公告输入解析和单策略触发函数供控制页面调用 |
| `web_api.py` | 当前核心 | web 输入与会话控制 API 的统一门面，集中导出事件、公告、策略与暂停/继续/回滚/重启函数 |
| `web_control.py` | 当前核心 | 单策略逐步控制层；维护 `web_control.json` 和回滚检查点，复用现有单轮仿真入口 |
| `web_server.py` | 辅助工具 | 纯标准库本地 HTTP 服务，将 `web_api` 暴露为 JSON 接口 |
| `event_example.json` | 当前核心输入 | 当前五策略实验的事件材料，包括 `event_id`、事件描述、标签和初始状态等 |
| `official_response_options.json` | 当前核心输入 | 配置“不回应、事实通报、共情安抚、辟谣澄清、处置进展、自定义”等实验场景及官方声明内容、状态与进场规则 |
| `comment_pool.json` | 运行产物 | 当前调试或最近一次准备得到的初始评论池；正式批次会复制独立快照 |

注意：`event_example.json` 与 `official_response_options.json` 中的 `event_id` 必须一致。`project_config.py` 涉及模型访问配置，敏感凭据应通过安全配置方式管理，不应在文档、日志或提交记录中暴露。

### 3.2 `demo/config`：业务配置数据

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `comment_profiles.json` | 当前核心配置 | 定义候选评论生成使用的人物类型、表达特点和信息倾向；它是评论模板，不是参与仿真的 Agent Persona |

### 3.3 `demo/comments`：评论生成与评论池

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记评论领域包并说明模块边界 |
| `angle_planner.py` | 当前核心 | 根据事件生成“评论角度计划”，并将角度、评论派系和人物类型组织成初始评论或增量评论生成任务 |
| `generation_service.py` | 当前核心 | 评论生成公共服务；加载人物类型、规范字段、校验评论、统计过滤原因并执行有限次数补齐 |
| `pool_generator.py` | 当前核心 | 生成初始评论池，检查五派覆盖情况并补齐缺少的评论派系 |
| `incremental_generator.py` | 当前核心 | 每轮生成增量评论；负责触发原因、并行首轮请求、补齐、质量救援、历史评论兜底、本地应急兜底和质量统计 |
| `repository.py` | 当前核心 | 统一读取初始评论、增量评论和全部评论，并按 `comment_id` 查询评论 |

### 3.4 `demo/agents`：Agent 感知与决策

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记 Agent 决策领域包并说明模块边界 |
| `decision_service.py` | 当前核心 | 调用 LLM 判断 Agent 当前情绪、对官方态度、评论意愿和派系，再交给本地决策逻辑选择最终评论 |
| `decision_engine.py` | 当前核心 | 构建事件、Persona、可见评论和历史摘要；约束 LLM 可选项；筛选候选评论、评分并从 Top-K 中可复现地选择表达 |
| `batch_decision.py` | 当前核心 | 为多个 Agent 构建个人可见信息，并发执行 Agent 决策，处理单 Agent 重试与批次结果 |
| `state_store.py` | 当前核心 | 维护 Agent 每轮状态、个人评论历史和情绪变化摘要，为后续轮次提供最近状态与个人经历 |
| `persona_repository.py` | 当前核心 | 从 `output/personas` 加载 Persona 和指定数量的 Agent |
| `rule_decision_demo.py` | 辅助工具 | 不调用 LLM 的规则版单 Agent 决策示例，用于本地理解和小范围调试，不是五策略实验主流程 |

### 3.5 `demo/simulation`：仿真运行与状态

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记仿真运行领域包并说明模块边界 |
| `event_context.py` | 当前核心 | 读取事件及当前状态，构建官方声明时间语义，并验证事件输入；提供默认 JSON 与 web 输入合并函数 |
| `event_state_updater.py` | 当前核心 | 追加、读取和校验事件状态历史，获取某事件的最新状态 |
| `state_manager.py` | 当前核心 | 创建、复制、校验和重置仿真状态目录，防止不同实验场景相互污染 |
| `batch_manager.py` | 当前核心 | 生成实验批次 ID，创建批次目录并保存事件、官方策略和初始评论池快照 |
| `runner.py` | 当前核心 | 执行单个时间步或多轮仿真；校验轮次顺序，串联增量评论、Agent 决策、状态更新和指标计算 |
| `propagation.py` | 当前核心 | 构建公共黑板；按当前评论、历史评论和 Agent 个人评论历史形成分层可见信息，并进行可复现抽样 |

`demo/experiment_runner.py` 继续保留在根目录，作为五策略实验总调度器，负责共享基线、动态进场、场景分流、质量与性能汇总和策略比较。

### 3.6 `demo/evaluation`：指标评估

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `__init__.py` | 包文件 | 标记指标评估包并说明模块边界 |
| `metrics.py` | 当前核心 | 计算负面率、情绪分布、质疑率、接受率、全局趋势，以及负面峰值、负面面积、恢复率、持续时间、反弹率和净效果等指标 |

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
| `decision_result.json` | 保存规则版单 Agent 最近一次调试结果，不是五策略实验结果 |
| `decision_result_llm.json` | 保存 LLM 版单 Agent 最近一次调试结果，不是五策略实验结果 |

该目录同时保存静态结构示例和单 Agent 调试输出。它们用于理解字段或局部调试，不是正式实验输入和正式实验结果。

### 3.9 `demo/state`：默认调试状态

| 文件 | 主要功能 |
| --- | --- |
| `.gitkeep` | 让空状态目录能够被 Git 保留 |

直接调试核心模块时，默认状态文件会写入本目录。正式五策略实验主要使用 `demo/experiments/<experiment_id>/<scenario>/state`，避免不同场景共享运行中状态。

### 3.10 `demo/experiments`：实验批次结果

该目录是运行产物目录。每个 `<experiment_id>` 表示一个独立实验批次，不建议手工修改其中内容。

#### 五策略实验批次

```text
demo/experiments/<experiment_id>/
├─ event_input.json
├─ official_response_options.json
├─ comment_pool.json
├─ experiment_result.json
├─ _shared_baseline/state/
├─ no_response/
├─ fact_report/
├─ empathy/
├─ rumor_clarification/
├─ handling_progress/
└─ custom/            # 由单策略模式显式触发且公告已填写时生成
```

| 文件或目录 | 主要功能 |
| --- | --- |
| `event_input.json` | 本批次实际使用的事件输入快照 |
| `official_response_options.json` | 本批次实际使用的官方策略快照 |
| `comment_pool.json` | 各策略场景共同使用的初始评论池快照 |
| `experiment_result.json` | 批次总结果，包括完成状态、进场原因、策略比较、数据质量和性能统计 |
| `_shared_baseline/state/` | 官方进场前的共享基线状态，保证各策略场景从同一舆情条件分流 |
| `<scenario>/scenario_result.json` | 单个策略场景的轮次结果、最终指标、质量与性能摘要 |
| `<scenario>/state/event_state_history.json` | 该场景每轮事件和官方声明状态 |
| `<scenario>/state/agent_state_history.jsonl` | 该场景各 Agent 的状态历史 |
| `<scenario>/state/decision_history.jsonl` | 该场景各 Agent 的决策历史 |
| `<scenario>/state/incremental_comment_history.jsonl` | 该场景每轮增量评论及生成质量记录 |
| `<scenario>/state/metrics_history.jsonl` | 该场景每轮舆情指标 |

#### 历史复现批次

历史复现批次通常包含 `historical_replay_result.json`、`official_response_timeline.json` 和 `historical_replay/state`。它不进行五策略比较，而是按历史时间线依次投入官方信息。

#### 其他文件

| 文件 | 主要功能 |
| --- | --- |
| `.gitkeep` | 保留实验输出根目录 |
| `integration_test_001/` | 早期或小范围集成测试产生的固定测试批次，主要用于问题追溯 |

### 3.11 `demo/historical_replay`：历史趋势复现

该模块与五策略实验隔离，但复用同一套 Persona、评论生成、Agent 决策和指标计算核心。

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `main.py` | 当前核心入口 | 历史趋势复现入口，命令为 `python demo\historical_replay\main.py` |
| `replay_runner.py` | 当前核心 | 按时间步执行历史复现，在指定轮次投入官方信息并汇总结果 |
| `timeline_service.py` | 当前核心 | 读取和校验官方信息时间线，返回指定轮次的官方状态和历史阶段 |
| `batch_manager.py` | 当前核心 | 创建隔离的历史复现批次目录，保存输入快照并准备初始评论池 |
| `runtime_paths.py` | 当前核心 | 设置模块搜索路径和运行时路径，使历史复现可以复用 `demo` 核心模块 |
| `event_input.json` | 当前输入 | 当前历史案例的事件输入 |
| `official_response_timeline.json` | 当前输入 | 指定官方信息在哪些轮次投入，以及每个轮次对应的声明内容与状态 |
| `example.xlsx` | 人工资料 | 人工整理的真实群体舆情变化数据，供可视化对比使用，不直接控制 Agent 决策 |
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
| `PROJECT_STATUS.md` | 当前完成情况、主要问题和下一步唯一工作 |
| `ARCHITECTURE.md` | 系统流程、模块边界和代码地图 |
| `DATA_CONTRACT.md` | 事件、评论、状态、决策、指标和实验结果的字段契约 |
| `RUNBOOK.md` | 环境准备、替换事件、运行实验、查看结果和常见排错步骤 |
| `SIMULATION_INTERFACE_SPEC.md` | 当前仿真核心接口、调用约束和禁止事项 |
| `TASK_BREAKDOWN.md` | 面向多人协作的任务拆分、输入输出和验收标准 |
| `TEAM_COLLABORATION.md` | 团队协作、分支、修改边界和交付规范 |
| `LLM_SERVICE.md` | 系统各处 LLM 调用点、用途和调用边界 |
| `HISTORICAL_REPLAY.md` | 历史趋势复现模式的配置和运行说明 |
| `VISUALIZATION.md` | 历史复现与人工真实趋势网页展示说明 |
| `WEB_API.md` | 事件/公告/策略 web 输入与逐步会话控制 API 说明 |
| `CHANGE_SUMMARY.md` | 本轮框架、Web API、前端和错误修复的完整变更总结 |
| `INTEGRATION_TEST_HISTORY.md` | 历次正式联调的日期、输入、结果、失败原因和修复记录 |
| `detail.md` | 长期开发记录，保存方案演变、阶段成果、历史计划和扩展方向 |

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

用于统一保存汇报所需的可编辑幻灯片、导出图片和相关视觉素材。当前目录为空，是预留的演示资产目录，不参与程序运行。

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
| `build_personas.py` | 辅助工具 | 清洗原始微博文本，调用 LLM 分类内容与表达特征，构建每个用户的 Persona，并生成全局量化策略 |
| `build_faction_preferences.py` | 辅助工具 | 对用户历史表达进行评论派系分类，将派系偏好写回 Persona |
| `emotion.py` | 辅助工具 | 汇总 Persona 情绪值并计算情绪分位点，辅助检查或生成情绪阈值 |
| `requirements.txt` | 环境配置 | Persona 构建流水线所需的 Python 依赖列表 |
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

## 七、`visualization`：历史趋势展示网页

| 文件 | 类型 | 主要功能 |
| --- | --- | --- |
| `app.py` | 辅助工具入口 | 启动本地 HTTP 服务，提供实验列表、实验详情、真实趋势和对比结果接口，并托管静态网页 |
| `config.py` | 辅助工具配置 | 定义实验目录、真实数据源、处理结果和静态资源路径 |
| `simulation_data_loader.py` | 辅助工具 | 只读加载历史复现实验，汇总 Agent 指标和评论池情绪分布，并兼容处理旧数据乱码 |
| `real_data_processor.py` | 辅助工具 | 将 `demo/historical_replay/example.xlsx` 中人工整理的群体趋势转换为网页可读的 JSON |
| `xlsx_reader.py` | 辅助工具 | 使用 Python 标准库读取 `.xlsx` 内部 XML，减少对大型表格依赖的要求 |
| `comparison_service.py` | 辅助工具 | 对齐模拟趋势与人工真实趋势，计算方向一致性、平均绝对差和峰值轮次差等展示指标 |
| `__init__.py` | 包文件 | 将目录标记为 Python 包 |
| `data/real_trend.json` | 处理产物 | 从真实数据表生成的标准化趋势数据，网页直接读取 |
| `web/` | 当前交互页面 | 事件/公告/策略输入与会话控制台，由 `demo/web_server.py` 托管 |
| `static/index.html` | 前端页面 | 定义可视化页面结构和展示容器 |
| `static/app.js` | 前端逻辑 | 调用本地接口并绘制趋势、指标卡、轮次表格和对比结果 |
| `static/styles.css` | 前端样式 | 控制页面配色、布局、响应式显示和组件样式 |
| `__pycache__/` | 运行产物 | Python 字节码缓存 |

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

以上三个目录均不是当前五策略 Demo 的直接依赖。若要借鉴其中的社交网络、传播或存储能力，应通过新接口逐步接入，不能直接改写当前核心的数据结构。

## 九、新成员快速判断表

| 需要完成的工作 | 优先查看的文件 |
| --- | --- |
| 运行现有五策略实验 | `demo/docs/RUNBOOK.md`、`demo/main.py`、`demo/project_config.py` |
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
