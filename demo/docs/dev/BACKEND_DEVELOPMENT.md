# 后端开发任务说明

更新日期：2026-09-07  
适用接口：`v1.1-product`

## 一、确定使用的技术栈

后端统一使用：

- `FastAPI`：定义HTTP路由、依赖和异常处理；
- `Pydantic`：定义请求模型、响应模型、状态枚举和字段校验；
- `MySQL 8.0`：保存实验输入、运行状态和仿真结果。

MySQL连接需要使用兼容驱动，但本文不强制指定ORM。可以选择简单的MySQL访问方式，只要支持参数化查询、事务、连接释放和本地测试。不能在路由函数中拼接SQL字符串。

FastAPI自动生成的`/docs`应能展示本文规定的Pydantic请求与响应结构。后端不能使用无约束的`dict`替代已经在公共契约中明确的数据模型。

## 二、需要完成什么

后端负责人需要完成两条业务流程：

1. 接收事件和四种官方声明，创建并串行运行一次五策略实验；
2. 查询数据库中的历史实验及其完整结果。

同时需要完成统一响应、状态管理、错误处理和旧实验导入。后端不能复制或修改评论生成、Agent决策、动态进场、指标计算和传播算法。

## 三、新建实验功能

### 接收输入

实现 `POST /api/v1/experiments`，接收：

- 事件编号、事件正文和事件标签；
- 动态进场规则；
- 停滞参数；
- 事实通报、共情安抚、辟谣澄清和处置进展四种声明；
- 每条声明的信息状态。

第一版不允许用户调整Agent数、最大轮次、并发数和每轮评论数，继续使用当前Demo已经联调的配置。

### 校验输入

- 事件编号和正文不能为空；
- 四种策略必须完整且不能重复；
- 声明正文不能为空；
- 声明状态只能是 `clear/incomplete/conflict`；
- 事件编号已存在但正文不同，应返回冲突；
- 已有实验处于 `pending/running` 时拒绝创建第二个运行任务。

### 运行实验

接口不能等待整个仿真完成后才响应。正确流程是：

```text
保存事件、回应方案和pending实验
→ 返回HTTP 202及experiment_id
→ 后台单工作进程开始运行
→ 更新run_status=running
→ 调用现有Demo核心
→ 校验并导入experiment_result.json
→ 更新run_status=succeeded或failed
```

后台执行应复用现有能力：

- `validate_event_input()`校验事件；
- `load_official_response_options()`校验四策略；
- `prepare_simulation_batch()`创建独立批次和输入快照；
- `prepare_comment_pool()`生成本批次初始评论；
- `run_experiment()`运行共享基线和五策略。

后端可以增加调用适配层，但不能复制这些函数内部算法。每个实验必须使用独立实验目录，禁止覆盖 `demo/event_example.json` 和 `demo/official_response_options.json`。

第一版同一时间只运行一个实验。服务重启后的任务恢复暂缓，但必须将已失去工作进程的`running`任务明确标记为失败或需要人工确认，不能永久显示运行中。

## 四、实验状态功能

实现 `GET /api/v1/experiments/{experiment_id}/status`。

至少返回：

```text
experiment_id
run_status
current_stage
current_scenario
result_status
error_message
started_at
finished_at
```

前端可以每3～5秒查询一次；当状态变为`succeeded/failed`后停止查询。不能根据估算伪造完成百分比。

## 五、历史实验查询功能

需要实现：

- 分页实验列表；
- 实验总体结果；
- 五策略场景摘要；
- 各场景逐轮指标；
- 场景评论；
- 共享社交网络；
- 按轮次和评论编号查询传播；
- 单个Agent逐轮轨迹。

只有实验列表使用 `page/page_size`。评论、轮次、场景、网络、传播和Agent轨迹不分页。

评论接口支持可选 `step` 参数，前端可以一次获取整个场景，或只获取当前轮次用于弹幕播放。

## 六、必须实现的API

