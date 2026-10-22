// 两类实验共用的网络视图；趋势比较留在各自的业务页面。
const palette = {
  navy: "#0d2948",
  blue: "#276ed8",
  teal: "#12a395",
  orange: "#f28a2a",
  red: "#dc5265",
  gray: "#aab7c5",
  positive: "#22c7a5",
  neutral: "#5b8def",
  negative: "#ff6178",
  unknown: "#8193a8"
};

const state = {
  experimentId: null,
  report: null,
  network: null,
  comments: null,
  cascade: null,
  scenarioId: null,
  step: 1,
  maxStep: 1,
  playTimer: null,
  selectedFollowAgentId: null,
  selectedAgentId: null,
  // 2026/10/9，新增功能：默认只突出当前轮新增传播，用户可切换累计视图。
  flowMode: "round"
};

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function percent(value, digits = 1) {
  if (value === null || value === undefined) return "—";
  return `${(Number(value) * 100).toFixed(digits)}%`;
}

function officialStatusLabel(status) {
  return ({ clear: "信息清晰", incomplete: "信息不完整", conflict: "信息存在冲突" })[status] || status || "未记录";
}

function hideNetworkOfficialDetails() {
  const panel = document.getElementById("network-official-details");
  panel.classList.add("hidden");
  panel.innerHTML = "";
}

function showNetworkOfficialDetails(announcements) {
  const items = Array.isArray(announcements) ? announcements : [announcements];
  const first = items[0] || {};
  const panel = document.getElementById("network-official-details");
  panel.innerHTML = `
    <div>
      <p class="official-detail-kicker">官方公告详情</p>
      <h3>${escapeHtml(first.strategy_name || state.network?.scenario_name || "未命名策略")} · 第${escapeHtml(first.step)}轮</h3>
    </div>
    <span class="official-detail-status">${items.length}项公告</span>
    <div class="network-official-list">${items.map(item => `
      <article>
        <div><strong>${escapeHtml(item.strategy_name || state.network?.scenario_name || "未命名策略")}</strong>
          <span>${escapeHtml(officialStatusLabel(item.official_statement_status))}</span></div>
        <p>${escapeHtml(item.official_statement || "未记录公告内容")}</p>
      </article>`).join("")}</div>`;
  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function shortAgent(agentId) {
  const value = String(agentId || "");
  return value.startsWith("agent_") ? `A·${value.slice(-4)}` : value;
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `请求失败：${response.status}`);
  }
  return data;
}

function showError(error) {
  const notice = document.getElementById("notice");
  notice.textContent = error.message;
  notice.classList.remove("hidden");
}

function hideError() {
  document.getElementById("notice").classList.add("hidden");
}

function metricItems(targetId, items) {
  document.getElementById(targetId).innerHTML = items.map(item => `
    <div class="metric-item">
      <strong>${escapeHtml(item[0])}</strong>
      <span>${escapeHtml(item[1])}</span>
    </div>
  `).join("");
}

function renderSummary() {
  const report = state.report;
  const network = report.network;
  const propagation = report.overall_propagation;
  const quality = report.overall_quality;
  const performance = report.performance || {};
  document.getElementById("experiment-id").textContent = report.experiment_id;
  document.getElementById("mode-eyebrow").textContent =
    `${report.mode_label} · SOCIAL PROPAGATION · READ ONLY`;
  document.getElementById("acceptance-status").textContent =
    report.status === "completed" ? "通过" : report.status;
  document.getElementById("network-snapshot-note").textContent =
    report.mode === "historical_replay" ? "历史路线固定网络" : "回应方案共享同一快照";
  document.getElementById("findings-title").textContent =
    `${report.mode_label}传播数据闭环`;
  const businessLink = document.getElementById("business-link");
  const businessPath = report.mode === "historical_replay" ? "/historical/" : "/strategy/";
  businessLink.textContent = report.mode === "historical_replay" ? "趋势复现" : "回应方案对比";
  businessLink.href = `${businessPath}?experiment_id=${encodeURIComponent(report.experiment_id)}`;

  const duration = Number(performance.total_duration_seconds || 0);
  const cards = [
    ["实验状态", report.status === "completed" ? "已完成" : report.status, report.mode_label],
    ["社交网络", `${network.node_count} 节点`, `${network.edge_count}条有向边 · 每人关注${network.neighbors_per_agent}人`],
    ["邻居曝光", propagation.exposure_count, `${report.scenarios.length}个场景累计`],
    ["继续传播", propagation.continued_propagation_count, `总体继续传播率 ${percent(propagation.continuation_rate)}`],
    ["最大深度", `${propagation.max_propagation_depth} 层`, `逐层衰减系数 ${network.propagation_decay_factor}`],
    ["运行与质量", duration ? `${(duration / 60).toFixed(1)} 分钟` : quality.quality_status, `兜底率 ${percent(quality.fallback_rate)}`]
  ];
  document.getElementById("summary-cards").innerHTML = cards.map(item => `
    <article class="summary-card">
      <div class="card-label">${escapeHtml(item[0])}</div>
      <div class="card-value">${escapeHtml(item[1])}</div>
      <div class="card-note">${escapeHtml(item[2])}</div>
    </article>
  `).join("");

  document.getElementById("findings").innerHTML = report.findings
    .map(item => `<li>${escapeHtml(item)}</li>`).join("");
  document.getElementById("limitations").innerHTML = report.limitations
    .map(item => `<li>${escapeHtml(item)}</li>`).join("");
}

