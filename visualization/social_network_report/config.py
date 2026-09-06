"""集中配置第二十六次联调专题页面的只读数据路径。"""

from pathlib import Path


REPORT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = REPORT_DIR.parents[1]
STATIC_DIR = REPORT_DIR / "static"

EXPERIMENT_ID = "event_gaoyang_assault_001_20260906_143939_040535"
EXPERIMENT_DIR = PROJECT_ROOT / "demo" / "experiments" / EXPERIMENT_ID

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8766

SCENARIO_NAMES = {
    "no_response": "不回应",
    "fact_report": "事实通报",
    "empathy": "共情安抚",
    "rumor_clarification": "辟谣澄清",
    "handling_progress": "处置进展",
}
