# 舆情社会模拟 Demo 文档中心

本目录是当前项目文档的统一入口。新成员应从本文件开始阅读，不要直接依据 `archive` 中的早期材料开发。

## 推荐阅读顺序

1. [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)：当前完成情况、问题和下一阶段目标。
2. [`RUNBOOK.md`](./RUNBOOK.md)：环境准备、替换事件、启动实验和查看结果。
3. [`ARCHITECTURE.md`](./ARCHITECTURE.md)：系统流程、模块边界和核心文件。
4. [`FILE_DIRECTORY_GUIDE.md`](./FILE_DIRECTORY_GUIDE.md)：项目目录、文件职责和使用边界。
5. [`DATA_CONTRACT.md`](./DATA_CONTRACT.md)：输入、状态和结果字段约定。
6. [`SIMULATION_INTERFACE_SPEC.md`](./SIMULATION_INTERFACE_SPEC.md)：核心模块接口与禁止事项。
7. [`TASK_BREAKDOWN.md`](./TASK_BREAKDOWN.md)：可以分配给不同成员的任务包。
8. [`TEAM_COLLABORATION.md`](./TEAM_COLLABORATION.md)：协作、验收和变更规则。
9. [`GIT_WORKFLOW.md`](./GIT_WORKFLOW.md)：更新已有代码、创建姓名分支、提交、推送和Pull Request流程。

## 专题文档

| 文档 | 用途 |
| --- | --- |
| [`LLM_SERVICE.md`](./LLM_SERVICE.md) | 记录系统调用LLM的位置和调用边界 |
| [`HISTORICAL_REPLAY.md`](./HISTORICAL_REPLAY.md) | 历史趋势复现模式说明 |
| [`VISUALIZATION.md`](./VISUALIZATION.md) | 五策略、历史复现、真实趋势和传播追踪的统一可视化说明 |
| [`GIT_WORKFLOW.md`](./GIT_WORKFLOW.md) | 团队Git姓名分支、旧代码更新、提交、推送和代码合并操作说明 |
| [`dev/README.md`](./dev/README.md) | 新建实验、查询历史实验及三端开发任务入口 |
| [`dev/SHARED_INTERFACE_CONTRACT.md`](./dev/SHARED_INTERFACE_CONTRACT.md) | 数据库、后端和JavaScript前端共同遵循的`v1.1-product`接口契约 |
| [`dev/INTEGRATION_CHECKLIST.md`](./dev/INTEGRATION_CHECKLIST.md) | 三端在本地完成新实验与历史结果联调、通过后再推送的清单 |
| [`INTEGRATION_TEST_HISTORY.md`](./INTEGRATION_TEST_HISTORY.md) | 每次正式联调的完整证据 |
| [`detail.md`](./detail.md) | 长期开发过程、方案演变和历史规划 |

## 历史文档

早期分工、旧接口、阶段性审查和临时说明统一保存在 [`archive`](./archive)。这些文件只用于追溯，不作为当前开发依据。

## 环境安装

以下命令均在项目根目录执行。当前验证环境为 Python 3.10.20，推荐使用 Conda 创建同名环境：

```powershell
conda create -n persona_sim python=3.10 -y
conda activate persona_sim
python -m pip install -r requirements.txt
python -m pip check
```

`requirements.txt` 位于项目根目录，包含当前环境实际使用的 Python 第三方依赖。最后一条命令输出 `No broken requirements found` 表示依赖关系完整。

以后再次运行项目时，只需先激活环境：

```powershell
conda activate persona_sim
```

## 配置准备

### 1. 配置 DeepSeek

当前代码从环境变量读取 DeepSeek API Key。首次运行前，在当前 PowerShell 窗口执行：

```powershell
$env:DEEPSEEK_API_KEY = "填写本机使用的API Key"
```

模型和接口地址默认分别为 `deepseek-v4-flash` 和 `https://api.deepseek.com/chat/completions`。如需调整，也可设置 `DEEPSEEK_MODEL` 和 `DEEPSEEK_ENDPOINT`。API Key 只应保存在本机环境变量中，不得写入文档、日志或提交到代码仓库。

### 2. 检查 Persona

确认 `output/personas` 中存在 Agent Persona JSON 文件，并保留：

- `policy_config.json`：全局决策规则；
- `agent_*.json`：参与仿真的个体 Persona。

五策略实验和历史复现都会只读这些基础 Persona，不会覆盖原文件。

如需从MongoDB重新生成Persona，请先阅读`persona_pipeline/README.md`，并按“基础Persona → 评论派系偏好 → 情绪分位点”的顺序执行三个脚本。

### 3. 准备五策略实验输入

需要检查：

- `demo/event_example.json`：当前事件材料；
- `demo/official_response_options.json`：四种回应内容以及不回应对照场景；
- `demo/config/comment_profiles.json`：评论生成使用的人物类型模板。
- `demo/config/social_network_config.json`：固定网络、邻居传播数量、公共评论补充和逐层衰减配置。

