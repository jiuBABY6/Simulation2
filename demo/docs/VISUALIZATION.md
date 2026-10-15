# 结果可视化

`visualization` 是统一的只读展示模块。它自动识别五策略实验和历史复现实验，不修改 `demo/experiments`，也不会调用大模型。

## 三层职责

2026/10/10 重构后，可视化按职责划分为三层：

- `visualization/historical/`：历史复现实验、人工真实趋势、探索性对照和历史页面；
- `visualization/strategy/`：五策略实验结果整理和五策略专属对比页面；
- `visualization/shared/`：实验目录适配，以及两种模式共用的社交网络、逐轮传播和评论传播链。

`visualization/app.py` 只负责 HTTP 路由和静态资源托管。历史趋势计算不会进入五策略服务，五策略比较也不会进入历史服务；共享网络通过统一实验适配器只读两类实验目录，避免复制两套网络构图代码。

## 启动统一入口

在项目根目录执行：

```powershell
conda activate persona_sim
python visualization\app.py
```

默认打开 `http://127.0.0.1:8765`。首页提供两种模式：

- **五策略推演**：查看五种回应策略、固定关注网络、逐轮传播和单评论传播链；
- **历史数据复现**：查看模拟趋势与人工真实趋势对照，并可进入同批次的社交网络和评论追踪。

不自动打开浏览器：

```powershell
python visualization\app.py --no-browser
```

## 实验自动识别

实验目录接口只索引 `status=completed` 的批次：

- 包含 `experiment_result.json`：识别为五策略实验；
- 包含 `historical_replay_result.json`：识别为历史复现；
- 失败批次不会作为可用入口展示。

首页还会检查页面所需数据：五策略入口要求网络快照及传播/决策记录完整；历史复现入口要求存在与实验 `event_id` 对应的真实趋势文件。旧历史批次即使没有网络记录，也可以展示趋势；此时页面明确隐藏网络入口，不伪造传播数据。

网络与评论追踪会根据实验类型自动选择路径：

```text
五策略：<experiment>/<scenario>/state/
历史复现：<experiment>/historical_replay/state/
```

轮次数从实验结果动态读取，不再固定为10轮；历史复现也不再要求八个阶段。

## 历史趋势与真实参考

历史复现页面只读加载：

- `historical_replay_result.json`；
- `metrics_history.jsonl` 和评论数据；
- `visualization/data/real_trends/<event_id>.json`。

历史模式的数据装配集中在 `visualization/historical/`；统一HTTP入口只负责路由和静态资源，不再直接拼接历史趋势业务。

模拟结果和真实趋势必须具有相同的 `event_id`。真实参考只有两个观测点时，只展示阶段变化、一次方向比较和探索性差异，不计算峰值轮次差或趋势拟合优度。

2026/10/8，新增功能：如果历史批次的 `comment_pool.json` 声明了 `initialization.evaluation_role=initial_condition`，页面会把对应轮次标记为“历史初始条件”。该点继续绘图并保留绝对差供审计，但不计入MAE和峰值轮次；从初始条件到下一轮的变化方向仍参与方向比较。Agent负面率始终是独立决策结果，不因评论池校准而被强制设置。

2026/10/12，历史页面同时提供四种观测口径：

- Agent实际表达（主口径）：只统计本轮真正决定发表评论的Agent所选择的评论；沉默Agent不进入情绪比例分母；
- 当前轮增量：只统计该阶段新产生的评论，适合观察新意见流入；
- 模拟评论池累计：统计第一轮至当前轮全部模拟评论，适合观察舆情存量；
- 活跃舆情：使用最近两轮滚动窗口，兼顾阶段变化与单轮小样本波动。

页面默认使用Agent实际表达与人工群体参考进行探索性对照，并允许切换其他三种评论池口径。Agent实际表达的分母是本轮具有合法情绪标签的实际表达数；评论池口径的分母是对应范围内具有合法情绪标签的模拟评论数。Agent内部情绪仍单独展示，不能替代实际表达口径。页面同时展示三类情绪宏平均差和逐轮同期公众语境；人工估计不强制归一化，第一轮人工初始条件仍排除在MAE和峰值指标之外。新批次以 `mode=historical_replay` 和 `public_context_enabled=true` 标识当前主线；旧批次只要保留决策历史，也可从Agent实际选择的评论恢复该口径。

2026/10/14，历史官方态度图下方新增诊断卡片，展示最终最大态度群体占比、标准化态度熵、最高同步转向率、最低态度熵和最终过程不满意比例。旧批次没有`official_attitude_diagnostics`时显示“旧批次没有态度诊断”，不会推测或补造指标。这些指标用于发现群体趋同，不会把实验标记为失败。

首次处理或 Excel 内容变化时，按事件编号重新生成：

```powershell
python visualization\historical\real_data_processor.py --event-id <event_id>
```

处理器默认读取 `demo/historical_replay/events/<event_id>/real_trend_source.xlsx`，结果保存在 `visualization/data/real_trends/<event_id>.json`。不同事件不会再互相覆盖；网页按所选实验自动加载对应JSON，不会重复读取Excel。

## 五策略可视化

首页选择五策略批次后进入 `/strategy/`。该页面只展示五策略业务指标：逐轮负面情绪率、最终趋势、官方投入次数、传播摘要和评论生成质量。点击“社交网络与评论追踪”后进入共享网络页面。

五策略页面的数据由 `visualization/strategy/service.py` 提供，不读取人工真实趋势，也不执行历史拟合计算。

## 共享社交网络与评论追踪

具备网络记录的两类实验都可以展示：

- “关注者 → 被关注者”的固定关注网络；
- 评论实际传播方向上的本轮新增/截至当前轮累计信息流切换；
- 双环宽屏Agent布局、逐轮时间轴、情绪着色、表达脉冲和节点聚焦；
- Agent影响力、发出曝光、接收曝光和继续表达；
- 按传播深度排序的评论目录；
- 单评论传播 DAG 和“看见但未继续”节点。

五策略实验显示场景传播差异；历史复现显示逐阶段传播变化，不把阶段差异解释为策略因果效果。

2026年9月2日以前的历史批次可能没有 `social_network_snapshot.json` 和 `propagation_history.jsonl`。这些批次仍可查看历史趋势，但不能事后重建真实传播链。

共享网络页面统一位于 `/network/?experiment_id=<experiment_id>`，必须通过 `visualization/app.py` 提供服务。旧的 `social_network_report` 独立服务器、转发模块和重复配置已经删除，避免同一组接口维护两份实现。

当前只读 API 按职责命名：

- `/api/catalog`：共享实验目录；
- `/api/strategy/dashboard`：五策略总览；
- `/api/historical/*`：历史结果、真实趋势和探索性比较；
- `/api/network/*`：两类实验共用的网络、评论目录和传播链。

## 安全边界

- 页面只读访问已有 JSON、JSONL 和网络快照；
- 不调用 DeepSeek，不产生费用；
- 不创建、重置或覆盖实验批次；
- 实验编号只能解析为 `demo/experiments` 的直接子目录；
- 公共评论补充不属于邻居传播记录，因此评论传播链不代表 Agent 接触到的全部信息。

本模块仅使用 Python 标准库，无需安装 Streamlit、Plotly、pandas 或 openpyxl。