function renderModeComparison() {
  const historical = state.report.mode === "historical_replay";
  const rows = historical ? state.report.rounds : state.report.scenarios;
  document.getElementById("comparison-tag").textContent = historical ? "阶段对照" : "策略对照";
  document.getElementById("comparison-title").textContent = historical
    ? "历史时间线中的阶段传播变化"
    : "同一张社交网络中的传播差异";
  document.getElementById("comparison-note").textContent = historical
    ? "单路线逐阶段展示，不解释为策略因果效果"
    : "五个场景共享网络快照，进入各自场景后传播轨迹独立演化";
  const normalized = rows.map(item => ({
    label: historical ? `第${item.step}轮 · ${item.phase || item.period || "阶段"}` : item.scenario_name,
    period: historical ? (item.period || "—") : "—",
    propagation: item.propagation || {},
    quality: historical ? state.report.overall_quality : (item.quality || {})
  }));
  const maxRate = Math.max(...normalized.map(item => Number(item.propagation.continuation_rate || 0)), 0.01);
  const tableHeader = historical
    ? "<tr><th>阶段</th><th>现实时间段</th><th>曝光次数</th><th>继续传播</th><th>继续传播率</th><th>覆盖Agent</th><th>最大深度</th></tr>"
    : "<tr><th>场景</th><th>曝光次数</th><th>继续传播</th><th>继续传播率</th><th>最大深度</th><th>平均深度</th><th>数据质量</th></tr>";
  const tableRows = normalized.map(item => {
    const p = item.propagation;
    if (historical) {
      return `<tr><td><strong>${escapeHtml(item.label)}</strong></td><td>${escapeHtml(item.period)}</td>
        <td>${p.exposure_count ?? 0}</td><td>${p.continued_propagation_count ?? 0}</td>
        <td>${percent(p.continuation_rate)}</td><td>${p.reached_agent_count ?? 0}</td><td>${p.max_propagation_depth ?? 0}</td></tr>`;
    }
    const status = item.quality.quality_status || "—";
    return `<tr><td><strong>${escapeHtml(item.label)}</strong></td><td>${p.exposure_count ?? 0}</td>
      <td>${p.continued_propagation_count ?? 0}</td><td>${percent(p.continuation_rate)}</td>
      <td>${p.max_propagation_depth ?? 0}</td><td>${Number(p.average_propagation_depth || 0).toFixed(3)}</td>
      <td><span class="quality-badge ${status === "normal" ? "normal" : ""}">${escapeHtml(status)}</span></td></tr>`;
  }).join("");
  document.getElementById("comparison-grid").innerHTML = `
    <div><p class="heading-note">继续传播率</p>${normalized.map(item => {
      const rate = Number(item.propagation.continuation_rate || 0);
      return `<div class="bar-row"><span>${escapeHtml(item.label)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, rate / maxRate * 100)}%"></div></div>
        <strong>${percent(rate)}</strong></div>`;
    }).join("")}</div>
    <div class="table-wrap"><table><thead>${tableHeader}</thead><tbody>${tableRows}</tbody></table></div>`;
}

function networkPositions(nodes, width, height) {
  const centerX = width / 2;
  const centerY = height * .51;
  const positions = {};

  // 2026/10/9，修改功能：30个Agent采用“核心层+外围层”的确定性双环布局。
  // 高影响力节点进入内环，既保留固定位置便于逐轮比较，也避免单环节点和连线拥挤。
  const sortedNodes = [...nodes].sort((left, right) =>
    Number(right.influence_weight || 0) - Number(left.influence_weight || 0)
      || String(left.agent_id).localeCompare(String(right.agent_id))
  );
  const innerCount = sortedNodes.length <= 14
    ? sortedNodes.length
    : Math.min(10, Math.max(7, Math.round(sortedNodes.length * .32)));
  const rings = sortedNodes.length <= 14
    ? [{ nodes: sortedNodes, radiusX: width * .35, radiusY: height * .34, offset: 0 }]
    : [
        { nodes: sortedNodes.slice(0, innerCount), radiusX: width * .22, radiusY: height * .24, offset: .06 },
        { nodes: sortedNodes.slice(innerCount), radiusX: width * .43, radiusY: height * .41, offset: 0 }
      ];
  rings.forEach(ring => ring.nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + ring.offset + index / ring.nodes.length * Math.PI * 2;
    positions[node.agent_id] = {
      x: centerX + Math.cos(angle) * ring.radiusX,
      y: centerY + Math.sin(angle) * ring.radiusY
    };
  }));
  return positions;
}

function emotionColor(emotion) {
  return palette[emotion] || palette.unknown;
}

function emotionLabel(emotion) {
  return { positive: "积极", neutral: "中性", negative: "负面" }[emotion] || "未记录";
}

function curvedEdgePath(source, target, sourceRadius, targetRadius) {
  const dx = target.x - source.x;
  const dy = target.y - source.y;
  const distance = Math.max(Math.hypot(dx, dy), 1);
  const ux = dx / distance;
  const uy = dy / distance;
  const startX = source.x + ux * (sourceRadius + 3);
  const startY = source.y + uy * (sourceRadius + 3);
  const endX = target.x - ux * (targetRadius + 10);
  const endY = target.y - uy * (targetRadius + 10);
  const curve = Math.min(27, distance * 0.1);
  const controlX = (startX + endX) / 2 - uy * curve;
  const controlY = (startY + endY) / 2 + ux * curve;
  return `M ${startX} ${startY} Q ${controlX} ${controlY} ${endX} ${endY}`;
}

function nodeRadius(node, minWeight, maxWeight) {
  const range = Math.max(maxWeight - minWeight, 0.001);
  return 24 + (Number(node.influence_weight) - minWeight) / range * 10;
}

