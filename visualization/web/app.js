"use strict";

const $ = (id) => document.getElementById(id);
const TOPICS = ["社会事件", "新闻时事", "娱乐", "其他"];
const STATUS_TEXT = {
  created: "已创建",
  running: "运行中",
  paused: "已暂停",
  completed: "已完成",
  completed_no_entry: "未触发进场",
  completed_with_pending: "待填写公告",
  not_run: "未运行",
  failed: "失败"
};
const PHASE_TEXT = {
  created: "已创建",
  baseline: "进场前基线",
  scenario: "策略运行",
  completed: "已完成",
  not_run: "未运行"
};

const state = {
  defaults: null,
  session: null,
  selectedStrategyId: null,
  busy: false,
  autoRun: false,
  autoToken: 0,
  poolComments: [],
  poolDrawerOpen: false,
  entryTiming: null
};

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[ch]));
}

async function api(url, options = {}) {
  const response = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...options
  });
  const data = await response.json();
  if (!response.ok || data.error) {
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  return data;
}

function setBusy(value, message = "") {
  state.busy = value;
  const busy = $("busy");
  busy.hidden = !value;
  busy.textContent = message;
  document.querySelectorAll("button").forEach((button) => {
    if (value && button.id === "pause-btn" && state.session) return;
    button.disabled = value;
  });
  if (!value) renderControls();
}

function setLive(message, running = true) {
  $("live-text").textContent = message;
  $("live-dot").classList.toggle("off", !running);
}

function eventInput() {
  return {
    event_content: $("event-content").value.trim(),
    event_labels: {
      topic: $("event-topic").value,
      event_valence: $("event-valence").value
    }
  };
}

function initEntryTiming() {
  const select = $("entry-round");
  const options = Array.from({ length: 9 }, (_, index) => {
    const round = index + 2;
    return `<option value="${round}">第 ${round} 轮</option>`;
  }).join("");
  select.innerHTML = options;
  $("timeline-round").innerHTML = options;
  $("timeline-round").value = "2";
  select.value = "3";
  $("entry-mode").value = "dynamic";
  state.entryTiming = entryTimingInput();
}

function entryTimingInput() {
  const mode = $("entry-mode").value;
  if (mode !== "fixed_round") return { mode: "dynamic" };
  return { mode: "fixed_round", round: Number($("entry-round").value) };
}

function collectAnnouncements() {
  const result = {};
  document.querySelectorAll(".announcement-item").forEach((item) => {
    const strategyId = item.dataset.strategyId;
    const textarea = item.querySelector(".announcement-text");
    const select = item.querySelector(".announcement-status");
    if (!strategyId || !textarea || !select) return;
    result[strategyId] = {
      official_statement: textarea.value,
      official_statement_status: select.value
    };
  });
  return result;
}

function customReady() {
  const content = collectAnnouncements()["custom"];
  if (!content) return false;
  return Boolean(content.official_statement.trim()) && content.official_statement_status !== "none";
}

function renderEventForm() {
  const event = state.defaults.event_default || {};
  $("event-content").value = event.event_content || "";
  $("event-id-label").textContent = event.event_id || "";
  const labels = event.event_labels || {};
  const topicSelect = $("event-topic");
  topicSelect.innerHTML = TOPICS.map((topic) =>
    `<option value="${topic}">${topic}</option>`
  ).join("");
  topicSelect.value = labels.topic || "社会事件";
  $("event-valence").value = labels.event_valence || "negative";
}

function renderAnnouncements() {
  const strategies = state.defaults.strategies || [];
  const contentStrategies = (state.defaults.official_default || {}).content_strategies || [];
  const contentById = Object.fromEntries(
    contentStrategies.map((item) => [item.strategy_id, item])
  );
  const list = $("announcement-list");
  const allCard = `
    <article class="announcement-item strategy-choice" data-strategy-id="__all__">
      <div class="strategy-summary">
        <strong>依次运行全部策略</strong>
        <span class="announcement-select-state">五种策略按顺序执行</span>
      </div>
    </article>`;
  const noResponseCard = `
    <article class="announcement-item strategy-choice" data-strategy-id="no_response">
      <div class="strategy-summary">
        <strong>不回应</strong>
        <span class="announcement-select-state">不发布官方声明</span>
      </div>
    </article>`;
  const cards = strategies
    .filter((item) => !["__all__", "no_response"].includes(item.strategy_id))
    .map((item, index) => {
      const content = contentById[item.strategy_id] || {};
      const statusLabel = content.official_statement_status || "none";
      const ready = item.ready !== false;
      return `
        <article class="announcement-item" data-strategy-id="${esc(item.strategy_id)}">
          <details ${index === 0 || item.strategy_id === "custom" ? "open" : ""}>
            <summary>
              <span>${esc(item.strategy_name)}</span>
              <span class="announcement-select-state">${ready ? "可触发" : "待填写公告"}</span>
              <span class="announcement-badge">${esc(statusLabel)}</span>
            </summary>
            <div class="announcement-body">
              <label class="field">
                <span>公告内容</span>
                <textarea class="announcement-text" maxlength="5000">${esc(content.official_statement || "")}</textarea>
              </label>
              <label class="field">
                <span>声明状态</span>
                <select class="announcement-status">
                  <option value="clear">clear</option>
                  <option value="incomplete">incomplete</option>
                  <option value="conflict">conflict</option>
                  <option value="none">none</option>
                </select>
              </label>
            </div>
          </details>
        </article>`;
    }).join("");
  list.innerHTML = allCard + noResponseCard + cards;
  list.querySelectorAll(".announcement-item").forEach((item) => {
    const strategyId = item.dataset.strategyId;
    const defaultItem = contentById[strategyId];
    const select = item.querySelector(".announcement-status");
    if (defaultItem) select.value = defaultItem.official_statement_status || "none";
  });
}