| ID | 方法 | 路径 | 功能 |
| --- | --- | --- | --- |
| A01 | GET | `/api/v1/health` | 后端和数据库健康状态 |
| A02 | POST | `/api/v1/experiments` | 创建并排队实验 |
| A03 | GET | `/api/v1/experiments` | 分页查询历史实验 |
| A04 | GET | `/api/v1/experiments/{experiment_id}/status` | 查询运行状态 |
| A05 | GET | `/api/v1/experiments/{experiment_id}` | 查询实验详情 |
| A06 | GET | `/api/v1/experiments/{experiment_id}/scenarios` | 查询五策略 |
| A07 | GET | `/api/v1/experiments/{experiment_id}/scenarios/{scenario_id}/rounds` | 查询逐轮指标 |
| A08 | GET | `/api/v1/experiments/{experiment_id}/scenarios/{scenario_id}/comments` | 查询弹幕评论 |
| A09 | GET | `/api/v1/experiments/{experiment_id}/network` | 查询关注网络 |
| A10 | GET | `/api/v1/experiments/{experiment_id}/scenarios/{scenario_id}/propagation` | 查询传播结果 |
| A11 | GET | `/api/v1/experiments/{experiment_id}/scenarios/{scenario_id}/agents/{agent_id}/rounds` | 查询Agent轨迹 |
| A12 | POST | `/api/v1/imports/experiments` | 导入已有实验 |

所有请求和响应字段直接使用 `SHARED_INTERFACE_CONTRACT.md`，不得自行改名。

## 七、旧实验导入

前端或管理员只提交 `experiment_id`。后端根据配置的实验根目录定位文件，不接受任意绝对路径。

导入成功后，旧实验设置为：

```text
run_status=succeeded
result_status=原始实验状态
```

重复导入返回 `already_imported`。导入失败不删除原始文件，并返回简短错误和 `request_id`。

## 八、Pydantic模型与统一接口规则

至少需要为以下数据建立Pydantic模型：

- 新建实验请求、事件输入、回应方案和四种官方声明；
- 实验创建响应、实验状态、实验摘要和实验详情；
- 场景摘要、逐轮指标、评论、社交网络、传播事件和Agent轨迹；
- 统一成功响应、统一错误响应和实验列表分页对象。

状态字段使用`Enum`或等价的Pydantic枚举约束。输入校验错误由FastAPI统一转换为约定错误结构，不把框架默认错误直接交给前端。

- 所有响应包含`code/message/data/request_id`；
- 实验列表使用`items/page/page_size/total`；
- 状态字段区分`run_status`和`result_status`；
- 比率返回`0～1`数值；
- 原始值不适用时返回`null`，不转换为0；
- 不返回`state_dir`、本机绝对路径、密钥或完整堆栈；
- 关注关系和传播关系不能混淆；
- 后端不重新计算仿真指标。

## 九、做好之后是什么样

- 用户提交事件和四种声明后，很快获得实验编号；
- 用户可以持续看到等待、运行、成功或失败状态；
- 实验成功后自动出现在历史实验列表；
- 用户可以查看5个场景、逐轮指标、评论、质量、网络和传播；
- 旧实验可以导入并使用相同接口查询；
- 同时提交第二个实验会得到明确提示，不会让两个实验互相覆盖；
- 后端失败不会影响原有 `python demo\main.py` 独立运行。

## 十、本地测试后再推送

后端负责人必须在本地完成：

1. 服务能够启动，`/docs`可以查看接口和Pydantic模型；
2. Pydantic能够拒绝缺字段、非法状态和不完整四策略输入；
3. 健康接口可以检查MySQL；
4. 使用简短测试事件提交新实验并立即收到HTTP 202；
5. 状态能够从`pending`变为`running`，最终变为`succeeded`或明确的`failed`；
6. 第二个同时运行请求返回409；
7. 成功实验能查询5个场景和完整轮次；
8. 统一本地旧实验可以导入且重复导入不重复写入；
9. 评论、网络、传播和Agent接口字段正确；
10. 不存在实验和场景返回统一404；
11. 数据库写入失败能够回滚，连接能够正常释放；
12. 自动化测试不调用真实LLM；完整运行测试由开发者明确使用测试Key后人工执行；
13. 原有 `python demo\main.py` 仍可独立运行。

本地测试通过后再推送个人分支。Pull Request附启动方式、接口测试结果、新实验状态截图或响应，以及尚未完成的内容。