// 2026/09/06 关注关系可视化，新增功能：构建立体投影坐标并按“关注者→被关注者”绘制关系。
function followNetworkPositions(nodes, width, height) {
  const centerX = width / 2;
  const centerY = height * .52;
  const positions = {};
  // 2026/10/9，修改功能：固定关注图与传播图使用同一类双环空间语言，
  // 但坐标分别计算，避免30节点挤在单一椭圆边缘。
  const sortedNodes = [...nodes].sort((left, right) =>
    Number(right.influence_weight || 0) - Number(left.influence_weight || 0)
      || String(left.agent_id).localeCompare(String(right.agent_id))
  );
  const innerCount = sortedNodes.length <= 14
    ? sortedNodes.length
    : Math.min(10, Math.max(7, Math.round(sortedNodes.length * .32)));
  const rings = sortedNodes.length <= 14
    ? [{ nodes: sortedNodes, radiusX: width * .36, radiusY: height * .34, offset: 0 }]
    : [
        { nodes: sortedNodes.slice(0, innerCount), radiusX: width * .22, radiusY: height * .24, offset: .06 },
        { nodes: sortedNodes.slice(innerCount), radiusX: width * .43, radiusY: height * .41, offset: 0 }
      ];
  rings.forEach(ring => ring.nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + ring.offset + index / ring.nodes.length * Math.PI * 2;
    positions[node.agent_id] = {
      x: centerX + Math.cos(angle) * ring.radiusX,
      y: centerY + Math.sin(angle) * ring.radiusY,
      depth: (Math.sin(angle) + 1) / 2
    };
  }));
  return positions;
}

function renderFollowNodeDetails(agentId) {
  const data = state.network;
  const node = data.nodes.find(item => item.agent_id === agentId);
  if (!node) return;
  const following = data.edges
    .filter(edge => edge.follower_agent_id === agentId)
    .map(edge => edge.followed_agent_id);
  const followers = data.edges
    .filter(edge => edge.followed_agent_id === agentId)
    .map(edge => edge.follower_agent_id);
  document.getElementById("follow-node-details").innerHTML = `
    <p class="side-kicker">RELATION FOCUS</p>
    <h3>${escapeHtml(agentId)}</h3>
    <div class="node-metric"><span>影响力权重</span><strong>${Number(node.influence_weight).toFixed(3)}</strong></div>
    <div class="relation-counts">
      <div class="relation-count"><strong>${following.length}</strong><span>关注人数</span></div>
      <div class="relation-count"><strong>${followers.length}</strong><span>粉丝人数</span></div>
    </div>
    <div class="relation-list"><h4>该Agent关注</h4><p>${following.map(shortAgent).join(" · ") || "无"}</p></div>
    <div class="relation-list"><h4>关注该Agent</h4><p>${followers.map(shortAgent).join(" · ") || "无"}</p></div>
    <p>青色箭头从该Agent发出，橙色箭头指向该Agent；再次点击可取消聚焦。</p>`;
}

