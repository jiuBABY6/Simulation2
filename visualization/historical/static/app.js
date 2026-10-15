// 历史复现页面只消费历史专用 API；网络传播由共享页面负责。
const colors = {
  blue: "#276ed8", teal: "#17a398", orange: "#f38a29",
  red: "#dd4b5c", purple: "#7358c7", gray: "#8796a6"
};

const state = {
  simulation: null,
  real: null,
  comparison: null,
  comparisonBundle: null,
  experiments: [],
  descriptor: null,
  comparisonBasis: "agent_expression"
};

const basisLabels = {
  agent_expression: "Agent实际表达",
  active_opinion: "活跃舆情（最近两轮）",
  current_round: "当前轮增量",
  cumulative: "模拟评论池累计"
};

const distributionFields = {
  agent_expression: "agent_expression_distribution",
  active_opinion: "active_comment_distribution",
  current_round: "current_comment_distribution",
  cumulative: "cumulative_comment_distribution"
};

function percent(value, fallback = "—") {
  return value === null || value === undefined ? fallback : `${Math.round(value * 100)}%`;
}

function selectedDistribution(round) {
  return round?.[distributionFields[state.comparisonBasis]] || {};
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>'"]/g, character => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
  })[character]);
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function showError(error) {
  const notice = document.getElementById("notice");
  notice.textContent = error.message;
  notice.classList.remove("hidden");
}

function renderCards() {
  const simulation = state.simulation;
  const finalMetrics = simulation.final_metrics || {};
  const finalRound = simulation.rounds[simulation.rounds.length - 1] || {};
  const selectedCommentNegative = selectedDistribution(finalRound)?.distribution?.negative?.rate;
  const cumulativeCommentNegative = finalRound.cumulative_comment_distribution?.distribution?.negative?.rate;
  const cards = [
    ["运行状态", simulation.status === "completed" ? "已完成" : simulation.status, simulation.experiment_id],
    ["复现阶段", `${simulation.step_count} 轮`, `真实观测 ${state.real.periods.length} 个阶段`],
    ["官方信息", `${simulation.official_update_count} 次`, "按指定历史节点投入"],
    [`最终${basisLabels[state.comparisonBasis]}负面率`, percent(selectedCommentNegative), `累计评论池 ${percent(cumulativeCommentNegative)}`],
    ["最终Agent负面率", percent(finalMetrics.negative_rate), "Agent 群体状态"]
  ];
  document.getElementById("summary-cards").innerHTML = cards.map(item => `
    <article class="card"><div class="card-label">${item[0]}</div>
    <div class="card-value">${item[1]}</div><div class="card-detail">${item[2]}</div></article>
  `).join("");
}

