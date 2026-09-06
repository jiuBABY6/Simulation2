const colors = {
  blue: "#276ed8", teal: "#17a398", orange: "#f38a29",
  red: "#dd4b5c", purple: "#7358c7", gray: "#8796a6"
};

const state = { simulation: null, real: null, comparison: null };

function percent(value, fallback = "—") {
  return value === null || value === undefined ? fallback : `${Math.round(value * 100)}%`;
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
  const currentCommentNegative = finalRound.current_comment_distribution?.distribution?.negative?.rate;
  const cumulativeCommentNegative = finalRound.cumulative_comment_distribution?.distribution?.negative?.rate;
  const cards = [
    ["运行状态", simulation.status === "completed" ? "已完成" : simulation.status, simulation.experiment_id],
    ["复现阶段", `${simulation.step_count} 轮`, "对应八个现实时间段"],
    ["官方信息", `${simulation.official_update_count} 次`, "按指定历史节点投入"],
    ["最终评论负面率", percent(currentCommentNegative), `累计评论池 ${percent(cumulativeCommentNegative)}`],
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
  makeLineChart("comparison-chart", [
    { name: "当前轮评论", color: colors.blue, values: rounds.map(item => item.current_comment_distribution?.distribution?.negative?.rate ?? null) },
    { name: "人工群体参考", color: colors.orange, dashed: true, values: rounds.map(item => realByStep[item.step]?.sentiment.negative.estimate ?? null) },
    { name: "Agent负面情绪", color: colors.purple, dashed: true, values: rounds.map(item => item.negative_rate) }
  ], { markers: state.simulation.official_updates, label: "当前轮评论负面率与人工群体趋势参考" });

  makeLineChart("emotion-chart", [
    { name: "正面", color: colors.teal, values: rounds.map(item => item.positive_rate) },
    { name: "中性", color: colors.blue, values: rounds.map(item => item.neutral_rate) },
    { name: "负面", color: colors.red, values: rounds.map(item => item.negative_rate) }
  ], { height: 285, markers: state.simulation.official_updates, label: "Agent情绪分布" });

  makeLineChart("comment-emotion-chart", [
    { name: "正面评论", color: colors.teal, values: rounds.map(item => item.current_comment_distribution?.distribution?.positive?.rate ?? null) },
    { name: "中性评论", color: colors.blue, values: rounds.map(item => item.current_comment_distribution?.distribution?.neutral?.rate ?? null) },
    { name: "负面评论", color: colors.red, values: rounds.map(item => item.current_comment_distribution?.distribution?.negative?.rate ?? null) }
  ], { height: 285, markers: state.simulation.official_updates, label: "当前轮评论池情绪分布" });

  makeLineChart("attitude-chart", [
    { name: "接受", color: colors.teal, values: rounds.map(item => item.accept_rate) },
    { name: "观望", color: colors.orange, values: rounds.map(item => item.wait_rate) },
    { name: "质疑", color: colors.red, values: rounds.map(item => item.question_rate) }
  ], { height: 285, markers: state.simulation.official_updates, label: "Agent官方态度" });
}

function renderComparisonMetrics() {
  const metrics = state.comparison.metrics || {};
  const items = [
    [percent(metrics.mean_absolute_error), "平均绝对差（MAE）"],
    [percent(metrics.final_absolute_error), "最终阶段绝对差"],
    [percent(metrics.direction_agreement_rate), "相邻阶段方向一致率"],
    [metrics.peak_step_difference ?? "—", "峰值轮次差"]
  ];
  document.getElementById("comparison-metrics").innerHTML = items.map(item => `
    <div class="metric"><strong>${item[0]}</strong><span>${item[1]}</span></div>
  `).join("");
  const differentSteps = state.comparison.alignment?.different_period_steps || [];
  const alignmentText = differentSteps.length
    ? ` 第 ${differentSteps.join("、")} 阶段的日期边界并不完全相同，当前仅按事件阶段顺序对齐。`
    : " 两组数据的阶段时间段一致。";
  document.getElementById("comparison-caution").textContent =
    `主对照使用当前轮评论负面率；Agent负面率仅用于解释主体状态。该结果不代表模型准确率，真实数据是人工整理的群体级近似判断。${alignmentText}`;
}

function renderTable() {
  const pairByStep = Object.fromEntries(state.comparison.pairs.map(item => [item.step, item]));
  document.getElementById("phase-table").innerHTML = state.simulation.rounds.map(item => {
    const pair = pairByStep[item.step];
    const official = item.official_update
      ? `<span class="badge">${item.official_update.published_at} · ${item.official_update.official_statement_status}</span>`
      : `<span class="badge empty">沿用/无声明</span>`;
    return `<tr>
      <td><strong>${item.step}</strong></td>
      <td>${item.period}<br><span class="reference-period">参考：${pair?.real_reference_period || "—"}</span></td>
      <td>${item.phase}</td><td>${official}</td>
      <td>${percent(item.negative_rate)}</td><td>${percent(pair?.simulation_comment_rate)}</td><td>${percent(pair?.real_reference_rate)}</td>
      <td>${percent(pair?.absolute_error)}</td><td>${item.global_trend || "—"}</td>
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
    <div class="quality-grid">
      <div><strong>${quality.llm_comment_count ?? 0}</strong><span>LLM 有效评论</span></div>
      <div><strong>${quality.history_fallback_count ?? 0}</strong><span>历史评论兜底</span></div>
      <div><strong>${quality.emergency_fallback_count ?? 0}</strong><span>应急评论兜底</span></div>
    </div>`;
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
  [state.simulation, state.real, state.comparison] = await Promise.all([
    getJson(`/api/dashboard?experiment_id=${query}`),
    getJson("/api/real-trend"),
    getJson(`/api/comparison?experiment_id=${query}`)
  ]);
  renderCards(); renderCharts(); renderComparisonMetrics(); renderTable(); renderQuality(); renderLimitations();
}

async function initialize() {
  try {
    const result = await getJson("/api/experiments");
    if (!result.experiments.length) throw new Error("未找到历史趋势复现实验结果。请先运行历史复现。 ");
    const select = document.getElementById("experiment-select");
    select.innerHTML = result.experiments.map(item => `<option value="${item.experiment_id}">${item.experiment_id}</option>`).join("");
    select.addEventListener("change", event => loadExperiment(event.target.value).catch(showError));
    await loadExperiment(result.experiments[0].experiment_id);
  } catch (error) { showError(error); }
}

initialize();