function renderFollowNetwork() {
  const data = state.network;
  if (!data) return;
  const width = 1360;
  const height = 820;
  const selected = state.selectedFollowAgentId;
  const positions = followNetworkPositions(data.nodes, width, height);
  const weights = data.nodes.map(item => Number(item.influence_weight));
  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);
  const radii = Object.fromEntries(data.nodes.map(node => [
    node.agent_id,
    21 + (nodeRadius(node, minWeight, maxWeight) - 24) * .75
  ]));

  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="关注者指向被关注者的固定社交网络">
    <defs>
      <radialGradient id="follow-orb" cx="32%" cy="25%" r="72%"><stop offset="0" stop-color="#f7ffff"/><stop offset=".18" stop-color="#6ed8ff"/><stop offset=".62" stop-color="#287ee1"/><stop offset="1" stop-color="#123c8c"/></radialGradient>
      <radialGradient id="follow-orb-selected" cx="32%" cy="25%" r="72%"><stop offset="0" stop-color="#fffdf2"/><stop offset=".2" stop-color="#ffd07b"/><stop offset=".66" stop-color="#f58d2a"/><stop offset="1" stop-color="#a84418"/></radialGradient>
      <linearGradient id="follow-deck" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#1b8fa8" stop-opacity=".22"/><stop offset="1" stop-color="#0a2949" stop-opacity=".03"/></linearGradient>
      <filter id="follow-node-glow" x="-70%" y="-70%" width="240%" height="260%"><feDropShadow dx="0" dy="10" stdDeviation="8" flood-color="#020a18" flood-opacity=".7"/><feDropShadow dx="0" dy="0" stdDeviation="6" flood-color="#42dcea" flood-opacity=".45"/></filter>
      <filter id="follow-line-glow" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="2" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      <marker id="follow-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#69e9e0"/></marker>
      <marker id="follow-arrow-out" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#58e9da"/></marker>
      <marker id="follow-arrow-in" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#ffad5c"/></marker>
    </defs>
    <ellipse cx="${width / 2}" cy="${height * .53 + 50}" rx="${width * .46}" ry="${height * .43}" fill="url(#follow-deck)" stroke="#5bd9e0" stroke-opacity=".2"/>
    <ellipse class="follow-scan-ring" cx="${width / 2}" cy="${height * .53 + 50}" rx="${width * .33}" ry="${height * .31}" fill="none" stroke="#65f2e1" stroke-width="1.5" stroke-opacity=".24" stroke-dasharray="12 10"/>
    <text x="${width / 2}" y="${height * .505}" text-anchor="middle" fill="#72e9e0" font-size="13" letter-spacing="4">FOLLOW GRAPH</text>
    <text x="${width / 2}" y="${height * .505 + 27}" text-anchor="middle" fill="#8caec4" font-size="12">${data.nodes.length} AGENTS · ${data.edges.length} DIRECTED EDGES</text>`;

  data.edges.forEach(edge => {
    const follower = edge.follower_agent_id;
    const followed = edge.followed_agent_id;
    const source = positions[follower];
    const target = positions[followed];
    if (!source || !target) return;
    const incident = !selected || follower === selected || followed === selected;
    const outgoing = selected && follower === selected;
    const incoming = selected && followed === selected;
    const color = outgoing ? "#58e9da" : incoming ? "#ffad5c" : "#69bcd6";
    const marker = outgoing ? "follow-arrow-out" : incoming ? "follow-arrow-in" : "follow-arrow";
    const opacity = selected ? (incident ? .9 : .045) : .22;
    const strokeWidth = selected && incident ? 2.7 : 1.15;
    svg += `<path class="follow-edge" d="${curvedEdgePath(source, target, radii[follower], radii[followed])}"
      fill="none" stroke="${color}" stroke-width="${strokeWidth}" opacity="${opacity}"
      marker-end="url(#${marker})" ${selected && incident ? 'filter="url(#follow-line-glow)"' : ""}>
      <title>${escapeHtml(follower)} 关注 ${escapeHtml(followed)}</title>
    </path>`;
  });

  [...data.nodes].sort((a, b) => positions[a.agent_id].y - positions[b.agent_id].y).forEach(node => {
    const position = positions[node.agent_id];
    const radius = radii[node.agent_id];
    const related = !selected || node.agent_id === selected || data.edges.some(edge =>
      (edge.follower_agent_id === selected && edge.followed_agent_id === node.agent_id) ||
      (edge.followed_agent_id === selected && edge.follower_agent_id === node.agent_id)
    );
    const selectedNode = node.agent_id === selected;
    const baseY = position.y + 44 + position.depth * 10;
    svg += `<g class="follow-node ${related ? "" : "is-muted"}" data-agent-id="${escapeHtml(node.agent_id)}" tabindex="0">
      <line x1="${position.x}" y1="${position.y + radius * .7}" x2="${position.x}" y2="${baseY}" stroke="#60dce3" stroke-width="2" opacity="${selectedNode ? .75 : .2}"/>
      <ellipse cx="${position.x}" cy="${baseY}" rx="${radius * .85}" ry="${radius * .24}" fill="#58e6e1" opacity="${selectedNode ? .34 : .1}"/>
      <circle cx="${position.x}" cy="${position.y}" r="${radius + 8}" fill="none" stroke="${selectedNode ? "#ffbc68" : "#63f5e2"}" stroke-width="2" opacity="${selectedNode ? .85 : .17}"/>
      <circle class="follow-orb" cx="${position.x}" cy="${position.y}" r="${radius}" fill="url(#${selectedNode ? "follow-orb-selected" : "follow-orb"})" filter="url(#follow-node-glow)"/>
      <circle cx="${position.x - radius * .28}" cy="${position.y - radius * .3}" r="${radius * .16}" fill="white" opacity=".72"/>
      <text x="${position.x}" y="${position.y + 4}" text-anchor="middle" fill="white" font-size="11" font-weight="750">${escapeHtml(shortAgent(node.agent_id))}</text>
      <text x="${position.x}" y="${baseY + 20}" text-anchor="middle" fill="#b9d5e7" font-size="10">W ${Number(node.influence_weight).toFixed(3)}</text>
      <title>${escapeHtml(node.agent_id)}\n影响力 ${Number(node.influence_weight).toFixed(3)}\n点击查看关注关系</title>
    </g>`;
  });
  svg += "</svg>";

  const container = document.getElementById("follow-network-chart");
  container.innerHTML = svg;
  container.querySelectorAll(".follow-node").forEach(element => {
    const activate = () => {
      const agentId = element.dataset.agentId;
      state.selectedFollowAgentId = state.selectedFollowAgentId === agentId ? null : agentId;
      renderFollowNetwork();
      if (state.selectedFollowAgentId) {
        renderFollowNodeDetails(state.selectedFollowAgentId);
      } else {
        document.getElementById("follow-node-details").innerHTML = `
          <p class="side-kicker">RELATION VIEW</p><h3>点击任意Agent</h3>
          <p>查看该Agent关注了谁、被谁关注，以及它在固定网络中的影响力。</p>`;
      }
    };
    element.addEventListener("click", activate);
    element.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") activate();
    });
  });
}

function renderNodeDetails(node) {
  const roundActivity = Number(node.round_sent_exposure_count || 0)
    + Number(node.round_received_exposure_count || 0);
  document.getElementById("node-details").innerHTML = `
    <p class="side-kicker">AGENT NODE</p>
    <h3>${escapeHtml(node.agent_id)}</h3>
    <div class="agent-state-line">
      <span class="emotion-chip ${escapeHtml(node.current_emotion || "unknown")}">${emotionLabel(node.current_emotion)}</span>
      <span>${escapeHtml(node.official_attitude || "未记录官方态度")}</span>
    </div>
    <div class="node-metric"><span>影响力权重</span><strong>${Number(node.influence_weight).toFixed(3)}</strong></div>
    <div class="node-metric"><span>本轮发出 / 接收曝光</span><strong>${node.round_sent_exposure_count || 0} / ${node.round_received_exposure_count || 0}</strong></div>
    <div class="node-metric"><span>本轮继续表达</span><strong>${node.round_continued_count || 0}</strong></div>
    <div class="node-metric"><span>累计发出 / 接收曝光</span><strong>${node.sent_exposure_count || 0} / ${node.received_exposure_count || 0}</strong></div>
    <div class="node-metric"><span>本轮是否评论</span><strong>${node.will_comment ? "是" : "否"}</strong></div>
    <p>${roundActivity ? "该Agent参与了本轮网络传播。" : "该Agent本轮没有产生邻居传播事件。"} 再次点击可取消聚焦。</p>`;
}

function renderNetwork() {
  const data = state.network;
  const width = 1380;
  const height = 850;
  const positions = networkPositions(data.nodes, width, height);
  const weights = data.nodes.map(item => Number(item.influence_weight));
  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);
  const radii = Object.fromEntries(data.nodes.map(node => [
    node.agent_id, 22 + (nodeRadius(node, minWeight, maxWeight) - 24) * .72
  ]));
  const roundMode = state.flowMode === "round";
  const selectedAgentId = state.selectedAgentId;
  const relatedAgentIds = new Set([selectedAgentId]);
  if (selectedAgentId) {
    data.edges.forEach(edge => {
      if (edge.source_agent_id === selectedAgentId) relatedAgentIds.add(edge.target_agent_id);
      if (edge.target_agent_id === selectedAgentId) relatedAgentIds.add(edge.source_agent_id);
    });
  }

  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(data.scenario_name)}第${data.step}轮社交网络信息流">
    <defs>
      <radialGradient id="network-deck" cx="50%" cy="48%" r="60%"><stop offset="0" stop-color="#133e63" stop-opacity=".4"/><stop offset="1" stop-color="#061526" stop-opacity="0"/></radialGradient>
      <marker id="arrow-gray" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="#607a94"/></marker>
      <marker id="arrow-teal" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#27d9c0"/></marker>
      <marker id="arrow-orange" markerWidth="9" markerHeight="9" refX="8" refY="3" orient="auto"><path d="M0,0 L0,6 L8,3 z" fill="#ffad55"/></marker>
      <filter id="node-shadow" x="-70%" y="-70%" width="240%" height="240%"><feDropShadow dx="0" dy="9" stdDeviation="7" flood-color="#020815" flood-opacity=".7"/></filter>
      <filter id="active-node-glow" x="-90%" y="-90%" width="280%" height="280%"><feGaussianBlur stdDeviation="5" result="blur"/><feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <ellipse cx="${width / 2}" cy="${height * .53}" rx="${width * .47}" ry="${height * .45}" fill="url(#network-deck)" stroke="#2a7194" stroke-opacity=".28"/>
    <ellipse class="network-scan-ring" cx="${width / 2}" cy="${height * .53}" rx="${width * .335}" ry="${height * .32}" fill="none" stroke="#2bd2c0" stroke-width="1.2" stroke-opacity=".19" stroke-dasharray="9 14"/>`;

  data.edges.forEach(edge => {
    const source = positions[edge.source_agent_id];
    const target = positions[edge.target_agent_id];
    if (!source || !target) return;
    const exposureCount = Number(roundMode ? edge.round_exposure_count : edge.exposure_count) || 0;
    const continuedCount = Number(roundMode ? edge.round_selected_exposure_count : edge.selected_exposure_count) || 0;
    const maxDepth = Number(roundMode ? edge.round_max_depth : edge.max_depth) || 0;
    const active = exposureCount > 0;
    const continued = continuedCount > 0;
    const related = !selectedAgentId
      || edge.source_agent_id === selectedAgentId
      || edge.target_agent_id === selectedAgentId;
    const color = continued ? "#ffad55" : active ? "#27d9c0" : "#607a94";
    const marker = continued ? "arrow-orange" : active ? "arrow-teal" : "arrow-gray";
    const widthValue = active ? Math.min(5.2, 1.5 + Math.log1p(exposureCount) * .9) : .8;
    const opacity = !related ? .025 : active ? .86 : roundMode ? .035 : .1;
    svg += `<path class="flow-edge ${active ? "is-active" : ""} ${continued ? "is-continued" : ""}" d="${curvedEdgePath(source, target, radii[edge.source_agent_id], radii[edge.target_agent_id])}"
      fill="none" stroke="${color}" stroke-width="${widthValue}" opacity="${opacity}"
      marker-end="url(#${marker})" ${active ? 'stroke-dasharray="8 9"' : 'stroke-dasharray="3 10"'}>
      <title>${escapeHtml(edge.source_agent_id)} → ${escapeHtml(edge.target_agent_id)}\n${roundMode ? "本轮" : "累计"}曝光${exposureCount}次，继续表达${continuedCount}次，最大深度${maxDepth}</title>
    </path>`;
  });

  const distribution = data.emotion_distribution || {};
  const centerY = height * .51;
  svg += `<circle cx="${width / 2}" cy="${centerY}" r="105" fill="#071b2e" stroke="#326d8c" stroke-width="1.5"/>
    <circle cx="${width / 2}" cy="${centerY}" r="94" fill="none" stroke="#2ad4bf" stroke-opacity=".18" stroke-dasharray="4 8"/>
    <text x="${width / 2}" y="${centerY - 38}" text-anchor="middle" fill="#6be8db" font-size="11" letter-spacing="3">ROUND ${data.step}</text>
    <text x="${width / 2}" y="${centerY - 8}" text-anchor="middle" fill="#effaff" font-size="18" font-weight="750">${escapeHtml(data.phase || data.scenario_name)}</text>
    <text x="${width / 2}" y="${centerY + 17}" text-anchor="middle" fill="#8fb2c7" font-size="11">${escapeHtml(data.period || (roundMode ? "当前轮新增信息流" : "截至当前轮累计信息流"))}</text>
    <text x="${width / 2}" y="${centerY + 46}" text-anchor="middle" fill="#dcebf4" font-size="12">${roundMode ? data.round_event_count : data.event_count} 次曝光 · ${data.commenting_agent_count || 0} 人评论</text>
    <g transform="translate(${width / 2 - 61} ${centerY + 66})">
      <circle cx="0" cy="0" r="4" fill="${palette.positive}"/><text x="9" y="4" fill="#9fb9ca" font-size="10">${distribution.positive?.count || 0}</text>
      <circle cx="53" cy="0" r="4" fill="${palette.neutral}"/><text x="62" y="4" fill="#9fb9ca" font-size="10">${distribution.neutral?.count || 0}</text>
      <circle cx="106" cy="0" r="4" fill="${palette.negative}"/><text x="115" y="4" fill="#9fb9ca" font-size="10">${distribution.negative?.count || 0}</text>
    </g>`;

  data.nodes.forEach(node => {
    const position = positions[node.agent_id];
    const radius = radii[node.agent_id];
    const roundActivity = Number(node.round_sent_exposure_count || 0) + Number(node.round_received_exposure_count || 0);
    const cumulativeActivity = Number(node.sent_exposure_count || 0) + Number(node.received_exposure_count || 0);
    const activity = roundMode ? roundActivity : cumulativeActivity;
    const selectedNode = node.agent_id === selectedAgentId;
    const related = !selectedAgentId || relatedAgentIds.has(node.agent_id);
    const fill = emotionColor(node.current_emotion);
    const ringColor = node.official_attitude === "accept" ? palette.teal
      : node.official_attitude === "wait" ? palette.orange
      : node.official_attitude === "question" ? palette.red : "#7690a5";
    svg += `<g class="network-node ${related ? "" : "is-muted"}" data-agent-id="${escapeHtml(node.agent_id)}" tabindex="0">
      ${node.will_comment ? `<circle class="activity-pulse" cx="${position.x}" cy="${position.y}" r="${radius + 11}" fill="none" stroke="${fill}" stroke-width="2" opacity=".58"/>` : ""}
      <circle cx="${position.x}" cy="${position.y}" r="${radius + 6}" fill="#0b2238" stroke="${selectedNode ? "#ffffff" : ringColor}" stroke-width="${selectedNode ? 3.5 : 2}" opacity="${activity || selectedNode ? 1 : .68}"/>
      <circle cx="${position.x}" cy="${position.y}" r="${radius}" fill="${fill}" stroke="#dff7ff" stroke-opacity=".75" stroke-width="1.5" filter="url(#${activity ? "active-node-glow" : "node-shadow"})" opacity="${activity || selectedNode ? 1 : .78}"/>
      <text x="${position.x}" y="${position.y + 4}" text-anchor="middle" fill="white" font-size="12" font-weight="700">${escapeHtml(shortAgent(node.agent_id))}</text>
      <text x="${position.x}" y="${position.y + radius + 19}" text-anchor="middle" fill="#aac2d2" font-size="10">${emotionLabel(node.current_emotion)} · W ${Number(node.influence_weight).toFixed(3)}</text>
      <title>${escapeHtml(node.agent_id)}\n情绪：${emotionLabel(node.current_emotion)}\n官方态度：${escapeHtml(node.official_attitude || "未记录")}\n本轮发出${node.round_sent_exposure_count || 0}、接收${node.round_received_exposure_count || 0}</title>
    </g>`;
  });
  svg += "</svg>";
  const container = document.getElementById("network-chart");
  container.innerHTML = svg;
  container.querySelectorAll(".network-node").forEach(element => {
    const activate = () => {
      const node = data.nodes.find(item => item.agent_id === element.dataset.agentId);
      if (!node) return;
      state.selectedAgentId = state.selectedAgentId === node.agent_id ? null : node.agent_id;
      if (state.selectedAgentId) {
        renderNodeDetails(node);
      } else {
        resetNodeDetails();
      }
      renderNetwork();
    };
    element.addEventListener("click", activate);
    element.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") activate();
    });
  });

  const scenario = state.report.scenarios.find(item => item.scenario_id === data.scenario_id);
  metricItems("network-stats", [
    [roundMode ? data.round_event_count : data.event_count, roundMode ? "本轮邻居曝光" : "截至当前轮累计曝光"],
    [roundMode ? data.round_active_edge_count : data.active_edge_count, `${roundMode ? "本轮" : "累计"}激活传播边 / 共${data.edges.length}条`],
    [data.commenting_agent_count ?? 0, "本轮表达Agent"],
    [distribution.negative?.count ?? 0, `负面Agent / 共${data.nodes.length}人`],
    [percent(scenario?.propagation.continuation_rate), "完整场景继续传播率"]
  ]);
}

