# Demo 目录团队参考

本文档面向第一次接触项目的团队成员，说明 `demo` 目录中每个文件的用途、输入输出和完成状态。

## 一、当前 Demo 的处理流程

```text
事件输入
    ↓
生成或读取候选评论池
    ↓
读取 Persona 和 Agent 最近状态
    ↓
单个或批量 Agent 决策
    ↓
保存决策结果和 Agent 状态
```

目前已经完成的是“单轮 Agent 决策”。评论传播、舆情指标、事件状态自动更新和多轮模拟仍属于待实现功能。

## 二、核心 Python 文件

### 1. `project_config.py`

集中管理项目路径和运行配置。

主要配置包括：

- Persona 目录；
- 事件文件路径；
- 评论池路径；
- Agent 状态路径；
- DeepSeek API 配置；
- Agent 数量、并发数和重试次数。

修改运行路径或 API 配置时，优先查看此文件。

### 2. `json_storage.py`

统一处理 JSON 和 JSONL 文件。

主要功能：

- 读取 JSON；
- 保存 JSON；
- 追加 JSONL；
- 批量追加 JSONL；
- 读取 JSONL。

其他模块不应重复编写文件读写代码。

### 3. `event_context.py`

负责读取和校验事件输入。

主要功能：

- 读取 `event_example.json`；
- 读取 `event_state.json`；
- 检查两个文件的 `event_id` 是否一致；
- 组合成 Agent 决策所需的事件上下文。

### 4. `persona_repository.py`

负责读取 Persona 文件。

主要功能：

- 读取多个 `agent_*.json`；
- 读取单个 Persona；
- 跳过无法解析的 Persona 文件。

### 5. `decision_engine.py`

Agent 决策核心逻辑模块。

负责：

- 计算主题匹配度；
- 判断当前情绪；
- 判断对官方声明的态度；
- 判断是否评论；
- 选择评论派系；
- 对候选评论进行匹配；
- 生成 LLM 允许选项；
- 校验 LLM 输出。

该模块不负责文件读写，也不负责调用 DeepSeek。

### 6. `llm_service.py`

统一负责 DeepSeek 请求和 JSON 解析。

负责：

- 发送请求；
- 设置模型、温度和输出长度；
- 读取第一个完整 JSON 对象；
- 输出错误信息。

其他模块不应直接调用 `requests.post()`。

### 7. `comment_pool_generator.py`

负责根据事件生成候选评论池。

处理流程：

```text
事件输入
→ 调用 DeepSeek 生成候选评论
→ 校验评论字段
→ 保存 comment_pool.json
```

候选评论尽量覆盖：

- 五种评论派系；
- 正面、中性、负面情绪；
- 事实、观点、质疑三种信息取向。

如果 API 不可用，会使用本地模板生成兜底评论池。

### 8. `agent_state_store.py`

独立管理 Agent 的动态状态。

负责：

- 读取最近状态；
- 读取历史状态；
- 生成历史摘要；
- 保存本轮 Agent 状态。

Agent 状态主要保存到：

```text
demo/state/agent_state_history.jsonl
```

Persona 保存长期特征，Agent 状态文件保存跨时间步变化。

### 9. `agent_decision_demo.py`

单个 Agent 的本地规则决策入口，不调用 DeepSeek。

运行：

```powershell
python demo\agent_decision_demo.py
```

适合验证：

- Persona 是否能正确读取；
- 事件状态是否正确；
- 本地规则是否能产生情绪、态度和评论选择。

### 10. `agent_decision_llm_demo.py`

单个 Agent 的受约束 LLM 决策入口。

运行：

```powershell
python demo\agent_decision_llm_demo.py
```

也可以指定 Persona：

```powershell
python demo\agent_decision_llm_demo.py --agent-file output\personas\agent_001.json
```

重新生成评论池：

```powershell
python demo\agent_decision_llm_demo.py --regenerate-comments
```

### 11. `batch_agent_decision.py`

多 Agent 批量决策入口。

运行：

```powershell
python demo\batch_agent_decision.py
```

指定 Agent 数量和并发数：

```powershell
python demo\batch_agent_decision.py --max-agents 30 --workers 5
```

重新生成评论池：

```powershell
python demo\batch_agent_decision.py --regenerate-comments
```

该模块负责：

