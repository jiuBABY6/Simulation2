"""集中管理可视化服务使用的只读数据路径。"""

from pathlib import Path


VISUALIZATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VISUALIZATION_DIR.parent
EXPERIMENTS_DIR = PROJECT_ROOT / "demo" / "experiments"
HISTORICAL_REPLAY_DIR = PROJECT_ROOT / "demo" / "historical_replay"
HISTORICAL_EVENTS_DIR = HISTORICAL_REPLAY_DIR / "events"
ACTIVE_HISTORICAL_EVENT_PATH = HISTORICAL_REPLAY_DIR / "active_event.json"
REAL_DATA_DIR = VISUALIZATION_DIR / "data" / "real_trends"
HISTORICAL_STATIC_DIR = VISUALIZATION_DIR / "historical" / "static"
STRATEGY_STATIC_DIR = VISUALIZATION_DIR / "strategy" / "static"
PORTAL_DIR = VISUALIZATION_DIR / "portal"
NETWORK_STATIC_DIR = VISUALIZATION_DIR / "shared" / "network" / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