function resetNodeDetails() {
  document.getElementById("node-details").innerHTML = `
    <p class="side-kicker">NODE INSPECTOR</p>
    <h3>点击任意Agent</h3>
    <p>查看其本轮情绪、官方态度和传播活动；再次点击可恢复全图。</p>`;
}

function renderStepTimeline() {
  const container = document.getElementById("step-timeline");
  if (!container) return;
  const historical = state.report.mode === "historical_replay";
  const roundByStep = new Map((state.report.rounds || []).map(item => [Number(item.step), item]));
  const officialResponses = state.network?.official_responses || [];
  const responsesByStep = new Map();
  officialResponses.forEach(response => {
    const step = Number(response.step);
    if (!responsesByStep.has(step)) responsesByStep.set(step, []);
    responsesByStep.get(step).push(response);
  });
  container.innerHTML = Array.from({ length: state.maxStep }, (_, index) => {
    const step = index + 1;
    const round = roundByStep.get(step) || {};
    const label = historical ? (round.phase || `第${step}轮`) : `第${step}轮`;
    const detail = historical ? (round.period || "历史阶段") : "模拟轮次";
    const responses = responsesByStep.get(step) || [];
    const officialMarker = responses.length
      ? `<button type="button" class="timeline-official-marker" data-official-step="${step}" title="查看第${step}轮官方公告">公告${responses.length > 1 ? `×${responses.length}` : ""}</button>`
      : "";
    return `<div class="timeline-item ${responses.length ? "has-official" : ""}">
      <button type="button" class="timeline-step ${step === state.step ? "is-active" : ""}" data-step="${step}" title="${escapeHtml(detail)}">
        <span>${String(step).padStart(2, "0")}</span><strong>${escapeHtml(label)}</strong>
      </button>${officialMarker}
    </div>`;
  }).join("");
  container.querySelectorAll(".timeline-step").forEach(button => {
    button.addEventListener("click", () => {
      stopPlayback();
      hideNetworkOfficialDetails();
      state.step = Number(button.dataset.step);
      state.selectedAgentId = null;
      document.getElementById("step-slider").value = state.step;
      document.getElementById("step-value").textContent = state.step;
      loadNetwork().catch(showError);
    });
  });
  container.querySelectorAll(".timeline-official-marker").forEach(marker => {
    marker.addEventListener("click", () => {
      stopPlayback();
      const step = Number(marker.dataset.officialStep);
      const announcements = responsesByStep.get(step) || [];
      state.step = step;
      state.selectedAgentId = null;
      document.getElementById("step-slider").value = step;
      document.getElementById("step-value").textContent = step;
      loadNetwork()
        .then(() => showNetworkOfficialDetails(announcements))
        .catch(showError);
    });
  });
}