function refreshCustomReadiness() {
  const ready = customReady();
  const defaultOption = (state.defaults.strategies || []).find(
    (item) => item.strategy_id === "custom"
  );
  if (defaultOption) defaultOption.ready = ready;
  const customCard = document.querySelector('.announcement-item[data-strategy-id="custom"]');
  if (!customCard) return;
  customCard.classList.toggle("disabled", !ready);
  const stateLine = customCard.querySelector(".announcement-select-state");
  stateLine.textContent = ready ? "可触发" : "待填写公告";
  if (state.selectedStrategyId === "custom" && !ready) {
    selectStrategy("no_response");
  }
}

function renderStrategies() {
  selectStrategy("no_response");
}

function selectStrategy(strategyId) {
  const strategies = state.defaults.strategies || [];
  if (strategyId === "__all__") {
    $("entry-timing-panel").hidden = true;
    $("entry-mode").value = "dynamic";
    state.selectedStrategyId = strategyId;
    document.querySelectorAll(".announcement-item").forEach((node) => {
      node.classList.toggle("selected", node.dataset.strategyId === strategyId);
    });
    return;
  }
  $("entry-timing-panel").hidden = false;
  const option = strategies.find((item) => item.strategy_id === strategyId);
  if (!option) return;
  if (option.ready === false && option.custom) {
    setLive("custom 公告为空，先填写公告内容", false);
    return;
  }
  state.selectedStrategyId = strategyId;
  document.querySelectorAll(".announcement-item").forEach((node) => {
    node.classList.toggle("selected", node.dataset.strategyId === strategyId);
  });
}

function strategyName(strategyId) {
  if (strategyId === "__all__") return "五种策略依次运行";
  if (!strategyId) return "—";
  const option = (state.defaults?.strategies || []).find(
    (item) => item.strategy_id === strategyId
  );
  return option ? option.strategy_name : strategyId;
}

function entryTimingLabel(session) {
  const timing = (session && session.entry_timing) || {};
  if (timing.mode === "fixed_round") {
    return `固定第 ${timing.round} 轮进场`;
  }
  return "动态进场";
}

function renderSessionSummary() {
  const session = state.session;
  if (!session) {
    $("session-title").textContent = "尚未创建";
    $("session-id-label").textContent = "";
    $("summary-strip").innerHTML = "";
    $("progress-label").textContent = "0 / 10";
    $("progress-track").innerHTML = "";
    $("phase-line").textContent = "创建会话后开始控制";
    $("detail-grid").innerHTML = "";
    $("detail-raw").textContent = "";
    $("current-strategy").textContent = "尚未选择策略";
    renderAgentSnapshot();
    renderTimelineEditor();
    renderLiveSnapshot();
    return;
  }
  const completed = session.completed_step_count || 0;
  const progressDone = session.mode === "all" && session.experiment_result_ready ? 10 : completed;
  const maxSteps = session.max_steps || 10;
  $("session-title").textContent = session.mode === "all" ? "全部策略会话" : "单策略会话";
  $("session-id-label").textContent = session.experiment_id || "";
  const statusLabel = STATUS_TEXT[session.status] || session.status;
  const phaseLabel = PHASE_TEXT[session.phase] || session.phase;
  const cards = session.mode === "all" ? [
    ["模式", "全部策略", "五种策略顺序运行"],
    ["状态", statusLabel, phaseLabel],
    ["策略", session.strategy_count ? `${session.strategy_count} 个` : "等待运行", session.phase || ""],
    ["官方进场", session.response_step ? `第 ${session.response_step} 轮` : "运行后确认", session.entry_reason || "—"]
  ] : [
    ["状态", statusLabel, session.paused ? "已暂停" : "可推进"],
    ["阶段", phaseLabel, session.phase || ""],
    ["轮次", session.current_step ? `第 ${session.current_step} 轮` : "—", `${completed} 步完成`],
    ["官方进场", session.response_step ? `第 ${session.response_step} 轮` : "未进场", session.entry_reason || "—"]
  ];
  $("summary-strip").innerHTML = cards.map(([label, value, detail]) => `
    <div class="summary-card">
      <div class="label">${label}</div>
      <div class="value" title="${esc(value)}">${esc(value)}</div>
      <div class="detail">${esc(detail)}</div>
    </div>`).join("");

  $("progress-label").textContent = `${progressDone} / ${maxSteps} 步`;
  const chips = Array.from({ length: maxSteps }, (_, index) => {
    const step = index + 1;
    const done = index < progressDone ? "done" : "";
    const entry = session.response_step === step ? "entry" : "";
    return `<div class="step-chip ${done} ${entry}" title="第${step}轮"></div>`;
  }).join("");
  $("progress-track").innerHTML = chips;
  if (state.busy || state.autoRun) {
    $("phase-line").textContent = "自动运行中";
  } else if (session.paused) {
    $("phase-line").textContent = "已暂停，点击“继续运行”恢复";
  } else {
    $("phase-line").textContent = phaseLabel;
  }
  if (session.mode === "all") {
    if (session.phase === "created" || session.phase === "ready") {
      $("current-strategy").textContent = "准备依次运行：不回应 + 四种内置策略";
    } else if (session.phase === "all_running") {
      $("current-strategy").textContent = "全部策略正在顺序运行";
    } else if (session.status === "completed") {
      $("current-strategy").textContent = "全部策略运行完成";
    } else {
      $("current-strategy").textContent = "全部策略模式";
    }
  } else if (session.phase === "baseline") {
    $("current-strategy").textContent = "进场前基线 · 等待进入策略场景";
  } else {
    $("current-strategy").textContent = `${session.phase === "scenario" ? "当前策略" : "目标策略"}：${strategyName(session.selected_strategy_id)}`;
  }
  $("current-strategy").textContent += ` · ${entryTimingLabel(session)}`;

  renderAgentSnapshot();
  renderTimelineEditor();
  renderResultDetail();
  renderLiveSnapshot();
}

