# Simulation2 Web API 文档

本文描述当前面向未来 web 页面提供的 Python API 层，并附带一个纯标准库
HTTP 路由服务；后端也可直接调用这些函数或在此基础上增加生产路由。

## 默认数据文件

| 输入 | 默认文件 |
| --- | --- |
| 事件 | `demo/event_example.json` |
| 官方公告策略 | `demo/official_response_options.json` |
| 策略选择 | `content_strategies` + 系统内置的 `no_response` |

所有输入都先加载默认文件，再由 web 输入按字段覆盖并进入既有校验。

## 输入 API

### 1. 事件 web 输入

```python
from web_api import get_event_web_default, apply_event_web_input

default_event = get_event_web_default()
event = apply_event_web_input({
    "event_content": "网页填写的事件正文",
    "event_labels": {"event_valence": "negative"}
})
```

规则：

- 不传 `web_event_input` 时完全使用默认事件。
- 只传 `event_content` 时沿用默认 `event_id` 与未覆盖标签。
- `event_labels` 浅层合并。
- 提供与默认不同的 `event_id` 时必须同时提供 `event_content`。

### 2. 公告内容 web 输入

```python
from web_api import get_official_content_web_default, prepare_web_inputs

default_options = get_official_content_web_default()
inputs = prepare_web_inputs(
    web_event_input=None,
    official_content_input={
        "custom": {
            "official_statement": "网页公告内容",
            "official_statement_status": "clear"
        }
    }
)
```

`official_content_input` 支持三种形式：

- 映射：`{"strategy_id": {"official_statement": "...", "official_statement_status": "..."}}`
- 列表：`[{"strategy_id": "...", "official_statement": "...", ...}]`
- 完整结构：`{"content_strategies": [...]}`

未覆盖策略保留默认 JSON 内容。校验错误（未知策略、空公告配非 `none`
状态等）会直接抛出 `ValueError`。

### 3. 策略选择 web 输入

```python
from web_api import list_strategy_web_options, apply_strategy_web_input

options = list_strategy_web_options()
selection = apply_strategy_web_input("custom")
```

返回的策略项：

```json
{
  "strategy_id": "custom",
  "strategy_name": "自定义",
  "custom": true,
  "ready": false
}
```

`ready=false` 表示 custom 尚未填写公告，web 端不应允许启动该策略会话。

## HTTP 服务

```powershell
& .\.venv\Scripts\python.exe demo\web_server.py
```

默认地址为 `http://127.0.0.1:8770`。同一服务同时托管
`Simulation2/visualization/web` 控制台页面，直接访问首页即可使用事件、
公告、策略输入和会话控制。以下为创建会话的 JSON 请求体：

```json
{
  "web_event_input": {
    "event_content": "网页事件正文"
  },
  "official_content_input": {
    "custom": {
      "official_statement": "网页公告内容",
      "official_statement_status": "clear"
    }
  },
  "selected_strategy_id": "custom"
}
```

| 方法 | 路径 | 作用 |
| --- | --- | --- |
| GET | `/api/input/defaults` | 返回事件、公告与可选策略默认值 |
| POST | `/api/input/preview` | 校验事件/公告 web 输入并返回解析结果 |
| GET | `/api/sessions` | 列出所有 web 控制会话 |
| POST | `/api/sessions` | 创建会话 |
| GET | `/api/sessions/{experiment_id}` | 查询会话状态 |
| POST | `/api/sessions/{id}/start` | 启动并准备初始评论池 |
| POST | `/api/sessions/{id}/step` | 执行一个时间步 |
| POST | `/api/sessions/{id}/continue` | 清空暂停并执行一个时间步 |
| POST | `/api/sessions/{id}/pause` | 暂停 |
| POST | `/api/sessions/{id}/resume` | 继续（不自动推进） |
| POST | `/api/sessions/{id}/rollback` | 回滚，body 可传 `{"steps": 1}` |
| POST | `/api/sessions/{id}/restart` | 创建同输入的新批次 |
| POST | `/api/sessions/{id}/announcement` | 暂停时向指定轮次追加公告 |

## 会话控制 API

控制粒度为一个被选择的策略。会话由 `web_control.json` 记录在
`demo/experiments/<experiment_id>/` 下。

| 函数 | 行为 |
| --- | --- |
| `create_web_experiment(...)` | 创建不可覆盖批次并写入控制文件，不调用 LLM |
| `start_web_experiment(experiment_id)` | 生成初始评论池并初始化共享基线 |
| `step_web_experiment(experiment_id)` | 执行一个时间步，执行后自动暂停 |
| `continue_web_experiment(experiment_id)` | 清空暂停并执行一个时间步 |
| `pause_web_experiment(experiment_id)` | 设置暂停，阻止下一次推进 |
| `resume_web_experiment(experiment_id)` | 仅清除暂停，不自动推进 |
| `rollback_web_experiment(experiment_id, steps=1)` | 回滚到最近完成步之前的检查点 |
| `restart_web_experiment(experiment_id)` | 用相同输入创建新的实验批次 |
| `add_web_announcement(experiment_id, round_no, official_statement, official_statement_status)` | 暂停时追加或替换指定轮次公告 |
| `get_web_experiment_status(experiment_id)` | 查询状态、进度与场景结果 |
| `list_web_experiments()` | 列出所有带控制文件的会话 |

### 典型调用顺序

```python
from web_api import (
    apply_event_web_input,
    apply_strategy_web_input,
    continue_web_experiment,
    create_web_experiment,
    pause_web_experiment,
    rollback_web_experiment,
    start_web_experiment,
)

event = apply_event_web_input({"event_content": "事件正文"})
selection = apply_strategy_web_input("fact_report")

session = create_web_experiment(
    web_event_input=event,
    official_content_input=None,
    selected_strategy_id=selection["strategy_id"],
)
experiment_id = session["experiment_id"]

start_web_experiment(experiment_id)
continue_web_experiment(experiment_id)   # 第1轮，结束后暂停
continue_web_experiment(experiment_id)   # 第2轮或进场后策略轮
pause_web_experiment(experiment_id)
rollback_web_experiment(experiment_id, steps=1)
```

### 控制语义

- `create` 只创建事件/公告/策略快照，不生成评论池。
- `start` 生成初始评论池并创建 `_shared_baseline` 状态。
- 固定轮次/公告时间线模式不创建基线，直接从第 1 轮运行所选策略，并按时间线
  在指定轮次发布公告。
- `step`/`continue` 每次最多执行一个时间步；步骤完成后 `paused=true`。
- 暂停与继续只发生在轮次边界；不能中止一个正在同步执行的单轮。
- `rollback` 恢复该步开始前的检查点；回滚跨越基线/场景边界时会清理旧的
  策略状态目录并删除过期的 `scenario_result.json`。
- `restart` 保留旧批次不可覆盖，新建一个同输入批次；若旧批次已有初始评论池，
  会复制该评论池以降低 LLM 成本。
- 会话暂停时可通过 `add_web_announcement()` 或
  `POST /api/sessions/{id}/announcement` 添加/替换任意轮次的公告。

## 当前限制

- 本阶段只支持单策略控制会话；`all` 模式仍由 `main.run_complete_simulation()`
  完整串行执行。
- HTTP 服务为本地开发形态，未包含生产鉴权、任务线程或浏览器页面。
- 未包含多用户并发锁与生产级队列。