function cascadePositions(nodes) {
  const groups = {};
  nodes.forEach(node => {
    const step = Number(node.step || 0);
    groups[step] = groups[step] || [];
    groups[step].push(node);
  });
  Object.values(groups).forEach(group => group.sort((a, b) => {
    if (a.node_type !== b.node_type) return a.node_type === "expression" ? -1 : 1;
    return String(a.agent_id).localeCompare(String(b.agent_id));
  }));
  const largestGroup = Math.max(...Object.values(groups).map(group => group.length), 1);
  const height = Math.max(400, largestGroup * 62 + 110);
  const width = Math.max(720, 160 + (state.maxStep - 1) * 190);
  const stepX = step => state.maxStep === 1
    ? width / 2
    : 80 + (step - 1) * ((width - 160) / (state.maxStep - 1));
  const positions = {};
  Object.entries(groups).forEach(([stepText, group]) => {
    const step = Number(stepText);
    const spacing = (height - 100) / (group.length + 1);
    group.forEach((node, index) => {
      positions[node.node_id] = { x: stepX(step), y: 62 + spacing * (index + 1) };
    });
  });
  return { positions, height, width, stepX };
}

function renderCascade() {
  const data = state.cascade;
  document.getElementById("comment-text").textContent = `${data.comment_id}｜${data.comment_text}`;
  const summary = data.summary;
  metricItems("cascade-stats", [
    [summary.expression_count, "实际表达节点"],
    [summary.exposure_count, "邻居曝光次数"],
    [summary.continued_count, "继续传播表达"],
    [summary.stopped_count, "看见但未继续"],
    [summary.reached_agent_count, "覆盖Agent"],
    [summary.max_depth, "最大传播深度"]
  ]);

  if (!data.nodes.length) {
    document.getElementById("cascade-chart").innerHTML = "<p class='heading-note' style='padding:24px'>该评论没有可展示的传播节点。</p>";
    return;
  }
  const layout = cascadePositions(data.nodes);
  const width = layout.width;
  const positions = layout.positions;
  let svg = `<svg viewBox="0 0 ${width} ${layout.height}" role="img" aria-label="${escapeHtml(data.comment_id)}传播路径">
    <defs><marker id="cascade-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="${palette.orange}"/></marker></defs>`;
  for (let step = 1; step <= state.maxStep; step += 1) {
    const x = layout.stepX(step);
    svg += `<line x1="${x}" x2="${x}" y1="45" y2="${layout.height - 24}" stroke="#edf1f5"/>
      <text x="${x}" y="27" text-anchor="middle" fill="#718398" font-size="12">第${step}轮</text>`;
  }

  data.links.forEach(link => {
    const source = positions[link.source];
    const target = positions[link.target];
    if (!source || !target) return;
    const stopped = link.link_type === "stopped";
    const path = `M ${source.x + 13} ${source.y} C ${(source.x + target.x) / 2} ${source.y}, ${(source.x + target.x) / 2} ${target.y}, ${target.x - 13} ${target.y}`;
    svg += `<path d="${path}" fill="none" stroke="${stopped ? palette.gray : palette.orange}" stroke-width="${stopped ? 1.5 : 2.7}" opacity="${stopped ? .58 : .82}" ${stopped ? 'stroke-dasharray="5 5"' : 'marker-end="url(#cascade-arrow)"'}>
      <title>${stopped ? "看见但未继续" : "看见后继续表达"}，有效权重 ${Number(link.effective_weight || 0).toFixed(6)}</title>
    </path>`;
  });

  data.nodes.forEach(node => {
    const position = positions[node.node_id];
    const stopped = node.node_type === "stopped_exposure";
    const root = !stopped && Number(node.depth) === 0;
    const fill = stopped ? "white" : root ? palette.blue : palette.teal;
    const stroke = stopped ? palette.red : "white";
    const radius = stopped ? 9 : 14;
    svg += `<g>
      <circle cx="${position.x}" cy="${position.y}" r="${radius}" fill="${fill}" stroke="${stroke}" stroke-width="${stopped ? 3 : 3}"/>
      ${stopped ? `<line x1="${position.x - 4}" y1="${position.y - 4}" x2="${position.x + 4}" y2="${position.y + 4}" stroke="${palette.red}" stroke-width="2"/><line x1="${position.x + 4}" y1="${position.y - 4}" x2="${position.x - 4}" y2="${position.y + 4}" stroke="${palette.red}" stroke-width="2"/>` : ""}
      <text x="${position.x}" y="${position.y + radius + 16}" text-anchor="middle" fill="#50657a" font-size="9">${escapeHtml(shortAgent(node.agent_id))}</text>
      <title>${stopped ? "停止曝光" : root ? "首次表达" : "继续表达"}\n${escapeHtml(node.agent_id)}\n第${node.step}轮，传播深度${node.depth}${stopped ? `\n有效权重${Number(node.effective_weight || 0).toFixed(6)}` : ""}</title>
    </g>`;
  });
  svg += "</svg>";
  document.getElementById("cascade-chart").innerHTML = svg;
}

