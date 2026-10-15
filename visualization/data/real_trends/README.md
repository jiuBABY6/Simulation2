# 多事件真实趋势数据

本目录中的每个JSON对应一个历史事件：

```text
<event_id>.json
```

文件由以下命令生成，不应手工拼接：

```powershell
python visualization\historical\real_data_processor.py --event-id <event_id>
```

源Excel保存在 `demo/historical_replay/events/<event_id>/real_trend_source.xlsx`，原始文件名和SHA-256保存在同目录的 `event_manifest.json`。统一可视化服务根据实验结果中的 `event_id` 自动选择这里的对应JSON。
