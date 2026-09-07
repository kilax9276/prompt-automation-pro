// Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
// All rights reserved. See LICENSE at the repository root.
const DEFAULT_SETTINGS = {
  serverBaseUrl: "http://192.168.10.78:8867",
  serverToken: "",
  delayMs: 15000,
  maxAssistantMessages: 4,
  downloadScope: "required",
  downloadGapMs: 1500,
  downloadStartTimeoutMs: 15000,
  downloadStallTimeoutMs: 120000,
  captureTimeoutMs: 60000,
  uploadStallTimeoutMs: 120000,
  uploadTimeoutMs: 60000,
  responseFailureReplayDelayMs: 15000,
  stopOnError: false
};

const $ = (id) => document.getElementById(id);
let currentTab = null;

const formatBytes = (value) => {
  const bytes = Number(value);
  if (!Number.isFinite(bytes) || bytes < 0) return "?";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let size = bytes / 1024;
  let unit = units[0];
  for (let i = 1; i < units.length && size >= 1024; i++) {
    size /= 1024;
    unit = units[i];
  }
  return `${size >= 100 ? size.toFixed(0) : size >= 10 ? size.toFixed(1) : size.toFixed(2)} ${unit}`;
};

const formatProgress = (done, total) => {
  const totalNumber = Number(total);
  if (Number.isFinite(totalNumber) && totalNumber > 0) {
    const pct = Math.min(100, Math.max(0, Number(done || 0) / totalNumber * 100));
    return `${formatBytes(done)} / ${formatBytes(totalNumber)} (${pct.toFixed(1)}%)`;
  }
  return `${formatBytes(done)} получено`;
};

const send = (message) => new Promise((resolve, reject) => {
  chrome.runtime.sendMessage(message, (response) => {
    if (chrome.runtime.lastError) {
      reject(new Error(chrome.runtime.lastError.message));
      return;
    }
    resolve(response);
  });
});

async function getCurrentTab() {
  const tabs = await chrome.tabs.query({ active: true, currentWindow: true });
  return tabs[0] || null;
}

async function loadSettings() {
  const settings = await chrome.storage.sync.get(null);
  $("serverBaseUrl").value = settings.serverBaseUrl || DEFAULT_SETTINGS.serverBaseUrl;
  $("serverToken").value = settings.serverToken || "";
  $("delayMs").value = settings.delayMs ?? DEFAULT_SETTINGS.delayMs;
  $("maxAssistantMessages").value = settings.maxAssistantMessages ?? DEFAULT_SETTINGS.maxAssistantMessages;
  $("downloadScope").value = "required";
  $("downloadGapMs").value = settings.downloadGapMs ?? DEFAULT_SETTINGS.downloadGapMs;
  $("downloadStartTimeoutMs").value = settings.downloadStartTimeoutMs ?? DEFAULT_SETTINGS.downloadStartTimeoutMs;
  $("downloadStallTimeoutMs").value = settings.downloadStallTimeoutMs ?? settings.downloadCompleteTimeoutMs ?? DEFAULT_SETTINGS.downloadStallTimeoutMs;
  $("captureTimeoutMs").value = settings.captureTimeoutMs ?? DEFAULT_SETTINGS.captureTimeoutMs;
  $("uploadStallTimeoutMs").value = settings.uploadStallTimeoutMs ?? settings.uploadTimeoutMs ?? DEFAULT_SETTINGS.uploadStallTimeoutMs;
  $("uploadTimeoutMs").value = settings.uploadTimeoutMs ?? DEFAULT_SETTINGS.uploadTimeoutMs;
  $("responseFailureReplayDelaySec").value = Math.max(3, Math.round((settings.responseFailureReplayDelayMs ?? DEFAULT_SETTINGS.responseFailureReplayDelayMs) / 1000));
}

async function saveSettings() {
  const settings = {
    serverBaseUrl: $("serverBaseUrl").value.trim().replace(/\/+$/, ""),
    serverToken: $("serverToken").value,
    delayMs: Math.max(0, Number($("delayMs").value) || 0),
    maxAssistantMessages: Math.max(1, Number($("maxAssistantMessages").value) || 4),
    downloadScope: "required",
    downloadGapMs: Math.max(0, Number($("downloadGapMs").value) || 0),
    downloadStartTimeoutMs: Math.max(1000, Number($("downloadStartTimeoutMs").value) || 15000),
    downloadStallTimeoutMs: Math.max(1000, Number($("downloadStallTimeoutMs").value) || 120000),
    captureTimeoutMs: Math.max(1000, Number($("captureTimeoutMs").value) || 60000),
    uploadStallTimeoutMs: Math.max(1000, Number($("uploadStallTimeoutMs").value) || 120000),
    uploadTimeoutMs: Math.max(1000, Number($("uploadTimeoutMs").value) || 60000),
    responseFailureReplayDelayMs: Math.max(3000, (Number($("responseFailureReplayDelaySec").value) || 15) * 1000),
    stopOnError: false
  };

  await chrome.storage.sync.set(settings);
  $("popupMessage").textContent = "Настройки сохранены.";
}

