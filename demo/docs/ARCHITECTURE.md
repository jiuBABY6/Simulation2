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
内置策略与显式触发的自定义策略场景从同一状态分叉
        ↓
增量评论 → 邻居传播＋公共补充 → Agent决策 → 状态与指标
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
| `config/social_network_config.json` | 固定网络、邻居传播、公共补充和逐层衰减配置 |
| `comments/` | 评论角度规划、初始评论、增量评论、校验与评论池访问 |
| `agents/` | Agent认知决策、候选选择、批量决策、状态和Persona访问 |
| `simulation/` | 单轮运行、事件状态、传播、实验批次和状态隔离 |
| `simulation/social_network.py` | 固定社交网络、影响力权重和关注关系查询 |
| `simulation/propagation_tracking.py` | Agent表达谱系、邻居曝光事件构建和传播历史保存 |
| `evaluation/metrics.py` | 计算Agent指标、趋势和过程效果 |
| `evaluation/propagation_metrics.py` | 计算传播覆盖、继续传播、层级和有效权重指标 |
| `infrastructure/llm_service.py` | 统一HTTP请求、JSON解析、重试和性能统计 |
| `infrastructure/json_storage.py` | JSON与JSONL读写 |
| `web_api.py` | 统一 Web 输入、会话控制和状态查询门面 |
| `web_control.py` | 单策略逐轮状态机、公告时间线、检查点和回滚 |
| `web_server.py` | V1 本地 HTTP 服务，托管 `visualization/web` |
| `web_server2.py` | V2 独立 HTTP 服务，托管 `visualization/web2` |

## Web 控制层

```text
V1 / V2 Vue 页面
        ↓ HTTP JSON
web_server.py / web_server2.py
        ↓
web_api.py
        ↓
web_control.py
        ↓
单轮仿真 runner 与实验状态目录
```

- V1 使用 `visualization/web`，默认端口 `8770`。
- V2 使用 `visualization/web2`，默认端口 `8771`，采用左侧状态、中间输入、右侧时机的单屏布局。
- 两版共用 `web_api.py` 和 `web_control.py`，不复制仿真计算逻辑。
- 不回应策略跳过进场前基线，直接从第 1 轮运行控制场景。

## 状态边界

- `output/personas`是长期画像，只读加载。
- `demo/state`是默认临时状态；正式实验使用批次内独立状态目录。
- `demo/experiments`保存不可覆盖的事件、策略、评论、状态和结果快照。
 - 五个策略共享进场前基线，进场后使用独立目录，禁止互相读取状态。
 - 五个策略读取实验根目录的同一网络快照；网络结构不随策略演化，场景状态彼此隔离。
 - 每个场景分别保存`propagation_history.jsonl`；共享基线传播记录随状态快照复制，进场后继续独立追加。
 - Web 单策略控制会额外保存 `web_control.json` 和 `.web_checkpoints`；不回应策略不创建共享基线。
 - 历史趋势复现位于`demo/historical_replay`，不调用五策略入口。

## LLM与本地逻辑边界

LLM负责事件角度、评论文本、Agent认知状态和全局趋势判断。本地代码负责字段校验、去重、兜底、候选评分、可复现选择、进场规则、指标公式和结果比较。所有网络请求必须经过`infrastructure/llm_service.py`。

## 权重是怎么计算出来的
