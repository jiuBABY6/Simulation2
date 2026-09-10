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

## 专题文档

| 文档 | 用途 |
| --- | --- |
| [`LLM_SERVICE.md`](./LLM_SERVICE.md) | 记录系统调用LLM的位置和调用边界 |
| [`HISTORICAL_REPLAY.md`](./HISTORICAL_REPLAY.md) | 历史趋势复现模式说明 |
| [`VISUALIZATION.md`](./VISUALIZATION.md) | 历史复现与真实趋势可视化说明 |
| [`WEB_API.md`](./WEB_API.md) | 事件/公告/策略 web 输入与逐步会话控制 API |
| [`CHANGE_SUMMARY.md`](./CHANGE_SUMMARY.md) | 本轮框架、API、前端和错误修复的完整变更总结 |
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

当前代码从 `demo/project_config.py` 的 `DEEPSEEK_API_KEY`、`DEEPSEEK_MODEL` 和 `DEEPSEEK_ENDPOINT` 读取模型配置。首次运行前，需要在本地填写可用的 API Key：

```python
DEEPSEEK_API_KEY = "填写本机使用的API Key"
```

API Key 只应保存在本机，不得写入文档、日志或提交到代码仓库。当前实现尚未直接读取系统环境变量，因此仅设置 Windows 环境变量并不能替代上述配置。

### 2. 检查 Persona

确认 `output/personas` 中存在 Agent Persona JSON 文件，并保留：

- `policy_config.json`：全局决策规则；
- `agent_*.json`：参与仿真的个体 Persona。

五策略实验和历史复现都会只读这些基础 Persona，不会覆盖原文件。

### 3. 准备五策略实验输入

需要检查：

- `demo/event_example.json`：当前事件材料；
- `demo/official_response_options.json`：四种内置回应内容、可留空的
  `custom`策略以及不回应对照场景；
- `demo/config/comment_profiles.json`：评论生成使用的人物类型模板。

`event_example.json` 与 `official_response_options.json` 的 `event_id` 必须完全一致。官方回应文件中的 `official_statement_status` 应与声明信息完整程度一致。

公告内容默认读取 `official_response_options.json`。后续 web 页面可通过
`resolve_official_response_options()`只覆盖需要修改策略的 `official_statement`
和 `official_statement_status`，其余策略仍沿用该默认文件。

事件正文默认读取 `demo/event_example.json`，后续 web 页面可通过
`resolve_event_input()`只覆盖 `event_content` 或事件标签；提供新事件时需同时
给出新的 `event_id` 与 `event_content`。

### 4. 准备历史复现输入

需要检查：

- `demo/historical_replay/event_input.json`：事件初始阶段公开信息；
- `demo/historical_replay/official_response_timeline.json`：官方信息投入轮次；
- `demo/historical_replay/example.xlsx`：人工整理的真实群体趋势；
- `demo/historical_replay/official.md`：配置时间线时参考的原始材料，程序不会自动读取。

历史复现的事件文件与时间线文件必须使用相同的 `event_id`。后续调查结论只能写入对应轮次的 `official_updates`，不能提前放入初始事件描述。

## 运行五策略实验

策略对照实验会生成共享的进场前基线，依据负面阈值、全局恶化或连续停滞判断官方进场时机，然后从相同状态分流并比较不回应、事实通报、共情安抚、辟谣澄清和处置进展；`custom`默认不自动触发，后续可视化控制页可通过单策略触发函数显式运行。

在项目根目录执行：

```powershell
conda activate persona_sim
python demo\main.py
```

每次运行都会创建新的实验目录，不会覆盖历史批次：

```text
demo/experiments/<event_id>_<timestamp>/
```

总体结果保存在该批次的 `experiment_result.json`，各场景的逐轮状态、评论、指标和性能数据保存在对应策略子目录中。

## 运行历史趋势复现

历史复现按照 `official_response_timeline.json` 指定的轮次依次投入官方信息，只运行一条历史路线，不执行动态进场，也不进行五策略对照。

在项目根目录执行：

```powershell
conda activate persona_sim
python demo\historical_replay\main.py
```

运行结果同样保存到新建的 `demo/experiments/<experiment_id>/`，主要查看：

```text
historical_replay_result.json
historical_replay/state/metrics_history.jsonl
historical_replay/state/incremental_comment_history.jsonl
```

## 启动可视化

可视化模块只读 `demo/experiments` 中已经完成的历史复现实验，不会修改实验数据，也不会调用 DeepSeek。

首次使用或 `example.xlsx` 更新后，先把人工整理的数据转换为展示用 JSON：

```powershell
conda activate persona_sim
python visualization\real_data_processor.py
```

处理结果保存在 `visualization/data/real_trend.json`。然后启动网页：

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

服务启动后，在网页中选择已经完成的历史复现实验进行展示。按 `Ctrl+C` 停止服务。

## 最短运行顺序

首次安装并完成配置后，可以按以下顺序操作：

```powershell
conda activate persona_sim
python demo\main.py
python demo\historical_replay\main.py
python visualization\real_data_processor.py
python visualization\app.py
```

五策略实验和历史复现都会产生大量 LLM 请求，应分别等待上一条命令执行完成。可视化只需已有历史复现结果；如果只查看旧结果，无需重新运行五策略实验。
