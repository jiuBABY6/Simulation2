const palette = {
  navy: "#0d2948",
  blue: "#276ed8",
  teal: "#12a395",
  orange: "#f28a2a",
  red: "#dc5265",
  gray: "#aab7c5"
};

const state = {
  report: null,
  network: null,
  comments: null,
  cascade: null,
  scenarioId: "no_response",
  step: 10,
  playTimer: null
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
  const performance = report.performance;
  document.getElementById("experiment-id").textContent = report.experiment_id;
  document.getElementById("acceptance-status").textContent =
    report.status === "completed" ? "通过" : report.status;

  const cards = [
    ["实验状态", report.status === "completed" ? "已完成" : report.status, `进场原因：${report.entry_reason || "—"}`],
    ["社交网络", `${network.node_count} 节点`, `${network.edge_count}条有向边 · 每人关注${network.neighbors_per_agent}人`],
    ["邻居曝光", propagation.exposure_count, "五个场景累计"],
    ["继续传播", propagation.continued_propagation_count, `总体继续传播率 ${percent(propagation.continuation_rate)}`],
    ["最大深度", `${propagation.max_propagation_depth} 层`, `逐层衰减系数 ${network.propagation_decay_factor}`],
    ["运行与质量", `${(Number(performance.total_duration_seconds || 0) / 60).toFixed(1)} 分钟`, `兜底率 ${percent(quality.fallback_rate)}`]
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

function renderStrategyComparison() {
  const scenarios = state.report.scenarios;
  const maxRate = Math.max(...scenarios.map(item => Number(item.propagation.continuation_rate || 0)), 0.01);
  document.getElementById("strategy-bars").innerHTML = `
    <p class="heading-note">继续传播率</p>
    ${scenarios.map(item => {
      const rate = Number(item.propagation.continuation_rate || 0);
      return `<div class="bar-row">
        <span>${escapeHtml(item.scenario_name)}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${Math.max(2, rate / maxRate * 100)}%"></div></div>
        <strong>${percent(rate)}</strong>
      </div>`;
    }).join("")}`;

  document.getElementById("strategy-table").innerHTML = scenarios.map(item => {
    const p = item.propagation;
    const status = item.quality.quality_status || "—";
    return `<tr>
      <td><strong>${escapeHtml(item.scenario_name)}</strong></td>
      <td>${p.exposure_count ?? 0}</td>
      <td>${p.continued_propagation_count ?? 0}</td>
      <td>${percent(p.continuation_rate)}</td>
      <td>${p.max_propagation_depth ?? 0}</td>
      <td>${Number(p.average_propagation_depth || 0).toFixed(3)}</td>
      <td><span class="quality-badge ${status === "normal" ? "normal" : ""}">${escapeHtml(status)}</span></td>
    </tr>`;
  }).join("");
}

function networkPositions(nodes, width, height) {
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = Math.min(width, height) * 0.36;
  const positions = {};
  nodes.forEach((node, index) => {
    const angle = -Math.PI / 2 + index / nodes.length * Math.PI * 2;
    positions[node.agent_id] = {
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius
    };
  });
  return positions;
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

function renderNodeDetails(node) {
  document.getElementById("node-details").innerHTML = `
    <p class="side-kicker">AGENT NODE</p>
    <h3>${escapeHtml(node.agent_id)}</h3>
    <div class="node-metric"><span>影响力权重</span><strong>${Number(node.influence_weight).toFixed(3)}</strong></div>
    <div class="node-metric"><span>发出邻居曝光</span><strong>${node.sent_exposure_count}</strong></div>
    <div class="node-metric"><span>接收邻居曝光</span><strong>${node.received_exposure_count}</strong></div>
    <div class="node-metric"><span>看见后继续表达</span><strong>${node.continued_count}</strong></div>
    <p>统计范围：${escapeHtml(state.network.scenario_name)}，截至第${state.network.step}轮。</p>`;
}

function renderNetwork() {
  const data = state.network;
  const width = 980;
  const height = 580;
  const positions = networkPositions(data.nodes, width, height);
  const weights = data.nodes.map(item => Number(item.influence_weight));
  const minWeight = Math.min(...weights);
  const maxWeight = Math.max(...weights);
  const radii = Object.fromEntries(data.nodes.map(node => [
    node.agent_id, nodeRadius(node, minWeight, maxWeight)
  ]));

  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(data.scenario_name)}社交网络信息流">
    <defs>
      <marker id="arrow-gray" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="${palette.gray}"/></marker>
      <marker id="arrow-teal" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="${palette.teal}"/></marker>
      <marker id="arrow-orange" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="${palette.orange}"/></marker>
      <filter id="node-shadow" x="-40%" y="-40%" width="180%" height="180%"><feDropShadow dx="0" dy="5" stdDeviation="5" flood-color="#173a5e" flood-opacity=".18"/></filter>
    </defs>`;

  data.edges.forEach(edge => {
    const source = positions[edge.source_agent_id];
    const target = positions[edge.target_agent_id];
    if (!source || !target) return;
    const active = edge.exposure_count > 0;
    const continued = edge.selected_exposure_count > 0;
    const color = continued ? palette.orange : active ? palette.teal : palette.gray;
    const marker = continued ? "arrow-orange" : active ? "arrow-teal" : "arrow-gray";
    const widthValue = active ? Math.min(5, 1.4 + Math.log1p(edge.exposure_count) * .8) : 1;
    const opacity = active ? .62 : .14;
    svg += `<path d="${curvedEdgePath(source, target, radii[edge.source_agent_id], radii[edge.target_agent_id])}"
      fill="none" stroke="${color}" stroke-width="${widthValue}" opacity="${opacity}"
      marker-end="url(#${marker})" ${active ? "" : 'stroke-dasharray="5 5"'}>
      <title>${escapeHtml(edge.source_agent_id)} → ${escapeHtml(edge.target_agent_id)}\n曝光${edge.exposure_count}次，继续表达${edge.selected_exposure_count}次，最大深度${edge.max_depth}</title>
    </path>`;
  });

  svg += `<circle cx="${width / 2}" cy="${height / 2}" r="88" fill="#f0f6fb" stroke="#dce7f0"/>
    <text x="${width / 2}" y="${height / 2 - 15}" text-anchor="middle" fill="${palette.navy}" font-size="17" font-weight="700">${escapeHtml(data.scenario_name)}</text>
    <text x="${width / 2}" y="${height / 2 + 12}" text-anchor="middle" fill="#66798d" font-size="13">截至第${data.step}轮</text>
    <text x="${width / 2}" y="${height / 2 + 36}" text-anchor="middle" fill="#8191a2" font-size="12">${data.event_count}次累计曝光</text>`;

  data.nodes.forEach(node => {
    const position = positions[node.agent_id];
    const radius = radii[node.agent_id];
    const activity = node.sent_exposure_count + node.received_exposure_count;
    const fill = activity ? palette.blue : "#8ca2b7";
    svg += `<g class="network-node" data-agent-id="${escapeHtml(node.agent_id)}" tabindex="0">
      <circle cx="${position.x}" cy="${position.y}" r="${radius + 5}" fill="#e7f1ff" opacity=".95"/>
      <circle cx="${position.x}" cy="${position.y}" r="${radius}" fill="${fill}" stroke="white" stroke-width="4" filter="url(#node-shadow)"/>
      <text x="${position.x}" y="${position.y + 4}" text-anchor="middle" fill="white" font-size="12" font-weight="700">${escapeHtml(shortAgent(node.agent_id))}</text>
      <text x="${position.x}" y="${position.y + radius + 20}" text-anchor="middle" fill="#52677d" font-size="11">权重 ${Number(node.influence_weight).toFixed(3)}</text>
      <title>${escapeHtml(node.agent_id)}\n影响力${Number(node.influence_weight).toFixed(3)}\n发出曝光${node.sent_exposure_count}，接收曝光${node.received_exposure_count}</title>
    </g>`;
  });
  svg += "</svg>";
  const container = document.getElementById("network-chart");
  container.innerHTML = svg;
  container.querySelectorAll(".network-node").forEach(element => {
    const activate = () => {
      const node = data.nodes.find(item => item.agent_id === element.dataset.agentId);
      if (node) renderNodeDetails(node);
    };
    element.addEventListener("click", activate);
    element.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") activate();
    });
  });

  const scenario = state.report.scenarios.find(item => item.scenario_id === data.scenario_id);
  metricItems("network-stats", [
    [data.event_count, "截至当前轮累计曝光"],
    [data.active_edge_count, `已激活传播边 / 共${data.edges.length}条`],
    [scenario?.propagation.reached_agent_count ?? 0, "完整场景覆盖Agent"],
    [scenario?.propagation.max_propagation_depth ?? 0, "完整场景最大深度"],
    [percent(scenario?.propagation.continuation_rate), "完整场景继续传播率"]
  ]);
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
  const positions = {};
  Object.entries(groups).forEach(([stepText, group]) => {
    const step = Number(stepText);
    const spacing = (height - 100) / (group.length + 1);
    group.forEach((node, index) => {
      positions[node.node_id] = { x: 70 + (step - 1) * 108, y: 62 + spacing * (index + 1) };
    });
  });
  return { positions, height };
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
  const width = 1090;
  const layout = cascadePositions(data.nodes);
  const positions = layout.positions;
  let svg = `<svg viewBox="0 0 ${width} ${layout.height}" role="img" aria-label="${escapeHtml(data.comment_id)}传播路径">
    <defs><marker id="cascade-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto"><path d="M0,0 L0,6 L7,3 z" fill="${palette.orange}"/></marker></defs>`;
  for (let step = 1; step <= 10; step += 1) {
    const x = 70 + (step - 1) * 108;
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
  const query = `scenario=${encodeURIComponent(state.scenarioId)}&step=${state.step}`;
  state.network = await getJson(`/api/network?${query}`);
  renderNetwork();
}

async function loadCascade(commentId) {
  const query = `scenario=${encodeURIComponent(state.scenarioId)}&comment_id=${encodeURIComponent(commentId)}`;
  state.cascade = await getJson(`/api/cascade?${query}`);
  renderCascade();
}

async function loadScenario() {
  hideError();
  stopPlayback();
  const query = encodeURIComponent(state.scenarioId);
  const [network, comments] = await Promise.all([
    getJson(`/api/network?scenario=${query}&step=${state.step}`),
    getJson(`/api/comments?scenario=${query}`)
  ]);
  state.network = network;
  state.comments = comments;
  renderNetwork();

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
  if (state.step >= 10) state.step = 1;
  const slider = document.getElementById("step-slider");
  slider.value = state.step;
  document.getElementById("step-value").textContent = state.step;
  loadNetwork().catch(showError);
  document.getElementById("play-button").textContent = "❚❚ 暂停";
  state.playTimer = setInterval(() => {
    if (state.step >= 10) {
      stopPlayback();
      return;
    }
    state.step += 1;
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
    state.report = await getJson("/api/report");
    renderSummary();
    renderStrategyComparison();
    const scenarioSelect = document.getElementById("scenario-select");
    scenarioSelect.innerHTML = state.report.scenarios.map(item => `
      <option value="${escapeHtml(item.scenario_id)}">${escapeHtml(item.scenario_name)}</option>
    `).join("");
    scenarioSelect.addEventListener("change", event => {
      state.scenarioId = event.target.value;
      loadScenario().catch(showError);
    });
    const slider = document.getElementById("step-slider");
    slider.addEventListener("input", event => {
      state.step = Number(event.target.value);
      document.getElementById("step-value").textContent = state.step;
    });
    slider.addEventListener("change", () => {
      stopPlayback();
      loadNetwork().catch(showError);
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
