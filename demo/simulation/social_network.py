"""固定社交网络及Agent影响力权重。

本模块只负责构建、校验和查询不可变网络快照，不执行评论传播、
Agent决策或文件存储。
"""

import hashlib
import math
import random


# 2026/9/5，社交网络传播，新增功能：根据粉丝规模和认证状态计算可解释的相对影响力权重。
def calculate_influence_weights(personas, verified_bonus=0.2):
    """计算Agent相对影响力，返回以agent_id为键的权重字典。"""
    follower_logs = {}
    verified_agents = set()
    for persona in personas:
        agent_id = str(persona.get("agent_id", "")).strip()
        if not agent_id:
            raise ValueError("Persona 缺少 agent_id。")
        identity = persona.get("identity", {})
        followers = identity.get("followers_count", 0)
        if isinstance(followers, bool) or not isinstance(followers, (int, float)):
            followers = 0
        follower_logs[agent_id] = math.log1p(max(0, followers))
        if identity.get("verified") is True:
            verified_agents.add(agent_id)

    max_log = max(follower_logs.values(), default=0.0)
    weights = {}
    for agent_id, follower_log in follower_logs.items():
        follower_weight = follower_log / max_log if max_log else 0.0
        weight = 1.0 + follower_weight
        if agent_id in verified_agents:
            weight += verified_bonus
        weights[agent_id] = round(weight, 3)
    return weights