`event_example.json` 与 `official_response_options.json` 的 `event_id` 必须完全一致。官方回应文件中的 `official_statement_status` 应与声明信息完整程度一致。

### 4. 准备历史复现输入

每个事件独立保存在 `demo/historical_replay/events/<event_id>/`，需要检查：

- `event_manifest.json`：事件名称、原始Excel名称和哈希；
- `event_input.json`：事件初始阶段公开信息；
- `initial_opinion.json`：必需的第一轮人工情绪比例，只影响历史回放；
- `public_context_timeline.json`：必需的逐轮同期公众语境，不得包含情绪比例或目标分布；
- `official_response_timeline.json`：官方信息投入轮次；
- `real_trend_source.xlsx`：人工整理的真实群体趋势，仅供可视化转换。

历史复现的事件文件与时间线文件必须使用相同的 `event_id`。后续调查结论只能写入对应轮次的 `official_updates`，不能提前放入初始事件描述。

历史趋势复现第1轮按人工整数情绪配额构造初始公共评论环境；第2轮以后投入同期公众语境和真实官方通告，但不读取真实评论文本或逐轮真实情绪比例。已核实事实统一广播，公众讨论和建设性证据按Agent个体曝光。规则层使用`persona_decision_v3 / personalized_hysteresis_v3 / emotion_transition_v1 / official_attitude_v3`：第一轮情绪由LLM初始化，后续情绪转移和官方态度由Persona门槛、当前证据和上一轮状态裁决；过程评价无新过程证据时跨轮保持；发言评分不奖励特定情绪。LLM解释既定状态、判断发言意愿并生成原创表达。当前不使用连续情绪值、跨轮响应记忆、群体比例限制或群体坍缩熔断；五策略实验仍不读取历史事件目录，并保留原有LLM态度和候选评论选择机制。

## 运行五策略实验

五策略实验会生成一份固定社交网络和共享的进场前基线，依据负面阈值、全局恶化或连续停滞判断官方进场时机，然后从相同网络与状态分流并比较不回应、事实通报、共情安抚、辟谣澄清和处置进展。

在项目根目录执行：

```powershell
conda activate persona_sim
python demo\main.py
```

每次运行都会创建新的实验目录，不会覆盖历史批次：

```text
demo/experiments/<event_id>_<timestamp>/
```

总体结果保存在该批次的 `experiment_result.json`，各场景的逐轮状态、评论、传播事件、指标和性能数据保存在对应策略子目录中。关系传播明细位于`state/propagation_history.jsonl`，逐轮和场景累计传播指标分别位于`rounds[].propagation_metrics`和`propagation_summary`。

## 运行历史趋势复现

历史趋势复现按照真实时间线逐轮投入当时已知的公众语境和官方信息，只运行一条历史路线，不执行动态进场，也不进行五策略对照。Agent 内部情绪、官方态度与公共表达分别判断，发言时生成原创评论；它用于解释“在这些历史条件和个体曝光下 Agent 如何响应”，不属于自主历史预测。

在项目根目录执行：

```powershell
conda activate persona_sim
python demo\historical_replay\main.py --event-id <event_id>
```

运行结果同样保存到新建的 `demo/experiments/<experiment_id>/`，主要查看：

```text
historical_replay_result.json
historical_replay/state/metrics_history.jsonl
historical_replay/state/incremental_comment_history.jsonl
historical_replay/state/propagation_history.jsonl
```

## 启动可视化

可视化模块只读 `demo/experiments` 中已经完成的五策略实验和历史复现实验，不会修改实验数据，也不会调用 DeepSeek。

首次使用或某事件的真实趋势Excel更新后，按事件编号转换：

```powershell
conda activate persona_sim
python visualization\historical\real_data_processor.py --event-id <event_id>
```

处理结果保存在 `visualization/data/real_trends/<event_id>.json`。不同事件的数据不会互相覆盖，然后启动网页：

```powershell
python visualization\app.py
```

浏览器默认打开：

```text
http://127.0.0.1:8765
```

如不希望程序自动打开浏览器，可以运行：

```powershell
python visualization\app.py --no-browser
```

服务启动后，首页可以选择“五策略推演”或“历史数据复现”。按 `Ctrl+C` 停止服务。

### 查看社交网络与评论传播

统一入口采用“历史复现、五策略、共享网络”三层结构。五策略和历史复现分别拥有业务总览，共用固定关注网络、逐轮信息流、Agent影响力和单条评论传播链。共享网络通过页面中的入口打开，不再维护端口8766的独立兼容服务。

## 最短运行顺序

首次安装并完成配置后，可以按以下顺序操作：

```powershell
conda activate persona_sim
python demo\main.py
python demo\historical_replay\main.py --event-id <event_id>
python visualization\historical\real_data_processor.py --event-id <event_id>
python visualization\app.py
```

五策略实验和历史复现都会产生大量 LLM 请求，应分别等待上一条命令执行完成。可视化只需已有实验结果；查看旧结果时无需重新运行任何模拟。
