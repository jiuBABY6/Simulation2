# Simulation2 阶段性修改总结

本文汇总本轮对 Simulation2 仿真框架、Web API 和前端控制台的全部主要修改。

## 1. 自定义策略

- `demo/official_response_options.json` 新增 `custom` 内容策略。
- 内置策略仍为事实通报、共情安抚、辟谣澄清和处置进展。
- `custom` 默认不随“依次运行全部策略”自动触发。
- 通过单策略入口可显式运行 `custom`。
- 空公告的 `custom` 会标记为 `not_run`，原因 `custom_statement_empty`。

主要文件：

- `demo/experiment_runner.py`
- `demo/official_response_options.json`
- `demo/main.py`

## 2. Web 输入 API

新增统一输入层：

- `resolve_event_input()`：事件默认值和 web 覆盖。
- `resolve_official_response_options()`：公告默认值和 web 覆盖。
- `list_triggerable_strategies()`：返回策略和 `ready` 状态。
- `resolve_entry_timing()`：动态进场和固定轮次进场。
- `resolve_announcement_timeline()`：任意轮次公告时间线。

所有默认值仍来自：

```text
demo/event_example.json
demo/official_response_options.json
```

## 3. 会话控制 API

新增 `demo/web_control.py`，在独立实验批次内维护：

```text
demo/experiments/<experiment_id>/web_control.json
```

支持：

- 创建会话
- 启动
- 单轮推进
- 自动继续
- 暂停
- 解除暂停
- 回滚
- 创建同输入的新批次
- 追加公告
- 查询状态和实时快照

HTTP 路由由 `demo/web_server.py` 提供，函数门面为 `demo/web_api.py`。

## 4. 固定轮次与公告时间线

- `dynamic`：沿用原来的负面阈值、全局恶化和连续停滞规则。
- `fixed_round`：不再运行基线，直接从第 1 轮运行所选策略，在指定轮次发布公告。
- 公告时间线支持多个事件：

```json
[
  {
    "round": 3,
    "official_statement": "第一条公告",
    "official_statement_status": "incomplete"
  },
  {
    "round": 5,
    "official_statement": "第二条公告",
    "official_statement_status": "clear"
  }
]
```

- 没有新公告的轮次继续沿用最近公告。
- 同一轮重复添加会替换该轮公告。

## 5. 暂停时追加公告

新增 API：

```python
add_web_announcement(
    experiment_id,
    round_no,
    official_statement,
    official_statement_status,
)
```

HTTP：

```text
POST /api/sessions/{experiment_id}/announcement
```

规则：

- 只能暂停时调用；
- 只能添加当前或未来轮次；
- 目标轮正是当前待运行轮时，直接替换当前事件状态；
- 目标轮在未来时，写入公告时间线，在对应轮次执行前生效；
- 不回应策略不能追加公告。

## 6. Agent 实时显示

会话状态接口的 `snapshot.agents` 返回当前轮全部 Agent：

```text
agent_id
current_emotion
official_attitude
will_comment
last_action
last_comment_faction
last_comment
comment_emotion
comment_orientation
```

前端参考 `D:\社会舆情预测\demo\visualization` 的节点视觉：

- 一级只显示 Agent 数量和正、中、负面数量；
- 二级抽屉用彩色小球展示全部 Agent；
- 小球颜色表示情绪；
- 外圈颜色表示官方态度；
- 点击小球查看单 Agent 详情。

## 7. 前端控制台

页面目录：

```text
visualization/web/
```

主要布局：

- 舆情指标：一级直接显示折线图；
- Agent 状态：一级数值卡，点击进入 Agent 二级抽屉；
- 舆论池：一级数值卡，点击进入评论二级抽屉；
- 会话控制：启动、继续运行、暂停、回滚、重启；
- 公告输入：合并展示所有内置公告策略和 custom；
- 公告追加：暂停时添加任意轮次公告；
- 公告时间线仅通过折线图中的“公告N”竖线显示。

折线图支持：

- 负面率、质疑率、接受率；
- 官方进场标记；
- 多条追加公告轮次标记；
- 数据点悬浮数值。

## 8. 错误修复

### 全局趋势无效评论编号

`demo/evaluation/metrics.py` 不再因为 LLM 编造评论编号中断整轮仿真。
无效编号会被过滤，只保留有效证据。

### 检查点重复

`demo/web_control.py` 在失败重试或暂停继续时会重建同序号检查点，
不再报 `.web_checkpoints/000N 已存在`。

### 回滚后检查点冲突

回滚后会清理目标序号之后的检查点，避免下一次继续时创建同序号快照失败。

## 9. 运行方式

启动 Web API 和控制台：

```powershell
cd D:\Simulation2
& .\.venv\Scripts\python.exe demo\web_server.py --port 8770
```

浏览器访问：

```text
http://127.0.0.1:8770
```

## 10. 已验证内容

- Python 全量 `compileall`
- 前端 JS 语法检查
- 固定第 3 轮直接进入场景，不创建基线
- 第 3/5 轮公告时间线分别生效
- 暂停时追加公告
- Agent 快照返回 10 个 Agent
- Agent 二级小球抽屉
- 舆情指标一级折线图
- 无效趋势证据编号过滤
- 检查点覆盖重建
- 回滚检查点清理

完整 API 细节见 `WEB_API.md`。