function makeLineChart(targetId, series, options = {}) {
  const width = 940, height = options.height || 320;
  const margin = { left: 58, right: 28, top: 35, bottom: 58 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const steps = state.simulation.rounds.map(item => item.step);
  const x = step => margin.left + ((step - 1) / Math.max(steps.length - 1, 1)) * chartWidth;
  const y = value => margin.top + (1 - value) * chartHeight;

  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="${options.label || "趋势图"}">`;
  const legendWidth = Math.min(180, chartWidth / Math.max(series.length, 1));
  series.forEach((item, index) => {
    const legendX = margin.left + index * legendWidth;
    svg += `<line x1="${legendX}" x2="${legendX + 24}" y1="16" y2="16" stroke="${item.color}" stroke-width="3" ${item.dashed ? 'stroke-dasharray="7 5"' : ""}/>`;
    svg += `<text x="${legendX + 31}" y="20" fill="#536477" font-size="12">${item.name}</text>`;
  });
  for (let tick = 0; tick <= 4; tick++) {
    const value = tick / 4;
    const yy = y(value);
    svg += `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="#e7edf4"/>`;
    svg += `<text x="${margin.left - 12}" y="${yy + 4}" text-anchor="end" fill="#718194" font-size="12">${Math.round(value * 100)}%</text>`;
  }

  (options.markers || []).forEach(marker => {
    const xx = x(marker.step);
    svg += `<line x1="${xx}" x2="${xx}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="${colors.teal}" stroke-width="2" stroke-dasharray="5 5" opacity=".8"/>`;
    svg += `<text x="${xx + 6}" y="${margin.top + 12}" fill="${colors.teal}" font-size="11">官方${marker.step}</text>`;
  });

  // 2026/10/8，新增功能：人工初始化轮次在趋势图中单独标记，避免被理解为模型预测点。
  (options.calibrationMarkers || []).forEach(marker => {
    const xx = x(marker.step);
    svg += `<line x1="${xx}" x2="${xx}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="${colors.gray}" stroke-width="2" stroke-dasharray="3 4" opacity=".9"/>`;
    svg += `<text x="${xx + 6}" y="${margin.top + 27}" fill="${colors.gray}" font-size="11">历史初始条件</text>`;
  });

  series.forEach(item => {
    const segments = [];
    let current = [];
    item.values.forEach((value, index) => {
      if (value === null || value === undefined) {
        if (current.length) segments.push(current);
        current = [];
      } else current.push([x(steps[index]), y(value), value, steps[index]]);
    });
    if (current.length) segments.push(current);
    segments.forEach(points => {
      const pointText = points.map(point => `${point[0]},${point[1]}`).join(" ");
      svg += `<polyline points="${pointText}" fill="none" stroke="${item.color}" stroke-width="3" ${item.dashed ? 'stroke-dasharray="9 7"' : ""}/>`;
      points.forEach(point => {
        svg += `<circle cx="${point[0]}" cy="${point[1]}" r="4.5" fill="white" stroke="${item.color}" stroke-width="3"><title>第${point[3]}轮 ${item.name}：${percent(point[2])}</title></circle>`;
      });
    });
  });

  steps.forEach((step, index) => {
    svg += `<text x="${x(step)}" y="${height - margin.bottom + 25}" text-anchor="middle" fill="#5f7082" font-size="12">第${step}轮</text>`;
    const period = state.simulation.rounds[index].period || "";
    svg += `<text x="${x(step)}" y="${height - margin.bottom + 43}" text-anchor="middle" fill="#91a0ae" font-size="9">${period.replace("2023.", "")}</text>`;
  });
  svg += `</svg>`;
  document.getElementById(targetId).innerHTML = svg;
}

function renderCharts() {
  const rounds = state.simulation.rounds;
  const realByStep = Object.fromEntries(state.real.periods.map(item => [item.step, item]));
  const calibrationMarkers = rounds.filter(item => item.is_calibration_point);
  const basisLabel = basisLabels[state.comparisonBasis];
  document.getElementById("comparison-title").textContent = `${basisLabel}负面率与真实群体趋势参考`;
  document.getElementById("comparison-legend-label").textContent = basisLabel;
  document.getElementById("comment-emotion-title").textContent = `${basisLabel}情绪分布`;
  document.getElementById("comment-rate-heading").textContent = `${basisLabel}负面率`;
  makeLineChart("comparison-chart", [
    { name: basisLabel, color: colors.blue, values: rounds.map(item => selectedDistribution(item)?.distribution?.negative?.rate ?? null) },
    { name: "人工群体参考", color: colors.orange, dashed: true, values: rounds.map(item => realByStep[item.step]?.sentiment.negative.estimate ?? null) },
    { name: "Agent负面情绪", color: colors.purple, dashed: true, values: rounds.map(item => item.negative_rate) }
  ], {
    markers: state.simulation.official_updates,
    calibrationMarkers,
    label: `${basisLabel}负面率与人工群体趋势参考`
  });

  makeLineChart("emotion-chart", [
    { name: "正面", color: colors.teal, values: rounds.map(item => item.positive_rate) },
    { name: "中性", color: colors.blue, values: rounds.map(item => item.neutral_rate) },
    { name: "负面", color: colors.red, values: rounds.map(item => item.negative_rate) }
  ], { height: 285, markers: state.simulation.official_updates, label: "Agent情绪分布" });

  makeLineChart("comment-emotion-chart", [
    { name: "正面评论", color: colors.teal, values: rounds.map(item => selectedDistribution(item)?.distribution?.positive?.rate ?? null) },
    { name: "中性评论", color: colors.blue, values: rounds.map(item => selectedDistribution(item)?.distribution?.neutral?.rate ?? null) },
    { name: "负面评论", color: colors.red, values: rounds.map(item => selectedDistribution(item)?.distribution?.negative?.rate ?? null) }
  ], { height: 285, markers: state.simulation.official_updates, label: `${basisLabel}情绪分布` });

  makeLineChart("attitude-chart", [
    { name: "接受", color: colors.teal, values: rounds.map(item => item.accept_rate) },
    { name: "观望", color: colors.orange, values: rounds.map(item => item.wait_rate) },
    { name: "质疑", color: colors.red, values: rounds.map(item => item.question_rate) }
  ], { height: 285, markers: state.simulation.official_updates, label: "Agent官方态度" });
}

