# 系统架构与代码地图

## 总体流程

```text
事件输入与官方策略
        ↓
事件角度规划与初始评论池
        ↓
共享进场前舆情基线
        ↓
动态进场条件判断
        ↓
五个策略场景从同一状态分叉
        ↓
增量评论 → 可见信息 → Agent决策 → 状态与指标
        ↓
策略效果、数据质量和性能结果比较
```

## 核心模块

| 文件 | 单一职责 |
| --- | --- |
| `main.py` | 五策略实验统一入口 |
| `project_config.py` | 路径、模型和运行参数 |
| `experiment_runner.py` | 共享基线、动态进场、策略分叉和结果比较 |
| `config/comment_profiles.json` | 评论生成使用的人物类型模板，不属于Agent Persona |
| `comments/` | 评论角度规划、初始评论、增量评论、校验与评论池访问 |
| `agents/` | Agent认知决策、候选选择、批量决策、状态和Persona访问 |
| `simulation/` | 单轮运行、事件状态、传播、实验批次和状态隔离 |
| `evaluation/metrics.py` | 计算Agent指标、趋势和过程效果 |
| `infrastructure/llm_service.py` | 统一HTTP请求、JSON解析、重试和性能统计 |
| `infrastructure/json_storage.py` | JSON与JSONL读写 |

## 状态边界

- `output/personas`是长期画像，只读加载。
- `demo/state`是默认临时状态；正式实验使用批次内独立状态目录。
- `demo/experiments`保存不可覆盖的事件、策略、评论、状态和结果快照。
- 五个策略共享进场前基线，进场后使用独立目录，禁止互相读取状态。
- 历史趋势复现位于`demo/historical_replay`，不调用五策略入口。

## LLM与本地逻辑边界

LLM负责事件角度、评论文本、Agent认知状态和全局趋势判断。本地代码负责字段校验、去重、兜底、候选评分、可复现选择、进场规则、指标公式和结果比较。所有网络请求必须经过`infrastructure/llm_service.py`。