async function loadNetwork() {
  const query = new URLSearchParams({
    experiment_id: state.experimentId,
    scenario: state.scenarioId,
    step: String(state.step)
  });
  state.network = await getJson(`/api/network/view?${query}`);
  renderFollowNetwork();
  renderNetwork();
  renderStepTimeline();
}

async function loadCascade(commentId) {
  const query = new URLSearchParams({
    experiment_id: state.experimentId,
    scenario: state.scenarioId,
    comment_id: commentId
  });
  state.cascade = await getJson(`/api/network/cascade?${query}`);
  renderCascade();
}

async function loadScenario() {
  hideError();
  stopPlayback();
  state.selectedFollowAgentId = null;
  state.selectedAgentId = null;
  hideNetworkOfficialDetails();
  const scenario = state.report.scenarios.find(item => item.scenario_id === state.scenarioId);
  state.maxStep = Number(scenario?.step_count || state.report.max_step || 1);
  state.step = Math.min(Math.max(state.step, 1), state.maxStep);
  const slider = document.getElementById("step-slider");
  slider.max = state.maxStep;
  slider.value = state.step;
  document.getElementById("step-value").textContent = state.step;
  const query = new URLSearchParams({
    experiment_id: state.experimentId,
    scenario: state.scenarioId
  });
  const networkQuery = new URLSearchParams(query);
  networkQuery.set("step", String(state.step));
  const [network, comments] = await Promise.all([
    getJson(`/api/network/view?${networkQuery}`),
    getJson(`/api/network/comments?${query}`)
  ]);
  state.network = network;
  state.comments = comments;
  renderFollowNetwork();
  renderNetwork();
  resetNodeDetails();
  renderStepTimeline();

  const select = document.getElementById("comment-select");
  select.innerHTML = comments.comments.map(item => `
    <option value="${escapeHtml(item.comment_id)}">${escapeHtml(item.comment_id)} · 深度${item.max_depth} · 曝光${item.exposure_count}</option>
  `).join("");
  if (comments.comments.length) {
    await loadCascade(comments.comments[0].comment_id);
  } else {
    document.getElementById("comment-text").textContent = "该场景没有邻居传播评论。";
    document.getElementById("cascade-chart").innerHTML = "";
    document.getElementById("cascade-stats").innerHTML = "";
  }
}

