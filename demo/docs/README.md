# 舆情社会模拟文档中心

本目录只保留当前使用、维护和后续开发所需文档。历史流水账、早期接口草案和已经失效的机制说明不再放在当前文档中心；需要追溯时使用Git历史。

## 第一次接手

按以下顺序阅读：

1. [PROJECT_HANDOFF_20261022.md](./PROJECT_HANDOFF_20261022.md)：完整使用教程，包括环境、三方案实验、历史复现、新事件、Persona、可视化和故障排查。
2. [PROJECT_STATUS.md](./PROJECT_STATUS.md)：当前已完成内容、验证边界、主要风险和下一步工作。
3. [ARCHITECTURE.md](./ARCHITECTURE.md)：系统流程、代码地图、目录职责和依赖方向。
4. [DATA_CONTRACT.md](./DATA_CONTRACT.md)：输入、状态、评论、传播和结果字段。
5. [SIMULATION_INTERFACE_SPEC.md](./SIMULATION_INTERFACE_SPEC.md)：稳定入口、模块接口和禁止事项。

只想运行或查看系统时，阅读前两份即可。

## 专题文档

| 文档 | 适用场景 |
| --- | --- |
| [HISTORICAL_REPLAY.md](./HISTORICAL_REPLAY.md) | 维护历史事件输入、时间线、Agent响应和真实趋势边界 |
| [VISUALIZATION.md](./VISUALIZATION.md) | 维护方案对照、历史复现和共享网络页面 |
| [LLM_SERVICE.md](./LLM_SERVICE.md) | 检查DeepSeek调用位置、重试、费用和本地逻辑边界 |
| [GIT_WORKFLOW.md](./GIT_WORKFLOW.md) | 分支、提交、审查和团队协作 |

## 三个稳定入口

~~~powershell
# 三种回应方案＋一组不回应基线
python demo/main.py

# 条件化历史复现
python demo/historical_replay/main.py --event-id <event_id>

# 只读可视化
python visualization/app.py
~~~

环境安装、API Key设置、输入准备、结果目录和错误处理统一以PROJECT_HANDOFF_20261022.md为准，不在本索引重复维护。

## 文档维护规则

- 使用教程只写在交接教程，不在多个文件重复命令；
- 当前完成状态只写在PROJECT_STATUS.md；
- 代码职责和目录结构只写在ARCHITECTURE.md；
- 字段变化先更新DATA_CONTRACT.md；
- 模块入口或依赖变化先更新SIMULATION_INTERFACE_SPEC.md和ARCHITECTURE.md；
- 尚未实现的内容不得写成当前能力；需要启动新阶段时，应先重新评审并建立与代码同步维护的设计说明；
- 不再创建按日期累计的超长开发日志或逐次联调流水账；有效结果摘要写入PROJECT_STATUS.md，原始证据保存在实验目录和Git历史；
- 文档不得包含API Key、个人敏感数据或不必要的本机绝对路径。
