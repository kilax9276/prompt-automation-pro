// Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
// All rights reserved. See LICENSE at the repository root.
(() => {
  if (globalThis.__PAP_CHAT_BRIDGE_ACTIVE__) {
    return;
  }
  globalThis.__PAP_CHAT_BRIDGE_ACTIVE__ = true;

  const BRIDGE_VERSION = '2.11.7';
  const runtimeGuard = globalThis.PAPRuntimeGuard || null;
  const POLL_MS = 1500;
  const CHUNK_BYTES = 512 * 1024;
  const HTTP_TIMEOUT_MS = 12000;
  const CHUNK_TIMEOUT_MS = 20000;
  const LEASE_HEARTBEAT_MS = 5000;
  const LOCAL_ATTEMPT_FLOOR_MS = 45000;
  const RECOVERY_SOURCE_KEY = 'pap2:last-submitted-delivery-job-v1';
  const RECOVERY_SOURCE_MAX_AGE_MS = 2 * 60 * 60 * 1000;
  const ACTIVE = new Map();
  const PAGE_GATE = {
    href:'',
    fingerprint:'',
    stableSince:0,
    ready:false,
    lastReason:'BOOT'
  };
  let stopped = false;
  let loopTimer = null;

  const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));
  const now = () => Date.now();
  const norm = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const currentAdapter = () => globalThis.PAPChatAdapters?.current?.(location.href) || null;
  const currentChatInfo = () => globalThis.PAPChatAdapters?.describe?.(location.href) || {type:'unknown', label:'Unknown'};
  const chatLabel = () => currentChatInfo().label || 'Chat';

  function rememberSubmittedDelivery(job, reason = 'SUBMITTED') {
    if (!job?.runId || !job?.jobId) return;

    try {
      sessionStorage.setItem(
        RECOVERY_SOURCE_KEY,
        JSON.stringify({
          runId:String(job.runId),
          jobId:String(job.jobId),
          submittedAt:now(),
          page:location.href,
          reason:String(reason || 'SUBMITTED')
        })
      );
    } catch {}
  }

  function readSubmittedDelivery() {
    try {
      const value = JSON.parse(sessionStorage.getItem(RECOVERY_SOURCE_KEY) || 'null');
      if (!value || typeof value !== 'object') return null;
      const submittedAt = Number(value.submittedAt || 0);
      if (!submittedAt || now() - submittedAt > RECOVERY_SOURCE_MAX_AGE_MS) return null;
      if (!value.runId || !value.jobId) return null;
      return value;
    } catch {
      return null;
    }
  }

  async function maybeQueueFailedResponseReplay(cfg) {
    if (!currentAdapter()?.capabilities?.failedResponseRecovery) return null;
    const recovery = globalThis.PAPClaudeLastResponseRecovery;
    const request = recovery?.takeReplayRequest?.();
    if (!request) return null;

    const source = readSubmittedDelivery();

    try {
      const response = await http(
        'POST',
        '/api/chat-delivery/recovery/requeue',
        {
          tabId:cfg.tabId,
          page:location.href,
          // These are hints, not a hard requirement. Platform 4.2.12 also
          // resolves the latest submitted PAP job for this exact tab/page.
          sourceRunId:source?.runId || '',
          sourceJobId:source?.jobId || '',
          failureKey:request.failureKey,
          failureRowIndex:request.rowIndex,
          reason:'LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD'
        },
        HTTP_TIMEOUT_MS
      );

      const replayJob = response?.job || null;
      if (!replayJob?.runId || !replayJob?.jobId) {
        throw new Error(response?.error || 'RECOVERY_REPLAY_JOB_NOT_CREATED');
      }

      recovery?.markReplayQueued?.({
        failureKey:request.failureKey,
        runId:replayJob.runId,
        jobId:replayJob.jobId
      });

      console.warn('[PAP Chat Bridge] recovery replay job queued', {
        sourceRunId:replayJob.recoveryOf?.runId || source?.runId || '',
        sourceJobId:replayJob.recoveryOf?.jobId || source?.jobId || '',
        sourceResolution:replayJob.recoverySourceResolution || '',
        replayRunId:replayJob.runId,
        replayJobId:replayJob.jobId,
        rowIndex:request.rowIndex
      });

      // Start it directly. Normal poll is blocked while the failed last
      // response is still visible, but this special job exists precisely to
      // restore the composer and attachments under that condition.
      startJobAttempt(replayJob, cfg);
      return replayJob;
    } catch (error) {
      recovery?.markReplayFailed?.(
        request.failureKey,
        String(error?.message || error)
      );
      return null;
    }
  }

  function randomToken() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}-${Math.random().toString(36).slice(2)}`;
  }

  function withTimeout(promise, timeoutMs, label = 'OPERATION') {
    let timer = null;
    return Promise.race([
      Promise.resolve(promise),
      new Promise((_, reject) => {
        timer = setTimeout(
          () => reject(new Error(`${label}_TIMEOUT after ${timeoutMs} ms`)),
          timeoutMs
        );
      })
    ]).finally(() => {
      if (timer) clearTimeout(timer);
    });
  }

  async function runtimeMessage(payload, timeoutMs = HTTP_TIMEOUT_MS) {
    if (runtimeGuard && !runtimeGuard.runtimeAvailable()) {
      throw new Error('EXTENSION_CONTEXT_INVALIDATED');
    }
    try {
      return await withTimeout(
        chrome.runtime.sendMessage(payload),
        timeoutMs,
        'RUNTIME_MESSAGE'
      );
    } catch (error) {
      runtimeGuard?.observeError?.(error);
      throw error;
    }
  }

  async function runtimeConfig() {
    const r = await runtimeMessage({type: 'GET_RUNTIME_CONFIG'});
    if (!r?.ok || !r.supported) return null;
    // The per-tab switch must gate the outbound side too, not only parsing.
    // Without this the bridge kept polling on a tab the operator had switched
    // off: the console saw it as online and could hand it delivery jobs.
    // background.js stays the single source of truth, and the check runs every
    // cycle so ON and OFF take effect without reloading the page.
    if (!r.enabled) return null;
    return r;
  }

  async function http(method, path, body = null, timeoutMs = HTTP_TIMEOUT_MS) {
    const r = await runtimeMessage(
      {type:'PAP_CHAT_BRIDGE_HTTP', method, path, body},
      timeoutMs
    );
    if (!r?.ok) throw new Error(r?.error || `HTTP ${r?.status || '?'}`);
    return r.body;
  }

  function b64ToBytes(text) {
    const binary = atob(String(text || ''));
    const bytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);
    return bytes;
  }

  function findComposer() {
    return currentAdapter()?.findComposer?.(document) || null;
  }

  function isChatConversationUrl(url = location.href) {
    return Boolean(globalThis.PAPChatSites?.identify?.(url)?.supported);
  }

  function pageHydrationSnapshot() {
    const adapter = currentAdapter();
    const rows = adapter?.transcriptRows?.(document) || [];
    const latest = rows.length ? rows[rows.length - 1] : null;
    const composer = findComposer();
    const readyState = String(document.readyState || '');
    const meta = latest ? (adapter?.rowMeta?.(latest) || {}) : {};
    const latestIndexRaw = String(meta.dataIndex ?? '');
    const latestIndex = Number(latestIndexRaw);
    const latestPerfRow = latest ? String(adapter?.rowRole?.(latest) || '') : '';
    const latestStreaming = String(meta.streaming ?? '');
    const latestIsLast = String(meta.lastMessage ?? (latest ? 'true' : ''));
    const chatUrl = isChatConversationUrl();

    const reasons = [];
    if (readyState !== 'complete') reasons.push(`DOCUMENT_${readyState || 'UNKNOWN'}`);
    if (!adapter) reasons.push('CHAT_ADAPTER_MISSING');
    if (!composer) reasons.push('COMPOSER_MISSING');
    if (chatUrl && rows.length && latestPerfRow === 'assistant') {
      const turn = adapter?.inspectTurnState?.(document);
      if (turn?.failed) reasons.push('LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD');
    }

    const structurallyReady = reasons.length === 0;
    const fingerprint = JSON.stringify([
      currentChatInfo().type,
      location.href,
      readyState,
      Boolean(composer),
      adapter?.rowKey?.(latest) || '',
      latestIndexRaw,
      latestPerfRow,
      latestStreaming,
      latestIsLast
    ]);

    return {
      structurallyReady,
      reasons,
      fingerprint,
      readyState,
      chatUrl,
      chatType:currentChatInfo().type,
      composerReady:Boolean(composer),
      latestIndex:Number.isFinite(latestIndex) ? latestIndex : null,
      latestPerfRow,
      latestStreaming,
      latestIsLast
    };
  }

  function pageHydrationGate(stableMs = 1800) {
    const snap = pageHydrationSnapshot();
    const href = location.href;

    if (PAGE_GATE.href !== href) {
      PAGE_GATE.href = href;
      PAGE_GATE.fingerprint = '';
      PAGE_GATE.stableSince = 0;
      PAGE_GATE.ready = false;
      PAGE_GATE.lastReason = 'URL_CHANGED';
    }

    if (!snap.structurallyReady) {
      PAGE_GATE.fingerprint = snap.fingerprint;
      PAGE_GATE.stableSince = 0;
      PAGE_GATE.ready = false;
      PAGE_GATE.lastReason = snap.reasons.join(',') || 'NOT_READY';
      return {...snap, ready:false, stableForMs:0, gateReason:PAGE_GATE.lastReason};
    }

    if (PAGE_GATE.fingerprint !== snap.fingerprint) {
      PAGE_GATE.fingerprint = snap.fingerprint;
      PAGE_GATE.stableSince = now();
      PAGE_GATE.ready = false;
      PAGE_GATE.lastReason = 'HYDRATION_FINGERPRINT_CHANGED';
      return {...snap, ready:false, stableForMs:0, gateReason:PAGE_GATE.lastReason};
    }

    if (!PAGE_GATE.stableSince) PAGE_GATE.stableSince = now();

    const stableForMs = now() - PAGE_GATE.stableSince;
    PAGE_GATE.ready = stableForMs >= stableMs;
    PAGE_GATE.lastReason = PAGE_GATE.ready
      ? 'PAGE_HYDRATED'
      : `WAIT_STABLE_${stableMs}MS`;

    return {
      ...snap,
      ready:PAGE_GATE.ready,
      stableForMs,
      gateReason:PAGE_GATE.lastReason
    };
  }

  async function waitForPageHydration(job, cfg, leaseToken, stableMs = 1800) {
    let lastHeartbeat = 0;

    for (;;) {
      if (stopped) throw new Error('bridge stopped');

      const responseRecovery = globalThis.PAPClaudeLastResponseRecovery?.snapshot?.();
      if (responseRecovery?.blocked && !job?.recoveryReplay) {
        if (now() - lastHeartbeat >= LEASE_HEARTBEAT_MS) {
          lastHeartbeat = now();
          await event(
            job, cfg,
            {
              event:'HEARTBEAT',
              clientPhase:'WAITING_LAST_RESPONSE_RECOVERY',
              busySignals:[responseRecovery.reason],
              readiness:{
                rowIndex:responseRecovery.rowIndex,
                cooldownRemainingMs:responseRecovery.cooldownRemainingMs
              }
            },
            leaseToken, 5000
          ).catch(() => {});
        }
        await sleep(150);
        continue;
      }

      const gate = pageHydrationGate(stableMs);
      if (gate.ready) {
        await event(
          job, cfg,
          {
            event:'HEARTBEAT',
            clientPhase:'PAGE_READY_CONFIRMED',
            busySignals:[],
            readiness:{
              documentReadyState:gate.readyState,
              latestIndex:gate.latestIndex,
              latestPerfRow:gate.latestPerfRow,
              latestStreaming:gate.latestStreaming,
              pageStableForMs:gate.stableForMs
            }
          },
          leaseToken, 5000
        ).catch(() => {});
        return gate;
      }

      if (now() - lastHeartbeat >= LEASE_HEARTBEAT_MS) {
        lastHeartbeat = now();
        await event(
          job, cfg,
          {
            event:'HEARTBEAT',
            clientPhase:'WAITING_PAGE_READY',
            busySignals:gate.reasons,
            readiness:{
              documentReadyState:gate.readyState,
              composerReady:gate.composerReady,
              latestIndex:gate.latestIndex,
              latestPerfRow:gate.latestPerfRow,
              latestStreaming:gate.latestStreaming,
              latestIsLast:gate.latestIsLast,
              gateReason:gate.gateReason,
              pageStableForMs:gate.stableForMs
            }
          },
          leaseToken, 5000
        ).catch(() => {});
      }

      await sleep(150);
    }
  }

  function latestTranscriptRows() {
    return currentAdapter()?.transcriptRows?.(document) || [];
  }

  function conversationMarker() {
    const adapter = currentAdapter();
    const rows = latestTranscriptRows();
    const latest = rows.length ? rows[rows.length - 1] : null;
    if (!latest) return {rowCount:0, latestRowKey:'', latestPerfRow:'', latestIndex:null};

    const meta = adapter?.rowMeta?.(latest) || {};
    const numericIndex = Number(meta.dataIndex);
    return {
      rowCount:rows.length,
      latestRowKey:adapter?.rowKey?.(latest) || `${adapter?.rowRole?.(latest) || ''}:${simpleHash(String(latest.textContent || '').slice(-1200))}`,
      latestPerfRow:adapter?.rowRole?.(latest) || '',
      latestIndex:Number.isFinite(numericIndex) ? numericIndex : null
    };
  }

  function chatActivitySnapshot() {
    const adapter = currentAdapter();
    const info = currentChatInfo();
    const turn = adapter?.inspectTurnState?.(document) || {
      kind:'UNKNOWN', ready:false, busy:true, row:null, signals:['CHAT_ADAPTER_SIGNALS_UNAVAILABLE']
    };
    const composer = findComposer();
    const latest = turn.row || latestTranscriptRows().at(-1) || null;
    const meta = latest ? (adapter?.rowMeta?.(latest) || {}) : {};
    const ready = Boolean(composer && (turn.ready || (!latest && !turn.busy)));

    return {
      busy:!ready,
      ready,
      chatType:info.type,
      composerReady:Boolean(composer),
      latestAssistant:adapter?.rowRole?.(latest) === 'assistant',
      rowStreamingAttr:String(meta.streaming ?? ''),
      innerStreamingTrue:Boolean(turn.busy),
      innerStreamingFalse:Boolean(turn.ready),
      responding:Boolean(turn.busy),
      finished:Boolean(turn.ready),
      stopResponse:Boolean(turn.signals?.some?.((x) => /STOP|STREAMING/i.test(String(x)))),
      signals:[...(turn.signals || [])],
      marker:conversationMarker()
    };
  }

  // Backward-compatible local name: all callers now receive normalized chat activity.
  const claudeActivitySnapshot = chatActivitySnapshot;

  function conversationAdvanced(baseline, current) {
    if (!baseline || !current) return false;

    // Do NOT use transcript rowCount. The probe showed Claude virtualizes the
    // transcript during a single response (e.g. 5 -> 3 and 5 -> 4 rows).
    // data-index remained monotonic across real turns: 3 -> 5 -> 7 -> 9.
    const baseIndex = Number(baseline.latestIndex);
    const currentIndex = Number(current.latestIndex);

    if (
      Number.isFinite(baseIndex) &&
      Number.isFinite(currentIndex)
    ) {
      return currentIndex > baseIndex;
    }

    return Boolean(
      baseline.latestRowKey &&
      current.latestRowKey &&
      baseline.latestRowKey !== current.latestRowKey
    );
  }

  function jobConsumedError(reason) {
    const error = new Error(`JOB_CONSUMED:${reason || 'conversation advanced'}`);
    error.code = 'JOB_CONSUMED';
    return error;
  }

  function isJobConsumedError(error) {
    return error?.code === 'JOB_CONSUMED' ||
      /^JOB_CONSUMED:/.test(String(error?.message || error || ''));
  }

  function composerRoot(composer) {
    return currentAdapter()?.composerRoot?.(composer) || composer?.closest('form') || document.body;
  }

  function findFileInput(composer) {
    return currentAdapter()?.findFileInput?.(composer) || null;
  }

  function composerText(el) {
    if (!el) return '';
    if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
      return String(el.value || '');
    }
    return String(el.innerText || el.textContent || '');
  }

  function normalizedComposerText(text) {
    return String(text || '')
      .replace(/\r\n?/g, '\n')
      .replace(/\u00a0/g, ' ')
      .replace(/\s+/g, ' ')
      .trim();
  }

  function composerHasExpectedText(el, expected) {
    return normalizedComposerText(composerText(el)) === normalizedComposerText(expected);
  }

  function selectComposerContents(el) {
    el.focus({preventScroll:true});
    const selection = window.getSelection();
    const range = document.createRange();
    range.selectNodeContents(el);
    selection.removeAllRanges();
    selection.addRange(range);
  }

  async function waitForComposerText(expected, timeoutMs = 1200) {
    const deadline = now() + timeoutMs;
    let last = '';
    while (now() < deadline) {
      const current = findComposer();
      if (current) {
        last = composerText(current);
        if (composerHasExpectedText(current, expected)) {
          return {ok:true, composer:current, actual:last};
        }
      }
      await sleep(80);
    }
    return {ok:false, composer:findComposer(), actual:last};
  }

  function setNativeControlValue(el, text) {
    const proto = el instanceof HTMLTextAreaElement
      ? HTMLTextAreaElement.prototype
      : HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto, 'value')?.set;
    if (setter) setter.call(el, text);
    else el.value = text;
    el.dispatchEvent(new InputEvent('input', {
      bubbles:true,
      composed:true,
      inputType:'insertText',
      data:text
    }));
    el.dispatchEvent(new Event('change', {bubbles:true, composed:true}));
  }

  function trySyntheticPaste(el, text) {
    selectComposerContents(el);
    const data = new DataTransfer();
    data.setData('text/plain', text);
    const event = new ClipboardEvent('paste', {
      bubbles:true,
      cancelable:true,
      composed:true,
      clipboardData:data
    });
    return el.dispatchEvent(event);
  }

  function tryExecCommandInsert(el, text) {
    selectComposerContents(el);
    try {
      return Boolean(document.execCommand('insertText', false, text));
    } catch (_) {
      return false;
    }
  }

  function replaceContentEditableDom(el, text) {
    el.focus({preventScroll:true});
    el.replaceChildren();

    const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
    if (!lines.length) lines.push('');

    for (const line of lines) {
      const p = document.createElement('p');
      if (line) p.textContent = line;
      else p.appendChild(document.createElement('br'));
      el.appendChild(p);
    }

    el.dispatchEvent(new InputEvent('beforeinput', {
      bubbles:true,
      cancelable:true,
      composed:true,
      inputType:'insertText',
      data:text
    }));
    el.dispatchEvent(new InputEvent('input', {
      bubbles:true,
      composed:true,
      inputType:'insertText',
      data:text
    }));
    el.dispatchEvent(new Event('change', {bubbles:true, composed:true}));

    // ProseMirror/Tiptap watches DOM mutations. A blur/focus cycle forces
    // pending DOM observation to settle instead of only changing visual DOM.
    el.blur();
    el.focus({preventScroll:true});
  }

  async function setTextValue(el, text) {
    if (!el) throw new Error(`${chatLabel()} composer not found`);

    const expected = String(text || '');
    const attempts = [];

    if (el instanceof HTMLTextAreaElement || el instanceof HTMLInputElement) {
      setNativeControlValue(el, expected);
      const check = await waitForComposerText(expected);
      if (check.ok) return 'native-value';
      throw new Error(
        `${chatLabel()} composer text verification failed after native-value; actual=${JSON.stringify(check.actual)}`
      );
    }

    if (!el.isContentEditable) {
      throw new Error(`Unsupported ${chatLabel()} composer element`);
    }

    // Strategy 1: let Tiptap/ProseMirror process a paste event itself.
    try {
      attempts.push('synthetic-paste');
      trySyntheticPaste(el, expected);
      let check = await waitForComposerText(expected);
      if (check.ok) return 'synthetic-paste';
    } catch (e) {
      attempts.push(`synthetic-paste-error:${String(e?.message || e)}`);
    }

    // Strategy 2: browser editing command on a real contenteditable selection.
    try {
      attempts.push('execCommand-insertText');
      const current = findComposer() || el;
      tryExecCommandInsert(current, expected);
      let check = await waitForComposerText(expected);
      if (check.ok) return 'execCommand-insertText';
    } catch (e) {
      attempts.push(`execCommand-error:${String(e?.message || e)}`);
    }

    // Strategy 3: mutate the editor DOM in ProseMirror paragraph form and
    // emit input/change. This is intentionally last because it is more direct.
    try {
      attempts.push('prosemirror-dom-input');
      const current = findComposer() || el;
      replaceContentEditableDom(current, expected);
      let check = await waitForComposerText(expected, 1800);
      if (check.ok) return 'prosemirror-dom-input';
      attempts.push(`verification-actual:${JSON.stringify(check.actual)}`);
    } catch (e) {
      attempts.push(`prosemirror-dom-error:${String(e?.message || e)}`);
    }

    throw new Error(
      `${chatLabel()} composer text was not inserted. Strategies: ${attempts.join(' | ')}`
    );
  }

  function visibleTextNodesContaining(root, needle) {
    const wanted = String(needle || '').toLowerCase();
    if (!wanted) return [];
    const all = [...(root || document).querySelectorAll('div,span,p,button,[role="status"],[role="alert"]')];
    return all.filter(el => norm(el.textContent).toLowerCase().includes(wanted) && el.getClientRects().length);
  }

  function uploadErrorSnapshot(root) {
    const selectors = '[role="alert"],[data-state="error"],[data-error="true"],[aria-invalid="true"]';
    const texts = [...(root || document).querySelectorAll(selectors)].map(x => norm(x.textContent)).filter(Boolean);
    return new Set(texts);
  }

  function newUploadError(root, baseline) {
    const texts = [...(root || document).querySelectorAll('[role="alert"],[data-state="error"],[data-error="true"],[aria-invalid="true"]')]
      .map(x => norm(x.textContent)).filter(Boolean);
    const uploadWords = /(upload|attach|file|загруз|файл|вложен|too large|unsupported|failed|ошиб)/i;
    return texts.find(t => !baseline.has(t) && uploadWords.test(t)) || null;
  }

  function attachmentCard(root, fileName) {
    return currentAdapter()?.findAttachmentCard?.(root, fileName, document) || null;
  }

  function observedFileThumbnailState(tile, fileName) {
    return currentAdapter()?.inspectAttachmentCard?.(tile, fileName) || {
      observed:false, pending:false, ready:false, token:'ATTACHMENT_SIGNALS_UNAVAILABLE'
    };
  }

  function fileCard(root, fileName) {
    // STRICT POSITIVE ONLY: adapters search only the live unsent composer area.
    return attachmentCard(root, fileName);
  }

  function liveAttachmentContext(fileName) {
    // Chat UIs may replace/remount the composer subtree while a
    // file changes from "Loading attachment" to the final file-thumbnail.
    // Always resolve the CURRENT editor/root/card on every observation.
    const composer = findComposer();
    if (!composer || !composer.isConnected) {
      return {composer:null, root:null, card:null};
    }

    const root = composerRoot(composer);
    if (!root || !root.isConnected) {
      return {composer, root:null, card:null};
    }

    return {
      composer,
      root,
      card:fileCard(root, fileName)
    };
  }


  function numericAttr(node, name) {
    const raw = node?.getAttribute?.(name);
    if (raw == null || raw === '') return null;
    const value = Number(raw);
    return Number.isFinite(value) ? value : null;
  }

  function progressState(progress) {
    if (!progress) {
      return {busy:false, complete:false, value:null, max:null, text:''};
    }

    let value = numericAttr(progress, 'aria-valuenow');
    if (value == null && 'value' in progress) {
      const v = Number(progress.value);
      if (Number.isFinite(v)) value = v;
    }

    let max = numericAttr(progress, 'aria-valuemax');
    if (max == null && 'max' in progress) {
      const m = Number(progress.max);
      if (Number.isFinite(m) && m > 0) max = m;
    }
    if (max == null || max <= 0) max = 100;

    const text = norm(
      progress.getAttribute?.('aria-valuetext') ||
      progress.textContent ||
      ''
    );

    const complete = Boolean(
      /(^|\D)100\s*%/.test(text) ||
      (value != null && value >= max)
    );

    return {busy:!complete, complete, value, max, text};
  }

  function busyInfo(root, card) {
    const scope = card || root;

    if (!scope) {
      return {
        busy:true,
        hardBusy:true,
        progressComplete:false,
        readyControl:false,
        cancelControl:false,
        token:'NO_SCOPE'
      };
    }

    const ariaBusyNode = scope.matches?.('[aria-busy="true"]')
      ? scope
      : scope.querySelector?.('[aria-busy="true"]');

    const loadingState = scope.matches?.(
      '[data-state="loading"],[data-state="uploading"],[data-state="pending"],[data-loading="true"]'
    )
      ? scope
      : scope.querySelector?.(
          '[data-state="loading"],[data-state="uploading"],[data-state="pending"],[data-loading="true"]'
        );

    const progressBars = [
      ...(scope.matches?.('[role="progressbar"]') ? [scope] : []),
      ...(scope.querySelectorAll?.('[role="progressbar"]') || [])
    ];
    const progressStates = progressBars.map(progressState);
    const incompleteProgress = progressStates.some((state) => state.busy);
    const progressComplete = progressStates.some((state) => state.complete);

    const buttons = [
      ...(scope.matches?.('button') ? [scope] : []),
      ...(scope.querySelectorAll?.('button') || [])
    ];

    const buttonText = (button) =>
      `${button.getAttribute?.('aria-label') || ''} ${button.title || ''} ${button.textContent || ''}`;

    const readyControl = buttons.some((button) =>
      /(remove file|remove attachment|delete file|удалить файл|удалить вложение)/i.test(
        buttonText(button)
      )
    );

    const cancelControl = buttons.some((button) =>
      /(cancel upload|cancel attachment|отменить загруз|прервать загруз)/i.test(
        buttonText(button)
      )
    );

    const txt = norm(scope.textContent || '');
    const textualBusy =
      /(uploading|loading attachment|загружается|ид[её]т загрузка|processing file|обработка файла)/i.test(txt);

    // A 100% progressbar is NOT busy. Likewise a ready/remove control wins over
    // stale aria-busy/data-state attributes that a chat UI may leave around.
    const hardBusy = Boolean(
      incompleteProgress ||
      cancelControl ||
      (ariaBusyNode && !progressComplete && !readyControl) ||
      (loadingState && !progressComplete && !readyControl)
    );

    const busy = Boolean(
      hardBusy ||
      (textualBusy && !progressComplete && !readyControl)
    );

    const progressToken = progressStates.map((state) =>
      `${state.value ?? ''}/${state.max ?? ''}/${state.complete ? 'done' : 'busy'}`
    ).join(',');

    return {
      busy,
      hardBusy,
      progressComplete,
      readyControl,
      cancelControl,
      textualBusy,
      token:norm(
        `${txt}|${progressToken}|${ariaBusyNode ? 'aria-busy' : ''}|` +
        `${loadingState?.getAttribute?.('data-state') || ''}|` +
        `${readyControl ? 'ready-control' : ''}|` +
        `${cancelControl ? 'cancel-control' : ''}`
      ).slice(0, 4000)
    };
  }

  function attachmentCardToken(card, info) {
    if (!card) return '';
    return simpleHash(
      norm(
        `${card.textContent || ''}|${info.token}|` +
        `${info.progressComplete ? '100%' : ''}|` +
        `${info.readyControl ? 'ready' : ''}`
      ).slice(0, 8000)
    );
  }

  function uploadCardReady(card, info, stableForMs, fileName) {
    if (!card) return false;

    const strictState = observedFileThumbnailState(card, fileName);

    if (currentChatInfo().type !== 'claude') {
      return Boolean(strictState.observed && strictState.ready && !strictState.pending && stableForMs >= 200);
    }

    // Adapter-declared exact attachment readiness is the positive signal.
    // The exact target filename must exist inside an actual file-thumbnail,
    // pending/busy/loading must be gone, and filename must be the ready control.
    if (
      strictState.observed &&
      strictState.ready &&
      !strictState.pending &&
      stableForMs >= 200
    ) {
      return true;
    }

    // Fail closed for an observed file-thumbnail whose exact ready transition
    // has not happened yet. Do not "stable-card" guess.
    if (strictState.observed) {
      return false;
    }

    // No strict file-thumbnail -> definitely not uploaded.
    return false;
  }

  function simpleHash(text) {
    let h = 2166136261;
    const s = String(text || '');
    for (let i=0;i<s.length;i++) { h ^= s.charCodeAt(i); h = Math.imul(h,16777619); }
    return (h >>> 0).toString(16);
  }

  async function event(job, cfg, body, leaseToken = null, timeoutMs = HTTP_TIMEOUT_MS) {
    const payload = {
      tabId: cfg.tabId,
      url: location.href,
      chatType: currentChatInfo().type,
      chatLabel: currentChatInfo().label,
      ...body
    };
    if (leaseToken) payload.leaseToken = leaseToken;

    return await http(
      'POST',
      `/api/chat-delivery/jobs/${encodeURIComponent(job.runId)}/${encodeURIComponent(job.jobId)}/event`,
      payload,
      timeoutMs
    );
  }

  async function claimJob(job, cfg, leaseToken) {
    const response = await event(
      job,
      cfg,
      {event:'CLAIM', leaseToken},
      null,
      HTTP_TIMEOUT_MS
    );
    const claimed = response?.job || response;
    if (!claimed || String(claimed.claimLeaseToken || '') !== String(leaseToken)) {
      throw new Error('CLAIM_NOT_CONFIRMED');
    }
    return claimed;
  }

  async function ensureConversationBaseline(job, cfg, leaseToken) {
    if (job.conversationBaseline?.latestRowKey || job.conversationBaseline?.rowCount) return job;

    const response = await event(
      job, cfg,
      {event:'CONVERSATION_BASELINE', marker:conversationMarker()},
      leaseToken
    );
    return response?.job || response || job;
  }

  async function waitForChatIdle(job, cfg, leaseToken, quietMs = 400) {
    let readySince = 0;
    let lastReadyKey = '';
    let lastHeartbeat = 0;

    for (;;) {
      if (stopped) throw new Error('bridge stopped');

      if (job?.messageState === 'INSERTED') {
        await throwIfConversationConsumed(job, cfg, leaseToken);
      }

      const snap = claudeActivitySnapshot();
      const readyKey = JSON.stringify([
        snap.marker.latestRowKey,
        snap.marker.latestIndex,
        snap.ready,
        snap.rowStreamingAttr,
        snap.innerStreamingTrue,
        snap.stopResponse,
        snap.responding
      ]);

      if (snap.ready && snap.composerReady) {
        if (readyKey !== lastReadyKey) {
          lastReadyKey = readyKey;
          readySince = now();
        } else if (!readySince) {
          readySince = now();
        }

        if (readySince && now() - readySince >= quietMs) {
          await event(
            job, cfg,
            {
              event:'HEARTBEAT',
              clientPhase:'CHAT_READY_CONFIRMED',
              busySignals:[],
              readiness:{
                latestIndex:snap.marker.latestIndex,
                rowStreamingAttr:snap.rowStreamingAttr,
                innerStreamingFalse:snap.innerStreamingFalse,
                stopResponse:snap.stopResponse,
                responding:snap.responding,
                finished:snap.finished
              }
            },
            leaseToken, 5000
          ).catch(() => {});
          return snap;
        }
      } else {
        readySince = 0;
        lastReadyKey = readyKey;
      }

      if (now() - lastHeartbeat >= LEASE_HEARTBEAT_MS) {
        lastHeartbeat = now();
        await event(
          job, cfg,
          {
            event:'HEARTBEAT',
            clientPhase:'WAITING_CHAT_READY',
            busySignals:snap.signals,
            readiness:{
              latestIndex:snap.marker.latestIndex,
              latestAssistant:snap.latestAssistant,
              rowStreamingAttr:snap.rowStreamingAttr,
              innerStreamingTrue:snap.innerStreamingTrue,
              innerStreamingFalse:snap.innerStreamingFalse,
              stopResponse:snap.stopResponse,
              responding:snap.responding,
              finished:snap.finished
            }
          },
          leaseToken, 5000
        ).catch(() => {});
      }

      await sleep(150);
    }
  }

  async function markConversationConsumed(job, cfg, leaseToken, reason) {
    rememberSubmittedDelivery(job, reason || 'MANUAL_SUBMIT_DETECTED');

    await event(
      job, cfg,
      {
        event:'CONSUMED',
        reason:String(reason || 'MANUAL_SUBMIT_DETECTED'),
        marker:conversationMarker()
      },
      leaseToken
    );
    job.status = 'CONSUMED';
    job.sendState = 'MANUAL_SENT';
    throw jobConsumedError(reason);
  }

  async function throwIfConversationConsumed(job, cfg, leaseToken) {
    if (job?.messageState !== 'INSERTED') return false;

    const expected = String(job.message || '');
    const composer = findComposer();

    if (composer && composerHasExpectedText(composer, expected)) {
      return false;
    }

    const snap = claudeActivitySnapshot();

    if (conversationAdvanced(job.conversationBaseline, snap.marker)) {
      await markConversationConsumed(
        job,
        cfg,
        leaseToken,
        'CONVERSATION_ADVANCED_AFTER_INSERT'
      );
    }

    if (snap.busy) {
      await markConversationConsumed(
        job,
        cfg,
        leaseToken,
        'CHAT_STARTED_RESPONDING_AFTER_INSERT'
      );
    }

    // If neither signal is visible, verifyInsertedMessageOwnership() gives the
    // editor a short remount grace period and then CONSUMES the job.
    // It never reinserts the text.
    return false;
  }

  async function releaseJob(job, cfg, leaseToken) {
    try {
      await event(job, cfg, {event:'RELEASE'}, leaseToken, 5000);
    } catch (_) {}
  }

  function leaseHeartbeat(job, cfg, leaseToken) {
    return event(job, cfg, {event:'HEARTBEAT'}, leaseToken, 5000).catch(() => {});
  }

  async function fetchAttachment(job, attachment, cfg, leaseToken) {
    const parts = [];
    let offset = 0;
    let total = Number(attachment.totalBytes || attachment.size || 0);

    await event(
      job,
      cfg,
      {
        event:'ATTACHMENT_STATE',
        attachmentId:attachment.attachmentId,
        state:'FETCHING',
        phase:'SERVER_FETCH',
        bytesFetched:0,
        totalBytes:total
      },
      leaseToken
    );

    for (;;) {
      const path =
        `/api/chat-delivery/jobs/${encodeURIComponent(job.runId)}/${encodeURIComponent(job.jobId)}` +
        `/attachments/${encodeURIComponent(attachment.attachmentId)}/chunk?offset=${offset}&limit=${CHUNK_BYTES}`;

      const r = await http('GET', path, null, CHUNK_TIMEOUT_MS);
      if (!r?.ok) throw new Error(r?.error || 'attachment chunk failed');

      const bytes = b64ToBytes(r.dataBase64);
      parts.push(bytes);
      offset += bytes.byteLength;
      total = Number(r.totalBytes || total || offset);

      await event(
        job,
        cfg,
        {
          event:'ATTACHMENT_STATE',
          attachmentId:attachment.attachmentId,
          state:'FETCHING',
          phase:'SERVER_FETCH',
          bytesFetched:offset,
          totalBytes:total
        },
        leaseToken
      );

      if (r.eof) break;
    }

    return new File(parts, attachment.name, {
      type: attachment.mimeType || 'application/octet-stream',
      lastModified: Date.now()
    });
  }

  async function removePriorFailedCard(fileName, composer) {
    const root = composerRoot(composer);
    const card = fileCard(root, fileName);
    if (!card) return;
    const button = [...card.querySelectorAll('button')].find(b => /(remove|delete|cancel|close|удал|отмен|закры)/i.test(`${b.getAttribute('aria-label') || ''} ${b.title || ''} ${b.textContent || ''}`));
    if (button && !button.disabled) {
      button.click();
      await sleep(350);
    }
  }

  async function monitorExistingUpload(job, attachment, cfg, leaseToken, root, card) {
    let lastProgress = now();
    let lastToken = '';
    let lastHeartbeat = 0;
    let cardStableSince = now();
    let lastCardToken = '';
    let missingSince = 0;
    const stallMs = Math.max(30000, Number(job.stallTimeoutSeconds || 120) * 1000);
    const baselineErrors = uploadErrorSnapshot(root);

    for (;;) {
      if (stopped) throw new Error('bridge stopped');
      await throwIfConversationConsumed(job, cfg, leaseToken);

      const live = liveAttachmentContext(attachment.name);
      const liveRoot = live.root;
      const liveCard = live.card;

      const err = liveRoot
        ? newUploadError(liveRoot, baselineErrors)
        : null;
      if (err) {
        await event(
          job, cfg,
          {
            event:'ATTACHMENT_STATE',
            attachmentId:attachment.attachmentId,
            state:'ERROR',
            phase:'CHAT_UPLOAD_ERROR',
            error:err
          },
          leaseToken
        );
        return 'error';
      }

      // A chat UI can briefly remove the old pending tile and mount the final card
      // into a NEW composer subtree. Do not treat that short remount gap as a
      // missing upload, and never keep observing the stale pre-remount root.
      if (!liveCard) {
        if (!missingSince) missingSince = now();

        if (now() - missingSince >= 2000) {
          return 'missing';
        }

        if (now() - lastHeartbeat >= LEASE_HEARTBEAT_MS) {
          lastHeartbeat = now();
          await leaseHeartbeat(job, cfg, leaseToken);
        }

        await sleep(100);
        continue;
      }

      missingSince = 0;
      const info = busyInfo(liveRoot, liveCard);
      const token = simpleHash(`${Boolean(liveCard)}|${info.token}`);
      const cardToken = attachmentCardToken(liveCard, info);

      if (token !== lastToken) {
        lastToken = token;
        lastProgress = now();

        await event(
          job, cfg,
          {
            event:'ATTACHMENT_STATE',
            attachmentId:attachment.attachmentId,
            state:'CHAT_UPLOADING',
            phase:'CHAT_UPLOAD_RECOVERY',
            progressToken:token
          },
          leaseToken
        );
      } else if (now() - lastHeartbeat >= LEASE_HEARTBEAT_MS) {
        lastHeartbeat = now();
        await leaseHeartbeat(job, cfg, leaseToken);
      }

      if (cardToken !== lastCardToken) {
        lastCardToken = cardToken;
        cardStableSince = now();
      }

      const stableForMs = now() - cardStableSince;
      if (uploadCardReady(liveCard, info, stableForMs, attachment.name)) {
        await event(
          job, cfg,
          {
            event:'ATTACHMENT_STATE',
            attachmentId:attachment.attachmentId,
            state:'UPLOADED',
            phase:'CHAT_ATTACHMENT_READY_RECOVERED',
            bytesFetched:Number(attachment.size || attachment.totalBytes || 0),
            totalBytes:Number(attachment.size || attachment.totalBytes || 0),
            progressToken:token
          },
          leaseToken
        );
        return 'uploaded';
      }

      if (now() - lastProgress > stallMs) {
        // IMPORTANT: an existing matching card is already present in the chat.
        // Do not auto-attach another copy. Surface STALLED for manual retry.
        await event(
          job, cfg,
          {
            event:'ATTACHMENT_STATE',
            attachmentId:attachment.attachmentId,
            state:'STALLED',
            phase:'EXISTING_CHAT_CARD_NOT_CONFIRMED',
            error:
              `Matching chat attachment card exists but completion could not ` +
              `be confirmed for ${Math.round(stallMs / 1000)} seconds. ` +
              `Automatic duplicate upload was blocked.`
          },
          leaseToken
        );
        return 'stalled';
      }

      await sleep(500);
    }
  }

  async function recoverAttachmentIfPossible(job, attachment, cfg, leaseToken) {
    const composer = findComposer();
    if (!composer) return 'missing';

    const root = composerRoot(composer);
    const card = fileCard(root, attachment.name);

    if (!card) {
      if (String(attachment.state || '') === 'CHAT_UPLOADING') {
        await event(
          job, cfg,
          {
            event:'ATTACHMENT_STATE',
            attachmentId:attachment.attachmentId,
            state:'STALLED',
            phase:'CHAT_UPLOAD_STATE_WITHOUT_CARD_NO_AUTO_RETRY',
            error:
              'Chat upload had already been started, but the matching card ' +
              'cannot currently be confirmed. Automatic re-attach is blocked ' +
              'to prevent duplicate files. Use manual retry if needed.'
          },
          leaseToken
        );
        return 'stalled';
      }
      return 'missing';
    }

    // Once a matching card exists, this path never re-attaches the same file.
    return await monitorExistingUpload(
      job,
      attachment,
      cfg,
      leaseToken,
      root,
      card
    );
  }

  async function attachFile(job, attachment, file, cfg, leaseToken) {
    const composer = findComposer();
    if (!composer) throw new Error(`${chatLabel()} composer not found`);

    if (attachment.state === 'RETRY_PENDING') {
      await removePriorFailedCard(attachment.name, composer);
    }

    const root = composerRoot(composer);

    // Last-moment idempotency guard: DOM can change between poll/fetch/attach.
    // If the same file card already exists, monitor it instead of adding a copy.
    const existing = fileCard(root, attachment.name);
    if (existing) {
      return await monitorExistingUpload(
        job,
        attachment,
        cfg,
        leaseToken,
        root,
        existing
      );
    }

    const baselineErrors = uploadErrorSnapshot(root);
    const input = findFileInput(composer);
    if (!input) throw new Error(`${chatLabel()} file input not found`);

    try {
      // File inputs may be reused by the chat UI. Clearing before assigning a new
      // DataTransfer guarantees that the next change event is a real new selection.
      input.value = '';
    } catch {}

    const dt = new DataTransfer();
    dt.items.add(file);
    input.files = dt.files;
    input.dispatchEvent(new Event('input', {bubbles:true}));
    input.dispatchEvent(new Event('change', {bubbles:true}));

    let lastProgress = now();
    let lastToken = '';
    let lastHeartbeat = 0;
    let cardStableSince = 0;
    let lastCardToken = '';
    const stallMs = Math.max(30000, Number(job.stallTimeoutSeconds || 120) * 1000);

    await event(
      job, cfg,
      {
        event:'ATTACHMENT_STATE',
        attachmentId:attachment.attachmentId,
        state:'CHAT_UPLOADING',
        phase:'CHAT_UPLOAD',
        bytesFetched:file.size,
        totalBytes:file.size,
        progressToken:'attach-start'
      },
      leaseToken
    );

    for (;;) {
      if (stopped) throw new Error('bridge stopped');
      await throwIfConversationConsumed(job, cfg, leaseToken);

      const live = liveAttachmentContext(attachment.name);
      const liveRoot = live.root;

      const err = liveRoot
        ? newUploadError(liveRoot, baselineErrors)
        : null;
      if (err) {
        await event(
          job, cfg,
          {
            event:'ATTACHMENT_STATE',
            attachmentId:attachment.attachmentId,
            state:'ERROR',
            phase:'CHAT_UPLOAD_ERROR',
            bytesFetched:file.size,
            totalBytes:file.size,
            error:err
          },
          leaseToken
        );
        return 'error';
      }

      // IMPORTANT: do not query the root captured before input/change.
      // The chat UI may replace the pending attachment subtree extremely quickly.
      // The probe showed the final ready card in the live composer ~116 ms
      // after the input event while the old bridge kept waiting.
      const card = live.card;
      const info = busyInfo(liveRoot, card);
      const strictState = observedFileThumbnailState(
        card,
        attachment.name
      );

      const token = simpleHash(
        `${Boolean(card)}|${Boolean(liveRoot)}|${info.token}|` +
        `${strictState.observed ? 'strict-card' : 'no-strict-card'}|` +
        `${strictState.ready ? 'strict-ready' : 'not-ready'}`
      );

      if (token !== lastToken) {
        lastToken = token;
        lastProgress = now();

        await event(
          job, cfg,
          {
            event:'ATTACHMENT_STATE',
            attachmentId:attachment.attachmentId,
            state:'CHAT_UPLOADING',
            phase:'CHAT_UPLOAD',
            bytesFetched:file.size,
            totalBytes:file.size,
            progressToken:token
          },
          leaseToken
        );
      } else if (now() - lastHeartbeat >= LEASE_HEARTBEAT_MS) {
        lastHeartbeat = now();
        await leaseHeartbeat(job, cfg, leaseToken);
      }

      if (card) {
        const cardToken = attachmentCardToken(card, info);
        if (cardToken !== lastCardToken) {
          lastCardToken = cardToken;
          cardStableSince = now();
        } else if (!cardStableSince) {
          cardStableSince = now();
        }

        const stableForMs = cardStableSince ? now() - cardStableSince : 0;
        if (uploadCardReady(card, info, stableForMs, attachment.name)) {
          await event(
            job, cfg,
            {
              event:'ATTACHMENT_STATE',
              attachmentId:attachment.attachmentId,
              state:'UPLOADED',
              phase:'CHAT_DRAFT_ATTACHMENT_READY',
              bytesFetched:file.size,
              totalBytes:file.size,
              progressToken:token
            },
            leaseToken
          );
          return 'uploaded';
        }
      } else {
        cardStableSince = 0;
        lastCardToken = '';
      }

      if (now() - lastProgress > stallMs) {
        if (card) {
          await event(
            job, cfg,
            {
              event:'ATTACHMENT_STATE',
              attachmentId:attachment.attachmentId,
              state:'STALLED',
              phase:'EXISTING_CHAT_CARD_NOT_CONFIRMED',
              bytesFetched:file.size,
              totalBytes:file.size,
              error:
                `Chat attachment card exists but completion could not be confirmed ` +
                `for ${Math.round(stallMs / 1000)} seconds. ` +
                `Automatic duplicate upload was blocked.`
            },
            leaseToken
          );
          return 'stalled';
        }

        throw new Error(
          `CHAT_UPLOAD_STALLED_NO_CARD after ${Math.round(stallMs / 1000)} seconds`
        );
      }

      await sleep(500);
    }
  }

  async function verifyInsertedMessageOwnership(
    job,
    cfg,
    leaseToken,
    expected,
    graceMs = 1200
  ) {
    const deadline = now() + Math.max(0, Number(graceMs) || 0);

    for (;;) {
      await throwIfConversationConsumed(job, cfg, leaseToken);

      const composer = findComposer();
      if (composer && composerHasExpectedText(composer, expected)) {
        return true;
      }

      if (now() >= deadline) break;
      await sleep(100);
    }

    // PAP inserted this text once, but no longer sees the exact text in the
    // live composer. From this moment PAP must stop owning the editor.
    //
    // Possible explanations include:
    // - user pressed Send and the chat already completed;
    // - user edited/cleared the draft;
    // - the chat remounted the editor in a way we cannot prove is safe.
    //
    // In all cases rewriting the Web Console message would be destructive.
    await markConversationConsumed(
      job,
      cfg,
      leaseToken,
      'INSERTED_MESSAGE_LEFT_COMPOSER'
    );

    return false;
  }

  async function ensureMessage(job, cfg, leaseToken) {
    const expected = String(job.message || '');

    try {
      let composer = findComposer();

      if (composer && composerHasExpectedText(composer, expected)) {
        if (job.messageState !== 'INSERTED') {
          const response = await event(
            job,
            cfg,
            {
              event:'MESSAGE_STATE',
              state:'INSERTED',
              strategy:'already-present'
            },
            leaseToken
          );
          const saved = response?.job || response;
          job.messageState = saved?.messageState || 'INSERTED';
          job.messageInsertedAt =
            saved?.messageInsertedAt ||
            job.messageInsertedAt ||
            new Date().toISOString();
        }
        return true;
      }

      // STRICT ONE-SHOT RULE.
      // Once INSERTED, this branch may only verify/consume. It is forbidden to
      // write the same Web Console text into the chat composer again.
      if (job.messageState === 'INSERTED') {
        return await verifyInsertedMessageOwnership(
          job,
          cfg,
          leaseToken,
          expected,
          1200
        );
      }

      // The first and only automatic write for this delivery job.
      const strategy = await setTextValue(composer, expected);
      composer = findComposer();

      if (!composer || !composerHasExpectedText(composer, expected)) {
        throw new Error(
          `${chatLabel()} composer verification failed after first insertion`
        );
      }

      const response = await event(
        job,
        cfg,
        {
          event:'MESSAGE_STATE',
          state:'INSERTED',
          strategy
        },
        leaseToken
      );

      const saved = response?.job || response;
      job.messageState = saved?.messageState || 'INSERTED';
      job.messageInsertedAt =
        saved?.messageInsertedAt ||
        job.messageInsertedAt ||
        new Date().toISOString();

      return true;
    } catch (e) {
      if (isJobConsumedError(e)) throw e;

      await event(
        job,
        cfg,
        {
          event:'MESSAGE_STATE',
          state:'ERROR',
          error:String(e?.message || e)
        },
        leaseToken
      ).catch(() => {});

      return false;
    }
  }

  function findSendButton(composer) {
    return currentAdapter()?.findSendButton?.(composer) || null;
  }

  async function handleSend(job, cfg, leaseToken) {
    if (job.sendState !== 'SEND_REQUESTED') return;

    try {
      const composer = findComposer();
      if (!composer) throw new Error(`${chatLabel()} composer not found`);

      const button = findSendButton(composer);
      if (!button) throw new Error(`${chatLabel()} Send button not found or disabled`);

      const before = norm(composerText(composer));
      rememberSubmittedDelivery(job, 'SEND_REQUESTED');
      button.click();

      const deadline = now() + 15000;
      while (now() < deadline) {
        await sleep(300);
        const after = norm(composerText(findComposer() || composer));
        if (!after || after !== before) {
          await event(
            job, cfg,
            {event:'SEND_STATE', state:'SENT'},
            leaseToken
          );
          return;
        }
      }

      throw new Error(`Send click did not clear/change ${chatLabel()} composer within 15 seconds`);
    } catch (e) {
      await event(
        job, cfg,
        {
          event:'SEND_STATE',
          state:'SEND_ERROR',
          error:String(e?.message || e)
        },
        leaseToken
      ).catch(() => {});
    }
  }

  async function processJob(job, cfg, leaseToken) {
    job = await claimJob(job, cfg, leaseToken);

    try {
      await throwIfConversationConsumed(job, cfg, leaseToken);

      // Two separate gates:
      // 1) the chat page/conversation must be fully hydrated;
      // 2) the chat itself must be idle/ready for the next interaction.
      await waitForPageHydration(job, cfg, leaseToken, 1800);
      await waitForChatIdle(job, cfg, leaseToken);
      job = await ensureConversationBaseline(job, cfg, leaseToken);

      await throwIfConversationConsumed(job, cfg, leaseToken);
      if (!await ensureMessage(job, cfg, leaseToken)) return;

      for (const attachment of (job.attachments || [])) {
        await throwIfConversationConsumed(job, cfg, leaseToken);
        const st = String(attachment.state || '');

        if (st === 'UPLOADED') {
          if (!await ensureMessage(job, cfg, leaseToken)) return;
          continue;
        }

        // Idempotency first. This runs for PENDING as well as recovery states.
        // If a matching card is already in the chat, NEVER add another copy.
        let existingState = 'missing';
        try {
          existingState = await recoverAttachmentIfPossible(
            job,
            attachment,
            cfg,
            leaseToken
          );
        } catch (recoverError) {
          if (isJobConsumedError(recoverError)) throw recoverError;
          console.debug(
            '[PAP Chat Bridge] existing attachment inspection:',
            recoverError?.message || recoverError
          );
        }

        if (existingState === 'uploaded' || existingState === 'stalled' || existingState === 'error') {
          if (!await ensureMessage(job, cfg, leaseToken)) return;
          continue;
        }

        if (!['PENDING','RETRY_PENDING','RECOVER_PENDING','FETCHING','CHAT_UPLOADING'].includes(st)) {
          continue;
        }

        let chatAttachAttemptStarted = false;

        try {
          const file = await fetchAttachment(job, attachment, cfg, leaseToken);
          await throwIfConversationConsumed(job, cfg, leaseToken);

          // From here the file may already reach the chat. If anything times out
          // after this point, automatic re-attach is forbidden.
          chatAttachAttemptStarted = true;

          const result = await attachFile(
            job,
            attachment,
            file,
            cfg,
            leaseToken
          );

          if (result === 'stalled' || result === 'error') {
            if (!await ensureMessage(job, cfg, leaseToken)) return;
            continue;
          }
        } catch (e) {
          if (isJobConsumedError(e)) throw e;

          const message = String(e?.message || e);

          // Before scheduling an automatic retry, check the live DOM once more.
          // If the card exists, block duplicate upload and surface STALLED.
          const composer = findComposer();
          const root = composer ? composerRoot(composer) : null;
          const card = root ? fileCard(root, attachment.name) : null;

          if (card || chatAttachAttemptStarted) {
            await event(
              job, cfg,
              {
                event:'ATTACHMENT_STATE',
                attachmentId:attachment.attachmentId,
                state:'STALLED',
                phase:card
                  ? 'EXISTING_CHAT_CARD_AFTER_ERROR'
                  : 'ATTACH_ATTEMPT_MAY_HAVE_REACHED_CHAT',
                error:
                  `${message}. A chat attach attempt was already started; ` +
                  `automatic duplicate upload was blocked.`
              },
              leaseToken
            ).catch(() => {});
          } else {
            const recoverable =
              /TIMEOUT|STALLED|lease|network|RUNTIME_MESSAGE/i.test(message);

            await event(
              job, cfg,
              {
                event:'ATTACHMENT_STATE',
                attachmentId:attachment.attachmentId,
                state:recoverable ? 'RECOVER_PENDING' : 'ERROR',
                phase:recoverable ? 'AUTO_RECOVER_BEFORE_CHAT_ATTACH' : 'BRIDGE_ERROR',
                error:message
              },
              leaseToken
            ).catch(() => {});
          }
        }

        await throwIfConversationConsumed(job, cfg, leaseToken);
        if (!await ensureMessage(job, cfg, leaseToken)) return;
      }

      await throwIfConversationConsumed(job, cfg, leaseToken);
      if (!await ensureMessage(job, cfg, leaseToken)) return;

      if (job.sendState === 'SEND_REQUESTED') {
        await handleSend(job, cfg, leaseToken);
      }
    } catch (e) {
      if (isJobConsumedError(e)) {
        console.info('[PAP Chat Bridge] job consumed by manual submit', {
          runId:job.runId,
          jobId:job.jobId,
          reason:String(e?.message || e)
        });
        return;
      }
      throw e;
    } finally {
      await releaseJob(job, cfg, leaseToken);
    }
  }

  function startJobAttempt(job, cfg) {
    const key = `${job.runId}/${job.jobId}`;
    if (ACTIVE.has(key)) return;

    const leaseToken = randomToken();
    const stallMs = Math.max(30000, Number(job.stallTimeoutSeconds || 120) * 1000);
    const watchdogMs = Math.max(LOCAL_ATTEMPT_FLOOR_MS, stallMs + 30000);

    ACTIVE.set(key, {
      leaseToken,
      startedAt:now(),
      watchdogAt:now() + watchdogMs
    });

    const watchdog = setTimeout(() => {
      const live = ACTIVE.get(key);
      if (!live || live.leaseToken !== leaseToken) return;

      // DIAGNOSTIC ONLY.
      //
      // Do NOT delete ACTIVE here. The old watchdog unlocked the same backend
      // job while processJob() was still executing, so the poll loop could
      // start a second overlapping attempt. That caused duplicate work,
      // conflicting DOM operations and unnecessary CPU load.
      live.watchdogWarnedAt = now();

      console.info('[PAP Chat Bridge] local watchdog: attempt still active; duplicate retry suppressed', {
        key,
        leaseToken,
        watchdogMs,
        startedAt:live.startedAt
      });
    }, watchdogMs);

    processJob(job, cfg, leaseToken)
      .catch((e) => {
        console.warn('[PAP Chat Bridge] job attempt failed', {
          key,
          leaseToken,
          error:String(e?.message || e)
        });
      })
      .finally(() => {
        clearTimeout(watchdog);
        const live = ACTIVE.get(key);
        if (live?.leaseToken === leaseToken) {
          ACTIVE.delete(key);
        }
      });
  }

  async function loop() {
    if (stopped) return;

    try {
      const cfg = await runtimeConfig();
      if (cfg) {
        const responseRecovery = globalThis.PAPClaudeLastResponseRecovery?.snapshot?.();
        if (responseRecovery?.blocked) {
          await maybeQueueFailedResponseReplay(cfg);

          const refreshedRecovery =
            globalThis.PAPClaudeLastResponseRecovery?.snapshot?.() ||
            responseRecovery;

          if (refreshedRecovery.replayQueued) {
            // Retry processing the SAME recovery job if a previous bridge
            // attempt was interrupted. Platform de-duplicates the clone.
            const queued = await http(
              'GET',
              `/api/chat-delivery/poll?tabId=${encodeURIComponent(cfg.tabId)}&page=${encodeURIComponent(location.href)}`
            ).catch(() => null);

            if (
              queued?.job?.recoveryReplay &&
              (
                !refreshedRecovery.replayJobId ||
                queued.job.jobId === refreshedRecovery.replayJobId
              )
            ) {
              startJobAttempt(queued.job, cfg);
            }
          }

          console.debug('[PAP Chat Bridge] failed-response recovery state', {
            reason:refreshedRecovery.reason,
            nextAction:refreshedRecovery.nextAction,
            refreshAttempted:refreshedRecovery.refreshAttempted,
            refreshWillRepeat:refreshedRecovery.refreshWillRepeat,
            refreshCooldownRemainingMs:refreshedRecovery.refreshCooldownRemainingMs,
            replayRequested:refreshedRecovery.replayRequested,
            replayDelayRemainingMs:refreshedRecovery.replayDelayRemainingMs,
            replayQueued:refreshedRecovery.replayQueued,
            replayJobId:refreshedRecovery.replayJobId,
            lastReplayError:refreshedRecovery.lastReplayError,
            rowIndex:refreshedRecovery.rowIndex
          });
          return;
        }

        const gate = pageHydrationGate(1800);

        if (!gate.ready) {
          console.debug('[PAP Chat Bridge] waiting page hydration before poll', {
            reason:gate.gateReason,
            readyState:gate.readyState,
            composerReady:gate.composerReady,
            latestIndex:gate.latestIndex,
            latestPerfRow:gate.latestPerfRow,
            latestStreaming:gate.latestStreaming,
            stableForMs:gate.stableForMs
          });
        } else {
          const r = await http(
            'GET',
            `/api/chat-delivery/poll?tabId=${encodeURIComponent(cfg.tabId)}&page=${encodeURIComponent(location.href)}`
          );
          if (r?.job) startJobAttempt(r.job, cfg);
        }
      }
    } catch (e) {
      console.debug('[PAP Chat Bridge] poll:', e?.message || e);
    } finally {
      if (!stopped) loopTimer = setTimeout(loop, POLL_MS);
    }
  }

  function resetPageGate(reason = 'RESET') {
    PAGE_GATE.href = location.href;
    PAGE_GATE.fingerprint = '';
    PAGE_GATE.stableSince = 0;
    PAGE_GATE.ready = false;
    PAGE_GATE.lastReason = reason;
  }

  window.addEventListener('pageshow', () => resetPageGate('PAGESHOW'), true);
  window.addEventListener('popstate', () => resetPageGate('POPSTATE'), true);
  window.addEventListener('hashchange', () => resetPageGate('HASHCHANGE'), true);

  chrome.runtime.onMessage.addListener((message) => {
    // Web Console delivery is explicit and independent from parser enable state.
    if (message?.type === 'TAB_ENABLED' || message?.type === 'RUN_NOW') {
      stopped = false;
      clearTimeout(loopTimer);
      loopTimer = setTimeout(loop, 100);
    }
  });

  console.info(`[PAP Chat Bridge] v${BRIDGE_VERSION} loaded`);
  console.info('[PAP Chat Bridge] started', {
    version: BRIDGE_VERSION,
    url: location.href,
    policy: 'ONE_SHOT_MESSAGE_INSERTION_AND_SINGLE_ACTIVE_DELIVERY_ATTEMPT'
  });
  loopTimer = setTimeout(loop, 500);
})();