function renderResultDetail() {
  const session = state.session;
  if (!session) return;
  const scenarioResult = session.scenario_result || null;
  if (!scenarioResult && session.mode === "all" && session.experiment_result) {
    const result = session.experiment_result;
    const comparison = result.comparison || {};
    const cards = [
      ["运行状态", result.status || "—"],
      ["策略数量", String(result.strategy_count ?? 0)],
      ["比较状态", result.comparison_status || "—"],
      ["官方进场", result.entry_reason || "—"]
    ];
    $("detail-grid").innerHTML = cards.map(([label, value]) => `
      <div class="detail-card"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
    $("detail-raw").textContent = JSON.stringify(result, null, 2);
    return;
  }
  if (!scenarioResult) {
    $("detail-grid").innerHTML = "";
    $("detail-raw").textContent = JSON.stringify({
      status: session.status,
      phase: session.phase,
      current_step: session.current_step,
      paused: session.paused,
      completed_step_count: session.completed_step_count
    }, null, 2);
    return;
  }
  const metrics = scenarioResult.final_metrics || {};
  const quality = scenarioResult.comment_quality || {};
  const cards = [
    ["最终负面率", pct(metrics.negative_rate)],
    ["质疑率", pct(metrics.question_rate)],
    ["接受率", pct(metrics.accept_rate)],
    ["评论质量", quality.quality_status || "—"]
  ];
  $("detail-grid").innerHTML = cards.map(([label, value]) => `
    <div class="detail-card"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  $("detail-raw").textContent = JSON.stringify(scenarioResult, null, 2);
}

function avatarColor(value) {
  if (value === "negative") return "#dc2626";
  if (value === "positive") return "#16a34a";
  return "#c2753d";
}

function emotionBadge(value) {
  const labels = { positive: "正面", neutral: "中性", negative: "负面" };
  const label = labels[value] || value || "—";
  const cls = value === "positive" ? "pos" : value === "negative" ? "neg" : "neu";
  return `<span class="badge ${cls}">${esc(label)}</span>`;
}

function renderMetricsLine(metrics) {
  const legend = $("metrics-legend");
  const target = $("metrics-chart");
  const hasTimeline = Boolean(
    state.session && (state.session.announcement_timeline || []).length
  );
  if (!metrics.length && !hasTimeline) {
    legend.innerHTML = "";
    target.innerHTML = '<div class="empty">尚无指标</div>';
    $("chart-tooltip").hidden = true;
    return;
  }
  const colors = {
    negative: "#dc2626",
    question: "#ea580c",
    accept: "#16a34a"
  };
  const series = [
    ["负面率", "negative"],
    ["质疑率", "question"],
    ["接受率", "accept"]
  ];
  legend.innerHTML = series.map(([name, key]) =>
    `<span><i style="background:${colors[key]}"></i>${name}</span>`
  ).join("");
  const metricsByStep = Object.fromEntries(metrics.map((item) => [item.step, item]));
  const maxAvailableStep = state.session?.max_steps || 10;
  const steps = Array.from({ length: maxAvailableStep }, (_, index) => index + 1);
  const width = 720;
  const height = 240;
  const margin = { left: 44, right: 18, top: 18, bottom: 30 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const minStep = steps[0];
  const maxStep = steps[steps.length - 1];
  const x = (step) => {
    const ratio = maxStep === minStep ? 0 : (step - minStep) / (maxStep - minStep);
    return margin.left + ratio * chartWidth;
  };
  const y = (value) => margin.top + (1 - value) * chartHeight;
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="舆情指标折线图">`;
  for (let tick = 0; tick <= 4; tick++) {
    const value = tick / 4;
    const yy = y(value);
    svg += `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="#f2e2cf"/>`;
    svg += `<text x="${margin.left - 7}" y="${yy + 4}" text-anchor="end" fill="#b58c69" font-size="10">${Math.round(value * 100)}%</text>`;
  }
  steps.forEach((step) => {
    svg += `<text x="${x(step)}" y="${height - 8}" text-anchor="middle" fill="#a77a54" font-size="10">${step}</text>`;
  });
  const entryStep = state.session && state.session.response_step;
  if (entryStep && entryStep >= minStep && entryStep <= maxStep) {
    const markerX = x(entryStep);
    svg += `<line x1="${markerX}" x2="${markerX}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#9a3412" stroke-width="1.6" stroke-dasharray="6 4" opacity="0.85"/>`;
    svg += `<text x="${markerX + 6}" y="${margin.top + 14}" fill="#9a3412" font-size="10">官方进场</text>`;
  }
  const timeline = (state.session && state.session.announcement_timeline) || [];
  timeline.forEach((event, index) => {
    const markerStep = event.round;
    if (markerStep < minStep || markerStep > maxStep) return;
    const markerX = x(markerStep);
    svg += `<line x1="${markerX}" x2="${markerX}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#7358c7" stroke-width="1.4" stroke-dasharray="3 4" opacity="0.9"/>`;
    svg += `<text x="${markerX + 5}" y="${margin.top + 27}" fill="#7358c7" font-size="10">公告${index + 1}</text>`;
  });
  series.forEach(([name, key]) => {
    const points = [];
    steps.forEach((step) => {
      const item = metricsByStep[step];
      if (!item) return;
      const value = item.policy_metrics[key === "negative" ? "negative_rate" : key === "question" ? "question_rate" : "accept_rate"];
      if (value === null || value === undefined) return;
      points.push({ step, value });
    });
    if (!points.length) return;
    const line = points.map((point, index) =>
      `${index ? "L" : "M"}${x(point.step).toFixed(1)},${y(point.value).toFixed(1)}`
    ).join("");
    svg += `<path d="${line}" fill="none" stroke="${colors[key]}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    points.forEach((point) => {
      const tooltipText = `第${point.step}轮 ${name} ${pct(point.value)}`;
      svg += `<circle cx="${x(point.step).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="3.6" fill="#fff" stroke="${colors[key]}" stroke-width="2" data-tooltip="${esc(tooltipText)}"><title>${esc(tooltipText)}</title></circle>`;
    });
  });
  svg += "</svg>";
  target.innerHTML = svg;
  const tooltip = $("chart-tooltip");
  const wrap = target.closest(".chart-wrap");
  target.querySelectorAll("circle").forEach((circle) => {
    circle.addEventListener("mousemove", (event) => {
      const rect = wrap.getBoundingClientRect();
      tooltip.textContent = circle.dataset.tooltip || "";
      tooltip.hidden = false;
      tooltip.style.left = `${event.clientX - rect.left + 12}px`;
      tooltip.style.top = `${event.clientY - rect.top + 10}px`;
    });
    circle.addEventListener("mouseleave", () => {
      tooltip.hidden = true;
    });
  });
}

