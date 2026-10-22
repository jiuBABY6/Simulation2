# 解耦重构说明

更新日期：2026-10-15

本轮重构只调整代码职责和依赖方向，不修改 Agent 决策机制、社会网络参数、
LLM 提示词、指标口径、命令行入口、实验目录或 JSON 字段。

## 依赖原则

```text
命令行 / HTTP 入口
        ↓
实验编排 / API 路由
        ↓
共享应用服务 / 领域服务
        ↓
文件、子进程、LLM 等基础设施
```

上层可以依赖下层，下层不能导入某一种具体实验的顶层入口。旧函数名保留为
兼容门面，外部脚本无需同步改造。

## Demo

`demo/application/` 是五策略实验和历史复现之间的共享应用层：

- `runtime_config.py`：保存两类实验一致的单轮执行参数；
- `error_summary.py`：统一生成控制台错误摘要；
- `scenario_state.py`：创建隔离场景状态，不了解具体实验模式；
- `step_executor.py`：封装 `simulation.runner` 子进程及环境变量协议；
- `round_results.py`：读取单轮指标、评论质量和传播摘要。

历史复现现在直接依赖这些共享服务，不再反向导入
`experiment_runner.py`。`experiment_runner.py` 继续保留原函数名并委托共享服务，
因此现有测试和调用方保持兼容。子进程隔离仍然保留，避免一次性改变配置加载
和场景隔离语义。历史复现模块同时支持包导入和既有直接脚本启动，不再把
顶层模块名作为唯一导入方式。

`demo/domain/contracts.py` 定义 `SimulationContext`、
`AgentDecisionInput` 和 `AgentDecisionResult`。批量编排器负责从状态仓库组装
完整输入，Agent 决策核心只接收该输入对象，不再自行定位事件或状态文件。
结果在写入边界转换回原有字典，因此历史 JSON/JSONL 和可视化字段不变。

`application/runtime_config.py` 还负责把现有 `project_config.py` 转换为可注入
的路径与运行参数对象。`project_config.py` 仍是兼容配置源；本轮先迁移单轮
编排和 Agent 决策链，其他稳定模块后续可以逐步迁移，避免一次性修改全部
业务代码。

## Visualization

- `api_router.py` 只负责只读 API 参数校验和服务分发；
- `app.py` 只负责 HTTP、静态文件和错误响应；
- `shared/artifact_io.py` 统一读取并校验 JSON/JSONL；
- `shared/event_resources.py` 统一校验事件资源编号和路径；
- `historical/`、`strategy/` 和 `shared/network/` 继续分别承担历史、五策略和
  共享网络职责。

可视化读取器不会回写实验目录，旧批次的乱码修复仍以只读转换函数完成。
共享实验目录索引不再导入 `historical/`，依赖方向保持为具体业务层依赖
共享层。

## Persona Pipeline

- `text_processing.py`：MongoDB 文档形态适配、微博清洗和转发拆分；
- `policy_builder.py`：根据 Persona 集合生成全局策略配置；
- `deepseek_json_client.py`：统一两个分类任务的请求、重试和 JSON 解析；
- `build_personas.py`：数据库读取、分类调度和输出；
- `build_faction_preferences.py`：派系分类与 Persona 更新；
- `emotion.py`、`rebuild_policy_config.py`：配置汇总工具。

流水线同时支持原有的直接脚本命令和包导入方式。断点文件、输出路径和计算
公式保持不变。

## 兼容边界

本轮明确保持以下内容不变：

1. `python demo/main.py`、`python demo/historical_replay/main.py`、
   `python visualization/app.py` 和 Persona 三步命令；
2. `demo/experiments` 与 `output/personas` 的目录布局；
3. 历史复现与五策略的观测口径和模式隔离；
4. DeepSeek 调用次数、请求参数和重试行为；
5. 社交网络、可见评论和 Agent 决策参数。

`decision_engine.py` 的基础结构、证据约束和最终结论已经分段校验；
`incremental_generator.py` 的输入准备、生成和记录装配也已拆开。后续若
继续解耦，应优先迁移剩余全局配置和存储访问，再拆分
`experiment_runner.py`，不要在同一个提交中同时调整业务机制。

