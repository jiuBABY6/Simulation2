"use strict";

const { createApp } = Vue;

createApp({
  data() {
    return {
      defaults: null,
      session: null,
      selectedStrategyId: "no_response",
      announcementState: {},
      eventContent: "",
      eventTopic: "社会事件",
      eventValence: "negative",
      entryMode: "dynamic",
      entryRound: 3,
      timelineRound: 2,
      timelineStatus: "clear",
      timelineText: "",
      busy: false,
      busyText: "",
      busyAction: null,
      autoRun: false,
      autoToken: 0,
      pauseRollbackPending: false,
      chartTooltip: null,
      poolOpen: false,
      poolDetail: null,
      agentOpen: false,
      agentDetail: null,
      networkHoverId: null,
      liveText: "正在连接服务",
      liveOk: false
    };
  },

  watch: {
    selectedStrategyId(strategyId) {
      this.ensureAnnouncementState(strategyId);
    },
    poolOpen(value) {
      if (value) this.resetPoolScroll();
    },
    poolDetail() {
      this.resetPoolScroll();
    }
  },

  computed: {
    strategies() {
      const list = (this.defaults?.strategies || []).filter(
        (item) => item.strategy_id !== "no_response"
      );
      return [
        { strategy_id: "__all__", strategy_name: "依次运行全部策略", ready: true },
        { strategy_id: "no_response", strategy_name: "不回应", ready: true },
        ...list
      ];
    },

    selectedStrategy() {
      return this.strategies.find(
        (item) => item.strategy_id === this.selectedStrategyId
      ) || null;
    },

    selectedAnnouncement() {
      return this.announcementState[this.selectedStrategyId] || null;
    },

    selectedHasContent() {
      return Boolean(
        this.selectedStrategyId &&
        !["__all__", "no_response"].includes(this.selectedStrategyId) &&
        this.announcementState[this.selectedStrategyId]
      );
    },

    strategyOverview() {
      return this.strategies.map((item, index) => {
        if (item.strategy_id === "__all__") {
          return {
            strategy_id: item.strategy_id,
            strategy_name: item.strategy_name,
            status: "all",
            ready: true,
            statement: "依次运行不回应与四种内置公告策略"
          };
        }
        if (item.strategy_id === "no_response") {
          return {
            strategy_id: item.strategy_id,
            strategy_name: item.strategy_name,
            status: "none",
            ready: true,
            statement: "不发布官方公告"
          };
        }
        const content = this.announcementState[item.strategy_id] || {};
        return {
          strategy_id: item.strategy_id,
          strategy_name: item.strategy_name,
          status: content.status || "none",
          ready:
            item.strategy_id !== "custom" ||
            Boolean(content.text?.trim() && content.status !== "none"),
          statement: content.text?.trim() || "尚未填写公告内容"
        };
      });
    },

    contentStrategies() {
      return (this.defaults?.official_default?.content_strategies || []).map((item) => ({
        ...item,
        ready:
          item.strategy_id !== "custom" ||
          Boolean(this.announcementState[item.strategy_id]?.text?.trim()) &&
          this.announcementState[item.strategy_id]?.status !== "none"
      }));
    },

    customReady() {
      const item = this.announcementState.custom;
      return Boolean(item && item.text.trim() && item.status !== "none");
    },

    snapshot() {
      return this.session?.snapshot || null;
    },

    agents() {
      return this.snapshot?.agents || [];
    },

    agentNetworkNodes() {
      const positions = this.buildAgentNetworkLayout(this.agents.length);
      return this.agents.map((agent, index) => ({
        ...agent,
        ...positions[index],
        index
      }));
    },

    agentNetworkEdges() {
      const nodes = this.agentNetworkNodes;
      const edges = [];
      for (let source = 0; source < nodes.length; source += 1) {
        for (let target = source + 1; target < nodes.length; target += 1) {
          const from = nodes[source];
          const to = nodes[target];
          edges.push({
            id: `${from.agent_id}-${to.agent_id}`,
            sourceId: from.agent_id,
            targetId: to.agent_id,
            x1: from.x,
            y1: from.y,
            x2: to.x,
            y2: to.y,
            index: edges.length
          });
        }
      }
      return edges;
    },

    networkActive() {
      return Boolean(
        this.agents.length &&
        this.session &&
        ["baseline", "scenario"].includes(this.session.phase) &&
        !this.session.paused &&
        !this.pauseRollbackPending
      );
    },

    networkStatusText() {
      if (!this.agents.length) return "等待 Agent 初始化";
      if (["completed", "completed_no_entry", "failed", "not_run"].includes(this.session?.status)) {
        return "全连接网络已结束";
      }
      if (this.networkActive) return "全连接网络动态运行中";
      return this.session?.phase === "created" ? "全连接网络待运行" : "全连接网络已暂停";
    },

    metricsRows() {
      return this.snapshot?.metrics_history || [];
    },

    latestMetrics() {
      return this.metricsRows.length ? this.metricsRows[this.metricsRows.length - 1] : null;
    },

    metricCards() {
      const policy = this.latestMetrics?.policy_metrics || {};
      return [
        ["负面率", policy.negative_rate],
        ["质疑率", policy.question_rate],
        ["接受率", policy.accept_rate],
        ["趋势", this.latestMetrics?.global_trend || "—"]
      ];
    },

    comments() {
      return this.snapshot?.latest_comments || [];
    },

    commentHistory() {
      return this.snapshot?.comment_history || [];
    },

    timeline() {
      return this.session?.announcement_timeline || [];
    },

    summaryCards() {
      if (!this.session) return [];
      const phase = {
        created: "已创建",
        baseline: "进场前基线",
        scenario: "策略运行",
        completed: "已完成",
        not_run: "未运行"
      }[this.session.phase] || this.session.phase;
      return [
        ["状态", this.session.status || "—", this.session.paused ? "已暂停" : "可推进"],
        ["阶段", phase, this.session.current_step ? `第 ${this.session.current_step} 轮` : "—"],
        ["官方进场", this.session.response_step ? `第 ${this.session.response_step} 轮` : "未进场", this.session.entry_reason || "—"],
        ["完成步数", this.session.completed_step_count || 0, `总计 ${this.session.max_steps || 10} 轮`]
      ];
    },

    agentSummary() {
      const count = (emotion) => this.agents.filter((item) => item.current_emotion === emotion).length;
      return [
        ["Agent 总数", this.agents.length],
        ["负面", count("negative")],
        ["中性", count("neutral")],
        ["正面", count("positive")]
      ];
    },

    commentsSummary() {
      const total = this.commentHistory.reduce((sum, item) => sum + (item.comment_count || 0), 0);
      const llm = this.commentHistory.reduce((sum, item) => sum + (item.llm_comment_count || 0), 0);
      const negative = this.comments.filter((item) => item.emotion === "negative").length;
      return [
        ["最新轮次", this.snapshot?.latest_step || "—"],
        ["当前评论", this.comments.length],
        ["LLM 占比", total ? this.percent(llm / total) : "—"],
        ["最新负面", this.comments.length ? this.percent(negative / this.comments.length) : "—"]
      ];
    },

    phaseLine() {
      if (!this.session) return "创建会话后开始控制";
      if (this.pauseRollbackPending) return "正在回退到上一轮结束状态";
      if (this.autoRun || this.busy) return "自动运行中";
      if (this.session.paused) return "已暂停，点击“继续运行”恢复";
      return "等待运行";
    },

    currentStrategyText() {
      const session = this.session;
      if (!session) return "尚未选择策略";
      const name = this.strategyName(session.selected_strategy_id);
      const timing = session.entry_timing?.mode === "fixed_round"
        ? `固定第 ${session.entry_timing.round} 轮进场`
        : "动态进场";
      return `${session.mode === "all" ? "全部策略" : `当前策略：${name}`} · ${timing}`;
    },

    metricsSvg() {
      return this.buildMetricsSvg();
    }
  },

  mounted() {
    this.initialize();
  },

  methods: {
    resetPoolScroll() {
      this.$nextTick(() => {
        const drawer = this.$refs.poolDrawerBody;
        if (drawer) drawer.scrollTop = 0;
      });
    },

    ensureAnnouncementState(strategyId) {
      if (!strategyId || this.announcementState[strategyId]) return;
      const item = (this.defaults?.official_default?.content_strategies || [])
        .find((strategy) => strategy.strategy_id === strategyId);
      if (!item) return;
      this.announcementState[strategyId] = {
        text: item.official_statement || "",
        status: item.official_statement_status || "none"
      };
    },

    esc(value) {
      return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
        "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
      }[ch]));
    },

    percent(value) {
      if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
      return `${Math.round(Number(value) * 100)}%`;
    },

    async api(url, options = {}) {
      const response = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options
      });
      const data = await response.json();
      if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
      return data;
    },

    async initialize() {
      try {
        this.defaults = await this.api("/api/input/defaults");
        const event = this.defaults.event_default || {};
        this.eventContent = event.event_content || "";
        this.eventTopic = event.event_labels?.topic || "社会事件";
        this.eventValence = event.event_labels?.event_valence || "negative";
        for (const item of this.defaults.official_default?.content_strategies || []) {
          this.announcementState[item.strategy_id] = {
            text: item.official_statement || "",
            status: item.official_statement_status || "none"
          };
        }
        const sessionId = location.hash.replace(/^#/, "");
        if (sessionId) {
          this.session = await this.api(`/api/sessions/${encodeURIComponent(sessionId)}`);
        }
        this.setLive("输入已加载", true);
      } catch (error) {
        this.setLive(error.message, false);
      }
    },

    setLive(text, ok) {
      this.liveText = text;
      this.liveOk = ok;
    },

    strategyName(strategyId) {
      if (strategyId === "__all__") return "依次运行全部策略";
      const item = this.strategies.find((strategy) => strategy.strategy_id === strategyId);
      return item?.strategy_name || strategyId || "—";
    },

    selectStrategy(strategyId) {
      if (strategyId === "custom" && !this.customReady) {
        this.setLive("custom 公告为空，先填写公告内容", false);
        return;
      }
      this.selectedStrategyId = strategyId;
    },

    isStrategyReady(id) {
      if (id === "custom") return this.customReady;
      return true;
    },

    eventInput() {
      return {
        event_content: this.eventContent.trim(),
        event_labels: {
          topic: this.eventTopic,
          event_valence: this.eventValence
        }
      };
    },

    officialContentInput() {
      const result = {};
      for (const item of Object.values(this.contentStrategies)) {
        result[item.strategy_id] = {
          official_statement: item.official_statement,
          official_statement_status: item.official_statement_status
        };
      }
      return result;
    },

    editableContentInput() {
      const result = {};
      for (const item of this.contentStrategies) {
        const editable = this.announcementState[item.strategy_id] || {};
        result[item.strategy_id] = {
          official_statement: editable.text || "",
          official_statement_status: editable.status || "none"
        };
      }
      return result;
    },

    entryTimingInput() {
      if (this.entryMode !== "fixed_round") return { mode: "dynamic" };
      return { mode: "fixed_round", round: Number(this.entryRound) };
    },

    async previewInputs() {
      this.withBusy("正在校验输入", async () => {
        const data = await this.api("/api/input/preview", {
          method: "POST",
          body: JSON.stringify({
            web_event_input: this.eventInput(),
            official_content_input: this.editableContentInput(),
            entry_timing_input: this.entryTimingInput()
          })
        });
        this.setLive("输入校验通过", true);
        return data;
      });
    },

    async createSession() {
      if (this.selectedStrategyId === "custom" && !this.customReady) {
        this.setLive("custom 公告为空，无法创建会话", false);
        return;
      }
      await this.withBusy("正在创建会话批次", async () => {
        const data = await this.api("/api/sessions", {
          method: "POST",
          body: JSON.stringify({
            web_event_input: this.eventInput(),
            official_content_input: this.editableContentInput(),
            entry_timing_input: this.entryTimingInput(),
            selected_strategy_id: this.selectedStrategyId
          })
        });
        this.session = data;
        history.replaceState(null, "", `#${data.experiment_id}`);
        this.setLive("会话已创建", true);
      });
    },

    async sessionAction(action, body = {}) {
      if (!this.session || this.busy) return;
      this.busyAction = action;
      await this.withBusy(
        ["continue", "step"].includes(action) ? "推演执行中" : "请求处理中",
        async () => {
          this.session = await this.api(
            `/api/sessions/${encodeURIComponent(this.session.experiment_id)}/${action}`,
            { method: "POST", body: JSON.stringify(body) }
          );
          if (this.pauseRollbackPending && ["continue", "step"].includes(action)) {
            this.pauseRollbackPending = false;
            this.session = await this.api(
              `/api/sessions/${encodeURIComponent(this.session.experiment_id)}/rollback`,
              { method: "POST", body: JSON.stringify({ steps: 1 }) }
            );
          }
        }
      );
      this.busyAction = null;
    },

    async withBusy(text, task) {
      this.busy = true;
      this.busyText = text;
      try {
        await task();
      } catch (error) {
        this.setLive(error.message, false);
      } finally {
        this.busy = false;
        this.busyText = "";
      }
    },

    async startRun() {
      await this.sessionAction("start");
      if (this.session && this.session.mode !== "all") {
        this.autoRun = true;
        this.runAutoLoop();
      }
    },

    async continueRun() {
      if (!this.session || this.busy) return;
      this.autoRun = true;
      this.runAutoLoop();
    },

    async pauseRun() {
      this.autoRun = false;
      this.autoToken += 1;
      if (this.busy && this.busyAction === "continue") {
        this.pauseRollbackPending = true;
        this.setLive("当前轮完成后将回退到上一轮结束状态", true);
        return;
      }
      if (this.busy) return;
      if (!this.session) return;
      try {
        this.session = await this.api(
          `/api/sessions/${encodeURIComponent(this.session.experiment_id)}/pause`,
          { method: "POST", body: "{}" }
        );
        this.setLive("已暂停", false);
      } catch (error) {
        this.setLive(error.message, false);
      }
    },

    async rollbackRun() {
      this.autoRun = false;
      this.autoToken += 1;
      await this.sessionAction("rollback", { steps: 1 });
    },

    async restartRun() {
      this.autoRun = false;
      this.autoToken += 1;
      const previousId = this.session?.experiment_id || null;
      await this.sessionAction("restart");
      if (
        this.session &&
        this.session.experiment_id &&
        this.session.experiment_id !== previousId
      ) {
        history.replaceState(null, "", `#${this.session.experiment_id}`);
        this.setLive("新批次已创建", true);
      }
    },

    async runAll() {
      this.autoRun = false;
      if (!this.session) return;
      await this.withBusy("五种策略依次运行中", async () => {
        this.session = await this.api(
          `/api/sessions/${encodeURIComponent(this.session.experiment_id)}/run`,
          { method: "POST", body: "{}" }
        );
      });
    },

    async runAutoLoop() {
      const token = ++this.autoToken;
      while (this.autoRun && token === this.autoToken) {
        const session = this.session;
        if (!session || ["completed", "completed_no_entry", "failed", "not_run"].includes(session.status)) {
          this.autoRun = false;
          break;
        }
        if (!["baseline", "scenario"].includes(session.phase)) {
          this.autoRun = false;
          break;
        }
        await new Promise((resolve) => setTimeout(resolve, 250));
        await this.sessionAction("continue");
      }
    },

    async addAnnouncement() {
      if (!this.session || !this.session.paused || this.busy) return;
      if (!this.timelineText.trim()) {
        this.setLive("请填写公告内容", false);
        return;
      }
      await this.withBusy("正在追加公告", async () => {
        this.session = await this.api(
          `/api/sessions/${encodeURIComponent(this.session.experiment_id)}/announcement`,
          {
            method: "POST",
            body: JSON.stringify({
              round: Number(this.timelineRound),
              official_statement: this.timelineText.trim(),
              official_statement_status: this.timelineStatus
            })
          }
        );
        this.timelineText = "";
        this.setLive("公告已加入时间线", true);
      });
    },

    canStart() {
      return Boolean(this.session && this.session.phase === "created" && !this.busy);
    },

    canContinue() {
      return Boolean(
        this.session &&
        ["baseline", "scenario"].includes(this.session.phase) &&
        !this.busy
      );
    },

    canPause() {
      return Boolean(
        this.session &&
        ["baseline", "scenario"].includes(this.session.phase) &&
        ((this.busy && this.busyAction === "continue") || this.autoRun || !this.session.paused)
      );
    },

    canRollback() {
      return Boolean(this.session && !this.busy && (this.session.completed_step_count || 0) > 0);
    },

    canAddAnnouncement() {
      return Boolean(this.session && this.session.paused && !this.busy);
    },

    openPool() {
      this.poolOpen = true;
      this.poolDetail = null;
    },

    openAgent() {
      this.agentOpen = true;
      this.agentDetail = null;
      this.networkHoverId = null;
    },

    openAgentDetail(agent) {
      this.networkHoverId = null;
      this.agentDetail = agent;
    },

    setNetworkHover(agentId) {
      this.networkHoverId = agentId || null;
    },

    isNetworkEdgeActive(edge) {
      return Boolean(
        this.networkHoverId &&
        (edge.sourceId === this.networkHoverId || edge.targetId === this.networkHoverId)
      );
    },

    buildMetricsSvg() {
      const metrics = this.metricsRows;
      const maxStep = this.session?.max_steps || 10;
      const timeline = this.timeline;
      const colors = { negative: "#dc2626", question: "#ea580c", accept: "#16a34a" };
      const steps = Array.from({ length: maxStep }, (_, index) => index + 1);
      const metricsByStep = Object.fromEntries(metrics.map((item) => [item.step, item]));
      const width = 860;
      const height = 270;
      const margin = { left: 48, right: 22, top: 26, bottom: 34 };
      const chartWidth = width - margin.left - margin.right;
      const chartHeight = height - margin.top - margin.bottom;
      const x = (step) => margin.left + ((step - 1) / Math.max(maxStep - 1, 1)) * chartWidth;
      const y = (value) => margin.top + (1 - value) * chartHeight;
      let svg = `<svg viewBox="0 0 ${width} ${height}" role="img">`;
      for (let tick = 0; tick <= 4; tick++) {
        const value = tick / 4;
        const yy = y(value);
        svg += `<line x1="${margin.left}" x2="${width - margin.right}" y1="${yy}" y2="${yy}" stroke="#f2e2cf"/>`;
        svg += `<text x="${margin.left - 8}" y="${yy + 4}" text-anchor="end" fill="#b58c69" font-size="10">${Math.round(value * 100)}%</text>`;
      }
      steps.forEach((step) => {
        svg += `<text x="${x(step)}" y="${height - 9}" text-anchor="middle" fill="#a77a54" font-size="10">${step}</text>`;
      });
      if (this.session?.response_step) {
        const xx = x(this.session.response_step);
        svg += `<line x1="${xx}" x2="${xx}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#9a3412" stroke-width="1.6" stroke-dasharray="6 4"/>`;
        svg += `<text x="${xx + 5}" y="${margin.top + 13}" fill="#9a3412" font-size="10">官方进场</text>`;
      }
      timeline.forEach((event, index) => {
        const xx = x(event.round);
        svg += `<line x1="${xx}" x2="${xx}" y1="${margin.top}" y2="${height - margin.bottom}" stroke="#7358c7" stroke-width="1.4" stroke-dasharray="3 4"/>`;
        svg += `<text x="${xx + 5}" y="${margin.top + 27}" fill="#7358c7" font-size="10">公告${index + 1}</text>`;
      });
      const series = [
        ["负面率", "negative", "negative_rate"],
        ["质疑率", "question", "question_rate"],
        ["接受率", "accept", "accept_rate"]
      ];
      series.forEach(([name, key, field]) => {
        const points = steps
          .map((step) => {
            const value = metricsByStep[step]?.policy_metrics?.[field];
            return value === null || value === undefined ? null : { step, value };
          })
          .filter(Boolean);
        if (!points.length) return;
        const path = points.map((point, index) =>
          `${index ? "L" : "M"}${x(point.step).toFixed(1)},${y(point.value).toFixed(1)}`
        ).join("");
        svg += `<path d="${path}" fill="none" stroke="${colors[key]}" stroke-width="2.5"/>`;
        points.forEach((point) => {
          const text = `第${point.step}轮 ${name} ${this.percent(point.value)}`;
          svg += `<circle cx="${x(point.step).toFixed(1)}" cy="${y(point.value).toFixed(1)}" r="3.8" fill="#fff" stroke="${colors[key]}" stroke-width="2" data-tooltip="${this.esc(text)}"><title>${this.esc(text)}</title></circle>`;
        });
      });
      return `${svg}</svg>`;
    },

    handleChartMove(event) {
      const circle = event.target.closest("circle[data-tooltip]");
      if (!circle) {
        this.chartTooltip = null;
        return;
      }
      const rect = event.currentTarget.getBoundingClientRect();
      this.chartTooltip = {
        text: circle.dataset.tooltip,
        left: event.clientX - rect.left + 12,
        top: event.clientY - rect.top + 10
      };
    },

    emotionText(value) {
      return { positive: "正面", neutral: "中性", negative: "负面" }[value] || "—";
    },

    orientationText(value) {
      return {
        fact: "事实信息",
        opinion: "观点表达",
        questioning: "质疑提问"
      }[value] || value || "—";
    },

    emotionClass(value) {
      return value === "positive" ? "pos" : value === "negative" ? "neg" : "neu";
    },

    emotionBadgeHtml(value) {
      const cls = value === "positive" ? "pos" : value === "negative" ? "neg" : "neu";
      return `<span class="badge ${cls}">${this.esc(this.emotionText(value))}</span>`;
    },

    emotionColor(value) {
      return value === "positive" ? "#16a34a" : value === "negative" ? "#dc2626" : "#c2753d";
    },

    buildAgentNetworkLayout(count) {
      if (!count) return [];
      if (count === 1) return [{ x: 50, y: 50 }];

      const ring = (nodeCount, radiusX, radiusY, phase = 0) => {
        if (!nodeCount) return [];
        return Array.from({ length: nodeCount }, (_, index) => {
          const angle = -Math.PI / 2 + phase + (index / nodeCount) * Math.PI * 2;
          return {
            x: 50 + Math.cos(angle) * radiusX,
            y: 50 + Math.sin(angle) * radiusY
          };
        });
      };

      if (count === 2) return [{ x: 32, y: 50 }, { x: 68, y: 50 }];
      if (count <= 4) return ring(count, count === 3 ? 38 : 37, count === 3 ? 35 : 34);

      const outerCount = Math.max(Math.ceil(count * 0.6), 3);
      const innerCount = count - outerCount;
      return [
        ...ring(outerCount, 39, 36),
        ...ring(innerCount, 20, 19, Math.PI / outerCount)
      ];
    },

    networkNodeStyle(node) {
      return {
        left: `${node.x}%`,
        top: `${node.y}%`,
        "--node-delay": `${-((node.index % 7) * 0.19).toFixed(2)}s`
      };
    },

    networkEdgeStyle(edge) {
      return {
        "--flow-delay": `${-((edge.index % 11) * 0.23).toFixed(2)}s`,
        "--flow-duration": `${(2.2 + (edge.index % 5) * 0.22).toFixed(2)}s`
      };
    },

    commentEmotionBlock(comments) {
      const total = comments.length;
      const count = (emotion) => comments.filter((item) => item.emotion === emotion).length;
      const items = [
        ["negative", "#dc2626", "负面"],
        ["neutral", "#c2753d", "中性"],
        ["positive", "#16a34a", "正面"]
      ];
      const stack = `<div class="stack-bar">${items.map(([key, color]) => {
        const c = count(key);
        return c ? `<i style="width:${Math.max(c / total * 100, 0.4)}%;background:${color}"></i>` : "";
      }).join("")}</div>`;
      const legend = `<div class="stack-legend">${items.map(([key, color, label]) => `
        <span><i style="background:${color}"></i>${label}<b>${count(key)} · ${this.percent(count(key) / Math.max(total, 1))}</b></span>`).join("")}</div>`;
      return `<div class="visual-block"><h3>情绪分布</h3>${stack}${legend}</div>`;
    },

    commentCompositionBlock(comments) {
      const total = Math.max(comments.length, 1);
      const countBy = (field) => comments.reduce((result, item) => {
        if (item[field]) result[item[field]] = (result[item[field]] || 0) + 1;
        return result;
      }, {});
      const rows = (data, color = "#ea580c") => Object.entries(data)
        .sort((a, b) => b[1] - a[1])
        .slice(0, 6)
        .map(([name, count]) => `
          <div class="bar-row"><span>${this.esc(name)}</span><div class="bar"><i style="width:${count / total * 100}%;background:${color}"></i></div><b>${count}</b></div>`)
        .join("");
      return `<div class="visual-block">
        <h3>派系</h3>${rows(countBy("faction"))}
        ${Object.keys(countBy("orientation")).length ? `<h3 style="margin-top:10px">信息取向</h3>${rows(countBy("orientation"), "#6b8f8a")}` : ""}
      </div>`;
    }
  },

  template: `
  <div class="app" v-cloak>
    <header class="topbar">
      <div class="brand">
        <span class="brand-mark">舆</span>
        <div>
          <h1>舆情推演控制台</h1>
          <p>Simulation2 · Vue 控制台</p>
        </div>
      </div>
      <div class="top-status">
        <span class="live-dot" :class="{ off: !liveOk }"></span>
        <span>{{ liveText }}</span>
      </div>
    </header>

    <div class="workspace">
      <aside class="setup">
        <section class="panel">
          <div class="panel-head">
            <div><p class="eyebrow">1 · 事件</p><h2>事件输入</h2></div>
          </div>
          <label class="field"><span>事件正文</span><textarea v-model="eventContent" maxlength="5000"></textarea></label>
          <div class="form-row">
            <label class="field"><span>主题</span>
              <select v-model="eventTopic">
                <option>社会事件</option><option>新闻时事</option><option>娱乐</option><option>其他</option>
              </select>
            </label>
            <label class="field"><span>情绪倾向</span>
              <select v-model="eventValence">
                <option value="negative">负面</option><option value="neutral">中性</option><option value="positive">正面</option>
              </select>
            </label>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><p class="eyebrow">2 · 公告策略</p><h2>公告内容与策略</h2></div>
            <span class="count">7 项汇总</span>
          </div>
          <label class="field">
            <span>策略菜单</span>
            <select v-model="selectedStrategyId" class="strategy-select">
              <option v-for="row in strategyOverview" :key="row.strategy_id" :value="row.strategy_id">
                {{ row.strategy_name }}
              </option>
            </select>
          </label>
          <div class="selected-strategy-card">
            <div class="strategy-summary">
              <strong>{{ selectedStrategy?.strategy_name || '—' }}</strong>
              <span
                v-if="selectedStrategyId === 'custom' && !customReady"
                class="badge warn"
              >待填写公告</span>
            </div>
            <div v-if="['__all__','no_response'].includes(selectedStrategyId)" class="strategy-empty-note">
              {{ selectedStrategyId === '__all__' ? '依次运行不回应和四种内置公告策略。' : '该策略不发布官方公告。' }}
            </div>
            <template v-else-if="selectedAnnouncement">
              <label class="field">
                <span>公告内容</span>
                <textarea v-model="selectedAnnouncement.text" maxlength="5000"></textarea>
              </label>
              <label class="field">
                <span>声明状态</span>
                <select v-model="selectedAnnouncement.status">
                  <option value="clear">clear</option>
                  <option value="incomplete">incomplete</option>
                  <option value="conflict">conflict</option>
                  <option value="none">none</option>
                </select>
              </label>
            </template>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><p class="eyebrow">3 · 时机</p><h2>公告发布时间</h2></div>
          </div>
          <div class="form-row">
            <label class="field"><span>模式</span>
              <select v-model="entryMode">
                <option value="dynamic">动态进场</option>
                <option value="fixed_round">固定轮次</option>
              </select>
            </label>
            <label class="field"><span>固定轮次</span>
              <select v-model.number="entryRound" :disabled="entryMode !== 'fixed_round'">
                <option v-for="n in 9" :key="n" :value="n + 1">第 {{ n + 1 }} 轮</option>
              </select>
            </label>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><p class="eyebrow">4 · 暂停追加公告</p><h2>任意轮次追加</h2></div>
          </div>
          <div class="form-row">
            <label class="field"><span>发布轮次</span>
              <select v-model.number="timelineRound">
                <option v-for="n in 9" :key="n" :value="n + 1">第 {{ n + 1 }} 轮</option>
              </select>
            </label>
            <label class="field"><span>状态</span>
              <select v-model="timelineStatus">
                <option value="clear">clear</option><option value="incomplete">incomplete</option><option value="conflict">conflict</option>
              </select>
            </label>
          </div>
          <label class="field"><span>公告内容</span><textarea v-model="timelineText" maxlength="5000"></textarea></label>
          <div class="setup-actions">
            <button class="button primary" :disabled="!canAddAnnouncement()" @click="addAnnouncement">添加到时间线</button>
          </div>
          <div class="timeline-list">
            <div v-if="!timeline.length" class="empty">暂无追加公告</div>
            <div v-for="(item, index) in timeline" :key="item.round" class="timeline-item">
              <b>公告{{ index + 1 }} · 第{{ item.round }}轮</b>
              <span :title="item.official_statement">{{ item.official_statement }}</span>
            </div>
          </div>
        </section>

        <div class="setup-actions">
          <button class="button ghost" :disabled="busy" @click="previewInputs">预览输入</button>
          <button class="button primary" :disabled="busy" @click="createSession">创建会话</button>
        </div>
      </aside>

      <main class="control">
        <section class="panel">
          <div class="panel-head">
            <div><p class="eyebrow">会话</p><h2>{{ session ? (session.mode === 'all' ? '全部策略会话' : '单策略会话') : '尚未创建' }}</h2></div>
            <span class="count">{{ session?.experiment_id || '' }}</span>
          </div>
          <div class="summary-strip">
            <div v-for="card in summaryCards" :key="card[0]" class="summary-card">
              <div class="label">{{ card[0] }}</div><div class="value">{{ card[1] }}</div><div class="detail">{{ card[2] }}</div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div><p class="eyebrow">实时</p><h2>舆情指标</h2></div>
            <span class="count">{{ metricsRows.length }} 轮</span>
          </div>
          <div class="mini-strip">
            <div v-for="card in metricCards" :key="card[0]" class="mini-card">
              <b>{{ typeof card[1] === 'number' ? percent(card[1]) : card[1] }}</b><span>{{ card[0] }}</span>
            </div>
          </div>
          <div class="chart-wrap" @mousemove="handleChartMove" @mouseleave="chartTooltip = null">
            <div class="line-chart" v-html="metricsSvg"></div>
            <div v-if="chartTooltip" class="chart-tooltip" :style="{ left: chartTooltip.left + 'px', top: chartTooltip.top + 'px' }">{{ chartTooltip.text }}</div>
          </div>
        </section>

        <section class="live-grid">
          <article class="panel detail-trigger" @click="openAgent">
            <div class="panel-head"><div><p class="eyebrow">实时</p><h2>Agent 状态</h2></div><span class="count">{{ agents.length }} 个 Agent</span></div>
            <div class="mini-strip">
              <div v-for="card in agentSummary" :key="card[0]" class="mini-card"><b>{{ card[1] }}</b><span>{{ card[0] }}</span></div>
            </div>
          </article>
          <article class="panel detail-trigger" @click="openPool">
            <div class="panel-head"><div><p class="eyebrow">实时</p><h2>舆论池</h2></div><span class="count">{{ comments.length }} 条</span></div>
            <div class="mini-strip">
              <div v-for="card in commentsSummary" :key="card[0]" class="mini-card"><b>{{ card[1] }}</b><span>{{ card[0] }}</span></div>
            </div>
          </article>
        </section>

        <section class="panel">
          <div class="panel-head"><div><p class="eyebrow">运行</p><h2>会话控制</h2></div></div>
          <div class="control-row">
            <button v-if="session?.mode !== 'all'" class="button primary" :disabled="!canStart()" @click="startRun">启动</button>
            <button v-if="session?.mode === 'all'" class="button primary" :disabled="busy || !['created','ready'].includes(session?.phase)" @click="runAll">运行全部策略</button>
            <button class="button" :disabled="!canContinue()" @click="continueRun">继续运行</button>
            <button class="button" :disabled="!canPause()" @click="pauseRun">暂停</button>
            <button class="button" :disabled="!canRollback()" @click="rollbackRun">回滚一步</button>
            <button class="button danger" :disabled="busy || !session" @click="restartRun">重启新批次</button>
          </div>
          <div v-if="busy" class="busy">{{ busyText }}</div>
          <div class="current-strategy">{{ currentStrategyText }}</div>
        </section>

        <section class="panel">
          <div class="panel-head"><div><p class="eyebrow">状态</p><h2>推进状态</h2></div><span class="count">{{ phaseLine }}</span></div>
          <div class="progress-track">
            <div v-for="n in (session?.max_steps || 10)" :key="n" class="step-chip" :class="{ done: n <= (session?.completed_step_count || 0), entry: session?.response_step === n }"></div>
          </div>
        </section>
      </main>
    </div>

    <div v-if="poolOpen" class="drawer-backdrop" @click="poolOpen = false"></div>
    <aside v-if="poolOpen" class="comment-drawer open">
      <div class="drawer-head">
        <div><p class="eyebrow">POOL DETAIL</p><h2>舆论池详情</h2></div>
        <button class="button ghost" @click="poolOpen = false">关闭</button>
      </div>
      <div ref="poolDrawerBody" class="drawer-body">
        <template v-if="poolDetail === null">
          <div class="summary-strip">
            <div v-for="card in commentsSummary" :key="card[0]" class="summary-card"><div class="label">{{ card[0] }}</div><div class="value">{{ card[1] }}</div></div>
          </div>
          <div class="comments-visual" v-html="commentEmotionBlock(comments) + commentCompositionBlock(comments)"></div>
          <div class="comment-list">
            <article v-for="(comment, index) in comments" :key="comment.comment_id || index" class="live-comment clickable" @click="poolDetail = comment">
              <div class="feed-meta" v-html="emotionBadgeHtml(comment.emotion) + (comment.faction ? '<span class=&quot;badge&quot;>' + esc(comment.faction) + '</span>' : '')"></div>
              <p>{{ comment.text }}</p>
            </article>
          </div>
        </template>
        <template v-else>
          <div class="drawer-detail-compact pool-detail-compact">
            <button class="button ghost drawer-back-button" @click="poolDetail = null">返回舆论池</button>
            <p class="pool-detail-text">{{ poolDetail.text }}</p>
            <div class="kv-grid">
              <div class="kv"><b>{{ poolDetail.comment_id || '—' }}</b><span>评论编号</span></div>
              <div class="kv"><b>{{ poolDetail.faction || '—' }}</b><span>派系</span></div>
              <div class="kv"><b>{{ orientationText(poolDetail.orientation) }}</b><span>信息取向</span></div>
              <div class="kv"><b>{{ poolDetail.stance || '—' }}</b><span>立场</span></div>
            </div>
          </div>
        </template>
      </div>
    </aside>

    <div v-if="agentOpen" class="drawer-backdrop" @click="agentOpen = false"></div>
    <aside v-if="agentOpen" class="comment-drawer open">
      <div class="drawer-head">
        <div><p class="eyebrow">AGENT DETAIL</p><h2>Agent 状态</h2></div>
        <button class="button ghost" @click="agentOpen = false">关闭</button>
      </div>
      <div class="drawer-body">
        <template v-if="agentDetail === null">
          <div class="agent-network" :class="{ 'is-live': networkActive, 'has-focus': networkHoverId }">
            <div class="network-toolbar">
              <span class="network-state"><i></i>{{ networkStatusText }}</span>
              <span>{{ agents.length }} 节点 · {{ agentNetworkEdges.length }} 条全连接</span>
            </div>
            <div class="network-stage">
              <svg class="network-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
                <g class="network-base-lines">
                  <line
                    v-for="edge in agentNetworkEdges"
                    :key="'base-' + edge.id"
                    class="network-edge-base"
                    :x1="edge.x1"
                    :y1="edge.y1"
                    :x2="edge.x2"
                    :y2="edge.y2"
                  />
                </g>
                <g class="network-flow-lines">
                  <line
                    v-for="edge in agentNetworkEdges"
                    :key="'flow-' + edge.id"
                    class="network-edge-flow"
                    :class="{ active: isNetworkEdgeActive(edge) }"
                    :x1="edge.x1"
                    :y1="edge.y1"
                    :x2="edge.x2"
                    :y2="edge.y2"
                    :style="networkEdgeStyle(edge)"
                  />
                </g>
              </svg>
              <button
                v-for="agent in agentNetworkNodes"
                :key="agent.agent_id"
                type="button"
                class="network-node"
                :class="{ 'is-commenting': agent.last_action === 'comment', dimmed: networkHoverId && networkHoverId !== agent.agent_id }"
                :style="networkNodeStyle(agent)"
                :title="agent.agent_id"
                @mouseenter="setNetworkHover(agent.agent_id)"
                @mouseleave="setNetworkHover(null)"
                @focus="setNetworkHover(agent.agent_id)"
                @blur="setNetworkHover(null)"
                @click="openAgentDetail(agent)"
              >
                <span class="agent-orb" :style="{ '--orb': emotionColor(agent.current_emotion), '--ring': '#ffffff' }">{{ agent.agent_id.slice(-4) }}</span>
                <small>{{ emotionText(agent.current_emotion) }}</small>
              </button>
              <div v-if="!agents.length" class="empty network-empty">等待 Agent 初始化</div>
            </div>
          </div>
          <div class="timeline-list">
            <div v-for="agent in agents" :key="agent.agent_id" class="timeline-item">
              <b>{{ agent.agent_id.slice(-4) }}</b>
              <span>{{ emotionText(agent.current_emotion) }} · {{ agent.last_comment_faction || '无派系' }}</span>
            </div>
          </div>
        </template>
        <template v-else>
          <div class="drawer-detail-compact agent-detail-compact">
            <button class="button ghost drawer-back-button" @click="agentDetail = null">返回全部 Agent</button>
            <div class="kv-grid">
              <div class="kv"><b>{{ agentDetail.agent_id }}</b><span>Agent</span></div>
              <div class="kv"><b>{{ emotionText(agentDetail.current_emotion) }}</b><span>情绪</span></div>
              <div class="kv"><b>{{ agentDetail.last_comment_faction || '—' }}</b><span>评论派系</span></div>
            </div>
            <p class="live-comment">{{ agentDetail.last_comment || '本轮未发表评论' }}</p>
          </div>
        </template>
      </div>
    </aside>
  </div>
  `
}).mount("#app");
