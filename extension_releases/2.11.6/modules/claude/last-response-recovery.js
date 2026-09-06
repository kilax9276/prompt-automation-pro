(() => {
  'use strict';

  if (globalThis.PAPClaudeLastResponseRecovery) return;

  const VERSION = '1.3.0';
  const GLOBAL_REFRESH_COOLDOWN_MS = 120_000;
  const CONFIRM_MS = 700;
  const SCAN_FALLBACK_MS = 1500;
  const MUTATION_DEBOUNCE_MS = 150;
  const REPLAY_RETRY_MS = 5_000;
  const HEALTHY_CLEAR_MS = 5_000;

  const LAST_REFRESH_KEY = 'pap2:last-response-load-failure-refresh-at';
  const CYCLE_KEY = 'pap2:last-response-load-failure-cycle-v2';

  let replayDelayMs = 15_000;
  let candidateKey = '';
  let candidateSince = 0;
  let healthySince = 0;
  let reloadScheduled = false;
  let replayTakenKey = '';
  let replayFailedAt = 0;
  let scanTimer = null;
  let scanRunning = false;
  let scanAgain = false;

  let lastSnapshot = {
    blocked:false,
    failed:false,
    reason:'BOOT',
    nextAction:'NONE',
    refreshAttempted:false,
    refreshWillRepeat:false,
    refreshCooldownRemainingMs:0,
    replayRequested:false,
    replayDelayRemainingMs:0,
    replayQueued:false,
    replayJobId:'',
    replayRunId:'',
    lastReplayError:'',
    rowIndex:'',
    warningText:''
  };

  const now = () => Date.now();

  function safeJsonParse(raw, fallback = null) {
    try {
      const value = JSON.parse(raw);
      return value ?? fallback;
    } catch {
      return fallback;
    }
  }

  function currentFailureKey(snapshot) {
    return [
      location.href.split('#', 1)[0],
      snapshot?.rowIndex || '',
      snapshot?.warningText || ''
    ].join('|');
  }

  function readLastRefreshAt() {
    try {
      const value = Number(sessionStorage.getItem(LAST_REFRESH_KEY) || 0);
      return Number.isFinite(value) && value > 0 ? value : 0;
    } catch {
      return 0;
    }
  }

  function writeLastRefreshAt(value) {
    try {
      sessionStorage.setItem(LAST_REFRESH_KEY, String(value));
    } catch {}
  }

  function readCycle() {
    try {
      const value = safeJsonParse(sessionStorage.getItem(CYCLE_KEY) || 'null');
      return value && typeof value === 'object' ? value : null;
    } catch {
      return null;
    }
  }

  function writeCycle(value) {
    try {
      if (value) sessionStorage.setItem(CYCLE_KEY, JSON.stringify(value));
      else sessionStorage.removeItem(CYCLE_KEY);
    } catch {}
  }

  function ensureCycle(failure) {
    const failureKey = currentFailureKey(failure);
    let cycle = readCycle();

    if (!cycle || cycle.failureKey !== failureKey) {
      cycle = {
        schemaVersion:2,
        failureKey,
        rowIndex:String(failure.rowIndex || ''),
        warningText:String(failure.warningText || ''),
        firstSeenAt:now(),
        refreshAttempted:false,
        refreshAt:0,
        replayQueued:false,
        replayQueuedAt:0,
        replayRunId:'',
        replayJobId:'',
        lastReplayError:'',
        lastReplayErrorAt:0
      };
      writeCycle(cycle);
      replayTakenKey = '';
      replayFailedAt = 0;
    }

    return cycle;
  }

  function configureReplayDelay() {
    try {
      chrome.storage.sync.get({responseFailureReplayDelayMs:15000}).then((settings) => {
        replayDelayMs = Math.max(
          3000,
          Number(settings?.responseFailureReplayDelayMs || 15000)
        );
        scheduleScan(0);
      }).catch(() => {});
    } catch {}

    try {
      chrome.storage.onChanged.addListener((changes, areaName) => {
        if (areaName !== 'sync' || !changes.responseFailureReplayDelayMs) return;
        replayDelayMs = Math.max(
          3000,
          Number(changes.responseFailureReplayDelayMs.newValue || 15000)
        );
        scheduleScan(0);
      });
    } catch {}
  }

  function inspect() {
    const signals = globalThis.PAPClaudeDomSignals;

    if (!signals?.inspectLastAssistantLoadFailure) {
      return {
        blocked:false,
        failed:false,
        reason:'DOM_SIGNALS_UNAVAILABLE',
        nextAction:'NONE',
        refreshAttempted:false,
        refreshWillRepeat:false,
        refreshCooldownRemainingMs:0,
        replayRequested:false,
        replayDelayRemainingMs:0,
        replayQueued:false,
        replayJobId:'',
        replayRunId:'',
        lastReplayError:'',
        rowIndex:'',
        warningText:''
      };
    }

    const failure = signals.inspectLastAssistantLoadFailure(document);

    if (!failure.failed) {
      return {
        blocked:false,
        failed:false,
        reason:failure.reason,
        nextAction:'NONE',
        refreshAttempted:Boolean(readCycle()?.refreshAttempted),
        refreshWillRepeat:false,
        refreshCooldownRemainingMs:0,
        replayRequested:false,
        replayDelayRemainingMs:0,
        replayQueued:Boolean(readCycle()?.replayQueued),
        replayJobId:String(readCycle()?.replayJobId || ''),
        replayRunId:String(readCycle()?.replayRunId || ''),
        lastReplayError:String(readCycle()?.lastReplayError || ''),
        rowIndex:failure.rowIndex || '',
        warningText:failure.warningText || ''
      };
    }

    const cycle = ensureCycle(failure);
    const lastRefreshAt = readLastRefreshAt();
    const globalElapsed = lastRefreshAt
      ? now() - lastRefreshAt
      : Number.POSITIVE_INFINITY;
    const refreshCooldownRemainingMs = Math.max(
      0,
      GLOBAL_REFRESH_COOLDOWN_MS - globalElapsed
    );

    if (cycle.refreshAttempted) {
      const elapsedAfterRefresh = Math.max(0, now() - Number(cycle.refreshAt || 0));
      const replayDelayRemainingMs = Math.max(
        0,
        replayDelayMs - elapsedAfterRefresh
      );

      const retryReady = !replayFailedAt || now() - replayFailedAt >= REPLAY_RETRY_MS;
      const replayRequested = Boolean(
        !cycle.replayQueued &&
        replayDelayRemainingMs === 0 &&
        retryReady &&
        (!replayTakenKey || replayTakenKey !== cycle.failureKey || replayFailedAt)
      );

      return {
        blocked:true,
        failed:true,
        reason:failure.reason,
        nextAction:cycle.replayQueued
          ? 'REPLAY_QUEUED'
          : replayRequested
            ? 'REPLAY_REQUESTED'
            : 'WAIT_REPLAY_DELAY',
        refreshAttempted:true,
        // CRITICAL: this exact failure cycle is NEVER refreshed a second time.
        refreshWillRepeat:false,
        refreshCooldownRemainingMs,
        replayRequested,
        replayDelayRemainingMs,
        replayQueued:Boolean(cycle.replayQueued),
        replayJobId:String(cycle.replayJobId || ''),
        replayRunId:String(cycle.replayRunId || ''),
        lastReplayError:String(cycle.lastReplayError || ''),
        failureKey:cycle.failureKey,
        rowIndex:failure.rowIndex || '',
        rowRsIndex:failure.rowRsIndex || '',
        rowStreaming:failure.rowStreaming || '',
        warningText:failure.warningText || ''
      };
    }

    return {
      blocked:true,
      failed:true,
      reason:failure.reason,
      nextAction:refreshCooldownRemainingMs > 0
        ? 'WAIT_REFRESH_COOLDOWN'
        : 'REFRESH_PENDING',
      refreshAttempted:false,
      refreshWillRepeat:false,
      refreshCooldownRemainingMs,
      replayRequested:false,
      replayDelayRemainingMs:replayDelayMs,
      replayQueued:false,
      replayJobId:'',
      replayRunId:'',
      lastReplayError:'',
      failureKey:cycle.failureKey,
      rowIndex:failure.rowIndex || '',
      rowRsIndex:failure.rowRsIndex || '',
      rowStreaming:failure.rowStreaming || '',
      warningText:failure.warningText || ''
    };
  }

  function triggerRefresh(snapshot) {
    if (reloadScheduled) return;

    const cycle = readCycle();
    if (!cycle || cycle.failureKey !== snapshot.failureKey) return;
    if (cycle.refreshAttempted) return;

    const timestamp = now();
    cycle.refreshAttempted = true;
    cycle.refreshAt = timestamp;
    cycle.lastReplayError = '';
    cycle.lastReplayErrorAt = 0;
    writeCycle(cycle);
    writeLastRefreshAt(timestamp);

    reloadScheduled = true;

    console.warn(
      `[PAP Claude Recovery] ONE refresh for failed response; ` +
      `this failure will NOT be refreshed again. row=${snapshot.rowIndex}`
    );

    setTimeout(() => location.reload(), 80);
  }

  function scan() {
    const snapshot = inspect();
    lastSnapshot = snapshot;

    if (!snapshot.failed) {
      candidateKey = '';
      candidateSince = 0;

      // Do not clear the cycle immediately after reload: Claude can briefly
      // render no warning while the transcript hydrates. Clear only after the
      // page has been healthy continuously for 5 seconds.
      if (!healthySince) healthySince = now();
      if (now() - healthySince >= HEALTHY_CLEAR_MS) {
        writeCycle(null);
        replayTakenKey = '';
        replayFailedAt = 0;
      }
      return;
    }

    healthySince = 0;

    if (snapshot.refreshAttempted) {
      // Strict state machine:
      // after the first refresh this cycle can only WAIT/REPLAY.
      // It can never come back to REFRESH.
      candidateKey = '';
      candidateSince = 0;
      return;
    }

    if (snapshot.refreshCooldownRemainingMs > 0) {
      candidateKey = '';
      candidateSince = 0;
      return;
    }

    const key = snapshot.failureKey;
    if (!key) return;

    if (candidateKey !== key) {
      candidateKey = key;
      candidateSince = performance.now();
      return;
    }

    if (performance.now() - candidateSince < CONFIRM_MS) return;

    triggerRefresh(snapshot);
  }

  function snapshot() {
    return {
      ...lastSnapshot,
      refreshCooldownMs:GLOBAL_REFRESH_COOLDOWN_MS,
      replayDelayMs,
      replayRetryMs:REPLAY_RETRY_MS,
      confirmMs:CONFIRM_MS,
      version:VERSION
    };
  }

  function takeReplayRequest() {
    const current = inspect();
    lastSnapshot = current;

    if (!current.replayRequested || !current.failureKey) return null;

    replayTakenKey = current.failureKey;
    replayFailedAt = 0;

    return {
      failureKey:current.failureKey,
      rowIndex:current.rowIndex,
      warningText:current.warningText,
      requestedAt:now(),
      replayDelayMs
    };
  }

  function markReplayQueued(info = {}) {
    const current = inspect();
    const failureKey = String(info.failureKey || current.failureKey || '');
    let cycle = readCycle();

    if (!cycle || !failureKey || cycle.failureKey !== failureKey) return;

    cycle.replayQueued = true;
    cycle.replayQueuedAt = now();
    cycle.replayRunId = String(info.runId || '');
    cycle.replayJobId = String(info.jobId || '');
    cycle.lastReplayError = '';
    cycle.lastReplayErrorAt = 0;
    writeCycle(cycle);

    replayTakenKey = failureKey;
    replayFailedAt = 0;
    lastSnapshot = inspect();
  }

  function markReplayFailed(failureKey = '', error = '') {
    let cycle = readCycle();
    if (!cycle) return;
    if (failureKey && cycle.failureKey !== failureKey) return;

    replayFailedAt = now();
    replayTakenKey = cycle.failureKey;
    cycle.lastReplayError = String(error || 'UNKNOWN_REPLAY_ERROR');
    cycle.lastReplayErrorAt = replayFailedAt;
    writeCycle(cycle);
    lastSnapshot = inspect();

    console.warn(
      `[PAP Claude Recovery] draft replay failed; NO MORE REFRESH. ` +
      `retry in ${Math.round(REPLAY_RETRY_MS / 1000)}s: ${cycle.lastReplayError}`
    );
  }

  function safeScan() {
    if (scanRunning) {
      scanAgain = true;
      return;
    }

    scanRunning = true;
    try {
      scan();
    } finally {
      scanRunning = false;
      if (scanAgain) {
        scanAgain = false;
        scheduleScan(0);
      }
    }
  }

  function scheduleScan(delayMs = MUTATION_DEBOUNCE_MS) {
    if (scanTimer) return;

    scanTimer = setTimeout(() => {
      scanTimer = null;
      safeScan();
    }, Math.max(0, Number(delayMs) || 0));
  }

  globalThis.PAPClaudeLastResponseRecovery = Object.freeze({
    version:VERSION,
    cooldownMs:GLOBAL_REFRESH_COOLDOWN_MS,
    snapshot,
    scan,
    takeReplayRequest,
    markReplayQueued,
    markReplayFailed
  });

  const observer = new MutationObserver(() => {
    scheduleScan(MUTATION_DEBOUNCE_MS);
  });

  function startObserver() {
    if (!document.documentElement) {
      setTimeout(startObserver, 50);
      return;
    }

    observer.observe(document.documentElement, {
      subtree:true,
      childList:true,
      characterData:true,
      attributes:true,
      attributeFilter:[
        'data-testid',
        'data-last-message',
        'data-perf-row',
        'data-perf-row-streaming',
        'role',
        'aria-label',
        'disabled'
      ]
    });

    scheduleScan(0);
  }

  configureReplayDelay();
  setInterval(() => scheduleScan(0), SCAN_FALLBACK_MS);
  startObserver();

  console.info('[PAP Claude Recovery] loaded', {
    version:VERSION,
    refreshPolicy:'ONE_REFRESH_PER_FAILURE_CYCLE',
    globalRefreshCooldownMs:GLOBAL_REFRESH_COOLDOWN_MS,
    replayDelayMs,
    mutationDebounceMs:MUTATION_DEBOUNCE_MS,
    fallbackScanMs:SCAN_FALLBACK_MS
  });
})();