function commentStats(comments) {
  const emotions = { positive: [], neutral: [], negative: [] };
  const factions = {};
  const orientations = {};
  comments.forEach((comment) => {
    if (emotions[comment.emotion]) emotions[comment.emotion].push(comment);
    if (comment.faction) factions[comment.faction] = (factions[comment.faction] || 0) + 1;
    if (comment.orientation) orientations[comment.orientation] = (orientations[comment.orientation] || 0) + 1;
  });
  return { emotions, factions, orientations, total: comments.length };
}

function emotionBlockHtml(comments) {
  if (!comments.length) return '<div class="empty">暂无评论</div>';
  const { emotions, total } = commentStats(comments);
  const emotionOrder = [
    ["negative", "#dc2626", "负面"],
    ["neutral", "#c2753d", "中性"],
    ["positive", "#16a34a", "正面"]
  ];
  const emotionWidth = (count) => `${Math.max(count ? count / total * 100 : 0, 0.4)}%`;
  const stack = `<div class="stack-bar">${emotionOrder.map(([key, color]) =>
    emotions[key].length ? `<i style="width:${emotionWidth(emotions[key].length)};background:${color}"></i>` : ""
  ).join("")}</div>`;
  const stackLegend = `<div class="stack-legend">${emotionOrder.map(([key, color, label]) => `
    <span><i style="background:${color}"></i>${label}<b>${emotions[key].length} · ${pct(emotions[key].length / total)}</b></span>`).join("")}</div>`;
  return `<div class="visual-block"><h3>情绪分布</h3>${stack}${stackLegend}</div>`;
}

function compositionBlockHtml(comments) {
  if (!comments.length) return '<div class="empty">暂无评论</div>';
  const { factions, orientations, total } = commentStats(comments);
  const factionTop = Object.entries(factions).sort((a, b) => b[1] - a[1]).slice(0, 6);
  const orientationTop = Object.entries(orientations).sort((a, b) => b[1] - a[1]).slice(0, 4);
  const factionRows = factionTop.length ? factionTop.map(([name, count]) => `
    <div class="bar-row"><span>${esc(name)}</span><div class="bar"><i style="width:${count / total * 100}%"></i></div><b>${count}</b></div>`
  ).join("") : '<div class="empty">暂无派系</div>';
  const orientationRows = orientationTop.map(([name, count]) => `
    <div class="bar-row"><span>${esc(name)}</span><div class="bar"><i style="width:${count / total * 100}%;background:#6b8f8a"></i></div><b>${count}</b></div>`
  ).join("");
  return `<div class="visual-block">
    <h3>派系</h3>${factionRows}
    ${orientationRows ? `<h3 style="margin-top:10px">信息取向</h3>${orientationRows}` : ""}
  </div>`;
}

