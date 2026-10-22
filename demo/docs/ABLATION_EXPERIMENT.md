# 回应方案机制消融实验

## 目的

该实验用于区分负面率变化主要来自哪条反馈链路，不用于挑选“最好看”的结果。2026/10/18 起，消融条件通过事件副本中的独立开关传入，不需要修改正式事件文件或注释代码。

默认比较以下三组：

| 变体 | 外部增量评论 | 外部增量评论进入内部状态 | 邻居反馈 | 回答的问题 |
| --- | --- | --- | --- | --- |
| `full_feedback` | 保留 | 保留 | 保留 | 当前完整机制的基准结果 |
| `frozen_public` | 第1轮后冻结 | 无新增数据可进入 | 保留 | 外部LLM持续生成是否推动趋势 |
| `public_context_only` | 保留 | 排除 | 保留 | 外部评论只作发言语境时，内部状态是否仍趋同 |

可选的 `no_neighbor_feedback` 保留外部增量评论，但关闭邻居表达曝光，用于判断社交网络反馈的边际作用。

## 可比性约束

同一消融组只生成一次初始评论池、一次固定社交网络和一次第1轮Agent状态。各变体从同一第1轮状态分叉，并固定官方回应投入轮次。每个变体内部只共享事件、初始评论、固定网络、客观事实时间线和进场前快照；通告后的公众反应与Agent表达按场景独立演化，不允许复制“不回应”场景的增量评论。

2026/10/20 起，每个变体结果都保存共同输入哈希、进场前快照哈希、场景输入哈希和跨场景污染检查。`counterfactual_controls.cross_scenario_audit.status` 不是 `passed` 时，该变体标记为 `failed_isolation_audit`，不能用于解释机制差异。

默认只运行“不回应基线＋回应方案一”，以控制API费用。消融实验不读取真实趋势，也不强制拟合目标比例。

## 运行命令

在项目根目录执行：

```powershell
conda activate persona_sim
$env:DEEPSEEK_API_KEY = "填写本机使用的API Key"
python demo\ablation_runner.py --response-plan response_plan_1
```

加入“关闭邻居反馈”变体：

```powershell
python demo\ablation_runner.py --response-plan response_plan_1 --variants full_feedback,frozen_public,public_context_only,no_neighbor_feedback
```

确需比较全部三个回应方案时使用：

```powershell
python demo\ablation_runner.py --all-response-plans
```

可用参数：

- `--event-file`：事件输入，默认 `demo/event_example.json`；
- `--official-response-file`：回应方案文件，默认 `demo/official_response_options.json`；
- `--fixed-response-step`：所有变体共同的回应投入轮次，默认第2轮；
- `--group-id`：自定义输出组目录名；
- `--variants`：逗号分隔的变体编号。

## 输出与判读

结果保存在：

```text
demo/experiments/ablation_<event_id>_<timestamp>/
├─ comment_pool.json
├─ social_network_snapshot.json
├─ _shared_baseline/
├─ full_feedback/
├─ frozen_public/
├─ public_context_only/
└─ ablation_result.json
```

每个变体目录保存场景级状态和 `variant_result.json`。组级 `ablation_result.json` 的 `comparison_matrix` 汇总相同方案在不同变体下的逐轮Agent内部负面率、实际表达负面率、发言率、有效邻居曝光率、邻居/公共状态证据保留率、个人充分非同伴证据数和增量生成模式；累计评论池情绪仍从场景状态文件读取。判读时不应只看最终负面率。正常动态公众反应记录为 `generation_mode=scenario_reactive_public`；只有冻结变体使用 `disabled_by_ablation`。

`incremental_comment_history.jsonl` 中的 `generation_mode=disabled_by_ablation` 表示按实验设计冻结，不是DeepSeek故障。场景结果中的 `ablation_config` 是判定实验条件的唯一依据。

## 恢复正式运行

消融入口不修改正式事件文件。直接运行以下命令即恢复完整反馈机制：

```powershell
python demo\main.py
```

正式流程未显式配置 `simulation_options.ablation` 时，默认保留外部增量评论和邻居反馈。回应方案的内部状态仍执行正常认知边界：最多2条邻居表达、最多5条Persona相关公共评论，并由个体影响门槛区分`hold_only`和可改变状态的证据；这属于完整机制，不是消融条件。