- 读取多个 Persona；
- 并发调用 Agent 决策；
- 失败重试；
- 保存批量决策；
- 保存 Agent 状态。

## 三、后续仿真接口文件

以下文件已经定义接口，但当前仍是待实现模块。

### 1. `propagation.py`

负责公共黑板、评论可见性、互动记录和下一轮可见信息。

当前状态：接口已定义，具体逻辑未完成。

### 2. `metrics.py`

负责统计每一轮的：

- 情绪分布；
- 官方态度分布；
- 评论派系分布；
- 评论率；
- 传播互动量。

当前状态：接口已定义，具体逻辑未完成。

### 3. `event_state_updater.py`

负责根据本轮 Agent 反应和传播结果生成下一轮事件状态。

需要更新的字段包括：

- `official_statement_status`；
- `group_conflict`；
- `seriousness`；
- `step`。

当前状态：接口已定义，具体逻辑未完成。

### 4. `simulation_runner.py`

多轮仿真总控模块。

未来负责串联：

```text
Agent 决策
→ 评论传播
→ Agent 状态保存
→ 舆情指标统计
→ 事件状态更新
→ 停止条件判断
```

当前状态：接口已定义，具体逻辑未完成。

### 5. `experiment_runner.py`

负责官方回应时机和内容策略实验。

当前状态：接口已定义，具体逻辑未完成。

## 四、输入 JSON 文件

### `event_example.json`

保存事件的固定信息，例如：

- `event_id`；
- `event_content`；
- 事件主题；
- 事件整体情绪基调。

一般不随时间步改变。

### `event_state.json`

保存当前时间步的动态事件信息，例如：

- 官方声明；
- 官方声明状态；
- 是否存在群体对立；
- 当前严重程度；
- 当前时间步。

### `candidate_comments.json`

早期候选评论示例文件，保留用于参考。

当前正式流程优先使用 `comment_pool.json`。

### `comment_pool.json`

当前事件生成的候选评论池。

每条评论包含：

- `comment_id`；
- `text`；
- `topic`；
- `emotion`；
- `faction`；
- `orientation`。

## 五、状态和结果文件

### `state/agent_state_history.jsonl`

保存每个 Agent 每个时间步的动态状态。

### `state/decision_history.jsonl`

保存每个 Agent 的完整决策结果，包括选择的评论和决策理由。

### 未来文件

以下文件会在多轮仿真功能完成后使用：

- `state/interaction_history.jsonl`：评论传播和互动记录；
- `state/metrics_history.jsonl`：每轮舆情指标；
- `state/event_state_history.jsonl`：每轮事件状态快照。

## 六、协作文档

| 文件 | 用途 |
|---|---|
| `SIMULATION_WORKFLOW.md` | 说明每轮仿真执行顺序 |
| `SIMULATION_INTERFACE_SPEC.md` | 说明模块接口和数据结构 |
| `SIMULATION_CORE_AUDIT.md` | 说明当前已完成和缺失的功能 |
| `TEAM_COLLABORATION.md` | 说明团队分工、开发顺序和验收条件 |
| `UNIMPLEMENTED_INTERFACES.md` | 早期未实现接口记录，可作为历史参考 |
| `README.md` | 本目录文件总览和入门说明 |

## 七、推荐阅读顺序

新成员建议按照以下顺序阅读：

1. `README.md`；
2. `SIMULATION_CORE_AUDIT.md`；
3. `SIMULATION_WORKFLOW.md`；
4. `SIMULATION_INTERFACE_SPEC.md`；
5. `decision_engine.py`；
6. `agent_state_store.py`；
7. `batch_agent_decision.py`；
8. 根据分工阅读 `propagation.py`、`metrics.py`、`event_state_updater.py` 或 `simulation_runner.py`。

## 八、代码修改原则

1. 业务规则写入 `decision_engine.py`，不要散落在入口文件中。
2. DeepSeek 请求统一通过 `llm_service.py`。
3. JSON 和 JSONL 读写统一通过 `json_storage.py`。
4. Agent 状态统一通过 `agent_state_store.py`。
5. 所有跨模块记录必须包含 `event_id` 和 `step`。
6. 新增函数需要使用清晰的英文函数名和变量名，并添加中文注释。
7. 修改接口前先同步更新 `SIMULATION_INTERFACE_SPEC.md`。