function renderLiveSnapshot() {
  const snapshot = state.session ? state.session.snapshot : null;
  if (!snapshot) {
    if (state.poolDrawerOpen) closeCommentDrawer();
    $("metrics-count").textContent = "无数据";
    $("comments-count").textContent = "无数据";
    $("metrics-summary").innerHTML = [["负面率", "—"], ["质疑率", "—"], ["接受率", "—"], ["趋势", "—"]]
      .map(([label, value]) => `<div class="mini-card"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
    $("comments-summary").innerHTML = [["轮次", "—"], ["初始评论", "0"], ["LLM", "—"], ["负面", "—"]]
      .map(([label, value]) => `<div class="mini-card"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
    renderMetricsLine([]);
    return;
  }
  const metrics = snapshot.metrics_history || [];
  const commentHistory = snapshot.comment_history || [];
  const latestMetrics = metrics.length ? metrics[metrics.length - 1] : null;
  const latestPolicy = (latestMetrics && latestMetrics.policy_metrics) || {};
  const trend = latestMetrics ? latestMetrics.global_trend || "—" : "—";
  const metricCards = latestMetrics ? [
    ["负面率", pct(latestPolicy.negative_rate)],
    ["质疑率", pct(latestPolicy.question_rate)],
    ["接受率", pct(latestPolicy.accept_rate)],
    ["全局趋势", trend]
  ] : [
    ["状态", "等待首轮"],
    ["负面率", "—"],
    ["接受率", "—"],
    ["全局趋势", "—"]
  ];
  $("metrics-count").textContent = `${metrics.length} 轮`;
  renderMetricsLine(metrics);
  $("metrics-summary").innerHTML = metricCards.map(([label, value]) => `
    <div class="mini-card"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");

  const comments = snapshot.latest_comments || [];
  const latestStep = snapshot.latest_step || "—";
  const totalComments = commentHistory.reduce((sum, item) => sum + (item.comment_count || 0), 0);
  const llmComments = commentHistory.reduce((sum, item) => sum + (item.llm_comment_count || 0), 0);
  const latestNegativeRate = comments.length ? _commentRate(comments) : null;
  $("comments-count").textContent = `${comments.length} 条`;
  $("comments-summary").innerHTML = [
    ["最新轮次", String(latestStep)],
    ["初始评论", String(snapshot.initial_comment_count || 0)],
    ["LLM 占比", totalComments ? `${Math.round(llmComments / totalComments * 100)}%` : "—"],
    ["最新负面", latestNegativeRate === null ? "—" : pct(latestNegativeRate)]
  ].map(([label, value]) => `
    <div class="mini-card"><b>${esc(value)}</b><span>${esc(label)}</span></div>`).join("");
  if (state.poolDrawerOpen) {
    if (comments.length) renderPoolDrawer();
    else closeCommentDrawer();
  }
}

function renderAgentSnapshot() {
  const agents = state.session?.snapshot?.agents || [];
  state.agentSnapshot = agents;
  $("agent-count").textContent = agents.length ? `${agents.length} 个 Agent` : "无数据";
  const counts = {
    negative: agents.filter((item) => item.current_emotion === "negative").length,
    neutral: agents.filter((item) => item.current_emotion === "neutral").length,
    positive: agents.filter((item) => item.current_emotion === "positive").length
  };
  $("agent-summary").innerHTML = [
    ["Agent 总数", agents.length],
    ["负面", counts.negative],
    ["中性", counts.neutral],
    ["正面", counts.positive]
  ].map(([label, value]) => `
    <div class="mini-card"><b>${value}</b><span>${label}</span></div>`).join("");
}

function shortAgentId(agentId) {
  return String(agentId || "").replace(/^agent_/, "").slice(-4);
}

function emotionText(value) {
  return { positive: "正面", neutral: "中性", negative: "负面" }[value] || "—";
}

function attitudeColor(value) {
  return {
    accept: "#16a34a",
    wait: "#d97706",
    question: "#dc2626",
    not_applicable: "#c2753d"
  }[value] || "#c2753d";
}

function openAgentPoolDrawer() {
  const agents = state.agentSnapshot || [];
  if (!agents.length) {
    $("agent-drawer-body").innerHTML = '<div class="empty">当前没有 Agent 状态</div>';
  } else {
    const orbs = agents.map((agent, index) => {
      const color = avatarColor(agent.current_emotion);
      const attitude = agent.official_attitude || "not_applicable";
      const angle = -Math.PI / 2 + (index / agents.length) * Math.PI * 2;
      const left = 50 + Math.cos(angle) * 38;
      const top = 50 + Math.sin(angle) * 38;
      return `
        <div class="agent-orb-wrap" role="button" tabindex="0" data-index="${index}" title="${esc(agent.agent_id)}" style="left:${left}%;top:${top}%">
          <span class="agent-orb" style="--orb:${color};--ring:${attitudeColor(attitude)}">
            ${esc(shortAgentId(agent.agent_id))}
          </span>
          <small>${esc(emotionText(agent.current_emotion))}</small>
        </div>`;
    }).join("");
    const details = agents.map((agent) => `
      <div class="timeline-item">
        <b>${esc(shortAgentId(agent.agent_id))}</b>
        <span>情绪 ${esc(emotionText(agent.current_emotion))} · 态度 ${esc(agent.official_attitude || "—")} · ${esc(agent.last_comment_faction || "无派系")}</span>
      </div>`).join("");
    $("agent-drawer-body").innerHTML = `
      <div class="agent-orbs">${orbs}</div>
      <section class="comment-detail-section">
        <h3>全部 Agent 状态（点击小球查看详情）</h3>
        <div class="timeline-list">${details}</div>
      </section>`;
  }
  $("agent-drawer").classList.add("open");
  $("agent-drawer").setAttribute("aria-hidden", "false");
  $("agent-drawer-backdrop").classList.remove("hidden");
}

function openAgentDrawer(index) {
  const agent = (state.agentSnapshot || [])[index];
  if (!agent) return;
  $("agent-drawer-body").innerHTML = `
    <button class="button ghost" id="agent-pool-back" type="button">返回全部 Agent</button>
    <div class="summary-strip">
      <div class="summary-card"><div class="label">情绪</div><div class="value">${esc(emotionText(agent.current_emotion))}</div><div class="detail">${esc(agent.agent_id)}</div></div>
      <div class="summary-card"><div class="label">官方态度</div><div class="value">${esc(agent.official_attitude || "—")}</div><div class="detail">${agent.will_comment ? "愿意评论" : "未表达"}</div></div>
    </div>
    <section class="comment-detail-section">
      <h3>本轮评论</h3>
      <p class="live-comment" style="margin:0">${esc(agent.last_comment || "本轮未发表评论")}</p>
    </section>
    <section class="comment-detail-section">
      <h3>状态属性</h3>
      <div class="kv-grid">
        <div class="kv"><b>${esc(agent.last_action || "—")}</b><span>最近动作</span></div>
        <div class="kv"><b>${esc(agent.last_comment_faction || "—")}</b><span>评论派系</span></div>
        <div class="kv"><b>${esc(agent.comment_orientation || "—")}</b><span>信息取向</span></div>
        <div class="kv"><b>${esc(agent.comment_emotion || "—")}</b><span>评论情绪</span></div>
      </div>
    </section>`;
  $("agent-drawer").classList.add("open");
  $("agent-drawer").setAttribute("aria-hidden", "false");
  $("agent-drawer-backdrop").classList.remove("hidden");
}

function closeAgentDrawer() {
  $("agent-drawer").classList.remove("open");
  $("agent-drawer").setAttribute("aria-hidden", "true");
  $("agent-drawer-backdrop").classList.add("hidden");
}

function renderTimelineEditor() {
  const session = state.session;
  const timeline = (session && session.announcement_timeline) || [];
  const button = $("add-announcement-btn");
  button.disabled = !session || !session.paused || !["baseline", "scenario"].includes(session.phase);
  const timelineHtml = timeline.length ? timeline.map((event) => `
    <div class="timeline-item">
      <b>第 ${event.round} 轮</b>
      <span title="${esc(event.official_statement)}">${esc(event.official_statement)}</span>
    </div>`).join("") : '<div class="empty">暂无追加公告</div>';
  $("timeline-list").innerHTML = timelineHtml;
  if (session && session.current_step) {
    $("timeline-round").value = String(Math.max(2, session.current_step));
  }
}

async function addAnnouncement() {
  if (!state.session || !state.session.paused || state.busy) return;
  const text = $("timeline-text").value.trim();
  if (!text) {
    setLive("请先填写公告内容", false);
    return;
  }
  setBusy(true, "正在追加公告");
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(state.session.experiment_id)}/announcement`, {
      method: "POST",
      body: JSON.stringify({
        round: Number($("timeline-round").value),
        official_statement: text,
        official_statement_status: $("timeline-status").value
      })
    });
    state.session = data;
    $("timeline-text").value = "";
    setLive("公告已加入时间线", true);
    renderSessionSummary();
    renderControls();
  } catch (error) {
    setLive(error.message, false);
  } finally {
    setBusy(false);
  }
}

