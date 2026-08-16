"""集中管理 Demo 的路径和运行配置。

其他模块只从本文件读取路径，避免每个模块分别拼接路径，
从而降低模块之间的耦合。
"""

from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DEMO_DIR.parent
PERSONA_DIR = PROJECT_DIR / "output" / "personas"

EVENT_FILE = DEMO_DIR / "event_example.json"
EVENT_STATE_FILE = DEMO_DIR / "event_state.json"
POLICY_FILE = PERSONA_DIR / "policy_config.json"

# Agent 动态状态单独放在 state 目录中，不再和决策代码、示例输入混在一起。
STATE_DIR = DEMO_DIR / "state"
AGENT_STATE_FILE = STATE_DIR / "agent_state_history.jsonl"
DECISION_HISTORY_FILE = STATE_DIR / "decision_history.jsonl"
INTERACTION_HISTORY_FILE = STATE_DIR / "interaction_history.jsonl"
METRICS_HISTORY_FILE = STATE_DIR / "metrics_history.jsonl"
EVENT_STATE_HISTORY_FILE = STATE_DIR / "event_state_history.jsonl"

COMMENT_POOL_FILE = DEMO_DIR / "comment_pool.json"
SINGLE_DECISION_RESULT_FILE = DEMO_DIR / "decision_result.json"
SINGLE_LLM_RESULT_FILE = DEMO_DIR / "decision_result_llm.json"

# DeepSeek 配置。建议实际运行时改为环境变量或本地配置文件。
DEEPSEEK_API_KEY = "请在这里填写 DeepSeek API Key"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
REQUEST_TIMEOUT = 120

# 批量决策配置。
MAX_AGENT_COUNT = 30
MAX_WORKERS = 5
RETRY_COUNT = 2

# 评论池配置。每个派系和情绪组合都会尽量覆盖。
COMMENT_POOL_SIZE = 60
COMMENT_POOL_TEMPERATURE = 0.7
COMMENT_POOL_MAX_TOKENS = 8000


def ensure_runtime_directories():
    """创建运行过程中需要的目录。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)

