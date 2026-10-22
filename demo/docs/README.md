# 舆情社会模拟 Demo 文档中心

本目录是当前项目文档的统一入口。新成员应从本文件开始阅读，不要直接依据 `archive` 中的早期材料开发。

## 推荐阅读顺序

1. [`PROJECT_HANDOFF_20261022.md`](./PROJECT_HANDOFF_20261022.md)：交接现场、验证边界、风险和接收端只读哨兵。
2. [`PROJECT_STATUS.md`](./PROJECT_STATUS.md)：当前完成情况、问题和下一阶段目标。
3. [`RUNBOOK.md`](./RUNBOOK.md)：环境准备、替换事件、启动实验和查看结果。
4. [`ARCHITECTURE.md`](./ARCHITECTURE.md)：系统流程、模块边界和核心文件。
5. [`FILE_DIRECTORY_GUIDE.md`](./FILE_DIRECTORY_GUIDE.md)：项目目录、文件职责和使用边界。
6. [`DATA_CONTRACT.md`](./DATA_CONTRACT.md)：输入、状态和结果字段约定。
7. [`SIMULATION_INTERFACE_SPEC.md`](./SIMULATION_INTERFACE_SPEC.md)：核心模块接口与禁止事项。
8. [`TASK_BREAKDOWN.md`](./TASK_BREAKDOWN.md)：可以分配给不同成员的任务包。
9. [`TEAM_COLLABORATION.md`](./TEAM_COLLABORATION.md)：协作、验收和变更规则。
10. [`GIT_WORKFLOW.md`](./GIT_WORKFLOW.md)：更新已有代码、创建姓名分支、提交、推送和Pull Request流程。

## 专题文档

| 文档 | 用途 |
| --- | --- |
| [`LLM_SERVICE.md`](./LLM_SERVICE.md) | 记录系统调用LLM的位置和调用边界 |
| [`HISTORICAL_REPLAY.md`](./HISTORICAL_REPLAY.md) | 历史趋势复现模式说明 |
| [`ABLATION_EXPERIMENT.md`](./ABLATION_EXPERIMENT.md) | 回应方案机制消融、可比性约束、运行与恢复说明 |
| [`VISUALIZATION.md`](./VISUALIZATION.md) | 回应方案对照、历史复现、真实趋势和传播追踪的统一可视化说明 |
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

回应方案对照实验和历史复现都会只读这些基础 Persona，不会覆盖原文件。

如需从MongoDB重新生成Persona，请先阅读`persona_pipeline/README.md`，并按“基础Persona → 评论派系偏好 → 情绪分位点”的顺序执行三个脚本。

### 3. 准备回应方案对照实验输入

需要检查：

- `demo/event_example.json`：当前事件材料；
- `demo/official_response_options.json`：三个可自由命名的回应方案；不回应基线由系统自动增加；
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

历史趋势复现第1轮按人工整数情绪配额构造初始公共评论环境；第2轮以后投入同期公众语境和真实官方通告，但不读取真实评论文本或逐轮真实情绪比例。已核实事实统一广播，公众讨论和建设性证据按Agent个体曝光。规则层使用`persona_decision_v3 / personalized_hysteresis_v3 / emotion_transition_v1 / official_attitude_v3`：第一轮情绪由LLM初始化，后续情绪转移和官方态度由Persona门槛、当前证据和上一轮状态裁决；过程评价无新过程证据时跨轮保持；发言评分不奖励特定情绪。LLM解释既定状态、判断发言意愿并生成原创表达。历史复现不使用群体比例限制或群体坍缩熔断；回应方案对照不读取历史事件目录。

## 运行回应方案对照实验

回应方案对照实验会生成一份固定社交网络和共享的进场前基线，依据负面阈值、全局恶化或连续停滞判断官方进场时机，然后从相同网络与状态分流并比较三个自定义回应方案和一组不回应基线。三个方案不限定内容类型。

Agent公开行为分为沉默、原创和转发。现实中不同个体可能形成相同或相近措辞，因此文本与可见评论一致时允许按Agent明确选择的原创动作发布，不会自动改成转发或导致实验失败；系统另存相似度审计信息，用于分析表达重复和群体趋同。只有Agent明确选择`reshare`时才按转发记录。