function renderComparisonMetrics() {
  const metrics = state.comparison.metrics || {};
  const items = [
    [percent(metrics.mean_absolute_error), "负面率平均绝对差"],
    [percent(metrics.macro_mean_absolute_error), "三类情绪宏平均差"],
    [percent(metrics.final_absolute_error), "最终阶段负面率差"],
    [percent(metrics.direction_agreement_rate), "相邻阶段方向一致率"]
  ];
  if (metrics.peak_step_difference !== null && metrics.peak_step_difference !== undefined) {
    items.push([metrics.peak_step_difference, "峰值轮次差"]);
  }
  document.getElementById("comparison-metrics").innerHTML = items.map(item => `
    <div class="metric"><strong>${item[0]}</strong><span>${item[1]}</span></div>
  `).join("");
  const differentSteps = state.comparison.alignment?.different_period_steps || [];
  const alignmentText = differentSteps.length
    ? ` 第 ${differentSteps.join("、")} 阶段的日期边界并不完全相同，当前仅按事件阶段顺序对齐。`
    : " 两组数据的阶段时间段一致。";
  document.getElementById("comparison-caution").textContent =
    `主对照使用${basisLabels[state.comparisonBasis]}；Agent负面率仅用于解释主体状态。${state.comparison.interpretation}${alignmentText}`;
}

// 2026/10/14，新增功能：展示群体趋同诊断而不把它当作失败条件。
function renderAttitudeDiagnostics() {
  const rounds = state.simulation.rounds.filter(item =>
    item.official_attitude_diagnostics?.applicable_agent_count > 0
  );
  const target = document.getElementById("attitude-diagnostics");
  if (!rounds.length) {
    target.innerHTML = '<div class="metric"><strong>—</strong><span>旧批次没有态度诊断</span></div>';
    return;
  }
  const latest = rounds[rounds.length - 1].official_attitude_diagnostics;
  const peakSynchronization = Math.max(...rounds.map(item =>
    item.official_attitude_diagnostics.synchronized_transition_rate ?? 0
  ));
  const minimumEntropy = Math.min(...rounds.map(item =>
    item.official_attitude_diagnostics.normalized_attitude_entropy ?? 1
  ));
  const process = latest.process_evaluation_distribution || {};
  const items = [
    [percent(latest.largest_attitude_group_rate), "最终最大态度群体"],
    [percent(latest.normalized_attitude_entropy), "最终态度熵（越高越多样）"],
    [percent(peakSynchronization), "最高单轮同步转向率"],
    [percent(minimumEntropy), "最低态度熵"],
    [percent(process.dissatisfied?.rate), "最终过程不满意比例"]
  ];
  target.innerHTML = items.map(item => `
    <div class="metric"><strong>${item[0]}</strong><span>${item[1]}</span></div>
  `).join("");
}

