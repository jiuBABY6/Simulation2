# LLM 调用说明

本文档记录当前 Demo 在运行 `python demo\main.py` 时调用 LLM 的业务环节。所有 DeepSeek JSON 请求最终统一通过 `infrastructure/llm_service.py` 中的 `call_deepseek_json()` 发出。

## 调用环节总览

| 环节 | LLM 主要功能 | 调用时机 |
| --- | --- | --- |
| 事件角度规划 | 根据事件正文生成可复用的事件讨论角度 | 每个实验批次开始时执行一次 |
| 初始评论池生成 | 根据事件和评论画像生成结构化初始评论 | 每个实验批次开始时执行一次 |
| 增量评论生成 | 根据当前事件状态、官方声明和上一轮舆情生成本轮新评论 | 进场前共享路径每轮一次，分叉后每个策略每轮执行 |
| Agent 认知决策 | 判断 Agent 的情绪、官方态度、评论意愿和评论派系 | 每条实际仿真路径中的每个 Agent 每轮执行一次 |
| 全局趋势分析 | 判断舆情趋势是 `improving`、`stable` 或 `worsening` | 进场前共享路径每轮一次，分叉后每个策略每轮执行 |

## 1. 初始评论池生成

调用链：

```text
main.py
→ comments/pool_generator.py
  → comments/angle_planner.py → infrastructure/llm_service.py → DeepSeek
  → comments/generation_service.py → infrastructure/llm_service.py → DeepSeek
```

`comments/angle_planner.py` 先调用一次 LLM 生成事件专属角度计划。程序随后把 60 条评论名额分配为角度任务，再由评论生成 LLM 针对指定角度选择合适的人物类型和派系。

LLM 输入主要包括：

- 事件内容；
- 事件标签；
- 本批次程序分配的事件角度任务；
- 评论画像类型；
- 允许使用的评论派系、情绪、信息取向和立场。

LLM 输出包含任务编号、评论文本、人物画像编号、派系、情绪、信息取向和立场等结构化字段。程序根据任务编号写入对应角度，不接受任务列表之外的编号。

当前初始评论池为 60 条，每批目标为 10 条，因此正常情况下至少发出 6 次请求。如果返回评论未通过字段校验、数量不足或者五派覆盖不足，系统会继续调用 LLM 补齐。

主要代码位置：

- `comments/angle_planner.py`：生成、校验并分配事件角度任务；
- `comments/pool_generator.py`：组织初始评论生成；
- `comments/generation_service.py`：统一执行评论批次生成、校验和重试；
- `infrastructure/llm_service.py`：发送 DeepSeek 请求并解析 JSON。

## 2. 增量评论生成

第 1 轮直接使用初始评论池，不生成增量评论。从第 2 轮开始，每条实际仿真路径每轮生成 20 条增量评论。官方进场条件触发前只运行一条共享路径，触发后才复制状态并为各个策略分别生成。

LLM 输入主要包括：

- 事件内容和当前事件状态；
- 当前官方声明及声明状态；
- 上一轮 Agent 实际选择的评论；
- 前一轮增量评论摘要；
- 本轮评论生成触发原因；
- 已有评论文本，用于减少重复；
- 本轮程序分配的活跃角度任务。

LLM 输出为本轮新增的结构化候选评论。当前每轮目标为 20 条，每批目标为 10 条，因此正常情况下每轮至少发出 2 次请求。若评论被过滤或数量不足，系统会请求 LLM 继续补齐；重试结束后仍不足时，再由本地评论兜底机制补足。

主要代码位置：

- `comments/incremental_generator.py`：构造增量评论上下文并组织生成；
- `comments/generation_service.py`：执行批次生成、结果校验和补齐重试；
- `infrastructure/llm_service.py`：发送 DeepSeek 请求并解析 JSON。

## 3. Agent 认知决策

每条实际仿真路径中的每个 Agent 在每一轮调用一次 LLM。官方进场前的Agent决策只执行一次并复制到各策略，进场后再分别调用。LLM 输入主要包括：

- Agent Persona；
- Persona 的 `information_orientation`；
- 事件内容和当前状态；
- 当前官方声明及声明状态；
- Agent 个人可见的 15 条评论；
- Agent 最近状态；
- Agent 此前所有轮次的个人评论历史；
- 本轮允许使用的情绪、官方态度、评论意愿和评论派系选项。

LLM 只负责输出以下认知决策字段：

```text
emotion
attitude_to_official
willingness_to_comment
faction
```

LLM 不直接选择 Agent 最终发表的评论。Agent 愿意评论时，本地决策引擎会根据认知结果筛选和评分全局候选评论，然后从评分最高的 3 条中进行可复现的随机选择。

主要代码位置：

- `agents/decision_service.py`：调用 LLM 完成单个 Agent 的认知决策；
- `agents/batch_decision.py`：并发组织多个 Agent 的决策；
- `agents/decision_engine.py`：构造提示词、校验认知结果并在本地选择最终评论；
- `infrastructure/llm_service.py`：发送 DeepSeek 请求并解析 JSON。

## 4. 全局舆情趋势分析

每轮 Agent 决策完成后，系统分析初始评论与当前轮增量评论之间的变化。官方进场前的趋势只分析一次，策略分叉后分别分析。

LLM 输入主要包括：

- 当前事件和官方声明状态；
- 初始评论；
- 当前轮 20 条增量评论。

LLM 输出主要包括：

- 趋势方向；
- 趋势判断理由；
- 作为判断依据的评论编号。

第 1 轮没有增量评论，系统直接将其作为趋势基线并返回 `stable`，不会调用 LLM。从第 2 轮开始，每个策略每轮调用一次。

主要代码位置：

- `evaluation/metrics.py`：构造趋势分析提示词、调用 LLM 并校验结果；
- `infrastructure/llm_service.py`：发送 DeepSeek 请求并解析 JSON。

## 不调用 LLM 的环节

以下功能由本地代码完成：

- 官方声明进场阈值判断；
- 负面率、质疑率和接受率计算；
- Agent 可见评论抽样；
- 最终候选评论过滤与评分；
- 从评分最高的 3 条评论中进行可复现的随机选择；
- Agent 状态和个人评论历史保存；
- 增量评论数量兜底；
- 策略比较和并列结果判断；
- 实验状态初始化、重置和结果文件保存。

## 当前配置下的最低调用量

当前联调配置为 5 个策略、每个策略最多 10 轮、每轮 10 个 Agent。以下按第 1 轮指标触发、第 2 轮开始策略分叉计算；忽略校验补齐、业务重试和 HTTP 重试时，一次完整联调的最低 LLM 调用量为：

| 调用类型 | 计算方式 | 最低调用次数 |
| --- | --- | ---: |
| 事件角度规划 | 每个实验批次一次 | 1 |
| 初始评论池生成 | 60 条 ÷ 每批 10 条 | 6 |
| 增量评论生成 | 5 个策略 × 9 轮 × 每轮 2 批 | 90 |
| Agent 认知决策 | 共享第 1 轮 10 次 + 5 个策略 × 9 轮 × 10 个 Agent | 460 |
| 全局趋势分析 | 5 个策略 × 9 轮 | 45 |
| 合计 | 1 + 6 + 90 + 460 + 45 | 602 |

实际请求次数取决于动态进场轮次，也可能因评论数量不足、评论字段校验失败、Agent 决策失败、JSON 解析失败、网络异常以及 HTTP 请求重试而增加。
