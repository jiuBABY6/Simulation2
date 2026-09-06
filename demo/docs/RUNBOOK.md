# 运行与排错手册

## 环境准备

当前验证环境使用Conda环境`persona_sim`。在项目根目录执行：

```powershell
conda activate persona_sim
python demo\main.py
```

正式交接前需要补充可复现依赖清单，并将LLM密钥放入本地环境变量，不得写入或发送到代码仓库。

## 更换测试事件

1. 修改`demo/event_example.json`。
2. 修改`demo/official_response_options.json`。
3. 确认两个文件的`event_id`完全一致。
4. 保持Agent数、轮数、增量评论数和随机种子不变，再进行跨事件性能比较。

## 输出位置

每次运行会创建新的：

```text
demo/experiments/<event_id>_<timestamp>/
```

重点查看：

- `experiment_result.json`：总体结果、策略比较和性能摘要；
- 各策略目录中的状态和逐轮指标；
- `comment_quality`和`data_quality`：LLM评论及兜底情况；
- `performance`：阶段耗时和分类LLM请求。
- `propagation_history.jsonl`：邻居曝光、传播层级、衰减权重和是否继续表达；
- `propagation_summary`：场景累计覆盖人数、继续传播次数和最大传播深度。

## 常见状态

| 状态 | 含义 |
| --- | --- |
| `completed` | 应运行的策略均成功完成 |
| `partial_failed` | 部分策略失败 |
| `failed` | 所有策略失败或关键流程失败 |
| `not_run` | 动态进场条件始终未触发，回应策略未实际运行 |
| `normal` | 评论兜底未触发质量告警 |
| `degraded` | 实验完成，但部分轮次历史兜底较多 |
| `emergency` | 使用了本地应急评论，结果需谨慎解释 |

## 进场原因

| 值 | 含义 |
| --- | --- |
| `negative_threshold` | Agent负面率达到当前阈值 |
| `global_worsening` | LLM全局趋势判断为恶化 |
| `stagnation` | 舆情连续多轮没有明显改善 |

## 最小交接检查

新成员首次接手时应依次完成：

1. `python -m compileall -q demo`；
2. 校验两个输入JSON的`event_id`；
3. 使用小规模参数完成一次运行；
4. 确认生成新实验目录且没有覆盖旧批次；
5. 确认结果中包含策略状态、数据质量、传播摘要和性能摘要。
