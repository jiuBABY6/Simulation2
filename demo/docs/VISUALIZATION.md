# 历史趋势复现可视化

本目录是独立的只读展示模块，不修改 `demo/experiments` 中的历史复现结果，也不影响原有五策略实验和历史复现入口。

## 数据处理边界

- 模拟数据：只读加载已完成的 `historical_replay_result.json` 和 `metrics_history.jsonl`。
- 评论池指标：第1轮读取初始评论池，第2轮起读取各轮增量评论，直接使用评论已有的 `emotion` 标签统计，不再次调用 LLM。
- 真实数据：从 `demo/historical_replay/example.xlsx` 的 `Sheet1` 提取八阶段群体情绪近似比例。
- 真实材料属于人工整理的群体趋势参考，不是完整平台样本，不用于推断个人态度，也不生成真实接受率或质疑率。
- 区间使用中点绘图，但保留下限、上限和原始表达；比例不强制归一化。
- 模拟结果与人工材料按八个事件阶段顺序对齐；若日期边界不同，页面分别展示原始时间段，不进行日级插值。
- 真实群体趋势主要与“当前轮评论负面率”对照；Agent负面率保留为主体状态辅助指标，累计评论池比例只作背景提示。

## 首次处理真实数据

```powershell
python visualization\real_data_processor.py
```

处理结果保存在 `visualization/data/real_trend.json`。当 `demo/historical_replay/example.xlsx` 内容更新后，需要重新执行一次处理命令。

## 启动网页

```powershell
python visualization\app.py
```

默认打开 `http://127.0.0.1:8765`。如不希望自动打开浏览器：

```powershell
python visualization\app.py --no-browser
```

本模块只使用 Python 标准库，无需安装 Streamlit、Plotly、pandas 或 openpyxl。