function renderState(state) {
  $("tabUrl").textContent = state.url || "—";
  $("chatType").textContent = state.chatLabel ? `${state.chatLabel} (${state.chatType || "unknown"})` : (state.chatType || "—");
  $("supported").textContent = state.supported ? "YES" : "NO";
  $("tabEnabled").textContent = state.enabled ? "ON" : "OFF";
  $("runState").textContent = state.status?.state || (state.enabled ? "ARMED" : "OFF");

  const details = [];
  if (state.status?.stage) details.push(`Этап: ${state.status.stage}`);
  if (state.status?.runId) details.push(`Run: ${state.status.runId}`);
  if (state.status?.currentFile) details.push(`Файл: ${state.status.currentFile}`);
  if (state.status?.expectedFiles != null) details.push(`Файлы: ${state.status.completedFiles || 0}/${state.status.expectedFiles}`);
  if (state.status?.fileBytesReceived != null) {
    details.push(`Download: ${formatProgress(state.status.fileBytesReceived, state.status.fileTotalBytes)}`);
  }
  if (state.status?.uploadBytesConfirmed != null) {
    details.push(`На сервер: ${formatProgress(state.status.uploadBytesConfirmed, state.status.uploadTotalBytes)}`);
  }
  if (state.status?.error) details.push(`Ошибка: ${state.status.error}`);
  $("runDetails").textContent = details.join("\n");

  $("enableTab").disabled = !state.supported || state.enabled;
  $("disableTab").disabled = !state.enabled;
  $("runNow").disabled = !state.enabled || !state.supported || state.status?.state === "RUNNING";
}

async function refreshState() {
  currentTab = await getCurrentTab();
  if (!currentTab?.id) {
    $("popupMessage").textContent = "Не удалось определить текущую вкладку.";
    return;
  }

  const state = await send({ type: "GET_TAB_STATE", tabId: currentTab.id });
  renderState(state);
}

$("save").addEventListener("click", () => {
  saveSettings().catch((error) => {
    $("popupMessage").textContent = `Ошибка сохранения: ${error.message}`;
  });
});

$("enableTab").addEventListener("click", async () => {
  try {
    if (!currentTab?.id) await refreshState();
    const response = await send({ type: "ENABLE_TAB", tabId: currentTab.id });
    if (!response?.ok) throw new Error(response?.error || "ENABLE_FAILED");
    $("popupMessage").textContent = "Вкладка включена. Запуск произойдёт после настроенной задержки.";
    await refreshState();
  } catch (error) {
    $("popupMessage").textContent = `Ошибка: ${error.message}`;
  }
});

$("disableTab").addEventListener("click", async () => {
  try {
    if (!currentTab?.id) await refreshState();
    const response = await send({ type: "DISABLE_TAB", tabId: currentTab.id });
    if (!response?.ok) throw new Error(response?.error || "DISABLE_FAILED");
    $("popupMessage").textContent = "Вкладка отключена. Текущий процесс остановлен.";
    await refreshState();
  } catch (error) {
    $("popupMessage").textContent = `Ошибка: ${error.message}`;
  }
});

$("runNow").addEventListener("click", async () => {
  try {
    if (!currentTab?.id) await refreshState();
    const response = await send({ type: "RUN_TAB_NOW", tabId: currentTab.id });
    if (!response?.ok) throw new Error(response?.error || "RUN_FAILED");
    $("popupMessage").textContent = "Ручной запуск отправлен на вкладку.";
    setTimeout(() => refreshState().catch(() => {}), 400);
  } catch (error) {
    $("popupMessage").textContent = `Ошибка: ${error.message}`;
  }
});

Promise.all([loadSettings(), refreshState()]).catch((error) => {
  $("popupMessage").textContent = `Ошибка инициализации: ${error.message}`;
});

setInterval(() => refreshState().catch(() => {}), 1000);
