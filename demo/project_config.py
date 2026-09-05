"""集中管理 Demo 的路径和运行配置。

其他模块只从本文件读取路径，避免每个模块分别拼接路径，
从而降低模块之间的耦合。
"""

import os
from pathlib import Path


DEMO_DIR = Path(__file__).resolve().parent
PROJECT_DIR = DEMO_DIR.parent
PERSONA_DIR = PROJECT_DIR / "output" / "personas"
EXAMPLE_DIR = DEMO_DIR / "example"

# 默认运行状态放在 state 目录；实验场景可以通过环境变量使用独立目录。
DEFAULT_STATE_DIR = (DEMO_DIR / "state").resolve()
STATE_DIR = Path(
    os.environ.get("SIMULATION_STATE_DIR", str(DEFAULT_STATE_DIR))
).resolve()
EXPERIMENT_DIR = DEMO_DIR / "experiments"
# 2026/08/22 系统重置与状态初始化，修改功能：正式实验可读取本批次独立的事件快照。
EVENT_FILE = Path(
    os.environ.get(
        "SIMULATION_EVENT_FILE",
        str(DEMO_DIR / "event_example.json"),
    )
).resolve()
# 2026/08/23 内容策略对照，新增功能：配置人工维护的官方内容策略输入文件。
OFFICIAL_RESPONSE_FILE = DEMO_DIR / "official_response_options.json"
EVENT_STATE_FILE = STATE_DIR / "event_state_history.json"
POLICY_FILE = PERSONA_DIR / "policy_config.json"

# Agent 动态状态单独放在 state 目录中，不再和决策代码、示例输入混在一起。
AGENT_STATE_FILE = STATE_DIR / "agent_state_history.jsonl"
DECISION_HISTORY_FILE = STATE_DIR / "decision_history.jsonl"
INCREMENTAL_COMMENT_FILE = STATE_DIR / "incremental_comment_history.jsonl"
METRICS_HISTORY_FILE = STATE_DIR / "metrics_history.jsonl"

# 2026/08/22 系统重置与状态初始化，修改功能：正式实验可读取本批次独立的评论池。
COMMENT_POOL_FILE = Path(
    os.environ.get(
        "SIMULATION_COMMENT_POOL_FILE",
        str(DEMO_DIR / "comment_pool.json"),
    )
).resolve()
# 2026/09/05 评论人物类型配置归档，修改功能：从 Demo 配置目录读取评论生成模板。
COMMENT_PROFILE_FILE = DEMO_DIR / "config" / "comment_profiles.json"
# 2026/09/05 示例文件归档，修改功能：单 Agent 调试结果统一保存到 example 目录。
SINGLE_DECISION_RESULT_FILE = EXAMPLE_DIR / "decision_result.json"
SINGLE_LLM_RESULT_FILE = EXAMPLE_DIR / "decision_result_llm.json"

# DeepSeek 配置。建议实际运行时改为环境变量或本地配置文件。
DEEPSEEK_API_KEY = "DEEPSEEK_API_KEY"
DEEPSEEK_MODEL = "deepseek-v4-flash"
DEEPSEEK_ENDPOINT = "https://api.deepseek.com/chat/completions"
REQUEST_TIMEOUT = 120

# 联调修改：增加DeepSeek请求和评论批次的重试配置 2026/08/21 19：06
HTTP_RETRY_COUNT = 3
HTTP_RETRY_INTERVAL = 2
# 2026/08/24 增量评论第二次修改，修改功能：增加评论批次补齐次数，并统一配置冗余生成数量。
COMMENT_BATCH_RETRY_COUNT = 5
COMMENT_BATCH_EXTRA_COUNT = 2
# 2026/09/04 增量评论生成架构优化，新增功能：限制增量评论首轮并发批次数，并将业务补齐收敛为一次。
INCREMENTAL_COMMENT_BATCH_WORKERS = 2
INCREMENTAL_COMMENT_REFILL_ATTEMPTS = 1
# 2026/09/04 评论质量与耗时平衡，新增功能：质量未达标时最多追加一次救援请求，并允许少量备选表达。
INCREMENTAL_COMMENT_QUALITY_RESCUE_ATTEMPTS = 1
INCREMENTAL_COMMENT_RESCUE_EXTRA_COUNT = 2
# 2026/08/24 增量评论稳定补齐，修改功能：三条仅作为数据质量告警阈值，不再作为场景失败上限。
INCREMENTAL_COMMENT_FALLBACK_WARNING_LIMIT = 3

# 批量决策配置。
MAX_AGENT_COUNT = 30
MAX_WORKERS = 5
RETRY_COUNT = 2

# 公共黑板配置。每个 Agent 每轮只随机看见部分全局评论。
VISIBLE_COMMENT_COUNT = 15
# 2026/08/25 第六次联调问题修复，新增功能：每轮优先向 Agent 展示 10 条当前轮评论。
CURRENT_STEP_VISIBLE_COUNT = 10
COMMENT_VISIBILITY_SEED = int(
    os.environ.get("SIMULATION_RANDOM_SEED", "2026")
)
# 2026/08/25 第六次联调问题修复，新增功能：从评分最高的 3 条评论中进行可复现选择。
COMMENT_SELECTION_TOP_K = 3
COMMENT_SELECTION_SEED = COMMENT_VISIBILITY_SEED

# 评论池配置。每个派系和情绪组合都会尽量覆盖。
COMMENT_POOL_SIZE = 60
# 2026/08/23 评论派系覆盖对齐，新增功能：配置初始评论池中每个派系的最低评论数量。
COMMENT_POOL_MIN_FACTION_COUNT = 5
INCREMENTAL_COMMENT_COUNT = 20
COMMENT_POOL_TEMPERATURE = float(
    os.environ.get("SIMULATION_COMMENT_TEMPERATURE", "0.7")
)
COMMENT_POOL_MAX_TOKENS = 8000


def ensure_runtime_directories():
    """创建运行过程中需要的目录。"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
