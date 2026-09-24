globalThis.WEB2_TEMPLATE = `
<div class="v2-app" v-cloak>
  <header class="v2-topbar">
    <div class="v2-brand">
      <span class="v2-brand-mark">舆</span>
      <div>
        <h1>舆情推演控制台 V2</h1>
        <p>状态总览 · 单屏控制</p>
      </div>
    </div>
    <div class="v2-session-id">{{ session?.experiment_id || '尚未创建会话' }}</div>
    <div class="v2-live-status">
      <i :class="{ off: !liveOk }"></i>
      <span>{{ liveText }}</span>
    </div>
  </header>

  <div class="v2-layout">
    <main class="v2-dashboard">
      <section class="v2-status-strip">
        <div
          v-for="card in (summaryCards.length ? summaryCards : [['状态','未创建','—'],['阶段','待配置','—'],['官方进场','—','—'],['完成步数','0','总计 10 轮']])"
          :key="card[0]"
          class="v2-status-item"
        >
          <span>{{ card[0] }}</span>
          <strong>{{ card[1] }}</strong>
          <small>{{ card[2] }}</small>
        </div>
      </section>

      <div class="v2-visual-grid">
        <section class="v2-card v2-agent-card">
          <div class="v2-card-head">
            <div>
              <p>AGENT NETWORK</p>
              <h2>Agent 关系网络</h2>
            </div>
            <div class="v2-network-meta">
              <span class="v2-network-state"><i></i>{{ networkStatusText }}</span>
              <span>{{ agents.length }} 节点 · {{ agentNetworkEdges.length }} 连接</span>
            </div>
          </div>
          <div class="v2-network-stage" :class="{ 'is-live': networkActive, 'has-focus': networkHoverId }">
            <svg class="v2-network-lines" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
              <g>
                <line
                  v-for="edge in agentNetworkEdges"
                  :key="'base-' + edge.id"
                  class="v2-edge-base"
                  :x1="edge.x1"
                  :y1="edge.y1"
                  :x2="edge.x2"
                  :y2="edge.y2"
                />
              </g>
              <g>
                <line
                  v-for="edge in agentNetworkEdges"
                  :key="'flow-' + edge.id"
                  class="v2-edge-flow"
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
              class="v2-agent-node"
              :class="{ commenting: agent.last_action === 'comment', dimmed: networkHoverId && networkHoverId !== agent.agent_id }"
              :style="networkNodeStyle(agent)"
              :title="agent.agent_id"
              @mouseenter="setNetworkHover(agent.agent_id)"
              @mouseleave="setNetworkHover(null)"
              @focus="setNetworkHover(agent.agent_id)"
              @blur="setNetworkHover(null)"
              @click="openAgentDetail(agent)"
            >
              <span
                class="v2-agent-orb"
                :style="{ '--orb': emotionColor(agent.current_emotion), '--ring': '#ffffff' }"
              >{{ agent.agent_id.slice(-4) }}</span>
              <small>{{ emotionText(agent.current_emotion) }}</small>
            </button>
            <div v-if="!agents.length" class="v2-empty">等待 Agent 初始化</div>
          </div>
        </section>

        <section class="v2-card v2-metrics-card">
          <div class="v2-card-head">
            <div>
              <p>PUBLIC OPINION</p>
              <h2>舆情指标</h2>
            </div>
            <span>{{ metricsRows.length }} 轮</span>
          </div>
          <div class="v2-mini-metrics">
            <div v-for="card in metricCards" :key="card[0]">
              <strong>{{ typeof card[1] === 'number' ? percent(card[1]) : card[1] }}</strong>
              <span>{{ card[0] }}</span>
            </div>
          </div>
          <div class="v2-chart-wrap" @mousemove="handleChartMove" @mouseleave="chartTooltip = null">
            <div class="v2-line-chart" v-html="metricsSvg"></div>
            <div
              v-if="chartTooltip"
              class="v2-chart-tooltip"
              :style="{ left: chartTooltip.left + 'px', top: chartTooltip.top + 'px' }"
            >{{ chartTooltip.text }}</div>
          </div>
        </section>

        <section class="v2-card v2-pool-card">
          <div class="v2-card-head">
            <div>
              <p>COMMENT POOL</p>
              <h2>舆论池</h2>
            </div>
            <span>{{ comments.length }} 条</span>
          </div>
          <div class="v2-pool-charts">
            <section class="v2-pool-chart v2-emotion-chart">
              <div class="v2-chart-title">
                <h3>情绪构成</h3>
                <span>{{ comments.length }} 条</span>
              </div>
              <div class="v2-donut-layout">
                <div class="v2-donut-chart" v-html="poolEmotionChartSvg"></div>
                <div class="v2-chart-legend">
                  <div v-for="item in poolEmotionStats" :key="item.key">
                    <i :style="{ background: item.color }"></i>
                    <span>{{ item.label }}</span>
                    <b>{{ item.count }}</b>
                    <small>{{ percent(item.rate) }}</small>
                  </div>
                </div>
              </div>
            </section>
            <section class="v2-pool-chart">
              <div class="v2-chart-title">
                <h3>主要派系</h3>
                <span>Top {{ Math.min(poolFactionStats.length, 6) }}</span>
              </div>
              <div class="v2-bar-chart">
                <div v-for="item in poolFactionStats" :key="item.key" class="v2-bar-row">
                  <span :title="item.label">{{ item.label }}</span>
                  <div><i :style="{ width: percent(item.rate) }"></i></div>
                  <b>{{ item.count }}</b>
                </div>
                <p v-if="!poolFactionStats.length">暂无派系数据</p>
              </div>
            </section>
            <section class="v2-pool-chart">
              <div class="v2-chart-title">
                <h3>信息取向</h3>
                <span>Top {{ Math.min(poolOrientationStats.length, 6) }}</span>
              </div>
              <div class="v2-bar-chart">
                <div v-for="item in poolOrientationStats" :key="item.key" class="v2-bar-row">
                  <span :title="item.label">{{ item.label }}</span>
                  <div><i :style="{ width: percent(item.rate) }"></i></div>
                  <b>{{ item.count }}</b>
                </div>
                <p v-if="!poolOrientationStats.length">暂无取向数据</p>
              </div>
            </section>
          </div>
        </section>
      </div>

      <section class="v2-control-bar">
        <div class="v2-progress">
          <div class="v2-progress-line">
            <i v-for="n in (session?.max_steps || 10)" :key="n" :class="{ done: n <= (session?.completed_step_count || 0), entry: session?.response_step === n }"></i>
          </div>
          <span>{{ phaseLine }}</span>
        </div>
        <div class="v2-controls">
          <button v-if="session?.mode !== 'all'" class="v2-btn primary" :disabled="!canStart()" @click="startRun">启动</button>
          <button v-if="session?.mode === 'all'" class="v2-btn primary" :disabled="busy || !['created','ready'].includes(session?.phase)" @click="runAll">运行全部策略</button>
          <button class="v2-btn" :disabled="!canContinue()" @click="continueRun">继续运行</button>
          <button class="v2-btn" :disabled="!canPause()" @click="pauseRun">暂停</button>
          <button class="v2-btn" :disabled="!canRollback()" @click="rollbackRun">回滚一步</button>
          <button class="v2-btn danger" :disabled="busy || !session" @click="restartRun">重启新批次</button>
        </div>
        <div class="v2-current-strategy">{{ busy ? busyText : currentStrategyText }}</div>
      </section>
    </main>

    <aside class="v2-input-rail">
      <section class="v2-rail-block v2-event-block">
        <div class="v2-rail-title"><span>01</span><h2>事件输入</h2></div>
        <label class="v2-field">
          <span>事件正文</span>
          <textarea v-model="eventContent" maxlength="5000"></textarea>
        </label>
        <div class="v2-inline-fields">
          <label class="v2-field">
            <span>主题</span>
            <select v-model="eventTopic">
              <option>社会事件</option>
              <option>新闻时事</option>
              <option>娱乐</option>
              <option>其他</option>
            </select>
          </label>
          <label class="v2-field">
            <span>情绪倾向</span>
            <select v-model="eventValence">
              <option value="negative">负面</option>
              <option value="neutral">中性</option>
              <option value="positive">正面</option>
            </select>
          </label>
        </div>
      </section>

      <section class="v2-rail-block v2-strategy-block">
        <div class="v2-rail-title"><span>02</span><h2>公告与策略</h2></div>
        <label class="v2-field">
          <span>策略</span>
          <select v-model="selectedStrategyId">
            <option v-for="row in strategyOverview" :key="row.strategy_id" :value="row.strategy_id">
              {{ row.strategy_name }}
            </option>
          </select>
        </label>
        <div class="v2-selected-strategy">
          <strong>{{ selectedStrategy?.strategy_name || '—' }}</strong>
          <span v-if="selectedStrategyId === 'custom' && !customReady" class="v2-badge warn">待填写</span>
          <span v-else-if="selectedStrategyId === 'no_response'" class="v2-badge muted">无公告</span>
          <span v-else-if="selectedStrategyId === '__all__'" class="v2-badge">全部</span>
        </div>
        <template v-if="selectedAnnouncement && !['__all__','no_response'].includes(selectedStrategyId)">
          <label class="v2-field v2-announcement-field">
            <span>公告内容</span>
            <textarea v-model="selectedAnnouncement.text" maxlength="5000"></textarea>
          </label>
          <label class="v2-field">
            <span>声明状态</span>
            <select v-model="selectedAnnouncement.status">
              <option value="clear">clear</option>
              <option value="incomplete">incomplete</option>
              <option value="conflict">conflict</option>
              <option value="none">none</option>
            </select>
          </label>
        </template>
      </section>

      <section class="v2-rail-block v2-timing-block">
        <div class="v2-rail-title"><span>03</span><h2>官方发布时机</h2></div>
        <div class="v2-inline-fields">
          <label class="v2-field">
            <span>模式</span>
            <select v-model="entryMode">
              <option value="dynamic">动态进场</option>
              <option value="fixed_round">固定轮次</option>
            </select>
          </label>
          <label class="v2-field">
            <span>固定轮次</span>
            <select v-model.number="entryRound" :disabled="entryMode !== 'fixed_round'">
              <option v-for="n in 9" :key="n" :value="n + 1">第 {{ n + 1 }} 轮</option>
            </select>
          </label>
        </div>
      </section>

      <section class="v2-rail-block v2-timeline-block">
        <div class="v2-rail-title"><span>04</span><h2>追加公告</h2></div>
        <div class="v2-inline-fields compact">
          <label class="v2-field">
            <span>轮次</span>
            <select v-model.number="timelineRound">
              <option v-for="n in 9" :key="n" :value="n + 1">第 {{ n + 1 }} 轮</option>
            </select>
          </label>
          <label class="v2-field">
            <span>状态</span>
            <select v-model="timelineStatus">
              <option value="clear">clear</option>
              <option value="incomplete">incomplete</option>
              <option value="conflict">conflict</option>
            </select>
          </label>
        </div>
        <label class="v2-field">
          <span>公告内容</span>
          <textarea
            ref="timelineTextarea"
            v-model="timelineText"
            maxlength="5000"
            @input="resizeTimelineTextarea"
          ></textarea>
        </label>
        <button class="v2-btn small" :disabled="!canAddAnnouncement()" @click="addAnnouncement">添加到时间线</button>
        <div class="v2-timeline-list">
          <span v-if="!timeline.length">暂无追加公告</span>
          <div v-for="(item, index) in timeline.slice(-3)" :key="item.round">
            <b>公告 {{ index + 1 }}</b>
            <span>第 {{ item.round }} 轮</span>
          </div>
        </div>
      </section>

      <div class="v2-rail-actions">
        <button class="v2-btn" :disabled="busy" @click="previewInputs">预览输入</button>
        <button class="v2-btn primary" :disabled="busy" @click="createSession">创建会话</button>
      </div>
    </aside>
  </div>

  <div v-if="agentOpen" class="v2-modal-backdrop" @click.self="agentOpen = false">
    <section class="v2-detail-modal">
      <header>
        <div><p>AGENT DETAIL</p><h2>Agent 详情</h2></div>
        <button class="v2-icon-btn" @click="agentOpen = false">×</button>
      </header>
      <template v-if="agentDetail">
        <div class="v2-agent-detail-head">
          <span :style="{ '--orb': emotionColor(agentDetail.current_emotion) }">{{ agentDetail.agent_id.slice(-4) }}</span>
          <div>
            <strong>{{ agentDetail.agent_id }}</strong>
            <small>{{ emotionText(agentDetail.current_emotion) }}</small>
          </div>
        </div>
        <div class="v2-detail-grid">
          <div><span>评论派系</span><strong>{{ agentDetail.last_comment_faction || '—' }}</strong></div>
          <div><span>本轮动作</span><strong>{{ agentDetail.last_action || '—' }}</strong></div>
        </div>
        <p class="v2-detail-copy">{{ agentDetail.last_comment || '本轮未发表评论' }}</p>
      </template>
    </section>
  </div>

</div>
`;
