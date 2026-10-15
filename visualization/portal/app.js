const state = { experiments: [] };

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

function selectId(mode) {
  return mode === "strategy_comparison" ? "strategy-experiment" : "historical-experiment";
}

function renderMode(mode) {
  const select = document.getElementById(selectId(mode));
  const items = state.experiments.filter(item => {
    if (item.mode !== mode || item.status !== "completed") return false;
    if (mode === "historical_replay") {
      return item.capabilities.real_trend_comparison;
    }
    return item.capabilities.network && item.capabilities.comment_trace;
  });
  select.innerHTML = items.length
    ? items.map(item => `<option value="${escapeHtml(item.experiment_id)}">${escapeHtml(item.experiment_id)}</option>`).join("")
    : '<option value="">暂无已完成实验</option>';
  select.disabled = !items.length;
  const button = document.querySelector(`button[data-mode="${mode}"]`);
  button.disabled = !items.length;
  const updateMeta = () => {
    const item = items.find(candidate => candidate.experiment_id === select.value);
    const target = document.getElementById(mode === "strategy_comparison" ? "strategy-meta" : "historical-meta");
    if (!item) {
      target.textContent = "没有可进入的已完成批次";
      return;
    }
    const capability = mode === "historical_replay"
      ? `真实趋势可用 · ${item.capabilities.network && item.capabilities.comment_trace ? "网络追踪可用" : "旧批次无网络追踪"}`
      : `${item.scenario_count} 个场景 · 网络追踪可用`;
    target.textContent = `${item.step_count} 轮 · ${capability} · event_id=${item.event_id || "—"}`;
  };
  select.addEventListener("change", updateMeta);
  updateMeta();
}

function enterMode(mode) {
  const experimentId = document.getElementById(selectId(mode)).value;
  if (!experimentId) return;
  const target = mode === "historical_replay" ? "/historical/" : "/strategy/";
  window.location.href = `${target}?experiment_id=${encodeURIComponent(experimentId)}`;
}

async function initialize() {
  try {
    const result = await getJson("/api/catalog");
    state.experiments = result.experiments;
    renderMode("strategy_comparison");
    renderMode("historical_replay");
    document.querySelectorAll("button[data-mode]").forEach(button => {
      button.addEventListener("click", () => enterMode(button.dataset.mode));
    });
  } catch (error) {
    const notice = document.getElementById("notice");
    notice.textContent = error.message;
    notice.classList.remove("hidden");
  }
}

initialize();