function renderTable() {
  const pairByStep = Object.fromEntries(state.comparison.pairs.map(item => [item.step, item]));
  document.getElementById("phase-table").innerHTML = state.simulation.rounds.map(item => {
    const pair = pairByStep[item.step];
    // 2026/10/8，新增功能：阶段表明确区分人工校准点和模型自由生成轮次。
    const stepLabel = item.is_calibration_point
      ? `${item.step}<br><span class="badge">历史初始条件</span>`
      : item.step;
    const official = item.official_update
      ? `<span class="badge">${item.official_update.published_at} · ${item.official_update.official_statement_status}</span>`
      : `<span class="badge empty">沿用/无声明</span>`;
    return `<tr>
      <td><strong>${stepLabel}</strong></td>
      <td>${item.period}<br><span class="reference-period">参考：${pair?.real_reference_period || "—"}</span></td>
      <td>${pair?.phase || item.phase || "—"}<br><span class="reference-period">采样：${pair?.sampling_method || "—"}</span></td><td>${official}</td>
      <td>${percent(item.negative_rate)}</td><td>${percent(pair?.simulation_comment_rate)}</td><td>${percent(pair?.real_reference_rate)}</td>
      <td>${pair?.included_in_point_error === false ? "不计入" : percent(pair?.absolute_error)}</td><td>${item.global_trend || "—"}</td>
    </tr>`;
  }).join("");
}

function renderQuality() {
  const quality = state.simulation.comment_quality || {};
  const total = (quality.llm_comment_count || 0) + (quality.fallback_count || 0);
  const llmRate = total ? quality.llm_comment_count / total : 0;
  document.getElementById("quality-content").innerHTML = `
    <p class="source-note">质量状态：<strong>${quality.quality_status || "—"}</strong></p>
    <div class="quality-bar"><span style="width:${Math.round(llmRate * 100)}%"></span></div>
    <p class="source-note">LLM 有效评论占全部增量评论总量 ${percent(llmRate)}</p>
    <p class="source-note">情绪覆盖：<strong>${quality.emotion_coverage_status || "未启用"}</strong>${(quality.emotion_coverage_warning_steps || []).length ? `；缺失轮次 ${quality.emotion_coverage_warning_steps.join("、")}` : ""}</p>
    <div class="quality-grid">
      <div><strong>${quality.llm_comment_count ?? 0}</strong><span>LLM 有效评论</span></div>
      <div><strong>${quality.history_fallback_count ?? 0}</strong><span>历史评论兜底</span></div>
      <div><strong>${quality.emergency_fallback_count ?? 0}</strong><span>应急评论兜底</span></div>
    </div>`;
}

function renderPublicContext() {
  const cards = state.simulation.rounds
    .filter(round => round.public_context)
    .map(round => {
      const context = round.public_context;
      const verified = (context.verified_updates || [])
        .map(item => `<li>${escapeHtml(item.content)}</li>`)
        .join("") || "<li>本阶段没有新增已核实信息。</li>";
      const discourse = (context.public_discourse || [])
        .map(item => `<li>${escapeHtml(item.content)}</li>`)
        .join("") || "<li>本阶段没有单独配置公众讨论议题。</li>";
      return `<article class="context-card">
        <h3>第${round.step}轮 · ${escapeHtml(context.phase || round.phase)}</h3>
        <p>${escapeHtml(context.period || round.period)}</p>
        <p><strong>已核实信息：</strong></p><ul>${verified}</ul>
        <p><strong>同期公众议题：</strong></p><ul>${discourse}</ul>
      </article>`;
    });
  document.getElementById("context-timeline").innerHTML = cards.length
    ? cards.join("")
    : '<p class="source-note">该批次没有保存逐轮公众语境；仍可查看事件初始资料、官方通告和模拟结果。</p>';
}