function _commentRate(comments) {
  const negative = comments.filter((comment) => comment.emotion === "negative").length;
  const total = comments.length;
  return total ? negative / total : null;
}

function pct(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
  return `${Math.round(Number(value) * 100)}%`;
}

function renderControls() {
  const session = state.session;
  const buttons = {
    start: $("start-btn"),
    runAll: $("run-all-btn"),
    continue: $("continue-btn"),
    pause: $("pause-btn"),
    rollback: $("rollback-btn"),
    restart: $("restart-btn")
  };
  if (!session) {
    buttons.start.disabled = true;
    buttons.runAll.disabled = true;
    buttons.continue.disabled = true;
    buttons.pause.disabled = true;
    buttons.rollback.disabled = true;
    buttons.restart.disabled = true;
    return;
  }
  const phase = session.phase || "";
  const allMode = session.mode === "all";
  const active = phase === "baseline" || phase === "scenario";
  const finished = ["completed", "completed_no_entry", "failed", "not_run"].includes(session.status);
  buttons.start.hidden = allMode;
  buttons.runAll.hidden = !allMode;
  buttons.runAll.disabled = state.busy || !["created", "ready"].includes(phase);
  buttons.start.disabled = state.busy || phase !== "created";
  buttons.continue.disabled = state.busy || !active;
  buttons.pause.disabled = finished || (!state.autoRun && session.paused && !state.busy);
  buttons.rollback.disabled = state.busy || !(session.completed_step_count > 0);
  buttons.restart.disabled = state.busy;
}

async function sessionAction(action, body = {}) {
  if (!state.session || state.busy) return;
  const experimentId = state.session.experiment_id;
  setBusy(true, action === "continue" || action === "step" ? "推演执行中，请等待当前时间步完成" : "请求处理中");
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(experimentId)}/${action}`, {
      method: "POST",
      body: JSON.stringify(body)
    });
    state.session = data;
    const running = !["completed", "completed_no_entry", "failed", "not_run", "created"].includes(data.status) || data.status === "running";
    setLive(data.status === "completed" || data.status === "completed_no_entry" ? "会话完成" : `已${data.paused ? "暂停" : "就绪"}`, running);
    renderSessionSummary();
    renderControls();
  } catch (error) {
    setLive(error.message, false);
    $("detail-raw").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function pauseNow() {
  stopAutoRun();
  if (!state.session) return;
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(state.session.experiment_id)}/pause`, {
      method: "POST",
      body: "{}"
    });
    state.session = data;
    setLive("已暂停", false);
    renderSessionSummary();
    renderControls();
  } catch (error) {
    setLive(error.message, false);
  }
}

