(() => {
  const PAP_WEB_CONSOLE_VERSION = '4.3.5';
  console.info('[PAP Web Console] frontend loaded', {version:PAP_WEB_CONSOLE_VERSION, href:location.href});
  const state = {
    token: sessionStorage.getItem('papToken') || '',
    operator: sessionStorage.getItem('papOperator') || '',
    ws: null,
    runs: [],
    selectedRunId: null,
    detail: null,
    logBuffers: new Map(),
    reconnectTimer: null,
    fullRunLog: '',
    deliveryDrafts: new Map(),
    deliveryModeByRun: new Map(),
    deliveryAggregateByRun: new Map(),
    deliveryStallByRun: new Map(),
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
    if (['ERROR','BLOCKED','STOPPED_BY_CONDITION','SEND_ERROR'].includes(s)) return 'bad';
    if (['RUNNING','FILES_PENDING','JSON_RECEIVED','READY','QUEUED','UPLOADING','READY_TO_SEND','SEND_REQUESTED','PENDING','RETRY_PENDING','FETCHING','CHAT_UPLOADING','CLAUDE_UPLOADING'].includes(s)) return 'info';
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
        state.runs = msg.runs || [];
        renderRuns();
        if (state.selectedRunId) subscribeRun(state.selectedRunId);
      } else if (msg.type === 'auth:error') {
        showLogin('WebSocket: unauthorized');
      } else if (msg.type === 'runs:update') {
        state.runs = msg.runs || [];
        renderRuns();
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
    const body = await api('/api/runs');
    state.runs = body.runs || [];
    renderRuns();
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
    $('workflowStatus').textContent = `Workflow: ${exec.workflowStatus || '-'}`;
    $('workflowStatus').className = `badge ${badgeClass(exec.workflowStatus)}`;
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

  $('loginBtn').onclick = login;
  $('tokenInput').onkeydown = (e) => { if (e.key === 'Enter') login(); };
  $('operatorInput').onkeydown = (e) => { if (e.key === 'Enter') login(); };
  $('forgetTokenBtn').onclick = () => { sessionStorage.removeItem('papToken'); sessionStorage.removeItem('papOperator'); state.token=''; state.operator=''; $('operatorBadge').textContent='Оператор: -'; if (state.ws) state.ws.close(); showLogin(); };
  $('refreshRunsBtn').onclick = () => refreshRuns().catch(e => toast(e.message));
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

  if (state.token && state.operator) { $('tokenInput').value=state.token; $('operatorInput').value=state.operator; login(); } else showLogin();
})();