2026/10/17 起，回应方案对照按“状态判断→行为门控→原创表达”顺序运行。状态LLM只返回内部情绪和官方态度；本地门控仅根据Persona关注度、历史活跃度、当轮新信息、状态变化和连续发言疲劳决定是否发言，不依赖LLM的发言意愿；动作再按Persona偏好从沉默、原创和转发中确定。只有选择原创时才发起独立表达请求，表达情绪始终允许`positive / neutral / negative`三分类，并且不会反向改写内部状态。

原创表达目标长度为120～200字，硬上限为280字符。格式或长度错误只重试表达阶段，不重新判断Agent状态和动作；连续两次纠错仍超长时，在280字符内按最后一个句末确定性裁剪，并保存原长度、裁剪后长度和规范化代码。用户用`Ctrl+C`中断实验时，主进程会主动终止当前轮子进程，避免残留后台Python任务。

2026/10/20起，回应方案对照的状态边界升级为`strategy_directional_utility_v3`：完整的4条邻居表达＋11条公共评论仍供发言、原创和转发使用；内部状态视图继续限流。每条证据先按评论目标分流到事件情绪、官方态度和参与通道，对调查过程的负面评价不再自动强化事件负面情绪。权威证据最多跨三轮渐进吸收，速度由各Agent的事实偏好、质疑倾向、主题关注和状态惯性决定，并随轮龄衰减；真正推动一次状态变化后即消费。普通传播根继续去重并按`1.0 / 0.5 / 0.25`递减累积。规则层保留离散三分类、Persona先验、上一轮惯性、切换边际和相邻变化约束，不读取真实趋势、不设置群体比例，也不改变历史复现路径。

回应方案实验每轮外生LLM增量评论默认由20条降为8条，让Agent原创和转发形成的内生表达在后续语境中占据更合理位置；历史复现仍使用原有增量数量。实际使用值写入`experiment_result.json.simulation_options.incremental_comment_count`，事件输入显式配置时仍以事件配置为准。

同日，回应方案的邻居表达窗口扩展为最近3轮：先按轮龄补最近邻居表达，再用公共评论补缺；同一根传播链只占一个曝光名额，有效抽样权重同时包含传播深度衰减和时间衰减。逐条决策与逐轮指标保存有效邻居曝光率、表达轮龄分布和唯一根表达数。历史复现继续沿用其既有上一轮邻居口径。

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

需要判断外部LLM评论、内部状态证据和邻居反馈各自影响时，使用独立消融入口；该入口共享初始评论池、固定网络和第1轮状态，并固定回应投入轮次：

```powershell
python demo\ablation_runner.py --response-plan response_plan_1
```

完整变体定义、输出结构和恢复方法见 [`ABLATION_EXPERIMENT.md`](./ABLATION_EXPERIMENT.md)。普通 `python demo\main.py` 不启用消融，继续运行完整反馈机制。

## 运行历史趋势复现

历史趋势复现按照真实时间线逐轮投入当时已知的公众语境和官方信息，只运行一条历史路线，不执行动态进场，也不进行回应方案对照。Agent 内部情绪、官方态度与公共表达分别判断，发言时生成原创评论；它用于解释“在这些历史条件和个体曝光下 Agent 如何响应”，不属于自主历史预测。

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

可视化模块只读 `demo/experiments` 中已经完成的回应方案对照实验和历史复现实验，不会修改实验数据，也不会调用 DeepSeek。

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

服务启动后，首页可以选择“回应方案对照推演”或“历史数据复现”。按 `Ctrl+C` 停止服务。

### 查看社交网络与评论传播

统一入口采用“历史复现、回应方案对照、共享网络”三层结构。回应方案对照和历史复现分别拥有业务总览，共用固定关注网络、逐轮信息流、Agent影响力和单条评论传播链。共享网络通过页面中的入口打开，不再维护端口8766的独立兼容服务。

## 最短运行顺序

首次安装并完成配置后，可以按以下顺序操作：

```powershell
conda activate persona_sim
python demo\main.py
python demo\historical_replay\main.py --event-id <event_id>
python visualization\historical\real_data_processor.py --event-id <event_id>
python visualization\app.py
```

回应方案对照实验和历史复现都会产生大量 LLM 请求，应分别等待上一条命令执行完成。可视化只需已有实验结果；查看旧结果时无需重新运行任何模拟。
