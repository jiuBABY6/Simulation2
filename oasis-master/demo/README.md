# 微博舆情群体 Agent 初期 Demo

## 1. 交付范围

本目录是一个独立、可直接运行的初期框架，用十个群体 Agent 模拟微博社会事件传播，并比较：

1. 官方在什么时机进场；
2. 官方发布哪类声明更有效。

传播由群体状态和行为参数涌现，生命周期只作为分析指标，不驱动传播。当前参数全部是演示先验，不应解释为真实微博平台结论。

已实现：

- 十个可配置的群体 Agent；
- 群体聚合状态：注意力、负面比例、谣言信念、官方信任、权威信息覆盖；
- 离散时间 step；
- 群体并行决策、平台稳定排序提交；
- 点赞、转发、评论、不作为的聚合动作；
- `S0-S4` 五类官方进场策略；
- `A-D` 四类声明模板；
- 舆情强度、增长率、负面比例、谣言比例、权威覆盖、风险分和生命周期；
- JSONL 事件溯源；
- 相同随机种子的可复现运行；
- 重置机制；
- 评论 JSONL 到十个群体的基线映射；
- LLM 并发、超时和调用预算接口。

暂未实现：

- 真实大模型供应商调用；
- 真实微博 API、爬虫或数据库导入；
- 语义向量聚类；
- 真实关注网络和个体传播路径；
- Web 可视化页面；
- 基于历史事件的参数校准。

## 2. 目录结构

```text
demo/
├── config/
│   └── scenario.json          # 十个群体、官方策略和仿真参数
├── data/
│   └── README.md              # 评论数据接入格式
├── outputs/
│   └── README.md              # 动态运行结果
├── tests/
│   └── test_demo.py           # 配置、可复现、介入和重置测试
├── weibo_demo/
│   ├── agents.py              # 群体 Agent
│   ├── comment_mapping.py     # 评论到群体的基线映射
│   ├── config.py              # 场景读取与校验
│   ├── engine.py              # 离散时间仿真引擎
│   ├── llm.py                 # LLM 并发/预算门控
│   ├── models.py              # 领域模型
│   ├── policy.py              # 官方策略 Agent
│   └── storage.py             # 内存/JSONL 事件存储
├── requirements.txt           # 当前无第三方依赖
└── run_demo.py                # 命令行入口
```

所有 Demo 代码、配置、数据约定和默认输出都在本目录内，不修改 Oasis 原有代码。

## 3. 快速运行

在 `oasis-master` 下执行：

```powershell
python demo/run_demo.py
```

默认运行 24 个 step，每个 step 表示 30 分钟，采用：

- 进场策略 `S3`：风险阈值；
- 声明类型 `C`：辟谣澄清；
- 固定随机种子 `20260723`。

比较同一场景下的五种进场策略：

```powershell
python demo/run_demo.py --compare
```

覆盖步数、随机种子、时机和声明类型：

```powershell
python demo/run_demo.py --steps 12 --seed 7 --policy S2 --statement D
```

声明类型：

| 类型 | 含义 |
| --- | --- |
| A | 事实通报 |
| B | 共情安抚 |
| C | 辟谣澄清 |
| D | 处置进展 |

进场策略：

| 策略 | 含义 |
| --- | --- |
| S0 | 不回应基线 |
| S1 | 第一个有效 step 立即回应 |
| S2 | 强度超过阈值且连续增长 |
| S3 | 综合风险分超过阈值 |
| S4 | 检测到峰值转折后回应 |

## 4. 每个 step 的执行顺序

```text
读取上一步聚合指标
        ↓
官方策略 Agent 判断是否进场
        ↓
十个群体 Agent 并行感知和决策
        ↓
按 agent_id 稳定排序并提交聚合动作
        ↓
保存群体状态与事件日志
        ↓
计算强度、风险和生命周期
```

每个群体使用由 `seed + step + group_id` 派生的独立随机数生成器。因此，即使 `asyncio` 的调度次序变化，相同配置和随机种子仍得到相同指标。

## 5. 群体状态与记忆

群体 Agent 不维护一段不断增长的自然语言记忆。每个群体只维护固定大小的聚合状态：

```json
{
  "attention": 0.72,
  "negative_ratio": 0.62,
  "rumor_belief": 0.41,
  "trust_official": 0.38,
  "authority_coverage": 0.25,
  "cumulative_exposures": 400,
  "last_active_step": 6
}
```

原始评论与代表性评论应放在数据层，不直接拼入群体状态。正式版本可以增加每个群体最多 10–20 条的有界证据池，供官方声明生成和审计使用。

## 6. 评论数据接入

评论文件采用 UTF-8 JSONL，每行至少有 `text`：

```json
{"comment_id": "c001", "text": "请公布证据和完整时间线"}
```

执行映射但仍使用场景预设规模：

```powershell
python demo/run_demo.py --comments demo/data/comments.jsonl
```

使用评论分类数量作为十个群体的规模：

```powershell
python demo/run_demo.py `
  --comments demo/data/comments.jsonl `
  --use-comment-population
```

当前 `KeywordCommentMapper` 只是数据管线占位实现。正式使用前必须替换为“事件隔离、去重清洗、语义聚类、多维标签、人工抽检”的流程。群体数量可以在展示层固定为十类，但聚类结果应允许合并、拆分和版本化。

## 7. LLM 并发和时间成本

当前群体行为完全由规则模型计算，不调用 LLM，因此十个群体 Agent 可以快速并行完成一步。

`weibo_demo/llm.py` 提供 `LLMCallGate`，默认建议：

- 最大并发：3；
- 单次运行预算：40；
- 单次超时：15 秒；
- 超时或预算耗尽时回退到规则/模板。

后续 LLM 只应进入以下位置：

1. 官方声明模板的受控改写；
2. 置信度较低的评论分类；
3. 少量高不确定性的关键 Agent 决策。

不应让十个群体 Agent 每个 step 都调用一次 LLM。

## 8. 输出与重置

默认结果写入 `demo/outputs`：

- `events_*.jsonl` 保存每个 step 的声明、群体动作、群体状态和指标；
- `summary_*.json` 保存单次运行摘要；
- `comparison_*.json` 保存 S0-S4 的对比结果。

`SimulationEngine.reset()` 会清空动态事件和 Agent 状态，重新生成 `run_id`，但不会修改场景配置和原始数据。

## 9. 测试

在 `oasis-master` 下执行：

```powershell
python -m unittest discover -s demo/tests -t demo -v
```

测试覆盖：

- 场景中恰好存在十个唯一群体；
- 评论分类回退；
- 相同随机种子的结果一致；
- 风险策略可以触发官方介入；
- reset 后动态状态可以复现。

## 10. 与 Oasis 主项目的衔接

该框架刻意保持独立，避免初期直接修改成熟项目。下一阶段可通过适配器接入 Oasis：

1. 将 `ActionBatch` 转换为 Oasis 平台的批量点赞、转发、评论事件；
2. 将 `JsonlEventStore` 替换为带 `run_id` 的 SQLite/PostgreSQL 仓储；
3. 复用 `Channel` 作为 Agent 到平台的间接通信通道；
4. 复用 `OasisEnv.step()` 的调度方式，但把默认 LLM 信号量从 128 降到 3–5；
5. 保持 Agent 并行计算、平台单写入器提交；
6. 真实数据只能写入 `raw_*`，运行状态写入 `sim_*`。

正式接入前，建议先用真实评论完成一次数据质量审计，再决定十个群体的定义和参数。视频评论只能作为该事件受众的样本，不能直接外推为微博全平台人口分布。
