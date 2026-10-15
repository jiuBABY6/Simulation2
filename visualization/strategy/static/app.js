const colors = ["#276ed8", "#17a398", "#f38a29", "#7358c7", "#dd4b5c"];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function getJson(url) {
  const response = await fetch(url);
  const data = await response.json();
  if (!response.ok || data.error) throw new Error(data.error || `请求失败：${response.status}`);
  return data;
}

function percent(value) {
  return Number.isFinite(Number(value)) ? `${Math.round(Number(value) * 100)}%` : "—";
}

function precisePercent(value, digits = 1) {
  return Number.isFinite(Number(value)) ? `${(Number(value) * 100).toFixed(digits)}%` : "—";
}

function numberValue(value, digits = 3) {
  if (!Number.isFinite(Number(value))) return "—";
  return Number(value).toLocaleString("zh-CN", { maximumFractionDigits: digits });
}

function integerValue(value) {
  return Number.isFinite(Number(value)) ? Number(value).toLocaleString("zh-CN") : "—";
}

function seconds(value) {
  return Number.isFinite(Number(value)) ? `${numberValue(value, 1)} 秒` : "—";
}

function trendLabel(value) {
  return ({ stable: "稳定", worsening: "恶化", improving: "改善" })[value] || value || "—";
}

function entryReasonLabel(value) {
  return ({ negative_threshold: "负面率达到阈值", global_worsening: "全局趋势恶化", stagnation: "连续未改善" })[value] || value || "—";
}

function qualityLabel(value) {
  return ({ normal: "正常", degraded: "降级", unknown: "未知" })[value] || value || "未记录";
}

function boolLabel(value) {
  if (value === true) return "是";
  if (value === false) return "否";
  return "—";
}

function metricValue(strategy, key) {
  const rounds = strategy.rounds || [];
  const last = rounds[rounds.length - 1] || {};
  return last.policy_metrics?.[key] ?? strategy.final_metrics?.[key] ?? null;
}

function officialStatusLabel(status) {
  return ({ clear: "信息清晰", incomplete: "信息不完整", conflict: "信息存在冲突" })[status] || status || "未记录";
}

function officialTiming(strategy) {
  const responses = strategy.official_responses || [];
  if (!responses.length) return "未投入";
  const steps = [...new Set(responses.map(item => Number(item.step)).filter(Number.isFinite))]
    .sort((left, right) => left - right);
  return `第${steps.join("、")}轮投入，共${responses.length}次`;
}

