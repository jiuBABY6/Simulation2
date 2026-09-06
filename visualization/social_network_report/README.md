# 第二十六次联调社交网络传播专题

本目录只读展示实验`event_gaoyang_assault_001_20260906_143939_040535`的固定社交网络、逐轮邻居传播、单评论传播链、五策略传播指标和验收分析。

## 启动命令

在项目根目录执行：

```powershell
conda activate persona_sim
python visualization\social_network_report\app.py
```

默认打开：

```text
http://127.0.0.1:8766
```

不自动打开浏览器：

```powershell
python visualization\social_network_report\app.py --no-browser
```

指定端口：

```powershell
python visualization\social_network_report\app.py --port 8767
```

## 页面内容

- 第二十六次联调总体状态、网络规模、传播规模、耗时和兜底率；
- 五个实验场景的固定网络及截至指定轮次的累计信息流；
- Agent影响力、发出曝光、接收曝光和继续表达情况；
- 按传播深度排序的评论目录及单评论传播DAG；
- 五策略曝光次数、继续传播率、最大深度和数据质量对照；
- 第二阶段A验收结论与结果解释边界。

## 数据来源与安全边界

页面只读取：

```text
demo/experiments/event_gaoyang_assault_001_20260906_143939_040535/
```

服务不调用大模型，不修改实验目录，不生成新的实验状态。网络图中的箭头统一表示评论实际传播方向；原始网络快照中的边表示关注方向，两者方向相反。

公共评论补充没有写入邻居传播事件，因此单评论传播图只表示关系网络中的邻居曝光和继续表达，不代表Agent接触到的全部公共信息。
