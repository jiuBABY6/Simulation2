"""集中管理历史复现模式使用的路径。"""

import sys
from pathlib import Path


HISTORICAL_REPLAY_DIR = Path(__file__).resolve().parent
DEMO_DIR = HISTORICAL_REPLAY_DIR.parent
PROJECT_DIR = DEMO_DIR.parent
EXPERIMENT_DIR = DEMO_DIR / "experiments"

# 2026/09/02 历史趋势复现，新增功能：仅在独立入口中加载现有 Demo 模块，不修改原有导入结构。
if str(DEMO_DIR) not in sys.path:
    sys.path.insert(0, str(DEMO_DIR))

EVENT_FILE = HISTORICAL_REPLAY_DIR / "event_input.json"
TIMELINE_FILE = HISTORICAL_REPLAY_DIR / "official_response_timeline.json"