function stopPlayback() {
  if (state.playTimer) {
    clearInterval(state.playTimer);
    state.playTimer = null;
  }
  document.getElementById("play-button").textContent = "▶ 播放轮次";
}

function togglePlayback() {
  if (state.playTimer) {
    stopPlayback();
    return;
  }
  if (state.step >= state.maxStep) state.step = 1;
  const slider = document.getElementById("step-slider");
  slider.value = state.step;
  document.getElementById("step-value").textContent = state.step;
  loadNetwork().catch(showError);
  document.getElementById("play-button").textContent = "❚❚ 暂停";
  state.playTimer = setInterval(() => {
    if (state.step >= state.maxStep) {
      stopPlayback();
      return;
    }
    state.step += 1;
    state.selectedAgentId = null;
    slider.value = state.step;
    document.getElementById("step-value").textContent = state.step;
    loadNetwork().catch(error => {
      stopPlayback();
      showError(error);
    });
  }, 1200);
}

async function initialize() {
  try {
    const requestedExperiment = new URLSearchParams(window.location.search).get("experiment_id");
    if (requestedExperiment) {
      state.experimentId = requestedExperiment;
    } else {
      const catalog = await getJson("/api/catalog");
      const first = catalog.experiments.find(item => item.capabilities.network && item.capabilities.comment_trace);
      if (!first) throw new Error("没有可展示社交网络与评论追踪的已完成实验。");
      state.experimentId = first.experiment_id;
    }
    state.report = await getJson(`/api/network/report?experiment_id=${encodeURIComponent(state.experimentId)}`);
    state.scenarioId = state.report.default_scenario_id;
    state.maxStep = Number(state.report.max_step || 1);
    state.step = state.maxStep;
    window.history.replaceState(null, "", `/network/?experiment_id=${encodeURIComponent(state.experimentId)}`);
    renderSummary();
    renderModeComparison();
    const scenarioSelect = document.getElementById("scenario-select");
    scenarioSelect.innerHTML = state.report.scenarios.map(item => `
      <option value="${escapeHtml(item.scenario_id)}">${escapeHtml(item.scenario_name)}</option>
    `).join("");
    scenarioSelect.value = state.scenarioId;
    scenarioSelect.closest("label").classList.toggle("hidden", state.report.scenarios.length <= 1);
    scenarioSelect.addEventListener("change", event => {
      state.scenarioId = event.target.value;
      const selected = state.report.scenarios.find(item => item.scenario_id === state.scenarioId);
      state.maxStep = Number(selected?.step_count || state.report.max_step || 1);
      state.step = state.maxStep;
      state.selectedAgentId = null;
      loadScenario().catch(showError);
    });
    const slider = document.getElementById("step-slider");
    slider.max = state.maxStep;
    slider.value = state.step;
    document.getElementById("step-value").textContent = state.step;
    slider.addEventListener("input", event => {
      state.step = Number(event.target.value);
      document.getElementById("step-value").textContent = state.step;
    });
    slider.addEventListener("change", () => {
      stopPlayback();
      state.selectedAgentId = null;
      loadNetwork().catch(showError);
    });
    document.querySelectorAll("[data-flow-mode]").forEach(button => {
      button.addEventListener("click", () => {
        state.flowMode = button.dataset.flowMode;
        state.selectedAgentId = null;
        document.querySelectorAll("[data-flow-mode]").forEach(item => {
          item.classList.toggle("is-active", item === button);
          item.setAttribute("aria-pressed", item === button ? "true" : "false");
        });
        resetNodeDetails();
        renderNetwork();
      });
    });
    document.getElementById("play-button").addEventListener("click", togglePlayback);
    document.getElementById("comment-select").addEventListener("change", event => {
      loadCascade(event.target.value).catch(showError);
    });
    await loadScenario();
  } catch (error) {
    showError(error);
  }
}

initialize();
