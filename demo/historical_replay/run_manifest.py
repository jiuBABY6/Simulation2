"""生成历史复现实验的可重复性清单。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agents.decision_service import HISTORICAL_DECISION_TEMPERATURE
from infrastructure.json_storage import read_jsonl, save_json
from project_config import COMMENT_VISIBILITY_SEED, DEEPSEEK_MODEL


# 2026/10/14，修改功能：v3标识本地情绪裁决、情绪无关发言评分、
# 过程评价迟滞与可达质疑门槛，避免与v2实验结果混淆。
HISTORICAL_REPLAY_MECHANISM_VERSION = "persona_evidence_replay_v3"

_CORE_CODE_FILES = (
    "agents/decision_engine.py",
    "agents/decision_profile.py",
    "agents/decision_service.py",
    "agents/evidence_appraisal.py",
    "agents/historical_participation.py",
    "agents/official_attitude.py",
    "simulation/evidence_policy.py",
    "simulation/propagation.py",
)


def _sha256_file(path):
    """流式计算文件 SHA-256。"""

    digest = hashlib.sha256()
    with Path(path).open("rb") as file_object:
        for chunk in iter(lambda: file_object.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value):
    """计算JSON兼容对象的稳定哈希。"""

    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _collect_persona_profiles(decision_history_file):
    """从实际决策记录提取参与者及其稳定画像，而不是推测选人顺序。"""

    profiles = {}
    for record in read_jsonl(decision_history_file):
        if record.get("status") != "success":
            continue
        agent_id = str(record.get("agent_id", "")).strip()
        profile = record.get("decision", {}).get("persona_decision_profile")
        if agent_id and isinstance(profile, dict) and agent_id not in profiles:
            profiles[agent_id] = profile
    return profiles


# 2026/10/14，新增功能：固定输入、模型和代码指纹，避免把两次随机运行的
# 差异误认为机制改善。清单只记录哈希和公开配置，绝不写入 API Key。
def save_historical_run_manifest(
    experiment_dir,
    state_dir,
    input_files,
):
    """保存本批次输入、机制代码和实际Agent画像的审计信息。"""

    experiment_dir = Path(experiment_dir)
    state_dir = Path(state_dir)
    demo_dir = Path(__file__).resolve().parents[1]
    normalized_inputs = {
        str(name): Path(path) for name, path in input_files.items()
    }
    profiles = _collect_persona_profiles(
        state_dir / "decision_history.jsonl"
    )
    code_hashes = {
        relative_path: _sha256_file(demo_dir / relative_path)
        for relative_path in _CORE_CODE_FILES
    }
    manifest = {
        "schema_version": 1,
        "mechanism_version": HISTORICAL_REPLAY_MECHANISM_VERSION,
        "model": DEEPSEEK_MODEL,
        "agent_decision_temperature": HISTORICAL_DECISION_TEMPERATURE,
        "simulation_random_seed": COMMENT_VISIBILITY_SEED,
        "input_sha256": {
            name: _sha256_file(path)
            for name, path in normalized_inputs.items()
        },
        "core_code_sha256": code_hashes,
        "core_code_fingerprint": _canonical_sha256(code_hashes),
        "prompt_template_sha256": code_hashes["agents/decision_engine.py"],
        "agent_ids": sorted(profiles),
        "agent_count": len(profiles),
        "persona_profile_sha256": {
            agent_id: _canonical_sha256(profile)
            for agent_id, profile in sorted(profiles.items())
        },
        "persona_set_fingerprint": _canonical_sha256(profiles),
        "contains_secret": False,
    }
    output_file = experiment_dir / "run_manifest.json"
    save_json(output_file, manifest)
    return manifest