function renderLimitations() {
  document.getElementById("limitations").innerHTML = `
    <p class="source-note">来源：${state.real.source.file} · ${state.real.source.sheet} · ${state.real.source.range}</p>
    <p class="source-note"><strong>处理原则</strong></p>
    <ul class="limitations">${state.real.methodology.map(item => `<li>${item}</li>`).join("")}</ul>
    <p class="source-note"><strong>解释限制</strong></p>
    <ul class="limitations">${state.real.limitations.map(item => `<li>${item}</li>`).join("")}</ul>`;
}

async function loadExperiment(experimentId) {
  document.getElementById("notice").classList.add("hidden");
  const query = encodeURIComponent(experimentId);
  state.descriptor = state.experiments.find(
    item => item.experiment_id === experimentId
  ) || null;
  [state.simulation, state.real, state.comparisonBundle] = await Promise.all([
    getJson(`/api/historical/dashboard?experiment_id=${query}`),
    getJson(`/api/historical/real-trend?experiment_id=${query}`),
    getJson(`/api/historical/comparison?experiment_id=${query}`)
  ]);
  const activeWindow = state.simulation.simulation_options?.active_opinion_window || 2;
  basisLabels.active_opinion = `活跃舆情（最近${activeWindow}轮）`;
  document.querySelector('#metric-basis-select option[value="active_opinion"]').textContent = basisLabels.active_opinion;
  state.comparisonBasis = state.comparisonBundle.default_basis || "agent_expression";
  state.comparison = state.comparisonBundle.comparisons?.[state.comparisonBasis]
    || state.comparisonBundle;
  document.getElementById("metric-basis-select").value = state.comparisonBasis;
  const hasNetwork = Boolean(
    state.descriptor?.capabilities?.network
    && state.descriptor?.capabilities?.comment_trace
  );
  const networkLink = document.getElementById("network-link");
  const networkUnavailable = document.getElementById("network-unavailable");
  networkLink.classList.toggle("hidden", !hasNetwork);
  networkUnavailable.classList.toggle("hidden", hasNetwork);
  if (hasNetwork) {
    networkLink.href = `/network/?experiment_id=${encodeURIComponent(experimentId)}`;
  }
  window.history.replaceState(null, "", `/historical/?experiment_id=${encodeURIComponent(experimentId)}`);
  renderCards(); renderCharts(); renderComparisonMetrics(); renderAttitudeDiagnostics(); renderTable(); renderPublicContext(); renderQuality(); renderLimitations();
}

async function initialize() {
  try {
    const result = await getJson("/api/catalog?mode=historical_replay");
    const matchingExperiments = result.experiments.filter(item =>
      item.status === "completed" && item.capabilities.real_trend_comparison
    );
    if (!matchingExperiments.length) {
      throw new Error("未找到同时具备模拟结果和真实趋势的历史复现实验。");
    }
    state.experiments = matchingExperiments;
    const select = document.getElementById("experiment-select");
    select.innerHTML = matchingExperiments.map(item => `<option value="${item.experiment_id}">${item.experiment_id}</option>`).join("");
    select.addEventListener("change", event => loadExperiment(event.target.value).catch(showError));
    document.getElementById("metric-basis-select").addEventListener("change", event => {
      state.comparisonBasis = event.target.value;
      state.comparison = state.comparisonBundle.comparisons?.[state.comparisonBasis]
        || state.comparisonBundle;
      renderCards(); renderCharts(); renderComparisonMetrics(); renderTable();
    });
    const requestedExperiment = new URLSearchParams(window.location.search).get("experiment_id");
    const initialExperiment = matchingExperiments.find(item => item.experiment_id === requestedExperiment)
      || matchingExperiments[0];
    select.value = initialExperiment.experiment_id;
    await loadExperiment(initialExperiment.experiment_id);
  } catch (error) { showError(error); }
}

initialize();
