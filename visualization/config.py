"""集中管理可视化服务使用的只读数据路径。"""

from pathlib import Path


VISUALIZATION_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = VISUALIZATION_DIR.parent
EXPERIMENTS_DIR = PROJECT_ROOT / "demo" / "experiments"
# 2026/09/05 历史复现材料归档，修改功能：从历史复现目录读取人工整理的真实趋势数据。
REAL_SOURCE_PATH = (
    PROJECT_ROOT / "demo" / "historical_replay" / "example.xlsx"
)
REAL_DATA_PATH = VISUALIZATION_DIR / "data" / "real_trend.json"
STATIC_DIR = VISUALIZATION_DIR / "static"

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