function showAnnouncementDetails(announcements) {
  const items = Array.isArray(announcements) ? announcements : [announcements];
  const first = items[0] || {};
  const panel = document.getElementById("announcement-details");
  panel.innerHTML = `
    <div>
      <p>官方公告详情</p>
      <h3>第${escapeHtml(first.step)}轮 · ${items.length}项策略公告</h3>
    </div>
    <span class="announcement-status">按策略分别展示</span>
    <div class="announcement-list">${items.map(item => `
      <article style="--announcement-color:${colors[item.strategyIndex % colors.length]}">
        <div><strong>${escapeHtml(item.strategy_name || item.scenario_name || "未命名策略")}</strong>
          <span>${escapeHtml(officialStatusLabel(item.official_statement_status))}</span></div>
        <p>${escapeHtml(item.official_statement || "未记录公告内容")}</p>
      </article>`).join("")}</div>`;
  panel.classList.remove("hidden");
  panel.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderSummary(data) {
  const successful = data.strategies.filter(item => item.status === "success").length;
  const warnings = data.strategies.filter(item => item.comment_quality?.quality_status !== "normal").length;
  document.getElementById("summary-cards").innerHTML = [
    [data.status === "completed" ? "已完成" : data.status || "未知", "运行状态"],
    [`${data.strategy_count} 项`, "策略场景"],
    [`${data.step_count} 轮`, "每场景轮次"],
    [`${successful}/${data.strategy_count}`, "成功场景"],
    [`${warnings} 项`, "数据质量提醒"]
  ].map(([value, label]) => `<article><strong>${escapeHtml(value)}</strong><span>${label}</span></article>`).join("");
}

function renderTrend(data) {
  const container = document.getElementById("trend-chart");
  const width = 1120, height = 380;
  const margin = { left: 70, right: 30, top: 70, bottom: 55 };
  const chartWidth = width - margin.left - margin.right;
  const chartHeight = height - margin.top - margin.bottom;
  const maxStep = Math.max(1, ...data.strategies.map(item => item.rounds.length));
  const x = step => margin.left + (maxStep === 1 ? chartWidth / 2 : (step - 1) * chartWidth / (maxStep - 1));
  const y = rate => margin.top + (1 - Math.max(0, Math.min(1, Number(rate) || 0))) * chartHeight;
  const grid = [0, .25, .5, .75, 1].map(rate => `
    <line x1="${margin.left}" y1="${y(rate)}" x2="${width - margin.right}" y2="${y(rate)}" class="grid-line" />
    <text x="${margin.left - 14}" y="${y(rate) + 5}" text-anchor="end">${Math.round(rate * 100)}%</text>`).join("");
  const steps = Array.from({ length: maxStep }, (_, index) => index + 1).map(step => `
    <text x="${x(step)}" y="${height - 18}" text-anchor="middle">第${step}轮</text>`).join("");
  const announcements = data.strategies.flatMap((strategy, strategyIndex) =>
    (strategy.official_responses || []).map(response => ({
      ...response,
      scenario_name: strategy.scenario_name,
      strategyIndex
    }))
  ).filter(item => Number(item.step) >= 1 && Number(item.step) <= maxStep);
  const announcementGroups = [...new Set(announcements.map(item => Number(item.step)))]
    .sort((left, right) => left - right)
    .map(step => ({ step, items: announcements.filter(item => Number(item.step) === step) }));
  const announcementGuides = announcementGroups.map((group, groupIndex) => `
    <g class="official-guide official-group-marker" data-group-index="${groupIndex}" tabindex="0" role="button" aria-label="第${group.step}轮共${group.items.length}项官方公告">
      <line x1="${x(group.step)}" y1="${margin.top - 32}" x2="${x(group.step)}" y2="${height - margin.bottom}" />
      <rect x="${x(group.step) - 38}" y="${margin.top - 58}" width="76" height="24" rx="12" />
      <text x="${x(group.step)}" y="${margin.top - 41}" text-anchor="middle">公告×${group.items.length}</text>
      <title>第${group.step}轮投入${group.items.length}项策略公告，点击查看详情</title>
    </g>`).join("");
  const lines = data.strategies.map((strategy, index) => {
    const points = strategy.rounds
      .map(round => ({ step: Number(round.step), rate: round.policy_metrics?.negative_rate }))
      .filter(point => Number.isFinite(Number(point.rate)));
    const polyline = points.map(point => `${x(point.step)},${y(point.rate)}`).join(" ");
    const dots = points.map(point => `<circle cx="${x(point.step)}" cy="${y(point.rate)}" r="5"><title>${escapeHtml(strategy.scenario_name)} 第${point.step}轮 ${percent(point.rate)}</title></circle>`).join("");
    return `<g style="--series:${colors[index % colors.length]}"><polyline points="${polyline}" />${dots}</g>`;
  }).join("");
  container.innerHTML = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="五策略负面情绪率趋势及官方公告投入轮次">${grid}${announcementGuides}${steps}${lines}</svg>`;
  document.getElementById("trend-legend").innerHTML = data.strategies.map((strategy, index) => `
    <span><i style="background:${colors[index % colors.length]}"></i>${escapeHtml(strategy.scenario_name)}</span>`).join("")
    + `<span><i class="official-legend"></i>公告投入轮次（同轮公告合并展示）</span>`;
  container.querySelectorAll(".official-group-marker").forEach(marker => {
    const openDetails = () => showAnnouncementDetails(announcementGroups[Number(marker.dataset.groupIndex)].items);
    marker.addEventListener("click", openDetails);
    marker.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openDetails();
      }
    });
  });
}

function fallbackRate(quality) {
  const total = Number(quality?.llm_comment_count || 0) + Number(quality?.fallback_count || 0);
  return total ? Number(quality.fallback_count || 0) / total : 0;
}

function netEffect(strategy, key) {
  return strategy.effect_metrics?.control_net_effect?.[key] ?? null;
}

function renderEffectComparison(data) {
  document.getElementById("effect-table").innerHTML = data.strategies.map(strategy => {
    const effect = strategy.effect_metrics || {};
    return `<tr>
      <th>${escapeHtml(strategy.scenario_name)}</th>
      <td>${percent(metricValue(strategy, "negative_rate"))}</td>
      <td>${percent(effect.negative_peak_rate)}</td>
      <td>${numberValue(effect.negative_area, 2)}</td>
      <td>${numberValue(netEffect(strategy, "negative_area_reduction"), 2)}</td>
      <td>${percent(effect.emotion_recovery_rate)}</td>
      <td>${Number.isFinite(Number(effect.effect_duration)) ? `${integerValue(effect.effect_duration)}轮` : "—"}</td>
      <td>${percent(effect.rebound_rate)}</td>
      <td>${percent(metricValue(strategy, "question_rate"))}</td>
      <td>${percent(metricValue(strategy, "accept_rate"))}</td>
    </tr>`;
  }).join("");
}

const comparisonDefinitions = [
  ["lowest_negative_rate", "最终负面率最低", "percent"],
  ["lowest_question_rate", "最终质疑率最低", "percent"],
  ["highest_accept_rate", "最终接受率最高", "percent"],
  ["lowest_negative_peak_rate", "负面峰值最低", "percent"],
  ["lowest_negative_area", "累计负面强度最低", "number"],
  ["highest_emotion_recovery_rate", "情绪恢复率最高", "percent"],
  ["longest_effect_duration", "效果持续最久", "round"],
  ["lowest_rebound_rate", "情绪反弹率最低", "percent"],
  ["highest_negative_area_reduction", "较不回应累计减少最多", "number"]
];

function comparisonValue(value, type) {
  if (type === "percent") return percent(value);
  if (type === "round") return Number.isFinite(Number(value)) ? `${integerValue(value)}轮` : "—";
  return numberValue(value, 2);
}

function renderComparison(data) {
  const comparison = data.comparison || {};
  document.getElementById("comparison-grid").innerHTML = comparisonDefinitions.map(([key, label, type]) => {
    const item = comparison[key] || {};
    const names = (item.strategies || []).map(strategy => strategy.strategy_name || strategy.strategy).filter(Boolean);
    const winner = names.length ? names.join("、") : "无可用结果";
    return `<article class="comparison-card">
      <span>${escapeHtml(label)}</span>
      <strong>${escapeHtml(winner)}</strong>
      <div><b>${comparisonValue(item.value, type)}</b>${item.is_tie ? '<em>并列</em>' : ""}</div>
    </article>`;
  }).join("");
}

function metricItem(label, value, hint = "") {
  return `<div class="metric-item"><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd>${hint ? `<small>${escapeHtml(hint)}</small>` : ""}</div>`;
}

function metricGroup(title, items) {
  return `<article class="metric-group"><h3>${escapeHtml(title)}</h3><dl>${items.join("")}</dl></article>`;
}

function requestTypeItems(requests) {
  return Object.entries(requests?.by_type || {}).flatMap(([key, value]) => [
    metricItem(`${requestLabels[key] || key}请求`, `${integerValue(value.logical_request_count)}次`),
    metricItem(`${requestLabels[key] || key}耗时`, seconds(value.total_duration_seconds))
  ]);
}

function renderMetricDetail(strategy) {
  const effect = strategy.effect_metrics || {};
  const propagation = strategy.propagation_summary || {};
  const quality = strategy.comment_quality || {};
  const performance = strategy.performance || {};
  const control = effect.control_net_effect || {};
  const warningSteps = Array.isArray(quality.warning_steps) && quality.warning_steps.length
    ? quality.warning_steps.map(step => `第${step}轮`).join("、") : "无";
  const peakSteps = Array.isArray(effect.negative_peak_steps) && effect.negative_peak_steps.length
    ? effect.negative_peak_steps.map(step => `第${step}轮`).join("、") : "—";
  const groups = [
    metricGroup("实验结果", [
      metricItem("场景状态", strategy.status || "—"),
      metricItem("可参与比较", boolLabel(strategy.comparison_eligible)),
      metricItem("公告已触发", boolLabel(strategy.entry_triggered)),
      metricItem("触发原因", entryReasonLabel(strategy.entry_reason)),
      metricItem("公告投入", officialTiming(strategy)),
      metricItem("最终趋势", trendLabel(strategy.final_trend)),
      metricItem("最终负面率", percent(metricValue(strategy, "negative_rate"))),
      metricItem("最终质疑率", percent(metricValue(strategy, "question_rate"))),
      metricItem("最终接受率", percent(metricValue(strategy, "accept_rate"))),
      metricItem("态度适用人数", integerValue(metricValue(strategy, "official_attitude_applicable_count")))
    ]),
    metricGroup("累计效果", [
      metricItem("分析起始轮", integerValue(effect.analysis_start_step)),
      metricItem("观测轮数", integerValue(effect.observed_step_count)),
      metricItem("负面峰值", percent(effect.negative_peak_rate)),
      metricItem("峰值轮次", peakSteps),
      metricItem("累计负面强度", numberValue(effect.negative_area, 2), "各轮负面率之和，越低越好"),
      metricItem("基线轮次", integerValue(effect.baseline_step)),
      metricItem("基线负面率", percent(effect.effect_baseline_negative_rate)),
      metricItem("基线负面人数", integerValue(effect.baseline_negative_agent_count)),
      metricItem("恢复人数", integerValue(effect.recovered_agent_count)),
      metricItem("情绪恢复率", percent(effect.emotion_recovery_rate)),
      metricItem("效果起始轮", integerValue(effect.effect_start_step)),
      metricItem("效果结束轮", integerValue(effect.effect_end_step)),
      metricItem("效果持续轮数", integerValue(effect.effect_duration)),
      metricItem("反弹人数", integerValue(effect.rebound_agent_count)),
      metricItem("反弹率", percent(effect.rebound_rate)),
      metricItem("最终负面率减少", percent(control.final_negative_rate_reduction), "相对不回应场景"),
      metricItem("负面峰值减少", percent(control.peak_negative_rate_reduction), "相对不回应场景"),
      metricItem("累计负面强度减少", numberValue(control.negative_area_reduction, 2), "相对不回应场景")
    ]),
    metricGroup("传播汇总", [
      metricItem("总曝光次数", integerValue(propagation.exposure_count)),
      metricItem("触达Agent", integerValue(propagation.reached_agent_count)),
      metricItem("触达率", precisePercent(propagation.reach_rate)),
      metricItem("传播源Agent", integerValue(propagation.source_agent_count)),
      metricItem("传播评论数", integerValue(propagation.propagated_comment_count)),
      metricItem("继续传播次数", integerValue(propagation.continued_propagation_count)),
      metricItem("继续传播Agent", integerValue(propagation.continued_agent_count)),
      metricItem("继续传播率", precisePercent(propagation.continuation_rate)),
      metricItem("最大传播深度", integerValue(propagation.max_propagation_depth)),
      metricItem("平均传播深度", numberValue(propagation.average_propagation_depth)),
      metricItem("总有效传播权重", numberValue(propagation.total_effective_weight))
    ]),
    metricGroup("评论质量", [
      metricItem("质量状态", qualityLabel(quality.quality_status)),
      metricItem("评论总量", integerValue(Number(quality.llm_comment_count || 0) + Number(quality.fallback_count || 0))),
      metricItem("LLM新生成", integerValue(quality.llm_comment_count)),
      metricItem("历史兜底", integerValue(quality.history_fallback_count)),
      metricItem("应急兜底", integerValue(quality.emergency_fallback_count)),
      metricItem("兜底总量", integerValue(quality.fallback_count)),
      metricItem("兜底率", precisePercent(fallbackRate(quality))),
      metricItem("生成尝试", integerValue(quality.generation_attempts)),
      metricItem("首轮请求", integerValue(quality.initial_request_count)),
      metricItem("补充请求", integerValue(quality.refill_request_count)),
      metricItem("救援请求", integerValue(quality.rescue_request_count)),
      metricItem("质量告警轮次", warningSteps)
    ]),
    metricGroup("场景运行", [
      metricItem("运行耗时", seconds(performance.duration_seconds)),
      metricItem("实际执行轮数", integerValue(performance.executed_step_count)),
      metricItem("LLM逻辑请求", integerValue(performance.llm_requests?.logical_request_count)),
      metricItem("HTTP尝试", integerValue(performance.llm_requests?.http_attempt_count)),
      metricItem("重试", integerValue(performance.llm_requests?.retry_count)),
      metricItem("失败请求", integerValue(performance.llm_requests?.failed_request_count)),
      metricItem("LLM累计耗时", seconds(performance.llm_requests?.total_duration_seconds))
    ]),
    metricGroup("场景阶段耗时", Object.entries(performance.stage_duration_seconds || {}).map(([key, value]) =>
      metricItem(stageLabels[key] || key, seconds(value))
    )),
    metricGroup("场景LLM请求构成", requestTypeItems(performance.llm_requests))
  ];
  document.getElementById("metric-groups").innerHTML = groups.join("");
  renderRoundTable(strategy);
  renderRoundQualityTable(strategy);
}

function renderRoundTable(strategy) {
  document.getElementById("round-table").innerHTML = (strategy.rounds || []).map(round => {
    const policy = round.policy_metrics || {};
    const propagation = round.propagation_metrics || {};
    const comments = round.comment_generation || {};
    return `<tr>
      <th>第${escapeHtml(round.step)}轮</th>
      <td>${percent(policy.negative_rate)}</td><td>${percent(policy.question_rate)}</td><td>${percent(policy.accept_rate)}</td>
      <td>${integerValue(policy.official_attitude_applicable_count)}</td><td>${escapeHtml(trendLabel(policy.global_trend))}</td>
      <td>${integerValue(propagation.exposure_count)}</td><td>${integerValue(propagation.reached_agent_count)}</td><td>${precisePercent(propagation.reach_rate)}</td>
      <td>${integerValue(propagation.source_agent_count)}</td><td>${integerValue(propagation.propagated_comment_count)}</td>
      <td>${integerValue(propagation.continued_propagation_count)}</td><td>${integerValue(propagation.continued_agent_count)}</td><td>${precisePercent(propagation.continuation_rate)}</td>
      <td>${integerValue(propagation.max_propagation_depth)}</td><td>${numberValue(propagation.average_propagation_depth)}</td><td>${numberValue(propagation.total_effective_weight)}</td>
    </tr>`;
  }).join("");
}

function compactObject(value) {
  if (Array.isArray(value)) return value.length ? value.join("；") : "—";
  if (value && typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? entries.map(([key, item]) => `${key}:${item}`).join("；") : "—";
  }
  return value === null || value === undefined || value === "" ? "—" : String(value);
}

function renderRoundQualityTable(strategy) {
  document.getElementById("round-quality-table").innerHTML = (strategy.rounds || []).map(round => {
    const comments = round.comment_generation || {};
    return `<tr>
      <th>第${escapeHtml(round.step)}轮</th>
      <td>${comments.quality_status ? escapeHtml(qualityLabel(comments.quality_status)) : "—"}</td>
      <td>${integerValue(comments.comment_count)}</td><td>${integerValue(comments.llm_comment_count)}</td>
      <td>${integerValue(comments.history_fallback_count)}</td><td>${integerValue(comments.emergency_fallback_count)}</td>
      <td>${integerValue(comments.fallback_count)}</td><td>${integerValue(comments.generation_attempts)}</td>
      <td>${integerValue(comments.initial_request_count)}</td><td>${integerValue(comments.refill_request_count)}</td>
      <td>${integerValue(comments.rescue_request_count)}</td><td>${integerValue(comments.generation_wave_count)}</td>
      <td>${integerValue(comments.quality_target_count)}</td><td>${integerValue(comments.model_returned_comment_count)}</td>
      <td class="long-cell">${escapeHtml(compactObject(comments.rejection_counts))}</td>
      <td class="long-cell">${escapeHtml(compactObject(comments.validation_errors))}</td>
    </tr>`;
  }).join("");
}

const stageLabels = {
  incremental_comment_generation: "增量评论生成",
  agent_decision: "Agent决策",
  metrics: "指标计算",
  initial_comment_pool: "初始评论池"
};

const requestLabels = {
  comment_angle: "评论角度规划",
  comment_generation: "评论生成",
  agent_decision: "Agent决策",
  global_trend: "全局趋势判断"
};

function compactRows(entries, labelMap, formatter = seconds) {
  return entries.map(([key, value]) => `<div><span>${escapeHtml(labelMap[key] || key)}</span><strong>${escapeHtml(formatter(value))}</strong></div>`).join("");
}

function renderPerformance(data) {
  const performance = data.performance || {};
  const requests = performance.llm_requests || {};
  document.getElementById("performance-summary").innerHTML = [
    [seconds(performance.total_duration_seconds), "总耗时"],
    [seconds(performance.experiment_duration_seconds), "策略实验耗时"],
    [seconds(performance.shared_baseline_duration_seconds), "共享基线耗时"],
    [seconds(performance.initial_comment_pool_duration_seconds), "初始评论池耗时"],
    [integerValue(requests.logical_request_count), "LLM逻辑请求"],
    [integerValue(requests.http_attempt_count), "HTTP尝试"],
    [integerValue(requests.retry_count), "重试"],
    [integerValue(requests.failed_request_count), "失败请求"],
    [seconds(requests.total_duration_seconds), "LLM累计耗时"]
  ].map(([value, label]) => `<article><strong>${escapeHtml(value)}</strong><span>${escapeHtml(label)}</span></article>`).join("");
  document.getElementById("stage-performance").innerHTML = compactRows(Object.entries(performance.stage_duration_seconds || {}), stageLabels);
  document.getElementById("strategy-performance").innerHTML = compactRows(
    Object.entries(performance.strategy_duration_seconds || {}),
    Object.fromEntries(data.strategies.map(strategy => [strategy.scenario_id, strategy.scenario_name]))
  );
  const byType = requests.by_type || {};
  document.getElementById("request-performance").innerHTML = Object.entries(byType).map(([key, value]) => `
    <div><span>${escapeHtml(requestLabels[key] || key)}</span><strong>${integerValue(value.logical_request_count)}次 / HTTP ${integerValue(value.http_attempt_count)} / 重试 ${integerValue(value.retry_count)} / 失败 ${integerValue(value.failed_request_count)} · ${seconds(value.total_duration_seconds)}</strong></div>`).join("");
}

function renderStrategies(data) {
  document.getElementById("strategy-grid").innerHTML = data.strategies.map((strategy, index) => {
    const propagation = strategy.propagation_summary || {};
    return `<article class="strategy-card" style="--accent:${colors[index % colors.length]}">
      <div><span class="strategy-index">0${index + 1}</span><h3>${escapeHtml(strategy.scenario_name)}</h3></div>
      <dl>
        <div><dt>最终趋势</dt><dd>${escapeHtml(trendLabel(strategy.final_trend))}</dd></div>
        <div><dt>最终负面率</dt><dd>${percent(metricValue(strategy, "negative_rate"))}</dd></div>
        <div><dt>累计负面强度</dt><dd>${numberValue(strategy.effect_metrics?.negative_area, 2)}</dd></div>
        <div><dt>官方投入</dt><dd>${escapeHtml(officialTiming(strategy))}</dd></div>
        <div><dt>传播深度</dt><dd>${propagation.max_propagation_depth ?? 0} 层</dd></div>
      </dl>
    </article>`;
  }).join("");
}

async function initialize() {
  const experimentId = new URLSearchParams(window.location.search).get("experiment_id");
  if (!experimentId) throw new Error("缺少 experiment_id，请从首页选择五策略实验。");
  const query = encodeURIComponent(experimentId);
  const data = await getJson(`/api/strategy/dashboard?experiment_id=${query}`);
  document.getElementById("experiment-id").textContent = `${data.experiment_id} · event_id=${data.event_id || "—"}`;
  document.getElementById("network-link").href = `/network/?experiment_id=${query}`;
  renderSummary(data);
  renderTrend(data);
  renderStrategies(data);
  renderEffectComparison(data);
  renderComparison(data);
  renderPerformance(data);
  const selector = document.getElementById("metric-strategy");
  selector.innerHTML = data.strategies.map((strategy, index) => `<option value="${index}">${escapeHtml(strategy.scenario_name)}</option>`).join("");
  const showSelectedMetrics = () => renderMetricDetail(data.strategies[Number(selector.value) || 0]);
  selector.addEventListener("change", showSelectedMetrics);
  showSelectedMetrics();
}

initialize().catch(error => {
  const notice = document.getElementById("notice");
  notice.textContent = error.message;
  notice.classList.remove("hidden");
});
