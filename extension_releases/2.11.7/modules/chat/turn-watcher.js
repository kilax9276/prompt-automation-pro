// Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
// All rights reserved. See LICENSE at the repository root.
(() => {
  'use strict';

  if (globalThis.PAPChatTurnWatcher) return;
  globalThis.PAPChatTurnWatcher = true;

  const VERSION = '1.1.0';
  const runtimeGuard = globalThis.PAPRuntimeGuard || null;
  const SCAN_FALLBACK_MS = 1000;
  const MUTATION_DEBOUNCE_MS = 120;
  const READY_STABLE_MS = 700;

  const chat = () => globalThis.PAPChatAdapters?.current?.(location.href) || null;
  const chatInfo = () => globalThis.PAPChatAdapters?.describe?.(location.href) || {type:'unknown', label:'Unknown'};
  const storageKey = () => `pap2:${chatInfo().type}:turn-watcher-last-emitted-v1`;

  let initialized = false;
  let currentHref = location.href;
  let currentChatType = chatInfo().type;
  let baselineAssistantKey = '';
  let activeAssistantKey = '';
  let awaitingAssistant = false;
  let readyCandidateKey = '';
  let readyCandidateFingerprint = '';
  let readySince = 0;
  let lastEmittedKey = readLastEmittedKey();
  let sending = false;
  let scanTimer = null;
  let scanRunning = false;
  let scanAgain = false;
  let disposed = false;
  let observer = null;
  let fallbackInterval = null;



  function stopWatcher(reason = 'STOPPED') {
    if (disposed) return;
    disposed = true;
    if (scanTimer) {
      clearTimeout(scanTimer);
      scanTimer = null;
    }
    if (fallbackInterval) {
      clearInterval(fallbackInterval);
      fallbackInterval = null;
    }
    try { observer?.disconnect?.(); } catch {}
    observer = null;
    if (reason !== 'EXTENSION_CONTEXT_INVALIDATED') {
      console.info(`[PAP Chat Turn Watcher] stopped: ${reason}`);
    }
  }

  function runtimeIsUsable() {
    if (!runtimeGuard) return true;
    const ok = runtimeGuard.runtimeAvailable();
    if (!ok) stopWatcher('EXTENSION_CONTEXT_INVALIDATED');
    return ok;
  }

  function nowMono() { return performance.now(); }
  function readLastEmittedKey() { try { return sessionStorage.getItem(storageKey()) || ''; } catch { return ''; } }
  function writeLastEmittedKey(value) { try { sessionStorage.setItem(storageKey(), String(value || '')); } catch {} }

  function turnKey(snapshot) {
    return [chatInfo().type, location.href.split('#', 1)[0], snapshot?.rowKey || ''].join('|');
  }

  function rowFingerprint(row) {
    if (!row) return '';
    const text = String(row.textContent || '');
    return JSON.stringify([
      chat()?.rowKey?.(row) || '',
      text.length,
      text.slice(-1200)
    ]);
  }

  function resetForContextChange() {
    initialized = false;
    currentHref = location.href;
    currentChatType = chatInfo().type;
    baselineAssistantKey = '';
    activeAssistantKey = '';
    awaitingAssistant = false;
    readyCandidateKey = '';
    readyCandidateFingerprint = '';
    readySince = 0;
    lastEmittedKey = readLastEmittedKey();
  }

  async function emitFinished(snapshot) {
    if (disposed || !runtimeIsUsable()) return false;
    if (sending) return false;
    const key = turnKey(snapshot);
    if (!key || key === lastEmittedKey) return false;
    const info = chatInfo();

    sending = true;
    try {
      const meta = chat()?.rowMeta?.(snapshot.row) || {};
      const response = await chrome.runtime.sendMessage({
        type:'CHAT_TURN_FINISHED',
        chatType:info.type,
        chatLabel:info.label,
        turnKey:key,
        rowKey:snapshot.rowKey || '',
        rowIndex:meta.dataIndex || '',
        page:location.href
      });
      if (!response?.ok) return false;

      lastEmittedKey = key;
      writeLastEmittedKey(key);
      baselineAssistantKey = snapshot.rowKey || baselineAssistantKey;
      activeAssistantKey = '';
      awaitingAssistant = false;
      readyCandidateKey = '';
      readyCandidateFingerprint = '';
      readySince = 0;

      console.info(`[PAP Chat Turn Watcher] ${info.label} assistant turn finished; parser scheduled. row=${meta.dataIndex || '?'}`);
      return true;
    } catch (error) {
      if (runtimeGuard?.observeError?.(error)) {
        stopWatcher('EXTENSION_CONTEXT_INVALIDATED');
        return false;
      }
      console.warn('[PAP Chat Turn Watcher] failed to schedule parser', String(error?.message || error));
      return false;
    } finally {
      sending = false;
    }
  }

  function initializeFrom(snapshot) {
    initialized = true;
    if (!snapshot) return;
    if (snapshot.kind === 'HUMAN') { awaitingAssistant = true; return; }
    if (snapshot.kind === 'ASSISTANT_BUSY' || snapshot.kind === 'ASSISTANT_FAILED') {
      activeAssistantKey = snapshot.rowKey || '';
      awaitingAssistant = true;
      return;
    }
    if (snapshot.kind === 'ASSISTANT_READY') baselineAssistantKey = snapshot.rowKey || '';
  }

  async function scan() {
    if (disposed || !runtimeIsUsable()) return;
    const info = chatInfo();
    if (location.href !== currentHref || info.type !== currentChatType) resetForContextChange();
    const adapter = chat();
    if (!adapter?.inspectTurnState) return;

    const snapshot = adapter.inspectTurnState(document);
    if (!initialized) { initializeFrom(snapshot); return; }

    if (snapshot.kind === 'HUMAN') {
      awaitingAssistant = true;
      activeAssistantKey = '';
      readyCandidateKey = '';
      readyCandidateFingerprint = '';
      readySince = 0;
      return;
    }

    if (snapshot.kind === 'ASSISTANT_FAILED' || snapshot.kind === 'ASSISTANT_BUSY') {
      awaitingAssistant = true;
      activeAssistantKey = snapshot.rowKey || activeAssistantKey;
      readyCandidateKey = '';
      readyCandidateFingerprint = '';
      readySince = 0;
      return;
    }

    if (snapshot.kind !== 'ASSISTANT_READY') return;

    const key = snapshot.rowKey || '';
    const fullKey = turnKey(snapshot);
    const isNewTurn = Boolean(awaitingAssistant || activeAssistantKey === key || (key && baselineAssistantKey && key !== baselineAssistantKey));
    if (!isNewTurn || fullKey === lastEmittedKey) {
      baselineAssistantKey = key || baselineAssistantKey;
      return;
    }

    const fingerprint = rowFingerprint(snapshot.row);
    if (readyCandidateKey !== key || readyCandidateFingerprint !== fingerprint) {
      readyCandidateKey = key;
      readyCandidateFingerprint = fingerprint;
      readySince = nowMono();
      return;
    }
    if (!readySince) { readySince = nowMono(); return; }
    if (nowMono() - readySince < READY_STABLE_MS) return;
    await emitFinished(snapshot);
  }

  async function safeScan() {
    if (disposed || !runtimeIsUsable()) return;
    if (scanRunning) { scanAgain = true; return; }
    scanRunning = true;
    try { await scan(); }
    finally {
      scanRunning = false;
      if (scanAgain) { scanAgain = false; scheduleScan(0); }
    }
  }

  function scheduleScan(delayMs = MUTATION_DEBOUNCE_MS) {
    if (disposed || !runtimeIsUsable()) return;
    if (scanTimer) return;
    scanTimer = setTimeout(() => { scanTimer = null; safeScan().catch(() => {}); }, Math.max(0, delayMs));
  }

  observer = new MutationObserver(() => scheduleScan());
  observer.observe(document.documentElement, {subtree:true, childList:true, attributes:true, characterData:true});
  fallbackInterval = setInterval(() => scheduleScan(0), SCAN_FALLBACK_MS);
  scheduleScan(0);

  globalThis.PAPChatTurnWatcher = Object.freeze({version:VERSION, scan:() => safeScan(), stop:() => stopWatcher('MANUAL_STOP')});
})();
