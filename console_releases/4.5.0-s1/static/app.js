(() => {
  const PAP_WEB_CONSOLE_VERSION = '4.4.0';
  console.info('[PAP Web Console] frontend loaded', {version:PAP_WEB_CONSOLE_VERSION, href:location.href});
  const state = {
    token: sessionStorage.getItem('papToken') || '',
    operator: sessionStorage.getItem('papOperator') || '',
    ws: null,
    runs: [],
    runProfileFilter: localStorage.getItem('pap:run-profile-filter:v1') || '',
    selectedRunId: null,
    detail: null,
    logBuffers: new Map(),
    reconnectTimer: null,
    fullRunLog: '',
    deliveryDrafts: new Map(),
    deliveryModeByRun: new Map(),
    deliveryAggregateByRun: new Map(),
    deliveryStallByRun: new Map(),
    activeView: 'runs',
    profiles: [],
    bindings: [],
    bindingsRevision: 0,
    bindingsDigest: '',
    endpoints: [],
    endpointPins: {},
    history: [],
    editingProfileId: null,
    editingBindingId: null,
    managementTimer: null,
    chatsInteractionEpoch: 0,
    chatsInteractionUntil: 0,
    chatsRerenderTimer: null,
    chatsGuardInstalled: false,
    chatsPointerDown: false,
    chatsPointerSince: 0,
    profileRoleRows: [],
  };

  const $ = (id) => document.getElementById(id);
  const esc = (value) => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmtBytes = (n) => {
    const x = Number(n || 0);
    if (x < 1024) return `${x} B`;
    const u = ['KiB','MiB','GiB','TiB'];
    let v = x / 1024, i = 0;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i++; }
    return `${v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2)} ${u[i]}`;
  };
  const badgeClass = (value) => {
    const s = String(value || '').toUpperCase();
    if (['DONE','COMPLETE','HANDLED','OVERRIDDEN','UPLOADED','SENT'].includes(s)) return 'good';
    if (['DONE_WITH_WARNINGS','COMPLETE_WITH_WARNINGS','PARTIAL','STALLED'].includes(s)) return 'warn';
    if (['ERROR','BLOCKED','STOPPED_BY_CONDITION','SEND_ERROR','CANCELLED','ENDPOINT_WAIT_TIMEOUT'].includes(s)) return 'bad';
    if (['RUNNING','FILES_PENDING','JSON_RECEIVED','READY','QUEUED','UPLOADING','READY_TO_SEND','SEND_REQUESTED','PENDING','RETRY_PENDING','FETCHING','CHAT_UPLOADING','CLAUDE_UPLOADING','WAITING_FOR_ENDPOINT'].includes(s)) return 'info';
    return '';
  };
  const toast = (text) => {
    const node = $('toast');
    node.textContent = text;
    node.classList.remove('hidden');
    clearTimeout(node._timer);
    node._timer = setTimeout(() => node.classList.add('hidden'), 3000);
  };

  async function api(path, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set('Authorization', `Bearer ${state.token}`);
    if (state.operator) headers.set('X-PAP-Operator', state.operator);
    if (options.body && !(options.body instanceof FormData)) headers.set('Content-Type', 'application/json');
    const res = await fetch(path, {...options, headers});
    if (res.status === 401) {
      showLogin('Неверный или устаревший token');
      throw new Error('unauthorized');
    }
    const ct = res.headers.get('content-type') || '';
    const body = ct.includes('application/json') ? await res.json() : await res.text();
    if (!res.ok) throw new Error(body?.error || body || `HTTP ${res.status}`);
    return body;
  }

  function showLogin(error = '') {
    $('login').classList.remove('hidden');
    $('loginError').textContent = error;
    $('tokenInput').value = state.token;
    $('operatorInput').value = state.operator;
  }
  function hideLogin() { $('login').classList.add('hidden'); }

  async function login() {
    state.operator = $('operatorInput').value.trim();
    state.token = $('tokenInput').value.trim();
    if (!state.operator) return showLogin('Укажите имя оператора — оно попадёт в audit log каждого запуска');
    if (!state.token) return;
    try {
      await api('/api/runs');
      sessionStorage.setItem('papToken', state.token);
      sessionStorage.setItem('papOperator', state.operator);
      $('operatorBadge').textContent = `Оператор: ${state.operator}`;
      hideLogin();
      connectWs();
      await refreshRunProfileFilter();
      await refreshRuns();
    } catch (e) {
      showLogin(e.message);
    }
  }

  function setWs(online, text) {
    const b = $('wsBadge');
    b.textContent = text || `WebSocket: ${online ? 'online' : 'offline'}`;
    b.className = `badge ${online ? 'online' : 'offline'}`;
  }

  function connectWs() {
    if (!state.token) return;
    if (state.ws) try { state.ws.close(); } catch (_) {}
    clearTimeout(state.reconnectTimer);
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const ws = new WebSocket(`${scheme}//${location.host}/ws`);
    state.ws = ws;
    setWs(false, 'WebSocket: connecting');
    ws.onopen = () => ws.send(JSON.stringify({type:'auth', token:state.token, operator:state.operator}));
    ws.onmessage = async (event) => {
      let msg; try { msg = JSON.parse(event.data); } catch (_) { return; }
      if (msg.type === 'auth:ok') {
        setWs(true);
        refreshRuns().catch(() => {});
        if (state.selectedRunId) subscribeRun(state.selectedRunId);
      } else if (msg.type === 'auth:error') {
        showLogin('WebSocket: unauthorized');
      } else if (msg.type === 'runs:update') {
        refreshRuns().catch(() => {});
      } else if (msg.type === 'config:update') {
        if (state.activeView !== 'runs') refreshManagementView().catch(e => toast(`Ошибка: ${e.message}`));
        refreshRunProfileFilter().then(refreshRuns).catch(() => {});
      } else if (msg.type === 'run:init' && msg.runId === state.selectedRunId) {
        state.detail = msg.detail;
        renderDetail();
      } else if (msg.runId && msg.runId === state.selectedRunId) {
        if (msg.type === 'step:log') appendLiveLog(msg.stepId, msg.text || '');
        if (msg.type === 'step:criteria') applyLiveCriteria(msg.stepId, msg.criteria || {});
        if (msg.type === 'step:audit') applyLiveAudit(msg.stepId, msg.audit || {});
        if (msg.type === 'delivery:update' && msg.job) {
          state.detail = state.detail || {};
          const jobs = Array.isArray(state.detail.deliveryJobs) ? state.detail.deliveryJobs : [];
          const rest = jobs.filter(x => x.jobId !== msg.job.jobId);
          state.detail.deliveryJobs = [msg.job, ...rest];
          renderDelivery();
        }
        if (['step:state','workflow:state','step:file'].includes(msg.type)) await refreshSelected();
      }
    };
    ws.onclose = () => {
      setWs(false);
      if (state.token) state.reconnectTimer = setTimeout(connectWs, 1500);
    };
    ws.onerror = () => setWs(false, 'WebSocket: error');
  }

  function subscribeRun(runId) {
    if (state.ws?.readyState === WebSocket.OPEN) {
      state.ws.send(JSON.stringify({type:'subscribe:run', runId}));
    }
  }

  async function refreshRuns() {
    const query = state.runProfileFilter ? `?profileId=${encodeURIComponent(state.runProfileFilter)}` : '';
    const body = await api(`/api/runs${query}`);
    state.runs = body.runs || [];
    renderRuns();
  }

  async function refreshRunProfileFilter() {
    const body = await api('/api/profiles');
    const rows = (body.profiles || []).filter(p => !p.invalid);
    const select = $('runProfileFilter');
    select.innerHTML = '<option value="">Все профили</option>' + rows.map(p => `<option value="${esc(p.id)}">${esc(p.name || p.id)} (${esc(p.id)})</option>`).join('');
    select.value = rows.some(p => p.id === state.runProfileFilter) ? state.runProfileFilter : '';
    if (select.value !== state.runProfileFilter) { state.runProfileFilter = select.value; localStorage.setItem('pap:run-profile-filter:v1', state.runProfileFilter); }
  }
  async function refreshSelected() {
    if (!state.selectedRunId) return;
    state.detail = await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}`);
    renderDetail();
  }

  function renderRuns() {
    $('runs').innerHTML = state.runs.map(run => `
      <div class="run-item ${run.runId === state.selectedRunId ? 'active' : ''}" data-run="${esc(run.runId)}">
        <div class="run-id-short">${esc(run.runId)}</div>
        <div class="run-meta">
          <span class="badge">${esc(run.chatLabel || run.chatType || 'Unknown')}</span>
          <span>${esc(run.receiverStatus || '-')}</span>
          <span class="badge ${badgeClass(run.workflowStatus)}">${esc(run.workflowStatus || 'NEW')}</span>
        </div>
        <div class="run-meta">
          <span class="badge ${run.resolutionStatus === 'RESOLVED' ? 'good' : 'bad'}">${esc(run.resolutionStatus || 'UNRESOLVED')}</span>
          <span>${esc(run.profileId || '-')}</span><span>${esc(run.profileRole || '')}</span>
        </div>
        <div class="run-meta">
          ${Number(run.duplicateCount || 0) ? `<span class="badge warn">duplicates ${esc(run.duplicateCount)}</span>` : ''}
          ${run.repeatOf ? `<span class="badge info">repeat of ${esc(run.repeatOf)}</span>` : ''}
          ${run.sessionId ? `<span>session ${esc(run.sessionId)}</span>` : '<span>session —</span>'}
        </div>
      </div>`).join('') || '<div class="hint">Пока нет run-ов.</div>';
    document.querySelectorAll('.run-item[data-run]').forEach(el => {
      el.onclick = () => selectRun(el.dataset.run);
    });
  }

  async function selectRun(runId) {
    const previousRunId = state.selectedRunId;
    const textarea = $('deliveryMessage');

    if (previousRunId && textarea) {
      saveDeliveryDraft(previousRunId, textarea.value);
    }

    state.selectedRunId = runId;

    // A newly selected Run must never visually inherit another Run's text.
    // Restore only this Run's persisted draft, otherwise start blank.
    const persisted = loadPersistedDeliveryDraft(runId);
    if (persisted !== null) {
      state.deliveryDrafts.set(runId, persisted);
      textarea.value = persisted;
    } else {
      state.deliveryDrafts.delete(runId);
      textarea.value = '';
    }

    state.logBuffers.clear();
    renderRuns();
    $('emptyState').classList.add('hidden');
    $('runView').classList.remove('hidden');
    $('copyFullRunLogBtn').disabled = false;
    $('downloadFullRunLogBtn').disabled = false;
    state.fullRunLog = '';
    $('fullRunLog').textContent = '';
    $('fullRunLog').classList.add('hidden');
    subscribeRun(runId);
    await refreshSelected();
  }

  function renderDetail() {
    const d = state.detail;
    if (!d) return;
    const result = d.result || {};
    const receiver = d.receiverStatus || {};
    const exec = d.execution || {};
    $('runId').textContent = d.runId;
    const chatLabel = result.chatLabel || receiver.chatLabel || result.chatType || receiver.chatType || 'Unknown';
    const chatType = result.chatType || receiver.chatType || 'unknown';
    $('chatTypeValue').textContent = `${chatLabel} (${chatType})`;
    $('chatConversationId').textContent = result.chatConversationId || receiver.chatConversationId || '-';
    $('deliveryMessageLabel').firstChild.textContent = `Текст сообщения для ${chatLabel} `;
    $('prepareDeliveryBtn').textContent = `Вставить текст и загрузить файлы в ${chatLabel}`;
    $('receiverStatus').textContent = `Receiver: ${receiver.status || '-'}`;
    $('receiverStatus').className = `badge ${badgeClass(receiver.status)}`;
    const pc = d.profileContext || {};
    const effectiveWorkflow = pc.resolutionStatus && pc.resolutionStatus !== 'RESOLVED' ? 'BLOCKED' : (exec.workflowStatus || '-');
    $('workflowStatus').textContent = `Workflow: ${effectiveWorkflow}`;
    $('workflowStatus').className = `badge ${badgeClass(effectiveWorkflow)}`;
    const profileBadge = document.getElementById('profileResolutionBadge');
    if (profileBadge) {
      profileBadge.textContent = `Profile: ${pc.resolutionStatus || 'UNRESOLVED'}${pc.profileId ? ' · ' + pc.profileId + '/' + (pc.role || '-') : ''}`;
      profileBadge.className = `badge ${pc.resolutionStatus === 'RESOLVED' ? 'good' : 'bad'}`;
    }
    $('pageUrl').textContent = result.page || '';
    $('generatedAt').textContent = result.generatedAt || '';
    $('fileCount').textContent = `${receiver.completedFiles || 0}/${receiver.expectedFiles || 0}`;
    const sourceMessages = Array.isArray(result.messages) ? result.messages : [];
    const webResult = {
      ...result,
      messages: sourceMessages.length ? [sourceMessages[sourceMessages.length - 1]] : [],
      webCommandScope: 'LATEST_ASSISTANT_MESSAGE',
      sourceMessageCount: sourceMessages.length,
      selectedMessagePosition: d.plan?.selectedMessagePosition ?? null
    };
    $('orderValue').textContent =
      `${d.plan?.order || ''} · только последний assistant-блок`;
    $('snapshotDigest').textContent = pc.snapshotDigest || '-';
    $('sessionId').textContent = pc.sessionId || '-';
    const intakeMeta = d.intakeMeta || {};
    $('duplicateInfo').textContent = `${Number(intakeMeta.duplicateCount || 0)}${intakeMeta.repeatOf ? ` · repeatOf ${intakeMeta.repeatOf}` : ''}`;
    $('provenanceInfo').textContent = `${pc.profileId || '-'} rev ${pc.profileRevision ?? '-'} · ${pc.role || '-'} · binding ${pc.bindingId || '-'}${intakeMeta.dedupeBypass ? ' · dedupe bypass' : ''}`;
    $('rawJson').textContent = JSON.stringify(webResult, null, 2);
    renderSourceFiles(d.sourceFiles || []);
    renderSteps(d.plan?.steps || [], exec);
    renderDelivery();
  }


  const DELIVERY_DRAFT_STORAGE_PREFIX = 'pap:delivery-draft:v1:';

  function deliveryDraftStorageKey(runId) {
    return `${DELIVERY_DRAFT_STORAGE_PREFIX}${String(runId || '')}`;
  }

  function loadPersistedDeliveryDraft(runId) {
    try {
      const value = localStorage.getItem(deliveryDraftStorageKey(runId));
      return value === null ? null : String(value);
    } catch (_) {
      return null;
    }
  }

  function saveDeliveryDraft(runId, value) {
    if (!runId) return String(value ?? '');
    const text = String(value ?? '');
    state.deliveryDrafts.set(runId, text);
    try {
      localStorage.setItem(deliveryDraftStorageKey(runId), text);
    } catch (_) {}
    return text;
  }

  function runScopedDeliveryDraft(runId) {
    if (!runId) return '';

    if (state.deliveryDrafts.has(runId)) {
      return String(state.deliveryDrafts.get(runId) ?? '');
    }

    const persisted = loadPersistedDeliveryDraft(runId);
    if (persisted !== null) {
      state.deliveryDrafts.set(runId, persisted);
      return persisted;
    }

    // No browser draft exists. Only this Run's own prepared job may provide
    // a fallback; text from another Run is never consulted.
    const jobs = state.detail?.deliveryJobs || [];
    const ownJobMessage = jobs.length
      ? String(jobs[0]?.message ?? '')
      : '';

    state.deliveryDrafts.set(runId, ownJobMessage);
    return ownJobMessage;
  }

  function restoreDeliveryDraftToTextarea(runId) {
    const textarea = $('deliveryMessage');
    if (!textarea) return '';
    const text = runScopedDeliveryDraft(runId);
    textarea.value = text;
    return text;
  }

  const MISSING_REPORTS_PREFIX = 'Такие файлы отсутствуют: ';

  function withMissingReportsSuffix(text, missing) {
    const cleaned = String(text || '')
      .replace(/(?:\n\n)?Такие файлы отсутствуют: [^\n]*(?:\n)?$/u, '')
      .replace(/\s+$/u, '');
    const rows = [...new Set((missing || []).map(x => String(x || '').trim()).filter(Boolean))];
    if (!rows.length) return cleaned;
    const suffix = MISSING_REPORTS_PREFIX + rows.join(', ');
    return cleaned ? `${cleaned}\n\n${suffix}` : suffix;
  }

  function syncDeliveryMessageMissingSuffix(runId, missing) {
    const textarea = $('deliveryMessage');
    const focused = document.activeElement === textarea;

    const current = (
      focused &&
      state.selectedRunId === runId &&
      state.deliveryDrafts.has(runId)
    )
      ? textarea.value
      : runScopedDeliveryDraft(runId);

    const next = withMissingReportsSuffix(current, missing);
    saveDeliveryDraft(runId, next);
    if (textarea.value !== next) {
      const start = textarea.selectionStart;
      const end = textarea.selectionEnd;
      textarea.value = next;
      if (focused && Number.isInteger(start) && Number.isInteger(end)) {
        const max = next.length;
        textarea.setSelectionRange(Math.min(start, max), Math.min(end, max));
      }
    }
    return next;
  }

  function latestDeliveryJob() {
    const jobs = state.detail?.deliveryJobs || [];
    return jobs.length ? jobs[0] : null;
  }

  function attachmentProgress(a) {
    const total = Number(a.totalBytes ?? a.size ?? 0);
    const fetched = Number(a.bytesFetched || 0);
    if (!total) return '';
    const pct = Math.max(0, Math.min(100, Math.round(fetched * 100 / total)));
    return `${fmtBytes(fetched)} / ${fmtBytes(total)} (${pct}%)`;
  }

  function renderDelivery() {
    if (!state.selectedRunId || !state.detail) return;
    const runId = state.selectedRunId;
    const summary = state.detail.reportSummary || {artifacts:[], missing:[], pendingReportSteps:[]};
    const target = state.detail.result?.papSource || {};
    const targetBadge = $('deliveryTargetBadge');
    const currentJobForConnection = latestDeliveryJob();
    if (target.tabId != null) {
      if (currentJobForConnection?.claimedBy || currentJobForConnection?.clientHeartbeatAt) {
        targetBadge.textContent = `Extension bridge: poll получен, tabId=${target.tabId}`;
        targetBadge.className = 'badge good';
      } else {
        targetBadge.textContent = `Extension bridge: ожидаем poll, tabId=${target.tabId}`;
        targetBadge.className = 'badge info';
      }
    } else {
      targetBadge.textContent = 'Нужен extension v2.10.3+ и новый run';
      targetBadge.className = 'badge bad';
    }

    const present = (summary.artifacts || []).filter(x => x?.present);
    const missing = summary.missing || [];
    const pending = summary.pendingReportSteps || [];
    $('reportSummary').innerHTML = `
      <div class="delivery-summary-row"><span>Reports найдены</span><strong>${present.length}</strong></div>
      <div class="delivery-summary-row"><span>Reports отсутствуют</span><strong class="${missing.length ? 'text-warn' : ''}">${missing.length}</strong></div>
      <div class="delivery-summary-row"><span>GET_REPORTS ещё не выполнены</span><strong class="${pending.length ? 'text-warn' : ''}">${esc(pending.join(', ') || 'нет')}</strong></div>
      ${missing.length ? `<div class="missing-files"><strong>Отсутствуют:</strong> ${missing.map(esc).join(', ')}</div>` : ''}`;

    const message = $('deliveryMessage');

    if (!state.deliveryDrafts.has(runId)) {
      restoreDeliveryDraftToTextarea(runId);
    }

    syncDeliveryMessageMissingSuffix(runId, missing);
    $('deliveryMode').value = state.deliveryModeByRun.get(runId) || 'smart_zip';
    $('aggregateMaxMiB').value = state.deliveryAggregateByRun.get(runId) || '30';
    $('deliveryStallSeconds').value = state.deliveryStallByRun.get(runId) || '120';

    const getReportsSteps = (state.detail.plan?.steps || []).filter(step => step.type === 'COMMAND_GET_REPORTS');
    const getReportsStep = getReportsSteps.length ? getReportsSteps[getReportsSteps.length - 1] : null;
    const getReportsState = getReportsStep ? (state.detail.execution?.steps?.[getReportsStep.stepId] || {}) : {};
    const getReportsStatus = String(getReportsState.status || (getReportsStep?.executable ? 'PENDING' : 'DISPLAY_ONLY'));
    const getReportsButton = $('runGetReportsBtn');

    if (getReportsStep) {
      getReportsButton.textContent = ['DONE','DONE_WITH_WARNINGS'].includes(getReportsStatus)
        ? 'COMMAND_GET_REPORTS ✓'
        : `Выполнить COMMAND_GET_REPORTS · ${getReportsStatus}`;
      getReportsButton.disabled = getReportsStatus !== 'PENDING';
      getReportsButton.dataset.step = getReportsStep.stepId;
    } else {
      getReportsButton.textContent = 'COMMAND_GET_REPORTS — нет в последнем блоке';
      getReportsButton.disabled = true;
      getReportsButton.dataset.step = '';
    }

    $('prepareDeliveryBtn').disabled = Boolean(pending.length) || target.tabId == null;
    const job = latestDeliveryJob();
    const holder = $('deliveryJob');
    if (!job) {
      holder.innerHTML = '<div class="hint">Задание на отправку ещё не создано.</div>';
      $('retryDeliveryBtn').disabled = true;
      $('retryDeliveryBtn').textContent = 'Повторить не загруженные';
      $('sendDeliveryBtn').disabled = true;
      return;
    }

    const attachments = job.attachments || [];
    const pausedAfterRestart = String(job.status || '').toUpperCase() === 'PAUSED_AFTER_RESTART';
    const retryable = attachments.filter(a => ['ERROR','STALLED'].includes(String(a.state || '').toUpperCase()));
    const recovering = attachments.filter(a => String(a.state || '').toUpperCase() === 'RECOVER_PENDING');
    const allUploaded = attachments.every(a => String(a.state || '').toUpperCase() === 'UPLOADED');
    const terminalDelivery = ['SENT','CONSUMED','SUPERSEDED','CANCELLED'].includes(String(job.status || '').toUpperCase());
    const readyToSend =
      !pausedAfterRestart &&
      !terminalDelivery &&
      allUploaded &&
      job.messageState === 'INSERTED' &&
      !['SENT','MANUAL_SENT','SEND_REQUESTED'].includes(job.sendState);

    $('retryDeliveryBtn').disabled = !pausedAfterRestart && retryable.length === 0;
    $('retryDeliveryBtn').textContent = pausedAfterRestart
      ? 'Продолжить после рестарта'
      : 'Повторить не загруженные';
    $('sendDeliveryBtn').disabled = !readyToSend;

    const finalMessage = String(job.message || '');
    holder.innerHTML = `
      <div class="delivery-job-head">
        <div><span class="label">Job</span><div class="mono wrap">${esc(job.jobId)}</div></div>
        <span class="badge ${badgeClass(job.status)}">${esc(job.status || '-')}</span>
      </div>
      <div class="delivery-job-meta">
        <span>tabId=${esc(job.target?.tabId)}</span>
        <span>mode=${esc(job.mode)}</span>
        ${job.packagingPolicy?.type ? `<span>pack=${esc(job.packagingPolicy.type)}</span>` : ''}
        <span>message=${esc(job.messageState)}</span>
        <span>send=${esc(job.sendState)}</span>
        ${job.profileDelivery ? `<span>endpoint=${esc(job.profileDelivery.state || '-')}</span>` : ''}
        ${job.profileDelivery?.state === 'WAITING_FOR_ENDPOINT' ? `<span>wait timeout=${esc(job.profileDelivery.timeoutSec)}s</span>` : ''}
        ${job.profileDelivery?.state === 'ENDPOINT_WAIT_TIMEOUT' ? `<span class="text-warn">ENDPOINT_WAIT_TIMEOUT</span>` : ''}
        <span>lease=${job.claimLeaseToken ? 'ACTIVE' : 'FREE'}</span>
        ${job.clientPhase ? `<span>client=${esc(job.clientPhase)}</span>` : ''}
        ${recovering.length ? `<span>auto-recover=${recovering.length}</span>` : ''}
        ${job.recoveryReplay ? `<span>recovery-replay=yes</span>` : ''}
      </div>
      ${job.recoveryReplay
        ? `<div class="delivery-recovery-replay"><strong>Recovery replay:</strong> тот же текст и те же файлы из job ${esc(job.recoveryOf?.jobId || '-')}. Источник: ${esc(job.recoverySourceResolution || 'exact job')}.</div>`
        : ''}
      ${String(job.status || '').toUpperCase() === 'CONSUMED'
        ? `<div class="delivery-consumed"><strong>Завершено:</strong> сообщение отправлено вручную в исходном чате. Этот job больше не будет вставляться повторно.</div>`
        : ''}
      ${pausedAfterRestart ? `<div class="missing-files"><strong>Пауза после рестарта:</strong> это старое задание НЕ будет автоматически передано в чат. Нажмите «Продолжить после рестарта» только если хотите явно возобновить его.</div>` : ''}
      <details class="delivery-message-preview"><summary>Итоговый текст сообщения</summary><pre class="code">${esc(finalMessage)}</pre></details>
      <div class="delivery-files">
        ${attachments.map(a => `<div class="delivery-file ${String(a.state||'').toLowerCase()}">
          <div class="delivery-file-main"><strong>${esc(a.name)}</strong><span class="badge ${badgeClass(a.state)}">${esc(a.state || '-')}</span></div>
          <div class="hint">${fmtBytes(a.size)} · ${esc(a.phase || '')} · попыток: ${esc(a.attempts || 0)}</div>
          ${a.separateReason ? `<div class="hint">Отдельно: ${esc(a.separateReason)}</div>` : ''}
          ${Array.isArray(a.members) && a.members.length ? `<div class="hint">В ZIP: ${a.members.map(m => esc(m.name || '')).join(', ')}</div>` : ''}
          <div class="delivery-progress"><div class="delivery-progress-bar" style="width:${Number(a.totalBytes||a.size||0) ? Math.max(0,Math.min(100,Math.round(Number(a.bytesFetched||0)*100/Number(a.totalBytes||a.size||1)))) : 0}%"></div></div>
          <div class="hint">${esc(attachmentProgress(a))}${a.lastProgressAt ? ` · progress ${esc(a.lastProgressAt)}` : ''}</div>
          ${a.error ? `<div class="error-text">${esc(a.error)}</div>` : ''}
        </div>`).join('') || '<div class="hint">Нет файлов для загрузки.</div>'}
      </div>
      ${job.messageError ? `<div class="error-text">Сообщение: ${esc(job.messageError)}</div>` : ''}
      ${job.sendError ? `<div class="error-text">Отправка: ${esc(job.sendError)}</div>` : ''}`;
  }

  async function runGetReportsFromDelivery() {
    const stepId = String($('runGetReportsBtn').dataset.step || '');
    if (!stepId) return;
    await executeStep(stepId);
  }

  async function prepareDelivery() {
    if (!state.selectedRunId) return;
    const runId = state.selectedRunId;
    const message = $('deliveryMessage').value;
    const mode = $('deliveryMode').value;
    const aggregateMaxMiB = Number($('aggregateMaxMiB').value || 30);
    const stallTimeoutSeconds = Number($('deliveryStallSeconds').value || 120);
    saveDeliveryDraft(runId, message);
    state.deliveryModeByRun.set(runId, mode);
    state.deliveryAggregateByRun.set(runId, String(aggregateMaxMiB));
    state.deliveryStallByRun.set(runId, String(stallTimeoutSeconds));
    try {
      const body = await api(`/api/runs/${encodeURIComponent(runId)}/delivery/prepare`, {
        method:'POST', body:JSON.stringify({message, mode, aggregateMaxMiB, stallTimeoutSeconds})
      });
      state.detail.deliveryJobs = [body.job, ...(state.detail.deliveryJobs || []).filter(x => x.jobId !== body.job.jobId)];
      saveDeliveryDraft(runId, String(body.job.message || ''));
      $('deliveryMessage').value = String(body.job.message || '');
      renderDelivery();
      toast('Задание создано. Итоговый текст (включая отсутствующие файлы) показан в окне; расширение начнёт загрузку.');
    } catch (e) { toast(`Ошибка подготовки: ${e.message}`); }
  }

  async function retryDelivery() {
    const job = latestDeliveryJob();
    if (!job) return;
    try {
      const body = await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/delivery/${encodeURIComponent(job.jobId)}/retry`, {method:'POST', body:'{}'});
      state.detail.deliveryJobs = [body.job, ...(state.detail.deliveryJobs || []).filter(x => x.jobId !== body.job.jobId)];
      renderDelivery();
      toast(
        String(body.job?.status || '') === 'PAUSED_AFTER_RESTART'
          ? 'Задание остаётся на паузе.'
          : 'Задание явно возобновлено/повтор поставлен.'
      );
    } catch (e) { toast(`Ошибка повтора: ${e.message}`); }
  }

  async function sendDelivery() {
    const job = latestDeliveryJob();
    if (!job) return;
    try {
      const body = await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/delivery/${encodeURIComponent(job.jobId)}/send`, {method:'POST', body:'{}'});
      state.detail.deliveryJobs = [body.job, ...(state.detail.deliveryJobs || []).filter(x => x.jobId !== body.job.jobId)];
      renderDelivery();
      toast('Команда отправки передана расширению.');
    } catch (e) { toast(`Ошибка отправки: ${e.message}`); }
  }

  function renderSourceFiles(files) {
    $('sourceFiles').innerHTML = files.map(f => `
      <div class="file-card">
        <div class="name">${esc(f.name)}</div>
        <div class="details">${fmtBytes(f.size)} · SHA-256 ${esc(f.sha256)}</div>
        <button class="small source-download" data-name="${esc(f.name)}">Скачать</button>
      </div>`).join('') || '<div class="hint">Файлы расширением ещё не переданы.</div>';
    document.querySelectorAll('.source-download').forEach(btn => {
      btn.onclick = () => authorizedDownload(`/api/runs/${encodeURIComponent(state.selectedRunId)}/source/${encodeURIComponent(btn.dataset.name)}/download`, btn.dataset.name);
    });
  }

  function renderSteps(steps, execution) {
    $('steps').innerHTML = steps.map(step => renderStep(step, execution?.steps?.[step.stepId] || step.execution || null)).join('');
    bindStepActions();
  }

  function payloadText(step) {
    if (step.type === 'AFTER_COMMANDS') return step.text || '';
    if ('payload' in step) return typeof step.payload === 'string' ? step.payload : JSON.stringify(step.payload, null, 2);
    return '';
  }

  function initialCriteria(step) {
    return {
      final: false,
      decision: 'WAITING',
      decisionBasis: step.conditionRun ? 'EXPLICIT_CONDITION' : ((step.stopRun || step.continueRun) ? 'COMPATIBILITY_CRITERIA' : 'RETURN_CODE'),
      declaredDecision: 'WAITING',
      declaredDecisionBasis: step.conditionRun ? 'EXPLICIT_CONDITION' : ((step.stopRun || step.continueRun) ? 'COMPATIBILITY_CRITERIA' : 'RETURN_CODE'),
      automaticErrorDetected: false,
      automaticErrorOverride: false,
      automaticErrorReasons: [],
      returnCode: null,
      stopRun: step.stopRun == null ? null : false,
      continueRun: step.continueRun == null ? null : false,
      conditionRun: step.conditionRun || null,
      effectiveCondition: step.conditionRun || null,
      conditionResult: null,
      stopPatterns: (step.stopRun || []).map(pattern => ({pattern, found:false, state:'WAITING'})),
      continuePatterns: (step.continueRun || []).map(pattern => ({pattern, found:false, state:'WAITING'})),
      stopMatched: 0,
      stopTotal: (step.stopRun || []).length,
      continueMatched: 0,
      continueTotal: (step.continueRun || []).length,
    };
  }

  function criteriaPatternClass(kind, row, final) {
    if (kind === 'STOP') {
      if (row.found) return 'stop-hit';
      return final ? 'stop-clear' : 'waiting';
    }
    if (row.found) return 'continue-hit';
    return final ? 'continue-missing' : 'waiting';
  }

  function criteriaPatternLabel(kind, row, final) {
    if (kind === 'STOP') {
      if (row.found) return 'СОВПАЛ → STOP_RUN=true';
      return final ? 'НЕ НАЙДЕН' : 'ожидание';
    }
    if (row.found) return 'СОВПАЛ';
    return final ? 'НЕ НАЙДЕН → CONTINUE_RUN=false' : 'ожидание';
  }

  function renderCriteria(step, st) {
    if (step.type !== 'COMMAND_RUN') return '';
    const c = st?.criteria || initialCriteria(step);
    const final = Boolean(c.final);
    const pats = [];
    (c.stopPatterns || []).forEach(x => pats.push(`<div class="criterion ${criteriaPatternClass('STOP', x, final)}"><span class="criterion-kind">STOP</span><span class="criterion-state">${esc(criteriaPatternLabel('STOP', x, final))}</span><div class="criterion-pattern">${esc(x.pattern)}</div></div>`));
    (c.continuePatterns || []).forEach(x => pats.push(`<div class="criterion ${criteriaPatternClass('CONTINUE', x, final)}"><span class="criterion-kind">CONTINUE</span><span class="criterion-state">${esc(criteriaPatternLabel('CONTINUE', x, final))}</span><div class="criterion-pattern">${esc(x.pattern)}</div></div>`));

    const decision = String(c.decision || 'WAITING');
    const automaticErrorIgnored = Boolean(st?.automaticErrorIgnored);
    const automaticIgnoreEffective = Boolean(
      automaticErrorIgnored &&
      c.automaticErrorDetected &&
      c.declaredDecision !== 'STOP' &&
      st?.status === 'OVERRIDDEN'
    );
    const displayDecision = automaticIgnoreEffective ? 'NO_STOP' : decision;
    const decisionClass = displayDecision === 'STOP' ? 'stop' : displayDecision === 'NO_STOP' ? 'go' : 'wait';
    const decisionText = automaticIgnoreEffective
      ? 'ИТОГ: ПРОДОЛЖИТЬ — AUTO ERROR ПРОИГНОРИРОВАН'
      : decision === 'STOP'
        ? (final ? 'ИТОГ: СТОП' : 'ИТОГ: СТОП УЖЕ ОПРЕДЕЛЁН')
        : decision === 'NO_STOP'
          ? (final ? 'ИТОГ: НЕ СТОП' : 'ИТОГ: НЕ СТОП УЖЕ ОПРЕДЕЛЁН')
          : 'ИТОГ: ОЖИДАНИЕ ВЫВОДА КОМАНДЫ';

    const stopSummary = c.stopTotal ? `${c.stopMatched || 0}/${c.stopTotal}` : 'нет критериев';
    const continueSummary = c.continueTotal ? `${c.continueMatched || 0}/${c.continueTotal}` : 'нет критериев';
    const conditionShown = c.conditionRun || c.effectiveCondition || 'returnCode != 0';
    const conditionValue = c.conditionResult == null ? 'ещё не определён' : String(c.conditionResult);
    const returnCode = final ? `<span>returnCode=${esc(c.returnCode)}</span>` : '<span>команда выполняется</span>';
    const automaticReasons = Array.isArray(c.automaticErrorReasons) ? c.automaticErrorReasons : [];
    const automaticErrorCanIgnore = Boolean(
      final &&
      c.automaticErrorDetected &&
      c.declaredDecision !== 'STOP' &&
      st?.status === 'STOPPED_BY_CONDITION'
    );
    const automaticAction = automaticErrorIgnored
      ? `<div class="auto-error-ignored-note">AUTO ERROR проигнорирован оператором${st?.automaticErrorIgnoredAt ? ` · ${esc(st.automaticErrorIgnoredAt)}` : ''}${st?.automaticErrorIgnoreNote ? `<br><span>${esc(st.automaticErrorIgnoreNote)}</span>` : ''}</div>`
      : automaticErrorCanIgnore
        ? `<div class="auto-error-actions"><button class="danger ignore-auto-error" data-step="${esc(step.stepId)}">Игнорировать AUTO ERROR и продолжить</button><span class="hint">Доступно только потому, что обычные STOP/CONTINUE-критерии сами по себе разрешают продолжение.</span></div>`
        : '';
    const automaticBlock = c.automaticErrorDetected
      ? `<div class="step-grid criteria-grid">${automaticReasons.map(x => `<div class="criterion stop-hit"><span class="criterion-kind">AUTO ERROR</span><span class="criterion-state">${automaticErrorIgnored ? 'IGNORED' : 'STOP'}</span><div class="criterion-pattern"><strong>${esc(x.id || 'EXECUTION_ERROR')}</strong>: ${esc(x.description || '')}${x.excerpt ? `<br><code>${esc(x.excerpt)}</code>` : ''}</div></div>`).join('')}</div>${automaticAction}`
      : '';

    return `<div class="criteria-panel" id="criteria-${esc(step.stepId)}">
      <div class="criteria-summary">
        <span>STOP совпало: <strong>${esc(stopSummary)}</strong></span>
        <span>CONTINUE совпало: <strong>${esc(continueSummary)}</strong></span>
        ${returnCode}
      </div>
      ${pats.length ? `<div class="step-grid criteria-grid">${pats.join('')}</div>` : '<div class="hint">STOP_RUN / CONTINUE_RUN не заданы; итог будет определён по returnCode.</div>'}
      ${automaticBlock}
      <div class="condition-line"><span>Условие: <code>${esc(conditionShown)}</code></span><span>Результат: <strong>${esc(conditionValue)}</strong></span></div>
      <div class="decision-banner ${decisionClass}">${esc(decisionText)}</div>
    </div>`;
  }

  function logHighlightRanges(text, step, criteria) {
    const ranges = [];
    const add = (pattern, cls, priority) => {
      if (!pattern) return;
      let from = 0;
      while (from <= text.length - pattern.length) {
        const at = text.indexOf(pattern, from);
        if (at < 0) break;
        ranges.push({start: at, end: at + pattern.length, cls, priority});
        from = at + Math.max(1, pattern.length);
      }
    };
    const c = criteria || initialCriteria(step);
    (c.continuePatterns || []).filter(x => x.found).forEach(x => add(String(x.pattern), 'log-continue-match', 1));
    (c.stopPatterns || []).filter(x => x.found).forEach(x => add(String(x.pattern), 'log-stop-match', 2));
    ranges.sort((a,b) => a.start - b.start || b.priority - a.priority || b.end - a.end);
    const selected = [];
    let cursor = -1;
    for (const r of ranges) {
      if (r.start < cursor) continue;
      selected.push(r);
      cursor = r.end;
    }
    return selected;
  }

  function highlightedLogHtml(text, step, criteria) {
    const ranges = logHighlightRanges(text, step, criteria);
    if (!ranges.length) return esc(text);
    let out = '', pos = 0;
    for (const r of ranges) {
      out += esc(text.slice(pos, r.start));
      out += `<mark class="${r.cls}">${esc(text.slice(r.start, r.end))}</mark>`;
      pos = r.end;
    }
    out += esc(text.slice(pos));
    return out;
  }

  function refreshLogHighlight(stepId) {
    const node = document.getElementById(`log-${stepId}`);
    if (!node || !state.detail) return;
    const step = state.detail.plan.steps.find(x => x.stepId === stepId);
    if (!step) return;
    const st = state.detail.execution?.steps?.[stepId] || step.execution || null;
    const text = state.logBuffers.get(stepId) || '';
    node.innerHTML = highlightedLogHtml(text, step, st?.criteria);
    node.scrollTop = node.scrollHeight;
  }

  function applyLiveCriteria(stepId, criteria) {
    if (!state.detail) return;
    state.detail.execution = state.detail.execution || {steps:{}};
    state.detail.execution.steps = state.detail.execution.steps || {};
    state.detail.execution.steps[stepId] = state.detail.execution.steps[stepId] || {};
    state.detail.execution.steps[stepId].criteria = criteria;
    const step = state.detail.plan.steps.find(x => x.stepId === stepId);
    if (step) {
      step.execution = step.execution || {};
      step.execution.criteria = criteria;
      const holder = document.getElementById(`criteria-${stepId}`);
      if (holder) holder.outerHTML = renderCriteria(step, state.detail.execution.steps[stepId]);
    }
    refreshLogHighlight(stepId);
  }

  function renderAudit(audit) {
    if (!audit || !Object.keys(audit).length) return '';
    const promptPrefix = audit.condaEnv ? `(${audit.condaEnv}) ` : '';
    return `<div class="audit-panel">
      <div><strong>Кто нажал:</strong> ${esc(audit.operator || 'unknown')} · ${esc(audit.requestSource || '')} · ${esc(audit.remoteAddr || '')}</div>
      <div><strong>Кто исполняет:</strong> ${esc(audit.execUser || '')} uid=${esc(audit.uid)} gid=${esc(audit.gid)} · host=${esc(audit.host || '')}</div>
      <div><strong>Процесс:</strong> PID ${esc(audit.commandPid)} · shell=${esc(audit.shell || '')}</div>
      <div><strong>Стартовая строка:</strong> <code>${esc(`${promptPrefix}${audit.execUser || ''}@${audit.host || ''}:${audit.cwd || ''}$`)}</code></div>
    </div>`;
  }

  function applyLiveAudit(stepId, audit) {
    if (!state.detail) return;
    state.detail.execution = state.detail.execution || {steps:{}};
    state.detail.execution.steps = state.detail.execution.steps || {};
    state.detail.execution.steps[stepId] = state.detail.execution.steps[stepId] || {};
    state.detail.execution.steps[stepId].audit = audit;
    const card = document.querySelector(`[data-step-card="${CSS.escape(stepId)}"]`);
    const holder = card?.querySelector('[data-audit-holder]');
    if (holder) holder.innerHTML = renderAudit(audit);
  }

  function renderPutFiles(step, st) {
    const sources = state.detail?.sourceFiles || [];
    const mapping = step.suggestedMapping || [];
    const rows = mapping.map((m, idx) => `
      <div class="mapping-row">
        <label>Target<input readonly value="${esc(m.target)}" data-put-target></label>
        <label>Downloaded source<select data-put-source>
          <option value="">— выбрать —</option>
          ${sources.map(s => `<option value="${esc(s.name)}" ${s.name === m.source ? 'selected' : ''}>${esc(s.name)} (${fmtBytes(s.size)})</option>`).join('')}
        </select></label>
      </div>`).join('');
    const done = (st?.filesPlaced || []).map(x => `<div class="report-row mono">${esc(x.source)} → ${esc(x.target)}<br>${fmtBytes(x.size)} · ${esc(x.sha256)}</div>`).join('');
    return `${rows}<label class="hint"><input type="checkbox" data-put-overwrite style="width:auto"> Разрешить перезапись существующего target</label>${done}`;
  }

  function renderReports(step, st) {
    const artifacts = st?.reportArtifacts || [];
    if (!artifacts.length) return '';
    return `<div>${artifacts.map(a => {
      if (!a.present) return `<div class="report-row"><strong>MISSING</strong> ${esc(a.originalPath)}</div>`;
      return `<div class="report-row">
        <div class="mono">${esc(a.originalPath)}</div>
        <div class="hint">snapshot: ${esc(a.name)} · ${fmtBytes(a.size)} · SHA-256 ${esc(a.sha256)}</div>
        <div class="buttons">
          ${a.isText ? `<button class="small copy-artifact" data-artifact="${esc(a.artifactId)}">Копировать текст</button>` : ''}
          <button class="small download-artifact" data-artifact="${esc(a.artifactId)}" data-name="${esc(a.name)}">Скачать</button>
        </div>
      </div>`;
    }).join('')}</div>`;
  }

  function renderStep(step, st) {
    const status = st?.status || (step.executable ? 'PENDING' : 'DISPLAY_ONLY');
    let content = '';
    if (step.type === 'COMMAND_RUN') {
      content += `<div data-audit-holder>${renderAudit(st?.audit)}</div>`;
      content += `<pre class="code">${esc(step.command || '')}</pre>`;
      if (step.stopRun) content += `<div class="hint">STOP_RUN::${esc(JSON.stringify(step.stopRun))}</div>`;
      if (step.continueRun) content += `<div class="hint">CONTINUE_RUN::${esc(JSON.stringify(step.continueRun))}</div>`;
      if (step.conditionRun) content += `<div class="hint">CONDITION_RUN::${esc(step.conditionRun)}</div>`;
      content += renderCriteria(step, st);
      content += `<pre class="terminal" id="log-${esc(step.stepId)}">${highlightedLogHtml(state.logBuffers.get(step.stepId) || '', step, st?.criteria)}</pre>`;
      if (st?.pipeDetachedAfterMainExit) {
        content += `<div class="hint">Основной shell завершился, но stdout удерживался фоновым потомком. Pipe отсоединён через ${esc(st.pipeDrainGraceMs || 750)} мс; COMMAND_RUN завершён по return code основного shell.</div>`;
      }
      if (st?.logPath) content += `<div class="step-actions"><button class="small load-log" data-step="${esc(step.stepId)}">Показать лог команды</button><button class="small copy-log" data-step="${esc(step.stepId)}">Копировать лог</button></div>`;
    } else if (step.type === 'COMMAND_PUT_FILES') {
      content += `<pre class="code">${esc(JSON.stringify(step.payload, null, 2))}</pre>` + renderPutFiles(step, st);
    } else if (step.type === 'COMMAND_GET_REPORTS') {
      content += `<pre class="code">${esc(JSON.stringify(step.payload, null, 2))}</pre>` + renderReports(step, st);
    } else if (step.type === 'COMMAND_USER_ACTION_REQ') {
      content += `<pre class="code">${esc(step.userAction?.text || payloadText(step))}</pre>`;
      if (step.userAction?.forId) content += `<div class="hint">FOR_ID::${esc(step.userAction.forId)}</div>`;
      content += `<label>Комментарий оператора<textarea data-operator-note>${esc(st?.userNote || '')}</textarea></label>`;
    } else if (['COMMAND_RUN_WORKER','COMMAND_RUN_INSERVER','COMMAND_CURRENT_DEV_COMPLETE'].includes(step.type)) {
      content += `<pre class="code">${esc(payloadText(step))}</pre><label>Комментарий оператора<textarea data-operator-note>${esc(st?.operatorNote || '')}</textarea></label>`;
    } else if (step.type === 'AFTER_COMMANDS') {
      content += `<pre class="code">${esc(step.text || '')}</pre><div class="step-actions"><button class="small copy-static" data-copy="after">Копировать текст</button></div>`;
    } else if (step.type === 'FILE') {
      content += `<div class="hint">${esc(step.name)} · ${esc(step.fileKind)} · ${esc(step.extension)}</div>`;
    } else {
      content += `<pre class="code">${esc(payloadText(step))}</pre>`;
    }

    const actions = [];
    if (step.executable) {
      if (status === 'PENDING') actions.push(`<button class="primary execute-step" data-step="${esc(step.stepId)}">${step.type === 'COMMAND_USER_ACTION_REQ' ? 'Подтвердить действие' : ['COMMAND_RUN_WORKER','COMMAND_RUN_INSERVER','COMMAND_CURRENT_DEV_COMPLETE'].includes(step.type) ? 'Отметить обработанным' : 'Выполнить этот шаг'}</button>`);
      if (status === 'RUNNING' && step.type === 'COMMAND_RUN') actions.push(`<button class="danger cancel-step" data-step="${esc(step.stepId)}">Остановить процесс</button>`);
      const automaticOnlyBlocker = status === 'STOPPED_BY_CONDITION' && Boolean(st?.criteria?.automaticErrorDetected) && st?.criteria?.declaredDecision !== 'STOP';
      if (['STOPPED_BY_CONDITION','ERROR','CANCELLED_BY_OPERATOR','INTERRUPTED_BY_BACKEND_RESTART'].includes(status) && !automaticOnlyBlocker) actions.push(`<button class="danger override-step" data-step="${esc(step.stepId)}">Override и продолжить</button>`);
    }
    if (step.type !== 'COMMAND_RUN' && step.type !== 'FILE') {
      let copyLabel = 'Копировать данные шага';
      if (step.type === 'COMMAND_USER_ACTION_REQ') copyLabel = 'Копировать инструкцию целиком';
      else if (step.type === 'COMMAND_PUT_FILES') copyLabel = 'Копировать список target-путей';
      else if (step.type === 'COMMAND_GET_REPORTS') copyLabel = 'Копировать список report-путей';
      else if (['COMMAND_RUN_WORKER','COMMAND_RUN_INSERVER','COMMAND_CURRENT_DEV_COMPLETE'].includes(step.type)) copyLabel = 'Копировать текст для следующего чата';
      else if (step.type === 'AFTER_COMMANDS') copyLabel = 'Копировать текст';
      actions.push(`<button class="small copy-payload" data-step="${esc(step.stepId)}" title="Копируется только в буфер обмена этого браузера; на сервер или в чат автоматически ничего не отправляется">${esc(copyLabel)}</button>`);
    }

    return `<article class="step" data-step-card="${esc(step.stepId)}">
      <div class="step-head"><div class="step-seq">#${esc(step.sequence)}</div><div class="step-type">${esc(step.type)}</div><span class="badge ${badgeClass(status)}">${esc(status)}</span></div>
      <div class="step-body">${content}${actions.length ? `<div class="step-actions">${actions.join('')}</div>` : ''}${st?.error ? `<div class="error-text">${esc(st.error)}</div>` : ''}</div>
    </article>`;
  }

  function bindStepActions() {
    document.querySelectorAll('.execute-step').forEach(btn => btn.onclick = () => executeStep(btn.dataset.step));
    document.querySelectorAll('.override-step').forEach(btn => btn.onclick = () => overrideStep(btn.dataset.step));
    document.querySelectorAll('.ignore-auto-error').forEach(btn => btn.onclick = () => ignoreAutomaticError(btn.dataset.step));
    document.querySelectorAll('.cancel-step').forEach(btn => btn.onclick = () => cancelStep(btn.dataset.step));
    document.querySelectorAll('.load-log').forEach(btn => btn.onclick = () => loadLog(btn.dataset.step, false));
    document.querySelectorAll('.copy-log').forEach(btn => btn.onclick = () => loadLog(btn.dataset.step, true));
    document.querySelectorAll('.copy-artifact').forEach(btn => btn.onclick = () => copyArtifact(btn.dataset.artifact));
    document.querySelectorAll('.download-artifact').forEach(btn => btn.onclick = () => authorizedDownload(`/api/runs/${encodeURIComponent(state.selectedRunId)}/artifacts/${encodeURIComponent(btn.dataset.artifact)}/download`, btn.dataset.name));
    document.querySelectorAll('.copy-payload').forEach(btn => btn.onclick = () => Promise.resolve(copyStepPayload(btn.dataset.step)).catch(e => toast(`Ошибка: ${e.message}`)));
    document.querySelectorAll('.copy-static').forEach(btn => btn.onclick = () => {
      const step = state.detail.plan.steps.find(x => x.stepId === btn.closest('[data-step-card]').dataset.stepCard);
      copyText(step?.text || '').catch(e => toast(`Ошибка: ${e.message}`));
    });
  }

  async function executeStep(stepId) {
    const step = state.detail.plan.steps.find(x => x.stepId === stepId);
    const card = document.querySelector(`[data-step-card="${CSS.escape(stepId)}"]`);
    let body = {};
    if (step.type === 'COMMAND_PUT_FILES') {
      const targets = [...card.querySelectorAll('[data-put-target]')];
      const sources = [...card.querySelectorAll('[data-put-source]')];
      body.mapping = targets.map((t,i) => ({target:t.value, source:sources[i]?.value || ''}));
      body.overwrite = Boolean(card.querySelector('[data-put-overwrite]')?.checked);
    } else if (step.type === 'COMMAND_USER_ACTION_REQ' || ['COMMAND_RUN_WORKER','COMMAND_RUN_INSERVER','COMMAND_CURRENT_DEV_COMPLETE'].includes(step.type)) {
      body.confirmed = true;
      body.note = card.querySelector('[data-operator-note]')?.value || '';
    }
    try {
      await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/steps/${encodeURIComponent(stepId)}/execute`, {method:'POST', body:JSON.stringify(body)});
      toast(`Шаг ${stepId} завершён`);
      await refreshSelected();
    } catch (e) {
      toast(`Ошибка: ${e.message}`);
      await refreshSelected();
    }
  }

  async function overrideStep(stepId) {
    const note = prompt('Причина ручного override:');
    if (note === null) return;
    try {
      await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/steps/${encodeURIComponent(stepId)}/override`, {method:'POST', body:JSON.stringify({note})});
      await refreshSelected();
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  async function ignoreAutomaticError(stepId) {
    if (!confirm('Игнорировать автоматически обнаруженную ошибку и разрешить выполнение следующих шагов? Сам факт ошибки останется в журнале и execution state.')) return;
    const note = prompt('Комментарий к игнорированию AUTO ERROR (можно оставить пустым):', 'Осознанно игнорирую AUTO ERROR');
    if (note === null) return;
    try {
      await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/steps/${encodeURIComponent(stepId)}/ignore-auto-error`, {method:'POST', body:JSON.stringify({note})});
      toast(`AUTO ERROR шага ${stepId} проигнорирован`);
      await refreshSelected();
    } catch (e) {
      toast(`Ошибка: ${e.message}`);
      await refreshSelected();
    }
  }

  async function cancelStep(stepId) {
    if (!confirm('Остановить только subprocess этого COMMAND_RUN?')) return;
    try {
      await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/steps/${encodeURIComponent(stepId)}/cancel`, {method:'POST', body:'{}'});
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  function appendLiveLog(stepId, text) {
    const old = state.logBuffers.get(stepId) || '';
    const next = (old + text).slice(-500000);
    state.logBuffers.set(stepId, next);
    refreshLogHighlight(stepId);
  }

  async function loadLog(stepId, copy) {
    try {
      const text = await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/steps/${encodeURIComponent(stepId)}/log`);
      state.logBuffers.set(stepId, text);
      refreshLogHighlight(stepId);
      if (copy) await copyText(text);
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  async function copyArtifact(artifactId) {
    try {
      const text = await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/artifacts/${encodeURIComponent(artifactId)}/text`);
      await copyText(text);
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  async function copyStepPayload(stepId) {
    const step = state.detail.plan.steps.find(x => x.stepId === stepId);
    if (!step) return;
    if (step.type === 'COMMAND_GET_REPORTS' || step.type === 'COMMAND_PUT_FILES') return copyText(JSON.stringify(step.payload, null, 2));
    if (step.type === 'AFTER_COMMANDS') return copyText(step.text || '');
    return copyText(payloadText(step));
  }

  async function copyText(text) {
    const value = String(text ?? '');
    let copied = false;
    let modernError = null;

    if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
      try {
        await navigator.clipboard.writeText(value);
        copied = true;
      } catch (e) {
        modernError = e;
      }
    }

    if (!copied) {
      const area = document.createElement('textarea');
      area.value = value;
      area.setAttribute('readonly', '');
      area.setAttribute('aria-hidden', 'true');
      area.style.position = 'fixed';
      area.style.left = '-10000px';
      area.style.top = '0';
      area.style.width = '1px';
      area.style.height = '1px';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.focus();
      area.select();
      area.setSelectionRange(0, area.value.length);
      try {
        copied = Boolean(document.execCommand && document.execCommand('copy'));
      } catch (_) {
        copied = false;
      }
      area.remove();
    }

    if (!copied) {
      const detail = modernError?.message ? `: ${modernError.message}` : '';
      throw new Error(`Браузер не разрешил запись в clipboard${detail}`);
    }
    toast(`Скопировано в буфер обмена (${value.length.toLocaleString('ru-RU')} символов)`);
  }

  async function fetchFullRunLog(show = false) {
    if (!state.selectedRunId) throw new Error('Run не выбран');
    const text = await api(`/api/runs/${encodeURIComponent(state.selectedRunId)}/full-log`);
    state.fullRunLog = String(text || '');
    if (show) {
      $('fullRunLog').textContent = state.fullRunLog;
      $('fullRunLog').classList.remove('hidden');
    }
    return state.fullRunLog;
  }

  async function copyFullRunLog() {
    try {
      const text = state.fullRunLog || await fetchFullRunLog(false);
      await copyText(text);
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  function downloadFullRunLog() {
    if (!state.selectedRunId) return;
    authorizedDownload(
      `/api/runs/${encodeURIComponent(state.selectedRunId)}/full-log/download`,
      `pap2-terminal-${state.selectedRunId}.log`
    );
  }

  async function authorizedDownload(path, name) {
    try {
      const res = await fetch(path, {headers:{Authorization:`Bearer ${state.token}`}});
      if (!res.ok) throw new Error(await res.text());
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url; a.download = name || 'download'; document.body.appendChild(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (e) { toast(`Ошибка скачивания: ${e.message}`); }
  }


  async function repeatSelectedRun() {
    if (!state.selectedRunId) return;
    const source = state.selectedRunId;
    try {
      const body = await api(`/api/runs/${encodeURIComponent(source)}/repeat-as-new`, {method:'POST', body:'{}'});
      toast(`Создан новый Run ${body.runId}`);
      await refreshRuns();
      await selectRun(body.runId);
    } catch (e) { toast(`Ошибка повтора: ${e.message}`); }
  }

  const prettyJson = (value) => JSON.stringify(value ?? {}, null, 2);
  const parseObjectInput = (id, label) => {
    let value;
    try { value = JSON.parse($(id).value || '{}'); } catch (e) { throw new Error(`${label}: JSON: ${e.message}`); }
    if (!value || Array.isArray(value) || typeof value !== 'object') throw new Error(`${label}: нужен JSON object`);
    return value;
  };

  function setView(view) {
    state.activeView = view;
    ['runs','profiles','chats','files','history'].forEach(name => {
      const node = $(`view${name[0].toUpperCase()}${name.slice(1)}`);
      if (node) node.classList.toggle('hidden', name !== view);
    });
    document.querySelectorAll('.nav-btn').forEach(btn => btn.classList.toggle('active', btn.dataset.view === view));
    clearInterval(state.managementTimer);
    state.managementTimer = null;
    if (view !== 'runs') {
      refreshManagementView().catch(e => toast(`Ошибка: ${e.message}`));
      if (view === 'chats') state.managementTimer = setInterval(() => refreshChats().catch(() => {}), 2000);
    }
  }

  async function refreshManagementView() {
    if (state.activeView === 'profiles') return refreshProfiles();
    if (state.activeView === 'chats') return refreshChats();
    if (state.activeView === 'files') return;
    if (state.activeView === 'history') return refreshHistory();
  }

  async function loadProfilesAndBindings() {
    const [profilesBody, bindingsBody] = await Promise.all([api('/api/profiles'), api('/api/chat-bindings')]);
    state.profiles = profilesBody.profiles || [];
    state.bindings = bindingsBody.bindings || [];
    state.bindingsRevision = bindingsBody.revision || 0;
    state.bindingsDigest = bindingsBody.digest || '';
  }

  async function refreshProfiles() {
    await loadProfilesAndBindings();
    $('profilesList').innerHTML = state.profiles.map(p => {
      const roles = Object.keys(p.roles || {});
      return `<div class="management-card ${p.invalid ? 'danger-card' : ''}">
        <div class="management-card-head"><div><strong>${esc(p.name || p.id)}</strong><div class="mono hint">${esc(p.id)}</div></div><span class="badge ${p.enabled && !p.invalid ? 'good' : 'bad'}">${p.invalid ? 'INVALID' : p.enabled ? 'Enabled' : 'Disabled'}</span></div>
        ${p.invalid ? `<div class="error-text">${esc(p.error)}</div>` : `<div class="management-kv"><span>Revision</span><b>${esc(p.revision)}</b><span>Roles</span><b>${esc(roles.join(', ') || '-')}</b><span>Chats</span><b>${esc(p.onlineBindingCount || 0)} online / ${esc(p.bindingCount || 0)} bound</b><span>Runs</span><b>${esc(p.runCount || 0)}</b></div><div class="mono hint wrap">${esc(p.digest || '')}</div>`}
        <div class="buttons"><button class="edit-profile" data-profile="${esc(p.id)}" ${p.invalid ? 'disabled' : ''}>Редактировать</button><button class="delete-profile" data-profile="${esc(p.id)}" ${p.invalid ? 'disabled' : ''}>Удалить</button></div>
      </div>`;
    }).join('') || '<div class="empty-management">Профилей пока нет.</div>';
    document.querySelectorAll('.edit-profile').forEach(btn => btn.onclick = () => openProfile(btn.dataset.profile));
    document.querySelectorAll('.delete-profile').forEach(btn => btn.onclick = () => deleteProfile(btn.dataset.profile));
  }

  function defaultProfile() {
    return {
      id:'', name:'', enabled:true, paths:{workDir:'/home/ext_disk/', tempDir:'/tmp/'}, variables:{}, secretRefs:{},
      prompts:{base:{source:'file',path:'prompts/base.md'}},
      roles:{developer:{promptPath:'prompts/roles/developer.md',basePromptRequired:true}},
      delivery:{offlineTargetPolicy:'wait',endpointWaitTimeoutSec:3600}, directives:{},
      errorDetection:{enabled:true,disabledBuiltins:[],customSignatures:[]}, promptTexts:{base:'',roles:{developer:''}}, secretMetadata:{}
    };
  }

  async function openProfile(profileId = null) {
    let p = defaultProfile();
    state.editingProfileId = profileId || null;
    if (profileId) p = (await api(`/api/profiles/${encodeURIComponent(profileId)}`)).profile;
    $('profileModalTitle').textContent = profileId ? `Профиль · ${p.name}` : 'Новый профиль';
    $('profileIdInput').value = p.id || '';
    $('profileIdInput').disabled = Boolean(profileId);
    $('profileNameInput').value = p.name || '';
    $('profileEnabledInput').checked = p.enabled !== false;
    $('profileRevisionInfo').textContent = profileId ? `revision ${p.revision} · ${p.digest || ''}` : 'новый';
    $('profileWorkDirInput').value = p.paths?.workDir || '';
    $('profileTempDirInput').value = p.paths?.tempDir || '';
    $('profileVariablesInput').value = prettyJson(p.variables || {});
    setProfileRoles(p.roles || {}, p.promptTexts?.roles || {});
    $('profileSecretRefsInput').value = prettyJson(p.secretRefs || {});
    $('profileDirectivesInput').value = prettyJson(p.directives || {});
    $('profileErrorsInput').value = prettyJson(p.errorDetection || {enabled:true,disabledBuiltins:[],customSignatures:[]});
    $('profileBasePromptInput').value = p.promptTexts?.base || '';
    $('offlinePolicyInput').value = p.delivery?.offlineTargetPolicy || 'wait';
    $('endpointTimeoutInput').value = p.delivery?.endpointWaitTimeoutSec || 3600;
    renderSecretMetadata(p);
    renderAssignedChats(p.id);
    $('errorTestInput').value = '';
    $('errorTestResult').textContent = '';
    $('profileModal').classList.remove('hidden');
    switchProfileTab('variables');
  }

  function switchProfileTab(name) {
    document.querySelectorAll('.editor-tab').forEach(x => x.classList.toggle('active', x.dataset.profileTab === name));
    document.querySelectorAll('.profile-tab-panel').forEach(x => x.classList.toggle('hidden', x.dataset.profilePanel !== name));
  }

  function renderSecretMetadata(profile) {
    const meta = profile.secretMetadata || {};
    const refs = profile.secretRefs || {};
    $('profileSecretsMeta').innerHTML = Object.entries(refs).map(([name, sid]) => {
      const m = meta[name] || {};
      return `<div class="management-card"><div><strong>${esc(name)}</strong> → <span class="mono">${esc(sid)}</span></div><div class="hint">${m.configured ? `configured · length ${esc(m.length)} · fingerprint ${esc(m.fingerprint)}` : 'not configured'}</div>${state.editingProfileId ? `<button class="set-secret small" data-secret-name="${esc(name)}">${m.configured ? 'Заменить' : 'Задать'} secret</button>` : '<div class="hint">Сначала сохраните профиль.</div>'}</div>`;
    }).join('') || '<div class="hint">Нет secretRefs.</div>';
    document.querySelectorAll('.set-secret').forEach(btn => btn.onclick = () => setSecret(btn.dataset.secretName));
  }

  function renderAssignedChats(profileId) {
    const rows = state.bindings.filter(b => b.profileId === profileId);
    $('profileAssignedChats').innerHTML = rows.map(b => `<div class="management-card"><strong>${esc(b.name)}</strong><div class="hint">${esc(b.chatType)} · ${esc(b.role)} · ${esc(b.conversationId)}</div><button class="goto-binding" data-binding="${esc(b.bindingId)}">Открыть в Чатах</button></div>`).join('') || '<div class="hint">Привязанных чатов нет.</div>';
    document.querySelectorAll('.goto-binding').forEach(btn => btn.onclick = () => { closeModal('profileModal'); setView('chats'); setTimeout(() => openBinding(btn.dataset.binding), 150); });
  }

  const ROLE_NAME_RE = /^[a-z0-9][a-z0-9_-]{0,31}$/;

  function setProfileRoles(roles, prompts) {
    const rows = Object.keys(roles || {}).sort().map(name => ({
      name,
      promptPath: (roles[name] || {}).promptPath || `prompts/roles/${name}.md`,
      basePromptRequired: Boolean((roles[name] || {}).basePromptRequired),
      text: (prompts || {})[name] || '',
    }));
    state.profileRoleRows = rows.length ? rows : [
      {name: 'developer', promptPath: 'prompts/roles/developer.md', basePromptRequired: true, text: ''},
    ];
    bindProfileRoleControls();
    renderProfileRoles();
  }

  function bindProfileRoleControls() {
    const add = $('profileAddRole');
    if (!add || add.dataset.bound) return;
    add.dataset.bound = '1';
    add.onclick = () => {
      readProfileRoleInputs();
      state.profileRoleRows.push({name: '', promptPath: '', basePromptRequired: false, text: ''});
      renderProfileRoles();
    };
  }

  function renderProfileRoles() {
    const holder = $('profileRolesList');
    if (!holder) return;
    holder.innerHTML = state.profileRoleRows.map((row, idx) => `
      <div class="role-row" data-role-index="${idx}">
        <div class="role-row-head">
          <label>Имя роли<input class="role-name" data-idx="${idx}" value="${esc(row.name)}" placeholder="developer"></label>
          <label>Файл промпта<input class="role-path" data-idx="${idx}" value="${esc(row.promptPath)}" placeholder="prompts/roles/developer.md"></label>
          <label class="role-flag"><input class="role-base" data-idx="${idx}" type="checkbox" ${row.basePromptRequired ? 'checked' : ''}> базовый промпт обязателен</label>
          <button type="button" class="role-remove" data-idx="${idx}">Удалить</button>
        </div>
        <label>Текст промпта роли<textarea class="role-text" data-idx="${idx}" rows="5" placeholder="Инструкции для чатов в этой роли">${esc(row.text)}</textarea></label>
      </div>`).join('') || '<div class="hint">Ролей нет. Нужна хотя бы одна: без неё чат нельзя привязать.</div>';
    holder.querySelectorAll('.role-remove').forEach(btn => btn.onclick = () => {
      readProfileRoleInputs();
      state.profileRoleRows.splice(Number(btn.dataset.idx), 1);
      renderProfileRoles();
    });
  }

  function readProfileRoleInputs() {
    const holder = $('profileRolesList');
    if (!holder) return;
    holder.querySelectorAll('.role-name').forEach(el => { state.profileRoleRows[Number(el.dataset.idx)].name = el.value.trim(); });
    holder.querySelectorAll('.role-path').forEach(el => { state.profileRoleRows[Number(el.dataset.idx)].promptPath = el.value.trim(); });
    holder.querySelectorAll('.role-base').forEach(el => { state.profileRoleRows[Number(el.dataset.idx)].basePromptRequired = el.checked; });
    holder.querySelectorAll('.role-text').forEach(el => { state.profileRoleRows[Number(el.dataset.idx)].text = el.value; });
  }

  function collectProfileRoles() {
    readProfileRoleInputs();
    const roles = {};
    const prompts = {};
    const seen = new Set();
    for (const row of state.profileRoleRows) {
      const name = String(row.name || '').trim();
      if (!name) throw new Error('У роли пустое имя');
      if (!ROLE_NAME_RE.test(name)) throw new Error(`Имя роли ${name}: строчные латинские буквы, цифры, дефис и подчёркивание`);
      if (seen.has(name)) throw new Error(`Роль ${name} объявлена дважды`);
      seen.add(name);
      roles[name] = {
        promptPath: String(row.promptPath || '').trim() || `prompts/roles/${name}.md`,
        basePromptRequired: Boolean(row.basePromptRequired),
      };
      prompts[name] = row.text || '';
    }
    if (!Object.keys(roles).length) throw new Error('Нужна хотя бы одна роль: к ней привязывается чат');
    return {roles, prompts};
  }

  async function saveProfile() {
    try {
      const collected = collectProfileRoles();
      const roles = collected.roles;
      const rolePrompts = collected.prompts;
      const body = {
        schemaVersion:1,
        id:$('profileIdInput').value.trim(), name:$('profileNameInput').value.trim(), enabled:$('profileEnabledInput').checked,
        paths:{workDir:$('profileWorkDirInput').value.trim(),tempDir:$('profileTempDirInput').value.trim()},
        variables:parseObjectInput('profileVariablesInput','Переменные'), secretRefs:parseObjectInput('profileSecretRefsInput','Секреты'),
        prompts:{base:{source:'file',path:'prompts/base.md'}}, roles,
        delivery:{offlineTargetPolicy:$('offlinePolicyInput').value,endpointWaitTimeoutSec:Number($('endpointTimeoutInput').value || 3600)},
        directives:parseObjectInput('profileDirectivesInput','Директивы'), errorDetection:parseObjectInput('profileErrorsInput','Определение ошибок'),
        promptTexts:{base:$('profileBasePromptInput').value,roles:rolePrompts}
      };
      const url = state.editingProfileId ? `/api/profiles/${encodeURIComponent(state.editingProfileId)}` : '/api/profiles';
      const method = state.editingProfileId ? 'PUT' : 'POST';
      await api(url,{method,body:JSON.stringify(body)});
      closeModal('profileModal'); toast('Профиль сохранён'); await refreshProfiles();
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  async function deleteProfile(profileId) {
    if (!confirm(`Удалить профиль ${profileId}? Привязанные профили удалить нельзя.`)) return;
    try { await api(`/api/profiles/${encodeURIComponent(profileId)}`,{method:'DELETE'}); toast('Профиль удалён'); await refreshProfiles(); } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  async function setSecret(name) {
    if (!state.editingProfileId) return;
    const value = prompt(`Новое значение secret ${name}. После сохранения оно больше не будет показано:`);
    if (value === null) return;
    try {
      const body = await api(`/api/profiles/${encodeURIComponent(state.editingProfileId)}/secrets/${encodeURIComponent(name)}`,{method:'POST',body:JSON.stringify({value})});
      toast(`Secret сохранён · fingerprint ${body.secret?.fingerprint || ''}`);
      const p = (await api(`/api/profiles/${encodeURIComponent(state.editingProfileId)}`)).profile;
      renderSecretMetadata(p);
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  async function testErrorSignatures() {
    if (!state.editingProfileId) return toast('Сначала сохраните профиль');
    try {
      const body = await api(`/api/profiles/${encodeURIComponent(state.editingProfileId)}/error-signatures/test`,{method:'POST',body:JSON.stringify({text:$('errorTestInput').value})});
      $('errorTestResult').textContent = prettyJson(body);
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  // Periodic refresh replaces the whole Chats DOM. A click needs pointerdown
  // and pointerup on the same element, so a refresh landing between them
  // silently swallows the action. The guard does not block the GET, only the
  // DOM replacement, and only while the operator is actually interacting.
  // The guard follows the actual pointer state rather than a fixed window.
  // A time limit cannot work here: holding the button longer than the window
  // lets a refresh replace the node between pointerdown and pointerup, and the
  // click is then never delivered. Event delegation alone does not help — with
  // the pressed node gone, the browser fires click on the common ancestor.
  const CHATS_RELEASE_GRACE_MS = 400;
  const CHATS_GUARD_CEILING_MS = 30000;

  function markChatsInteraction() {
    state.chatsInteractionEpoch += 1;
    state.chatsInteractionUntil = Date.now() + CHATS_RELEASE_GRACE_MS;
  }

  function holdChatsInteraction() {
    state.chatsInteractionEpoch += 1;
    state.chatsPointerDown = true;
    // Safety ceiling: a pointerup that never arrives must not freeze the view.
    state.chatsPointerSince = Date.now();
  }

  function releaseChatsInteraction() {
    state.chatsPointerDown = false;
    state.chatsInteractionEpoch += 1;
    state.chatsInteractionUntil = Date.now() + CHATS_RELEASE_GRACE_MS;
  }

  function chatsInteractionActive() {
    if (state.chatsPointerDown) {
      if (Date.now() - state.chatsPointerSince > CHATS_GUARD_CEILING_MS) {
        state.chatsPointerDown = false;
        return false;
      }
      return true;
    }
    return Date.now() < state.chatsInteractionUntil;
  }

  function installChatsGuard() {
    if (state.chatsGuardInstalled) return;
    ['endpointsList', 'bindingsList'].forEach(id => {
      const holder = $(id);
      if (!holder) return;
      holder.addEventListener('pointerdown', holdChatsInteraction, true);
      holder.addEventListener('focusin', markChatsInteraction, true);
      holder.addEventListener('keydown', markChatsInteraction, true);
    });
    // pointerup and cancellation are observed on the window: the pointer may
    // be released outside the card, and the press must still end.
    ['pointerup', 'pointercancel'].forEach(evt =>
      window.addEventListener(evt, releaseChatsInteraction, true));
    window.addEventListener('blur', releaseChatsInteraction, true);
    state.chatsGuardInstalled = true;
  }

  function scheduleChatsRerender() {
    if (state.chatsRerenderTimer) return;
    const delay = Math.max(250, state.chatsInteractionUntil - Date.now() + 100);
    state.chatsRerenderTimer = setTimeout(() => {
      state.chatsRerenderTimer = null;
      refreshChats().catch(() => {});
    }, delay);
  }

  async function refreshChats(options) {
    const force = Boolean(options && options.force);
    // Captured before the request, so a GET that started before the operator
    // touched anything and finished after is still caught.
    const epoch = state.chatsInteractionEpoch;
    installChatsGuard();
    await loadProfilesAndBindings();
    const epBody = await api('/api/endpoints');
    state.endpoints = epBody.endpoints || [];
    state.endpointPins = epBody.pins || {};
    $('chatsSummary').innerHTML = `<span class="badge good">Online: ${state.endpoints.filter(x=>x.online).length}</span><span class="badge">Endpoints: ${state.endpoints.length}</span><span class="badge">Bindings: ${state.bindings.length}</span><span class="badge">rev ${esc(state.bindingsRevision)}</span>`;
    if (!force && (state.chatsInteractionEpoch !== epoch || chatsInteractionActive())) {
      scheduleChatsRerender();
      return;
    }
    renderEndpoints(); renderBindings();
  }

  function renderEndpoints() {
    $('endpointsList').innerHTML = state.endpoints.map(ep => {
      const b = ep.binding;
      const pinState = b ? state.endpointPins[b.bindingId] : null;
      const pinTab = pinState && typeof pinState === 'object' ? pinState.tabId : pinState;
      const pinned = b && Number(pinTab) === Number(ep.tabId);
      const pinStale = Boolean(pinState && typeof pinState === 'object' && pinState.stale);
      // Two causes of staleness are not equivalent. A lost heartbeat means the
      // same conversation came back and one click may confirm it. A changed
      // identity means this tab now shows a different chat: the server refuses
      // such a pin, so offering "confirm" here would only produce an error.
      // A heartbeat gap no longer stales a pin: the same conversation coming
      // back resumes on its own. Only a changed conversation blocks, and that
      // one is never resumed automatically.
      const staleReason = pinStale ? String(pinState.staleReason || '') : '';
      const pinConversation = pinState && typeof pinState === 'object' ? (pinState.conversationId || '') : '';
      const sameConversation = !pinConversation || String(pinConversation) === String(ep.conversationId || '');
      const canConfirm = pinStale && sameConversation && ep.online;
      const pinBadge = !pinned ? ''
        : (pinStale ? '<span class="badge bad">вкладка сменила переписку</span>'
          : (ep.online ? '<span class="badge good">закреплено</span>' : '<span class="badge warn">закреплено, вкладка офлайн</span>'));
      const waitingNotice = (pinned && !pinStale && !ep.online)
        ? '<div class="pin-notice pin-notice-warn">Вкладка сейчас офлайн. Отправка ждёт её возвращения и продолжится сама, как только та же переписка снова выйдет на связь. Подтверждать ничего не нужно.</div>'
        : '';
      const conflictNotice = (pinned && pinStale)
        ? `<div class="pin-notice pin-notice-bad">В этой вкладке сейчас открыта другая переписка. Отправка приостановлена и сама не возобновится. Сними закрепление и закрепи вкладку с нужной перепиской.${staleReason ? `<div class="hint mono wrap">${esc(staleReason)}</div>` : ''}</div>`
        : '';
      const pinNotice = conflictNotice || waitingNotice;
      const gaps = Number(ep.disconnects24h || 0);
      const telemetry = gaps > 0
        ? `<div class="hint">Разрывов связи за сутки: ${gaps}${ep.lastDisconnectAt ? ` · последний ${esc(String(ep.lastDisconnectAt))}` : ''}${ep.lastGapSeconds ? ` · длительность ${esc(String(ep.lastGapSeconds))} с` : ''}</div>`
        : '';
      return `<div class="management-card ${ep.online ? '' : 'offline-card'}">
        <div class="management-card-head"><div><strong>${esc((ep.chatType || 'unknown').toUpperCase())} · tab ${esc(ep.tabId)}</strong><div class="mono hint wrap">${esc(ep.conversationId || 'no conversation id')}</div></div><span class="badge ${ep.online ? 'good' : 'offline'}">${ep.online ? 'online' : 'offline'}</span></div>
        <div class="hint wrap">${esc(ep.url || '')}</div><div class="management-kv"><span>Project</span><b class="mono">${esc(ep.projectId || '-')}</b><span>Last seen</span><b>${esc(ep.lastSeenAt || '-')}</b><span>Endpoint ID</span><b class="mono">${esc(ep.endpointId || 'нет в 4.4.0')}</b></div>
        ${b ? `<div class="binding-summary"><b>${esc(b.name)}</b> · ${esc(b.profileId)} / ${esc(b.role)} ${pinBadge}</div>${telemetry}${pinNotice}<div class="buttons"><button class="edit-binding" data-binding="${esc(b.bindingId)}">Править привязку</button>${(!pinned && ep.online) ? `<button class="pin-endpoint" data-tab="${esc(ep.tabId)}" data-binding="${esc(b.bindingId)}">Закрепить эту вкладку</button>` : ''}${canConfirm ? `<button class="pin-endpoint" data-tab="${esc(ep.tabId)}" data-binding="${esc(b.bindingId)}">Закрепить заново</button>` : ''}${pinned ? `<button class="unpin-endpoint" data-tab="${esc(ep.tabId)}" data-binding="${esc(b.bindingId)}">Снять pin</button>` : ''}</div>` : `<button class="bind-endpoint primary" data-tab="${esc(ep.tabId)}">Привязать</button>`}
      </div>`;
    }).join('') || '<div class="empty-management">Поддерживаемые вкладки пока не пульсировали в pro2 Console.</div>';
    document.querySelectorAll('.bind-endpoint').forEach(btn => btn.onclick = () => openBinding(null, state.endpoints.find(x=>String(x.tabId)===String(btn.dataset.tab))));
    document.querySelectorAll('.edit-binding').forEach(btn => btn.onclick = () => openBinding(btn.dataset.binding));
    document.querySelectorAll('.pin-endpoint').forEach(btn => btn.onclick = () => pinEndpoint(btn.dataset.binding, btn.dataset.tab, btn));
    document.querySelectorAll('.unpin-endpoint').forEach(btn => btn.onclick = () => unpinEndpoint(btn.dataset.binding, btn.dataset.tab, btn));
  }

  function renderBindings() {
    $('bindingsList').innerHTML = state.bindings.map(b => {
      const profile = state.profiles.find(p => p.id === b.profileId);
      const eps = state.endpoints.filter(ep => ep.chatType===b.chatType && ep.conversationId===b.conversationId);
      return `<div class="management-card"><div class="management-card-head"><div><strong>${esc(b.name)}</strong><div class="mono hint">${esc(b.bindingId)}</div></div><span class="badge ${b.enabled ? 'good' : 'bad'}">${b.enabled ? 'Enabled' : 'Disabled'}</span></div><div class="management-kv"><span>Profile</span><b>${esc(profile?.name || b.profileId)}</b><span>Role</span><b>${esc(b.role)}</b><span>Chat</span><b>${esc(b.chatType)}</b><span>Conversation</span><b class="mono wrap">${esc(b.conversationId)}</b><span>Tabs</span><b>${eps.filter(x=>x.online).length} online / ${eps.length} seen</b><span>Policy</span><b>${esc(b.endpointPolicy)}</b></div><div class="buttons"><button class="edit-binding" data-binding="${esc(b.bindingId)}">Редактировать</button><button class="delete-binding" data-binding="${esc(b.bindingId)}">Удалить</button></div></div>`;
    }).join('') || '<div class="empty-management">Привязок пока нет.</div>';
    document.querySelectorAll('.edit-binding').forEach(btn => btn.onclick = () => openBinding(btn.dataset.binding));
    document.querySelectorAll('.delete-binding').forEach(btn => btn.onclick = () => deleteBinding(btn.dataset.binding));
  }

  function bindingIdFromEndpoint(ep) {
    const stem = `${ep?.chatType || 'chat'}-${String(ep?.conversationId || 'conversation').slice(0,16)}`.toLowerCase().replace(/[^a-z0-9._-]+/g,'-').replace(/^-+|-+$/g,'');
    let id = stem || 'chat-binding'; let i=2;
    while (state.bindings.some(x=>x.bindingId===id)) id = `${stem}-${i++}`;
    return id;
  }

  async function openBinding(bindingId = null, endpoint = null) {
    if (!state.profiles.length) await loadProfilesAndBindings();
    const b = bindingId ? state.bindings.find(x => x.bindingId === bindingId) : null;
    state.editingBindingId = bindingId || null;
    $('bindingModalTitle').textContent = b ? `Привязка · ${b.name}` : 'Новая привязка';
    $('bindingIdInput').value = b?.bindingId || bindingIdFromEndpoint(endpoint);
    $('bindingIdInput').disabled = Boolean(b);
    $('bindingNameInput').value = b?.name || `${endpoint?.chatType === 'chatgpt' ? 'ChatGPT' : 'Claude'} ${endpoint?.tabId ? 'tab '+endpoint.tabId : ''}`.trim();
    $('bindingChatTypeInput').value = b?.chatType || endpoint?.chatType || 'claude';
    $('bindingConversationInput').value = b?.conversationId || endpoint?.conversationId || '';
    $('bindingProjectInput').value = b?.projectId || endpoint?.projectId || '';
    $('bindingEnabledInput').checked = b ? b.enabled !== false : true;
    $('bindingPolicyInput').value = b?.endpointPolicy || 'conversation';
    $('bindingProfileInput').innerHTML = state.profiles.filter(p=>!p.invalid).map(p=>`<option value="${esc(p.id)}">${esc(p.name)} (${esc(p.id)})</option>`).join('');
    if (b?.profileId) $('bindingProfileInput').value = b.profileId;
    updateRoleOptions(b?.role);
    $('bindingModal').classList.remove('hidden');
  }

  function updateRoleOptions(selected = null) {
    const profile = state.profiles.find(p => p.id === $('bindingProfileInput').value);
    const roles = Object.keys(profile?.roles || {});
    $('bindingRoleInput').innerHTML = roles.map(r=>`<option value="${esc(r)}">${esc(r)}</option>`).join('');
    if (selected && roles.includes(selected)) $('bindingRoleInput').value = selected;
  }

  async function saveBinding() {
    try {
      const body = {bindingId:$('bindingIdInput').value.trim(),name:$('bindingNameInput').value.trim(),chatType:$('bindingChatTypeInput').value,conversationId:$('bindingConversationInput').value.trim(),projectId:$('bindingProjectInput').value.trim()||null,profileId:$('bindingProfileInput').value,role:$('bindingRoleInput').value,enabled:$('bindingEnabledInput').checked,endpointPolicy:$('bindingPolicyInput').value,approvedEndpointId:null};
      const url = state.editingBindingId ? `/api/chat-bindings/${encodeURIComponent(state.editingBindingId)}` : '/api/chat-bindings';
      await api(url,{method:state.editingBindingId?'PUT':'POST',body:JSON.stringify(body)});
      closeModal('bindingModal'); toast('Привязка сохранена'); state.chatsInteractionUntil = 0; state.chatsPointerDown = false; await refreshChats({force:true});
    } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  async function deleteBinding(id) {
    if (!confirm(`Удалить привязку ${id}?`)) return;
    try { await api(`/api/chat-bindings/${encodeURIComponent(id)}`,{method:'DELETE'}); toast('Привязка удалена'); state.chatsInteractionUntil = 0; state.chatsPointerDown = false; await refreshChats({force:true}); } catch (e) { toast(`Ошибка: ${e.message}`); }
  }

  function withBusy(btn, label) {
    if (!btn || btn.disabled) return null;
    const restore = {text: btn.textContent, disabled: btn.disabled};
    btn.disabled = true;
    btn.textContent = label;
    return () => { btn.disabled = restore.disabled; btn.textContent = restore.text; };
  }

  async function pinEndpoint(bindingId, tabId, btn) {
    const release = withBusy(btn, 'Отправляю…');
    if (btn && !release) return;
    try { await api(`/api/endpoints/${encodeURIComponent(tabId)}/pin`,{method:'POST',body:JSON.stringify({bindingId})}); toast(`Вкладка ${tabId} подтверждена и закреплена до конца сессии браузера`); } catch (e) { toast(`Закрепление отклонено: ${e.message}`); }
    finally { if (release) release(); state.chatsInteractionUntil = 0; state.chatsPointerDown = false; await refreshChats({force:true}); }
  }
  async function unpinEndpoint(bindingId, tabId, btn) {
    const release = withBusy(btn, 'Снимаю…');
    if (btn && !release) return;
    try { await api(`/api/endpoints/${encodeURIComponent(tabId)}/pin`,{method:'DELETE',body:JSON.stringify({bindingId})}); toast('Runtime pin снят'); } catch (e) { toast(`Ошибка: ${e.message}`); }
    finally { if (release) release(); state.chatsInteractionUntil = 0; state.chatsPointerDown = false; await refreshChats({force:true}); }
  }

  async function refreshHistory() {
    const body = await api('/api/config-history?limit=500'); state.history = body.history || [];
    $('historyList').innerHTML = state.history.map(row => `<div class="history-row"><div><span class="badge">${esc(row.kind)}</span> <strong>${esc(row.action)}</strong> <span class="mono">${esc(row.objectId)}</span></div><div class="hint">${esc(row.at)} · ${esc(row.actor || 'unknown')}</div><details><summary>Изменение</summary><pre class="code">${esc(prettyJson({before:row.before,after:row.after}))}</pre></details></div>`).join('') || '<div class="empty-management">Журнал пока пуст.</div>';
  }

  function closeModal(id) { $(id)?.classList.add('hidden'); }

  $('loginBtn').onclick = login;
  $('tokenInput').onkeydown = (e) => { if (e.key === 'Enter') login(); };
  $('operatorInput').onkeydown = (e) => { if (e.key === 'Enter') login(); };
  $('forgetTokenBtn').onclick = () => { sessionStorage.removeItem('papToken'); sessionStorage.removeItem('papOperator'); state.token=''; state.operator=''; $('operatorBadge').textContent='Оператор: -'; if (state.ws) state.ws.close(); showLogin(); };
  $('refreshRunsBtn').onclick = () => refreshRuns().catch(e => toast(e.message));
  $('runProfileFilter').value = state.runProfileFilter;
  $('runProfileFilter').onchange = () => { state.runProfileFilter = $('runProfileFilter').value; localStorage.setItem('pap:run-profile-filter:v1', state.runProfileFilter); refreshRuns().catch(e => toast(e.message)); };
  $('repeatRunBtn').onclick = repeatSelectedRun;
  $('copyRawBtn').onclick = () => copyText(JSON.stringify(state.detail?.result || {}, null, 2)).catch(e => toast(`Ошибка: ${e.message}`));
  $('loadFullRunLogBtn').onclick = () => fetchFullRunLog(true).catch(e => toast(`Ошибка: ${e.message}`));
  $('copyFullRunLogInlineBtn').onclick = copyFullRunLog;
  $('downloadFullRunLogInlineBtn').onclick = downloadFullRunLog;
  $('copyFullRunLogBtn').onclick = copyFullRunLog;
  $('downloadFullRunLogBtn').onclick = downloadFullRunLog;
  $('deliveryMessage').oninput = () => {
    if (state.selectedRunId) {
      saveDeliveryDraft(state.selectedRunId, $('deliveryMessage').value);
    }
  };
  $('deliveryMode').onchange = () => { if (state.selectedRunId) state.deliveryModeByRun.set(state.selectedRunId, $('deliveryMode').value); };
  $('aggregateMaxMiB').onchange = () => { if (state.selectedRunId) state.deliveryAggregateByRun.set(state.selectedRunId, $('aggregateMaxMiB').value); };
  $('deliveryStallSeconds').onchange = () => { if (state.selectedRunId) state.deliveryStallByRun.set(state.selectedRunId, $('deliveryStallSeconds').value); };
  $('runGetReportsBtn').onclick = runGetReportsFromDelivery;
  $('prepareDeliveryBtn').onclick = prepareDelivery;
  $('retryDeliveryBtn').onclick = retryDelivery;
  $('sendDeliveryBtn').onclick = sendDelivery;

  document.querySelectorAll('.nav-btn').forEach(btn => btn.onclick = () => setView(btn.dataset.view));
  document.querySelectorAll('[data-close-modal]').forEach(btn => btn.onclick = () => closeModal(btn.dataset.closeModal));
  document.querySelectorAll('.editor-tab').forEach(btn => btn.onclick = () => switchProfileTab(btn.dataset.profileTab));
  $('addProfileBtn').onclick = () => openProfile().catch(e => toast(`Ошибка: ${e.message}`));
  $('saveProfileBtn').onclick = saveProfile;
  $('errorTestBtn').onclick = testErrorSignatures;
  $('addBindingBtn').onclick = () => openBinding().catch(e => toast(`Ошибка: ${e.message}`));
  $('saveBindingBtn').onclick = saveBinding;
  $('bindingProfileInput').onchange = () => updateRoleOptions();
  $('refreshHistoryBtn').onclick = () => refreshHistory().catch(e => toast(`Ошибка: ${e.message}`));
  $('profileModal').onclick = (e) => { if (e.target === $('profileModal')) closeModal('profileModal'); };
  $('bindingModal').onclick = (e) => { if (e.target === $('bindingModal')) closeModal('bindingModal'); };

  if (state.token && state.operator) { $('tokenInput').value=state.token; $('operatorInput').value=state.operator; login(); } else showLogin();
})();