async function runAutoLoop() {
  const token = ++state.autoToken;
  while (state.autoRun && token === state.autoToken) {
    const session = state.session;
    if (!session) break;
    if (["created", "ready"].includes(session.phase)) break;
    if (["completed", "completed_no_entry", "failed", "not_run"].includes(session.status)) {
      state.autoRun = false;
      break;
    }
    if (!["baseline", "scenario"].includes(session.phase)) break;
    await new Promise((resolve) => setTimeout(resolve, 250));
    setLive("自动续跑中", true);
    await sessionAction("continue");
    if (token !== state.autoToken) break;
  }
}

function stopAutoRun() {
  state.autoRun = false;
  state.autoToken += 1;
}

async function handleStart() {
  await sessionAction("start");
  if (state.session && state.session.mode !== "all") {
    state.autoRun = true;
    runAutoLoop();
  }
}

async function runAllAction() {
  if (!state.session || state.busy) return;
  stopAutoRun();
  setBusy(true, "五种策略依次运行中，请等待全部完成");
  try {
    const data = await api(`/api/sessions/${encodeURIComponent(state.session.experiment_id)}/run`, {
      method: "POST",
      body: "{}"
    });
    state.session = data;
    setLive(data.status === "completed" ? "全部策略运行完成" : data.status, true);
    renderSessionSummary();
    renderControls();
  } catch (error) {
    setLive(error.message, false);
    $("detail-raw").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function createSession() {
  if (state.busy) return;
  const selected = state.selectedStrategyId || "no_response";
  const announcements = collectAnnouncements();
  if (selected === "custom" && !customReady()) {
    setLive("custom 公告为空，无法创建自定义策略会话", false);
    return;
  }
  setBusy(true, "正在创建会话批次");
  try {
    const data = await api("/api/sessions", {
      method: "POST",
      body: JSON.stringify({
        web_event_input: eventInput(),
        official_content_input: announcements,
        entry_timing_input: entryTimingInput(),
        selected_strategy_id: selected
      })
    });
    state.session = data;
    history.replaceState(null, "", `#${data.experiment_id}`);
    setLive("会话已创建，点击启动", false);
    renderSessionSummary();
    renderControls();
  } catch (error) {
    setLive(error.message, false);
    $("detail-raw").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function previewInputs() {
  if (state.busy) return;
  setBusy(true, "正在校验输入");
  try {
    const data = await api("/api/input/preview", {
      method: "POST",
      body: JSON.stringify({
        web_event_input: eventInput(),
        official_content_input: collectAnnouncements(),
        entry_timing_input: entryTimingInput()
      })
    });
    setLive("输入校验通过", true);
    $("detail-raw").textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    setLive(error.message, false);
    $("detail-raw").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

function renderPoolDrawer() {
  const snapshot = state.session ? state.session.snapshot : null;
  const comments = snapshot ? (snapshot.latest_comments || []) : [];
  state.poolComments = comments;
  const commentHistory = (snapshot && snapshot.comment_history) || [];
  const latestStep = snapshot ? snapshot.latest_step : null;
  const historyItem = commentHistory.find((item) => item.step === latestStep) || {};
  const totalComments = commentHistory.reduce((sum, item) => sum + (item.comment_count || 0), 0);
  const llmComments = commentHistory.reduce((sum, item) => sum + (item.llm_comment_count || 0), 0);
  $("comment-drawer-body").innerHTML = `
    <div class="summary-strip">
      ${[
        ["当前轮次", latestStep ? `第 ${latestStep} 轮` : "—"],
        ["当前评论", `${comments.length} 条`],
        ["初始评论", `${(snapshot && snapshot.initial_comment_count) || 0} 条`],
        ["LLM 占比", totalComments ? `${Math.round(llmComments / totalComments * 100)}%` : "—"]
      ].map(([label, value]) => `
        <div class="summary-card">
          <div class="label">${label}</div>
          <div class="value">${esc(value)}</div>
          <div class="detail">${esc(historyItem.quality_status || "")}</div>
        </div>`).join("")}
    </div>
    <div class="comments-visual">
      ${emotionBlockHtml(comments)}
      ${compositionBlockHtml(comments)}
    </div>
    <section class="comment-detail-section">
      <h3>评论内容（点击查看单条详情）</h3>
      <div class="comment-list">
        ${comments.length ? comments.map((comment, index) => `
          <article class="live-comment clickable" role="button" tabindex="0" data-index="${index}" style="border-left-color:${avatarColor(comment.emotion)}">
            <div class="feed-meta">
              ${emotionBadge(comment.emotion)}
              ${comment.faction ? `<span class="badge">${esc(comment.faction)}</span>` : ""}
              ${comment.orientation ? `<span class="badge neu">${esc(comment.orientation)}</span>` : ""}
            </div>
            <p>${esc(comment.text || "")}</p>
          </article>`).join("") : '<div class="empty">暂无评论</div>'}
      </div>
    </section>`;
  $("comment-drawer").classList.add("open");
  $("comment-drawer").setAttribute("aria-hidden", "false");
  $("comment-drawer-backdrop").classList.remove("hidden");
  state.poolDrawerOpen = true;
}

function renderCommentDetail(index) {
  const comment = state.poolComments[index];
  if (!comment) return;
  const orientationText = {
    fact: "事实信息",
    opinion: "观点表达",
    questioning: "质疑提问"
  }[comment.orientation] || comment.orientation || "—";
  const stanceText = comment.stance || "—";
  $("comment-drawer-body").innerHTML = `
    <button class="button ghost" id="pool-detail-back" type="button">返回舆论池</button>
    <section class="comment-detail-section">
      <h3>评论原文</h3>
      <p class="live-comment" style="border-left-color:${avatarColor(comment.emotion)};margin:0">
        ${esc(comment.text || "")}
      </p>
    </section>
    <section class="comment-detail-section">
      <h3>结构化属性</h3>
      <div class="kv-grid">
        <div class="kv"><b>${emotionBadge(comment.emotion)}</b><span>情绪</span></div>
        <div class="kv"><b>${esc(comment.faction || "—")}</b><span>派系</span></div>
        <div class="kv"><b>${esc(orientationText)}</b><span>信息取向</span></div>
        <div class="kv"><b>${esc(stanceText)}</b><span>立场</span></div>
        <div class="kv"><b>${esc(comment.comment_id || "—")}</b><span>评论编号</span></div>
        <div class="kv"><b>第 ${state.session?.snapshot?.latest_step ?? "—"} 轮</b><span>当前轮次</span></div>
      </div>
    </section>`;
}

function closeCommentDrawer() {
  state.poolDrawerOpen = false;
  $("comment-drawer").classList.remove("open");
  $("comment-drawer").setAttribute("aria-hidden", "true");
  $("comment-drawer-backdrop").classList.add("hidden");
}

async function initialize() {
  try {
    state.defaults = await api("/api/input/defaults");
    renderEventForm();
    renderAnnouncements();
    initEntryTiming();
    renderStrategies();
    renderSessionSummary();
    renderControls();
    const sessionId = location.hash.replace(/^#/, "");
    if (sessionId) {
      const session = await api(`/api/sessions/${encodeURIComponent(sessionId)}`);
      state.session = session;
      renderSessionSummary();
      renderControls();
      setLive(session.paused ? "会话已暂停" : "会话已加载", true);
    } else {
      setLive("输入已加载", true);
    }
  } catch (error) {
    setLive(error.message, false);
  }
}

$("preview-btn").addEventListener("click", previewInputs);
$("create-btn").addEventListener("click", createSession);
$("start-btn").addEventListener("click", handleStart);
$("run-all-btn").addEventListener("click", runAllAction);
$("continue-btn").addEventListener("click", () => {
  if (!state.session || state.busy) return;
  state.autoRun = true;
  runAutoLoop();
});
$("pause-btn").addEventListener("click", () => {
  pauseNow();
});
$("rollback-btn").addEventListener("click", () => {
  stopAutoRun();
  sessionAction("rollback", { steps: Number($("rollback-steps").value) });
});
$("restart-btn").addEventListener("click", () => {
  stopAutoRun();
  sessionAction("restart");
});
$("add-announcement-btn").addEventListener("click", addAnnouncement);
$("announcement-list").addEventListener("input", refreshCustomReadiness);
$("announcement-list").addEventListener("change", refreshCustomReadiness);
$("announcement-list").addEventListener("click", (event) => {
  if (event.target.closest("textarea, select")) return;
  const option = event.target.closest(".announcement-item");
  if (option) selectStrategy(option.dataset.strategyId);
});
$("announcement-list").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const option = event.target.closest(".announcement-item");
  if (option) {
    event.preventDefault();
    selectStrategy(option.dataset.strategyId);
  }
});
$("pool-panel").addEventListener("click", renderPoolDrawer);
$("comment-drawer-body").addEventListener("click", (event) => {
  const back = event.target.closest("#pool-detail-back");
  if (back) {
    renderPoolDrawer();
    return;
  }
  const item = event.target.closest(".live-comment");
  if (item) renderCommentDetail(Number(item.dataset.index));
});
$("comment-drawer-body").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const back = event.target.closest("#pool-detail-back");
  if (back) {
    event.preventDefault();
    renderPoolDrawer();
    return;
  }
  const item = event.target.closest(".live-comment");
  if (item) {
    event.preventDefault();
    renderCommentDetail(Number(item.dataset.index));
  }
});
$("comment-drawer-close").addEventListener("click", closeCommentDrawer);
$("comment-drawer-backdrop").addEventListener("click", closeCommentDrawer);
$("agent-panel").addEventListener("click", openAgentPoolDrawer);
$("agent-drawer-body").addEventListener("click", (event) => {
  const back = event.target.closest("#agent-pool-back");
  if (back) {
    openAgentPoolDrawer();
    return;
  }
  const orb = event.target.closest(".agent-orb-wrap");
  if (orb) openAgentDrawer(Number(orb.dataset.index));
});
$("agent-drawer-body").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const back = event.target.closest("#agent-pool-back");
  if (back) {
    event.preventDefault();
    openAgentPoolDrawer();
    return;
  }
  const orb = event.target.closest(".agent-orb-wrap");
  if (orb) {
    event.preventDefault();
    openAgentDrawer(Number(orb.dataset.index));
  }
});
$("agent-drawer-close").addEventListener("click", closeAgentDrawer);
$("agent-drawer-backdrop").addEventListener("click", closeAgentDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    closeCommentDrawer();
    closeAgentDrawer();
  }
});

initialize();
