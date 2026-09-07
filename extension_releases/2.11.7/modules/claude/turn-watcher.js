// Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
// All rights reserved. See LICENSE at the repository root.
(() => {
  'use strict';

  if (globalThis.PAPClaudeTurnWatcher) return;

  const VERSION = '1.1.0';
  const SCAN_FALLBACK_MS = 1000;
  const MUTATION_DEBOUNCE_MS = 120;
  const READY_STABLE_MS = 700;
  const STORAGE_KEY = 'pap2:claude-turn-watcher-last-emitted-v1';

  let initialized = false;
  let currentHref = location.href;
  let baselineAssistantKey = '';
  let activeAssistantKey = '';
  let awaitingAssistant = false;
  let readyCandidateKey = '';
  let readyCandidateFingerprint = '';
  let readySince = 0;
  let lastEmittedKey = readLastEmittedKey();
  let lastSnapshot = null;
  let sending = false;
  let scanTimer = null;
  let scanRunning = false;
  let scanAgain = false;

  function nowMono() {
    return performance.now();
  }

  function readLastEmittedKey() {
    try {
      return sessionStorage.getItem(STORAGE_KEY) || '';
    } catch {
      return '';
    }
  }

  function writeLastEmittedKey(value) {
    try {
      sessionStorage.setItem(STORAGE_KEY, String(value || ''));
    } catch {}
  }

  function turnKey(snapshot) {
    return [
      location.href.split('#', 1)[0],
      snapshot?.rowKey || ''
    ].join('|');
  }

  function rowFingerprint(row) {
    if (!row) return '';

    const text = String(row.textContent || '');
    return JSON.stringify([
      row.getAttribute?.('data-index') || '',
      row.getAttribute?.('data-rs-index') || '',
      row.getAttribute?.('data-perf-row-streaming') || '',
      text.length,
      text.slice(-1200)
    ]);
  }

  function resetForUrlChange() {
    initialized = false;
    currentHref = location.href;
    baselineAssistantKey = '';
    activeAssistantKey = '';
    awaitingAssistant = false;
    readyCandidateKey = '';
    readyCandidateFingerprint = '';
    readySince = 0;
    lastEmittedKey = readLastEmittedKey();
  }

  async function emitFinished(snapshot) {
    if (sending) return false;

    const key = turnKey(snapshot);
    if (!key || key === lastEmittedKey) return false;

    sending = true;
    try {
      const response = await chrome.runtime.sendMessage({
        type:'CLAUDE_TURN_FINISHED',
        turnKey:key,
        rowKey:snapshot.rowKey || '',
        rowIndex:snapshot.row?.getAttribute?.('data-index') || '',
        rowRsIndex:snapshot.row?.getAttribute?.('data-rs-index') || '',
        page:location.href
      });

      if (!response?.ok) {
        return false;
      }

      lastEmittedKey = key;
      writeLastEmittedKey(key);

      baselineAssistantKey = snapshot.rowKey || baselineAssistantKey;
      activeAssistantKey = '';
      awaitingAssistant = false;
      readyCandidateKey = '';
      readyCandidateFingerprint = '';
      readySince = 0;

      console.info(
        `[PAP Claude Turn Watcher] assistant turn finished; parser scheduled. ` +
        `row=${snapshot.row?.getAttribute?.('data-index') || '?'}`
      );

      return true;
    } catch (error) {
      console.warn(
        '[PAP Claude Turn Watcher] failed to schedule parser',
        String(error?.message || error)
      );
      return false;
    } finally {
      sending = false;
    }
  }

  function initializeFrom(snapshot) {
    initialized = true;

    if (!snapshot) return;

    if (snapshot.kind === 'HUMAN') {
      // Extension can be injected after the user already pressed Send.
      awaitingAssistant = true;
      return;
    }

    if (snapshot.kind === 'ASSISTANT_BUSY') {
      // Extension can be injected while Claude is already generating.
      activeAssistantKey = snapshot.rowKey || '';
      awaitingAssistant = true;
      return;
    }

    if (snapshot.kind === 'ASSISTANT_FAILED') {
      activeAssistantKey = snapshot.rowKey || '';
      awaitingAssistant = true;
      return;
    }

    if (snapshot.kind === 'ASSISTANT_READY') {
      // Existing historical ready response is only a baseline.
      // content.js handles the initial/enabled-page parse separately.
      baselineAssistantKey = snapshot.rowKey || '';
    }
  }

  async function scan() {
    if (location.href !== currentHref) {
      resetForUrlChange();
    }

    const signals = globalThis.PAPClaudeDomSignals;
    if (!signals?.inspectTurnState) {
      return;
    }

    const snapshot = signals.inspectTurnState(document);
    lastSnapshot = snapshot;

    if (!initialized) {
      initializeFrom(snapshot);
      return;
    }

    if (snapshot.kind === 'HUMAN') {
      awaitingAssistant = true;
      activeAssistantKey = '';
      readyCandidateKey = '';
      readyCandidateFingerprint = '';
      readySince = 0;
      return;
    }

    if (snapshot.kind === 'ASSISTANT_FAILED') {
      // Recovery module owns the failed-response path. Keep the turn active so
      // a successful Try again / remount can still finish the same turn later.
      awaitingAssistant = true;
      activeAssistantKey = snapshot.rowKey || activeAssistantKey;
      readyCandidateKey = '';
      readyCandidateFingerprint = '';
      readySince = 0;
      return;
    }

    if (snapshot.kind === 'ASSISTANT_BUSY') {
      const key = snapshot.rowKey || '';

      if (
        awaitingAssistant ||
        key !== baselineAssistantKey
      ) {
        activeAssistantKey = key;
        awaitingAssistant = true;
      }

      readyCandidateKey = '';
      readyCandidateFingerprint = '';
      readySince = 0;
      return;
    }

    if (snapshot.kind !== 'ASSISTANT_READY') {
      return;
    }

    const key = snapshot.rowKey || '';
    const fullKey = turnKey(snapshot);

    const isNewTurn = Boolean(
      awaitingAssistant ||
      activeAssistantKey === key ||
      (
        key &&
        baselineAssistantKey &&
        key !== baselineAssistantKey
      )
    );

    if (!isNewTurn || fullKey === lastEmittedKey) {
      baselineAssistantKey = key || baselineAssistantKey;
      return;
    }

    const fingerprint = rowFingerprint(snapshot.row);

    if (
      readyCandidateKey !== key ||
      readyCandidateFingerprint !== fingerprint
    ) {
      readyCandidateKey = key;
      readyCandidateFingerprint = fingerprint;
      readySince = nowMono();
      return;
    }

    if (!readySince) {
      readySince = nowMono();
      return;
    }

    if (nowMono() - readySince < READY_STABLE_MS) {
      return;
    }

    await emitFinished(snapshot);
  }

  async function safeScan() {
    if (scanRunning) {
      scanAgain = true;
      return;
    }

    scanRunning = true;
    try {
      await scan();
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
      safeScan().catch(() => {});
    }, Math.max(0, Number(delayMs) || 0));
  }

  globalThis.PAPClaudeTurnWatcher = Object.freeze({
    version:VERSION,
    scan,
    snapshot:() => ({
      version:VERSION,
      initialized,
      currentHref,
      baselineAssistantKey,
      activeAssistantKey,
      awaitingAssistant,
      readyCandidateKey,
      readySince,
      lastEmittedKey,
      lastSnapshotKind:lastSnapshot?.kind || '',
      lastSnapshotRowKey:lastSnapshot?.rowKey || ''
    })
  });

  const observer = new MutationObserver(() => {
    scheduleScan(MUTATION_DEBOUNCE_MS);
  });

  function start() {
    if (!document.documentElement) {
      setTimeout(start, 50);
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
        'data-is-streaming',
        'role',
        'aria-label',
        'disabled'
      ]
    });

    setInterval(() => {
      scheduleScan(0);
    }, SCAN_FALLBACK_MS);

    scheduleScan(0);

    console.info('[PAP Claude Turn Watcher] loaded', {
      version:VERSION,
      readyStableMs:READY_STABLE_MS,
      mutationDebounceMs:MUTATION_DEBOUNCE_MS,
      fallbackScanMs:SCAN_FALLBACK_MS,
      mode:'SPA_DOM_TURN_LIFECYCLE_THROTTLED'
    });
  }

  start();
})();