# 2026/9/5，社交网络传播，新增功能：使用固定种子为本批次Agent建立可复现的有向关注网络。
def build_fixed_social_network(personas, config):
    """构建固定社交网络；边表示source Agent能够看到target Agent的表达。"""
    if not isinstance(personas, list) or not personas:
        raise ValueError("personas 必须是非空列表。")
    if not isinstance(config, dict):
        raise ValueError("社交网络配置必须是JSON对象。")

    agent_ids = sorted(
        str(persona.get("agent_id", "")).strip() for persona in personas
    )
    if any(not agent_id for agent_id in agent_ids):
        raise ValueError("Persona 缺少 agent_id。")
    if len(agent_ids) != len(set(agent_ids)):
        raise ValueError("Persona 中存在重复的 agent_id。")

    seed = config.get("network_seed", 2026)
    neighbors_per_agent = config.get("neighbors_per_agent", 5)
    neighbor_comment_count = config.get("neighbor_comment_count", 0)
    public_comment_count = config.get("public_comment_count", 0)
    verified_bonus = config.get("verified_bonus", 0.2)
    propagation_decay_factor = config.get("propagation_decay_factor", 0.7)
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ValueError("network_seed 必须是整数。")
    if (
        isinstance(neighbors_per_agent, bool)
        or not isinstance(neighbors_per_agent, int)
        or neighbors_per_agent < 0
    ):
        raise ValueError("neighbors_per_agent 必须是非负整数。")
    if (
        isinstance(verified_bonus, bool)
        or not isinstance(verified_bonus, (int, float))
        or verified_bonus < 0
    ):
        raise ValueError("verified_bonus 必须是非负数。")
    if (
        isinstance(propagation_decay_factor, bool)
        or not isinstance(propagation_decay_factor, (int, float))
        or not 0 < propagation_decay_factor <= 1
    ):
        raise ValueError("propagation_decay_factor 必须是0到1之间的数值。")
    for field_name, value in (
        ("neighbor_comment_count", neighbor_comment_count),
        ("public_comment_count", public_comment_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{field_name} 必须是非负整数。")

    influence_weights = calculate_influence_weights(personas, verified_bonus)
    edges = []
    neighbor_count = min(neighbors_per_agent, max(0, len(agent_ids) - 1))
    for source_agent_id in agent_ids:
        candidates = [item for item in agent_ids if item != source_agent_id]
        seed_text = f"{seed}:{source_agent_id}"
        seed_number = int(
            hashlib.sha256(seed_text.encode("utf-8")).hexdigest(), 16
        )
        selected = random.Random(seed_number).sample(candidates, neighbor_count)
        edges.extend(
            {
                "source_agent_id": source_agent_id,
                "target_agent_id": target_agent_id,
            }
            for target_agent_id in sorted(selected)
        )

    snapshot = {
        "network_version": 1,
        "network_seed": seed,
        "neighbors_per_agent": neighbor_count,
        # 2026/9/5，社交网络传播第二阶段A，新增功能：将传播衰减参数固化到网络快照。
        "propagation_decay_factor": float(propagation_decay_factor),
        "visibility": {
            "neighbor_comment_count": neighbor_comment_count,
            "public_comment_count": public_comment_count,
        },
        "nodes": [
            {
                "agent_id": agent_id,
                "influence_weight": influence_weights[agent_id],
            }
            for agent_id in agent_ids
        ],
        "edges": edges,
    }
    return validate_social_network(snapshot, agent_ids)


# 2026/9/5，社交网络传播，新增功能：集中校验网络节点、影响力权重和关注边。
def validate_social_network(snapshot, expected_agent_ids=None):
    """校验网络快照并返回不共享内部引用的规范化结果。"""
    if not isinstance(snapshot, dict):
        raise ValueError("社交网络快照必须是JSON对象。")
    nodes = snapshot.get("nodes")
    edges = snapshot.get("edges")
    if not isinstance(nodes, list) or not nodes:
        raise ValueError("社交网络快照必须包含非空nodes数组。")
    if not isinstance(edges, list):
        raise ValueError("社交网络快照必须包含edges数组。")

    normalized_nodes = []
    node_ids = set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("网络节点必须是JSON对象。")
        agent_id = str(node.get("agent_id", "")).strip()
        weight = node.get("influence_weight")
        if not agent_id or agent_id in node_ids:
            raise ValueError("网络节点缺少agent_id或存在重复编号。")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, (int, float))
            or weight <= 0
        ):
            raise ValueError(f"Agent {agent_id} 的影响力权重不合法。")
        node_ids.add(agent_id)
        normalized_nodes.append(
            {"agent_id": agent_id, "influence_weight": float(weight)}
        )

    if expected_agent_ids is not None and node_ids != set(expected_agent_ids):
        raise ValueError("社交网络节点与本轮参与决策的Agent不一致。")

    normalized_edges = []
    edge_keys = set()
    for edge in edges:
        if not isinstance(edge, dict):
            raise ValueError("网络边必须是JSON对象。")
        source = str(edge.get("source_agent_id", "")).strip()
        target = str(edge.get("target_agent_id", "")).strip()
        edge_key = (source, target)
        if source not in node_ids or target not in node_ids:
            raise ValueError("网络边引用了不存在的Agent。")
        if source == target:
            raise ValueError("社交网络不允许Agent关注自己。")
        if edge_key in edge_keys:
            raise ValueError("社交网络中存在重复关注边。")
        edge_keys.add(edge_key)
        normalized_edges.append(
            {"source_agent_id": source, "target_agent_id": target}
        )

    visibility = snapshot.get("visibility", {})
    if not isinstance(visibility, dict):
        raise ValueError("社交网络快照的visibility必须是JSON对象。")
    neighbor_comment_count = visibility.get("neighbor_comment_count", 0)
    public_comment_count = visibility.get("public_comment_count", 0)
    for field_name, value in (
        ("neighbor_comment_count", neighbor_comment_count),
        ("public_comment_count", public_comment_count),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"网络快照中的{field_name}不合法。")

    # 2026/9/5，社交网络传播第二阶段A，新增功能：兼容旧快照并校验传播衰减系数。
    propagation_decay_factor = snapshot.get("propagation_decay_factor", 1.0)
    if (
        isinstance(propagation_decay_factor, bool)
        or not isinstance(propagation_decay_factor, (int, float))
        or not 0 < propagation_decay_factor <= 1
    ):
        raise ValueError("网络快照中的propagation_decay_factor不合法。")

    return {
        "network_version": snapshot.get("network_version", 1),
        "network_seed": snapshot.get("network_seed", 2026),
        "neighbors_per_agent": snapshot.get("neighbors_per_agent", 0),
        "propagation_decay_factor": float(propagation_decay_factor),
        "visibility": {
            "neighbor_comment_count": neighbor_comment_count,
            "public_comment_count": public_comment_count,
        },
        "nodes": normalized_nodes,
        "edges": normalized_edges,
    }


# 2026/9/5，社交网络传播，新增功能：查询一个Agent能够接收表达的固定邻居。
def get_followed_agent_ids(snapshot, agent_id):
    """返回当前Agent关注的邻居编号。"""
    return [
        edge["target_agent_id"]
        for edge in snapshot["edges"]
        if edge["source_agent_id"] == agent_id
    ]


# 2026/9/5，社交网络传播，新增功能：查询邻居评论传播使用的影响力权重。
def get_influence_weight(snapshot, agent_id):
    """返回指定Agent的影响力权重，未知Agent使用普通权重1.0。"""
    for node in snapshot["nodes"]:
        if node["agent_id"] == agent_id:
            return node["influence_weight"]
    return 1.0


# 2026/9/5，社交网络传播第二阶段A，新增功能：统一读取网络快照中的传播衰减系数。
def get_propagation_decay_factor(snapshot):
    """返回传播衰减系数，旧网络快照保持不衰减以兼容历史数据。"""
    return float(snapshot.get("propagation_decay_factor", 1.0))
