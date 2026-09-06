importScripts("modules/chat/sites.js");

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

const chatInfoForUrl = (url) => globalThis.PAPChatSites?.identify?.(url) || {
  type:"unknown", label:"Unknown", supported:false, conversationId:""
};
const isSupportedUrl = (url) => Boolean(chatInfoForUrl(url).supported);

const SESSION_TABS_KEY = "enabledTabs";
const SESSION_STATUS_KEY = "tabStatuses";

const downloadWatches = new Map();
const requestControllers = new Map();
const incomingTransfers = new Map();

const normalizeBaseUrl = (value) => {
  let url = String(value || "").trim().replace(/\/+$/, "");
  url = url.replace(/\/api\/(?:claude|chat)-result$/i, "");
  return url;
};

async function getSettings() {
  const stored = await chrome.storage.sync.get(null);
  return {
    ...DEFAULT_SETTINGS,
    ...stored,
    serverBaseUrl: normalizeBaseUrl(stored.serverBaseUrl || DEFAULT_SETTINGS.serverBaseUrl),
    downloadStallTimeoutMs: Math.max(
      1000,
      Number(stored.downloadStallTimeoutMs ?? stored.downloadCompleteTimeoutMs ?? DEFAULT_SETTINGS.downloadStallTimeoutMs) || DEFAULT_SETTINGS.downloadStallTimeoutMs
    ),
    uploadStallTimeoutMs: Math.max(
      1000,
      Number(stored.uploadStallTimeoutMs ?? stored.uploadTimeoutMs ?? DEFAULT_SETTINGS.uploadStallTimeoutMs) || DEFAULT_SETTINGS.uploadStallTimeoutMs
    )
  };
}

async function getEnabledTabs() {
  const data = await chrome.storage.session.get({ [SESSION_TABS_KEY]: {} });
  return data[SESSION_TABS_KEY] || {};
}

async function setTabEnabled(tabId, enabled) {
  const tabs = await getEnabledTabs();

  if (enabled) {
    tabs[String(tabId)] = {
      enabled: true,
      enabledAt: new Date().toISOString()
    };
  } else {
    delete tabs[String(tabId)];
  }

  await chrome.storage.session.set({ [SESSION_TABS_KEY]: tabs });
}

async function isTabEnabled(tabId) {
  const tabs = await getEnabledTabs();
  return Boolean(tabs[String(tabId)]?.enabled);
}

async function getStatuses() {
  const data = await chrome.storage.session.get({ [SESSION_STATUS_KEY]: {} });
  return data[SESSION_STATUS_KEY] || {};
}

async function setTabStatus(tabId, patch) {
  const statuses = await getStatuses();
  const key = String(tabId);
  const previous = statuses[key] || {};

  statuses[key] = {
    ...previous,
    ...patch,
    tabId,
    updatedAt: new Date().toISOString()
  };

  await chrome.storage.session.set({ [SESSION_STATUS_KEY]: statuses });
  return statuses[key];
}

async function clearTabStatus(tabId) {
  const statuses = await getStatuses();
  delete statuses[String(tabId)];
  await chrome.storage.session.set({ [SESSION_STATUS_KEY]: statuses });
}

async function getTabState(tabId) {
  let tab = null;
  try {
    tab = await chrome.tabs.get(tabId);
  } catch (_) {
    // Tab may have disappeared.
  }

  const enabled = await isTabEnabled(tabId);
  const statuses = await getStatuses();
  const chat = chatInfoForUrl(tab?.url);
  const supported = Boolean(chat.supported);
  const status = statuses[String(tabId)] || null;

  return {
    tabId,
    enabled,
    supported,
    chatType:chat.type,
    chatLabel:chat.label,
    conversationId:chat.conversationId || null,
    url: tab?.url || null,
    title: tab?.title || null,
    status: status || {
      state: enabled ? (supported ? "ARMED" : "IDLE") : "OFF"
    }
  };
}

const COMMON_RUNTIME_PREFIX_FILES = Object.freeze([
  "modules/chat/sites.js",
  "modules/chat/adapter-core.js",
  "modules/chat/runtime-guard.js"
]);

const CHAT_RUNTIME_FILES = Object.freeze({
  claude:Object.freeze([
    ...COMMON_RUNTIME_PREFIX_FILES,
    "modules/claude/dom-signals.js",
    "modules/claude/attachment-signals.js",
    "modules/claude/adapter.js",
    "content.js",
    "modules/chat/turn-watcher.js",
    "modules/claude/last-response-recovery.js",
    "chat-bridge.js"
  ]),
  chatgpt:Object.freeze([
    ...COMMON_RUNTIME_PREFIX_FILES,
    "modules/chatgpt/adapter.js",
    "content.js",
    "modules/chat/turn-watcher.js",
    "chat-bridge.js"
  ])
});

async function injectChatIsolatedRuntime(tabId, chatType) {
  const files = CHAT_RUNTIME_FILES[String(chatType || '')];
  if (!files) throw new Error(`CHAT_ADAPTER_NOT_REGISTERED:${chatType || 'unknown'}`);
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "ISOLATED",
    files: [...files]
  });
}

async function injectPageHook(tabId) {
  await chrome.scripting.executeScript({
    target: { tabId },
    world: "MAIN",
    files: ["page-hook.js"]
  });
}

async function ensureChatRuntimeInjected(tabId, url = null) {
  const tab = url ? null : await chrome.tabs.get(tabId);
  const chat = chatInfoForUrl(url || tab?.url || '');
  if (!chat.supported) throw new Error('UNSUPPORTED_URL');

  await injectChatIsolatedRuntime(tabId, chat.type);
  await injectPageHook(tabId);

  const probe = await chrome.scripting.executeScript({
    target: { tabId },
    world: "ISOLATED",
    func: () => {
      const info = globalThis.PAPChatAdapters?.describe?.(location.href) || null;
      return {
        content:Boolean(globalThis.__PAP_PROTOCOL_CONTENT_ACTIVE__),
        chatType:info?.type || 'unknown',
        chatLabel:info?.label || 'Unknown',
        adapterVersion:info?.adapterVersion || '',
        domReady:Boolean(info?.domReady),
        turnWatcher:Boolean(globalThis.PAPChatTurnWatcher),
        chatBridge:Boolean(globalThis.__PAP_CHAT_BRIDGE_ACTIVE__),
        responseRecovery:Boolean(globalThis.PAPClaudeLastResponseRecovery),
        recoverySnapshot:globalThis.PAPClaudeLastResponseRecovery?.snapshot?.() || null
      };
    }
  });

  return probe?.[0]?.result || null;
}
function cancelRequestsForTab(tabId, reason = "TAB_DISABLED_BY_USER") {
  const entry = requestControllers.get(tabId);
  if (entry) {
    for (const controller of entry) {
      try {
        controller.abort(reason);
      } catch (_) {}
    }
    requestControllers.delete(tabId);
  }

  for (const [watchId, watch] of downloadWatches.entries()) {
    if (watch.tabId === tabId) {
      finishDownloadWatch(watchId, {
        ok: false,
        error: reason,
        stage: watch.downloadId ? "DOWNLOAD_COMPLETE" : "DOWNLOAD_START"
      });
    }
  }

  for (const [transferId, transfer] of incomingTransfers.entries()) {
    if (transfer.tabId === tabId) {
      incomingTransfers.delete(transferId);
      abortChunkedUpload(tabId, transfer.uploadId, reason).catch(() => {});
    }
  }
}

function registerController(tabId, controller) {
  if (!requestControllers.has(tabId)) {
    requestControllers.set(tabId, new Set());
  }
  requestControllers.get(tabId).add(controller);
}

function unregisterController(tabId, controller) {
  const set = requestControllers.get(tabId);
  if (!set) return;
  set.delete(controller);
  if (!set.size) requestControllers.delete(tabId);
}

async function fetchWithTimeout(tabId, url, options, timeoutMs) {
  const controller = new AbortController();
  registerController(tabId, controller);
  const timer = setTimeout(() => controller.abort("TIMEOUT"), Math.max(1, Number(timeoutMs) || 60000));

  try {
    return await fetch(url, {
      ...options,
      signal: controller.signal,
      cache: "no-store"
    });
  } finally {
    clearTimeout(timer);
    unregisterController(tabId, controller);
  }
}


const REQUIRED_SERVER_SERVICE = "prompt-automation-pro2-receiver";
const SUPPORTED_SERVER_VERSIONS = new Set(["2.10.0"]);

async function assertServerCompatibility(tabId) {
  const settings = await getSettings();
  const base = normalizeBaseUrl(settings.serverBaseUrl);

  if (!base) {
    throw new Error("SERVER_BASE_URL_EMPTY");
  }

  let response;
  try {
    response = await fetchWithTimeout(
      tabId,
      `${base}/health`,
      { method: "GET" },
      settings.uploadTimeoutMs
    );
  } catch (error) {
    throw new Error(`SERVER_HEALTH_FAILED url=${base} detail=${error?.message || error}`);
  }

  let body = null;
  try {
    body = await response.json();
  } catch (_) {
    throw new Error(`SERVER_HEALTH_INVALID_JSON url=${base} status=${response.status}`);
  }

  if (!response.ok || body?.ok !== true) {
    throw new Error(`SERVER_HEALTH_BAD_RESPONSE url=${base} status=${response.status}`);
  }

  const actualService = String(body?.service || "");
  const actualVersion = String(body?.version || "");

  if (actualService !== REQUIRED_SERVER_SERVICE || !SUPPORTED_SERVER_VERSIONS.has(actualVersion)) {
    throw new Error(
      `SERVER_INCOMPATIBLE url=${base} expected=${REQUIRED_SERVER_SERVICE}/${[...SUPPORTED_SERVER_VERSIONS].join("|")} actual=${actualService || "unknown"}/${actualVersion || "unknown"}`
    );
  }

  return { base, body };
}
function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function postJson(tabId, path, payload, timeoutMs) {
  const settings = await getSettings();
  const base = normalizeBaseUrl(settings.serverBaseUrl);

  if (!base) {
    throw new Error("SERVER_BASE_URL_EMPTY");
  }

  const response = await fetchWithTimeout(
    tabId,
    `${base}${path}`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(settings.serverToken)
      },
      body: JSON.stringify(payload)
    },
    timeoutMs ?? settings.uploadTimeoutMs
  );

  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch (_) {
    body = { raw: text.slice(0, 4000) };
  }

  if (!response.ok || body?.ok === false) {
    const error = new Error(body?.error || `HTTP_${response.status}`);
    error.httpStatus = response.status;
    error.serverBody = body;
    throw error;
  }

  return {
    ok: true,
    status: response.status,
    body
  };
}

async function postBinaryFile(tabId, { runId, fileName, mimeType, bytes, sha256 }) {
  const view = bytes instanceof ArrayBuffer
    ? new Uint8Array(bytes)
    : (ArrayBuffer.isView(bytes) ? new Uint8Array(bytes.buffer, bytes.byteOffset, bytes.byteLength) : null);

  if (!view || view.byteLength <= 0) {
    throw new Error("FILE_UPLOAD_EMPTY_BUFFER");
  }

  let uploadId = null;
  let offset = 0;
  try {
    const started = await beginChunkedUpload(tabId, {
      runId,
      fileName,
      mimeType: mimeType || "application/octet-stream",
      totalBytes: view.byteLength
    });
    uploadId = started.uploadId;

    const CHUNK_BYTES = 4 * 1024 * 1024;
    while (offset < view.byteLength) {
      const chunk = view.subarray(offset, Math.min(offset + CHUNK_BYTES, view.byteLength));
      const response = await postUploadChunk(tabId, {
        uploadId,
        offset,
        bytes: chunk
      });
      offset = Number(response?.receivedBytes ?? (offset + chunk.byteLength));
      sendTransferProgressToTab(tabId, {
        phase: "SERVER_UPLOAD",
        fileName,
        transferredBytes: offset,
        totalBytes: view.byteLength,
        uploadId
      });
    }

    const body = await finishChunkedUpload(tabId, uploadId);
    uploadId = null;

    if (sha256 && body?.sha256 && sha256.toLowerCase() !== String(body.sha256).toLowerCase()) {
      throw new Error(`SHA256_MISMATCH client=${sha256} server=${body.sha256}`);
    }

    sendTransferProgressToTab(tabId, {
      phase: "SERVER_COMPLETE",
      fileName,
      transferredBytes: view.byteLength,
      totalBytes: view.byteLength,
      sha256: body?.sha256 || null
    });

    return body;
  } catch (error) {
    await abortChunkedUpload(tabId, uploadId, error?.message || error);
    throw error;
  }
}

function sendTransferProgressToTab(tabId, payload) {
  chrome.tabs.sendMessage(tabId, {
    type: "FILE_TRANSFER_PROGRESS",
    ...payload
  }).catch(() => {});
}

function withStallTimeout(promise, timeoutMs, onTimeout, code) {
  let timer = null;
  return new Promise((resolve, reject) => {
    timer = setTimeout(() => {
      try { onTimeout?.(); } catch (_) {}
      reject(new Error(code));
    }, Math.max(1000, Number(timeoutMs) || 120000));

    Promise.resolve(promise).then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      }
    );
  });
}

function knownPositiveByteLength(value) {
  if (value == null || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

async function beginChunkedUpload(tabId, { runId, fileName, mimeType, totalBytes }) {
  const settings = await getSettings();
  const result = await postJson(
    tabId,
    "/api/chat-file/start",
    {
      runId,
      fileName,
      mimeType: mimeType || "application/octet-stream",
      totalBytes: knownPositiveByteLength(totalBytes)
    },
    settings.uploadTimeoutMs
  );

  if (!result.body?.uploadId) {
    throw new Error("FILE_UPLOAD_START_NO_ID");
  }

  return result.body;
}

async function postUploadChunk(tabId, { uploadId, offset, bytes }) {
  const settings = await getSettings();
  const base = normalizeBaseUrl(settings.serverBaseUrl);
  const response = await fetchWithTimeout(
    tabId,
    `${base}/api/chat-file/chunk`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/octet-stream",
        "X-Upload-Id": uploadId,
        "X-Chunk-Offset": String(offset),
        ...authHeaders(settings.serverToken)
      },
      body: bytes
    },
    settings.uploadStallTimeoutMs
  );

  const text = await response.text();
  let body = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch (_) {
    body = { raw: text.slice(0, 4000) };
  }

  if (!response.ok || body?.ok === false) {
    const error = new Error(body?.error || `HTTP_${response.status}`);
    error.httpStatus = response.status;
    error.serverBody = body;
    throw error;
  }
  return body;
}

async function finishChunkedUpload(tabId, uploadId) {
  const settings = await getSettings();
  const result = await postJson(
    tabId,
    "/api/chat-file/finish",
    { uploadId },
    settings.uploadTimeoutMs
  );
  return result.body;
}

async function abortChunkedUpload(tabId, uploadId, reason) {
  if (!uploadId) return;
  try {
    const settings = await getSettings();
    await postJson(
      tabId,
      "/api/chat-file/abort",
      { uploadId, reason: String(reason || "CLIENT_ABORT") },
      settings.uploadTimeoutMs
    );
  } catch (_) {}
}

function concatUint8Arrays(chunks, totalBytes) {
  const out = new Uint8Array(totalBytes);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return out;
}

async function uploadFileFromUrl(tabId, { runId, fileName, mimeType, url, totalBytes: browserTotalBytes }) {
  const settings = await getSettings();
  const sourceController = new AbortController();
  registerController(tabId, sourceController);

  let uploadId = null;
  let reader = null;
  let confirmedBytes = 0;

  try {
    const response = await withStallTimeout(
      fetch(url, {
        method: "GET",
        credentials: "include",
        redirect: "follow",
        cache: "no-store",
        signal: sourceController.signal
      }),
      settings.uploadStallTimeoutMs,
      () => sourceController.abort("FILE_REFETCH_STALLED"),
      "FILE_REFETCH_START_STALLED"
    );

    if (!response.ok) {
      throw new Error(`FILE_REFETCH_HTTP_${response.status}`);
    }
    if (!response.body) {
      throw new Error("FILE_REFETCH_STREAM_UNAVAILABLE");
    }

    const browserLength = knownPositiveByteLength(browserTotalBytes);
    const headerLength = knownPositiveByteLength(response.headers.get("content-length"));
    const expectedBytes = browserLength ?? headerLength;
    const actualMime = mimeType || response.headers.get("content-type") || "application/octet-stream";

    const started = await beginChunkedUpload(tabId, {
      runId,
      fileName,
      mimeType: actualMime,
      totalBytes: expectedBytes
    });
    uploadId = started.uploadId;

    sendTransferProgressToTab(tabId, {
      phase: "SERVER_UPLOAD",
      fileName,
      transferredBytes: 0,
      totalBytes: expectedBytes,
      uploadId
    });

    reader = response.body.getReader();
    const TARGET_CHUNK_BYTES = 4 * 1024 * 1024;
    let pendingChunks = [];
    let pendingBytes = 0;
    let sourceBytes = 0;

    const flush = async () => {
      if (!pendingBytes) return;
      const payload = concatUint8Arrays(pendingChunks, pendingBytes);
      const body = await postUploadChunk(tabId, {
        uploadId,
        offset: confirmedBytes,
        bytes: payload
      });
      confirmedBytes = Number(body?.receivedBytes ?? (confirmedBytes + payload.byteLength));
      pendingChunks = [];
      pendingBytes = 0;

      sendTransferProgressToTab(tabId, {
        phase: "SERVER_UPLOAD",
        fileName,
        transferredBytes: confirmedBytes,
        totalBytes: expectedBytes,
        sourceBytes,
        uploadId
      });
    };

    while (true) {
      const part = await withStallTimeout(
        reader.read(),
        settings.uploadStallTimeoutMs,
        () => sourceController.abort("FILE_REFETCH_STALLED"),
        "FILE_REFETCH_STALLED"
      );

      if (part.done) break;
      if (!part.value?.byteLength) continue;

      sourceBytes += part.value.byteLength;
      pendingChunks.push(part.value);
      pendingBytes += part.value.byteLength;

      if (pendingBytes >= TARGET_CHUNK_BYTES) {
        await flush();
      }
    }

    await flush();

    if (expectedBytes != null && confirmedBytes !== expectedBytes) {
      throw new Error(`FILE_SIZE_MISMATCH expected=${expectedBytes} uploaded=${confirmedBytes}`);
    }
    if (confirmedBytes <= 0) {
      throw new Error("FILE_REFETCH_EMPTY");
    }

    const server = await finishChunkedUpload(tabId, uploadId);
    uploadId = null;

    sendTransferProgressToTab(tabId, {
      phase: "SERVER_COMPLETE",
      fileName,
      transferredBytes: confirmedBytes,
      totalBytes: expectedBytes ?? confirmedBytes,
      sha256: server?.sha256 || null
    });

    return {
      ok: true,
      source: "url-refetch-stream",
      byteLength: confirmedBytes,
      sha256: server?.sha256 || null,
      server
    };
  } catch (error) {
    try { await reader?.cancel?.(); } catch (_) {}
    try { sourceController.abort("FILE_TRANSFER_FAILED"); } catch (_) {}
    await abortChunkedUpload(tabId, uploadId, error?.message || error);
    throw error;
  } finally {
    unregisterController(tabId, sourceController);
  }
}

function fileKeyVariants(value) {
  let text = String(value || "").trim();
  if (!text) return new Set();

  try {
    const parsed = new URL(text);
    const part = parsed.pathname.split("/").pop();
    if (part) text = decodeURIComponent(part);
  } catch (_) {
    text = text.split(/[?#]/, 1)[0];
    text = text.replace(/^.*[\\/]/, "");
    try {
      text = decodeURIComponent(text);
    } catch (_) {}
  }

  text = text.toLowerCase();

  const names = new Set([text]);
  const known = /\.(?:gz|zip|tar|tgz|bz2|xz|7z|rar|txt|log|json|diff|patch|sh|csv|pdf|js|mjs|py)$/i;

  let stem = text;
  while (known.test(stem)) {
    stem = stem.replace(known, "");
    names.add(stem);
  }

  const variants = new Set();
  for (const name of names) {
    const compact = name.replace(/[^a-z0-9а-яё]+/gi, "");
    if (compact) variants.add(compact);
  }

  return variants;
}

function downloadMatchesExpected(downloadItem, expectedName) {
  const expected = fileKeyVariants(expectedName);
  if (!expected.size) return false;

  const candidates = new Set();
  for (const value of [downloadItem.filename, downloadItem.url, downloadItem.finalUrl]) {
    for (const key of fileKeyVariants(value)) {
      candidates.add(key);
    }
  }

  for (const key of expected) {
    if (candidates.has(key)) return true;
  }

  return false;
}

function sendDownloadResultToTab(watch, result) {
  chrome.tabs.sendMessage(watch.tabId, {
    type: "BROWSER_DOWNLOAD_RESULT",
    watchId: watch.watchId,
    result
  }).catch(() => {});
}

function sendDownloadProgressToTab(watch, item) {
  chrome.tabs.sendMessage(watch.tabId, {
    type: "BROWSER_DOWNLOAD_PROGRESS",
    watchId: watch.watchId,
    progress: {
      downloadId: item?.id ?? watch.downloadId,
      fileName: item?.filename || null,
      state: item?.state || "in_progress",
      bytesReceived: Number(item?.bytesReceived || 0),
      totalBytes: Number(item?.totalBytes || 0),
      paused: Boolean(item?.paused),
      canResume: Boolean(item?.canResume),
      finalUrl: item?.finalUrl || item?.url || null
    }
  }).catch(() => {});
}

function finishDownloadWatch(watchId, result) {
  const watch = downloadWatches.get(watchId);
  if (!watch) return;

  clearTimeout(watch.startTimer);
  clearInterval(watch.pollTimer);
  watch.startTimer = null;
  watch.pollTimer = null;
  downloadWatches.delete(watchId);
  sendDownloadResultToTab(watch, result);
}

async function pollDownloadWatch(watchId) {
  const watch = downloadWatches.get(watchId);
  if (!watch?.downloadId) return;

  let item = null;
  try {
    const rows = await chrome.downloads.search({ id: watch.downloadId });
    item = rows?.[0] || null;
  } catch (error) {
    finishDownloadWatch(watchId, {
      ok: false,
      error: `DOWNLOAD_STATUS_READ_FAILED: ${error?.message || error}`,
      stage: "DOWNLOAD_PROGRESS",
      expectedName: watch.expectedName,
      downloadId: watch.downloadId
    });
    return;
  }

  if (!item) {
    finishDownloadWatch(watchId, {
      ok: false,
      error: "DOWNLOAD_ITEM_DISAPPEARED",
      stage: "DOWNLOAD_PROGRESS",
      expectedName: watch.expectedName,
      downloadId: watch.downloadId
    });
    return;
  }

  if (item.state === "interrupted") {
    finishDownloadWatch(watchId, {
      ok: false,
      error: item.error || "DOWNLOAD_INTERRUPTED",
      stage: "DOWNLOAD_PROGRESS",
      downloadId: item.id,
      expectedName: watch.expectedName,
      bytesReceived: item.bytesReceived ?? null,
      totalBytes: item.totalBytes ?? null
    });
    return;
  }

  if (item.state === "complete") {
    finishDownloadWatch(watchId, {
      ok: true,
      downloadId: item.id,
      fileName: item.filename || null,
      finalUrl: item.finalUrl || item.url || null,
      bytesReceived: item.bytesReceived ?? null,
      totalBytes: item.totalBytes ?? null,
      fileSize: item.fileSize ?? null,
      state: "complete"
    });
    return;
  }

  const now = Date.now();
  const bytes = Number(item.bytesReceived || 0);
  if (bytes > watch.lastBytesReceived) {
    watch.lastBytesReceived = bytes;
    watch.lastProgressAt = now;
    sendDownloadProgressToTab(watch, item);
  } else if (watch.lastProgressAt == null) {
    watch.lastProgressAt = now;
  }

  if (now - watch.lastProgressAt >= watch.stallTimeoutMs) {
    finishDownloadWatch(watchId, {
      ok: false,
      error: item.paused ? "DOWNLOAD_PAUSED_STALLED" : "DOWNLOAD_STALLED",
      stage: "DOWNLOAD_PROGRESS",
      downloadId: item.id,
      expectedName: watch.expectedName,
      bytesReceived: item.bytesReceived ?? null,
      totalBytes: item.totalBytes ?? null,
      stalledMs: now - watch.lastProgressAt
    });
  }
}

function armBrowserDownload(tabId, expectedName, startTimeoutMs, stallTimeoutMs) {
  const watchId = crypto.randomUUID();
  const watch = {
    watchId,
    tabId,
    expectedName: expectedName || "",
    createdAt: Date.now(),
    downloadId: null,
    stallTimeoutMs: Math.max(1000, Number(stallTimeoutMs) || 120000),
    lastBytesReceived: 0,
    lastProgressAt: null,
    startTimer: null,
    pollTimer: null
  };

  watch.startTimer = setTimeout(() => {
    finishDownloadWatch(watchId, {
      ok: false,
      error: "DOWNLOAD_START_TIMEOUT",
      stage: "DOWNLOAD_START",
      expectedName: watch.expectedName
    });
  }, Math.max(1000, Number(startTimeoutMs) || 15000));

  downloadWatches.set(watchId, watch);
  return watchId;
}

chrome.downloads.onCreated.addListener((downloadItem) => {
  const pending = [...downloadWatches.values()]
    .filter((watch) => !watch.downloadId)
    .sort((a, b) => a.createdAt - b.createdAt);

  if (!pending.length) return;

  let watch = pending.find((candidate) => downloadMatchesExpected(downloadItem, candidate.expectedName));

  if (!watch && pending.length === 1) {
    const candidate = pending[0];
    const ageMs = Date.now() - candidate.createdAt;

    // Claude can return a generated/CDN filename unrelated to the visible label.
    // With exactly one freshly armed watcher, accept the newly-created download
    // from the click instead of timing out on a cosmetic filename mismatch.
    if (!candidate.expectedName || ageMs <= 5000) {
      watch = candidate;
    }
  }

  if (!watch) return;

  watch.downloadId = downloadItem.id;
  watch.lastBytesReceived = Number(downloadItem.bytesReceived || 0);
  watch.lastProgressAt = Date.now();
  clearTimeout(watch.startTimer);
  watch.startTimer = null;

  sendDownloadProgressToTab(watch, downloadItem);
  watch.pollTimer = setInterval(() => {
    pollDownloadWatch(watch.watchId).catch((error) => {
      finishDownloadWatch(watch.watchId, {
        ok: false,
        error: `DOWNLOAD_PROGRESS_ERROR: ${error?.message || error}`,
        stage: "DOWNLOAD_PROGRESS",
        expectedName: watch.expectedName,
        downloadId: watch.downloadId
      });
    });
  }, 1000);

  pollDownloadWatch(watch.watchId).catch(() => {});
});

chrome.downloads.onChanged.addListener(async (delta) => {
  const watch = [...downloadWatches.values()].find((entry) => entry.downloadId === delta.id);
  if (!watch) return;

  if (delta.state?.current === "interrupted") {
    let item = null;
    try {
      const results = await chrome.downloads.search({ id: delta.id });
      item = results?.[0] || null;
    } catch (_) {}

    finishDownloadWatch(watch.watchId, {
      ok: false,
      error: delta.error?.current || item?.error || "DOWNLOAD_INTERRUPTED",
      stage: "DOWNLOAD_PROGRESS",
      downloadId: delta.id,
      expectedName: watch.expectedName,
      bytesReceived: item?.bytesReceived ?? null,
      totalBytes: item?.totalBytes ?? null
    });
    return;
  }

  if (delta.state?.current === "complete") {
    await pollDownloadWatch(watch.watchId);
  }
});

chrome.tabs.onRemoved.addListener(async (tabId) => {
  cancelRequestsForTab(tabId, "TAB_CLOSED");
  await setTabEnabled(tabId, false);
  await clearTabStatus(tabId);
});

chrome.tabs.onUpdated.addListener(async (tabId, changeInfo, tab) => {
  if (!(await isTabEnabled(tabId))) {
    return;
  }

  const chat = chatInfoForUrl(tab.url);
  const supported = Boolean(chat.supported);

  if (!supported) {
    await setTabStatus(tabId, {
      state: "IDLE",
      stage: "UNSUPPORTED_URL",
      url: tab.url || null
    });
    cancelRequestsForTab(tabId, "UNSUPPORTED_URL");
    chrome.tabs.sendMessage(tabId, { type: "TAB_BECAME_UNSUPPORTED" }).catch(() => {});
    return;
  }

  if (changeInfo.status === "loading") {
    cancelRequestsForTab(tabId, "TAB_NAVIGATED");
    await setTabStatus(tabId, {
      state: "ARMED",
      stage: "PAGE_LOADING",
      chatType:chat.type,
      chatLabel:chat.label,
      url: tab.url || null
    });
    chrome.tabs.sendMessage(tabId, { type: "TAB_NAVIGATING" }).catch(() => {});
    return;
  }

  if (changeInfo.url) {
    cancelRequestsForTab(tabId, "TAB_NAVIGATED");
  }

  if (changeInfo.status === "complete" || changeInfo.url) {
    try {
      await injectPageHook(tabId);
    } catch (_) {}

    await setTabStatus(tabId, {
      state: "ARMED",
      stage: changeInfo.status === "complete" ? "PAGE_COMPLETE" : "URL_CHANGED",
      chatType:chat.type,
      chatLabel:chat.label,
      url: tab.url || null
    });

    chrome.tabs.sendMessage(tabId, {
      type: "SCHEDULE_AUTORUN",
      reason: changeInfo.status === "complete" ? "PAGE_COMPLETE" : "URL_CHANGED"
    }).catch(() => {});
  }
});

chrome.runtime.onConnect.addListener((port) => {
  if (!["pap-file-transfer", "claude-file-transfer"].includes(port.name)) {
    return;
  }

  const tabId = port.sender?.tab?.id;
  if (!tabId) {
    port.disconnect();
    return;
  }

  port.onMessage.addListener(async (message) => {
    const transferId = message?.transferId;
    try {
      if (message.type === "BEGIN_FILE_TRANSFER") {
        const started = await beginChunkedUpload(tabId, {
          runId: message.runId,
          fileName: message.fileName,
          mimeType: message.mimeType,
          totalBytes: message.totalBytes
        });

        incomingTransfers.set(transferId, {
          tabId,
          runId: message.runId,
          fileName: message.fileName,
          mimeType: message.mimeType,
          sha256: message.sha256,
          totalBytes: Number(message.totalBytes || 0),
          receivedBytes: 0,
          uploadId: started.uploadId,
          nextChunkIndex: 0
        });

        port.postMessage({
          type: "FILE_TRANSFER_READY",
          transferId,
          uploadId: started.uploadId
        });
        return;
      }

      if (message.type === "FILE_CHUNK") {
        const transfer = incomingTransfers.get(transferId);
        if (!transfer || transfer.tabId !== tabId) {
          throw new Error("UNKNOWN_FILE_TRANSFER");
        }
        if (Number(message.chunkIndex) !== transfer.nextChunkIndex) {
          throw new Error(`TRANSFER_CHUNK_INDEX_MISMATCH expected=${transfer.nextChunkIndex} got=${message.chunkIndex}`);
        }
        if (Number(message.offset) !== transfer.receivedBytes) {
          throw new Error(`TRANSFER_OFFSET_MISMATCH expected=${transfer.receivedBytes} got=${message.offset}`);
        }

        const binary = atob(message.base64);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
          bytes[i] = binary.charCodeAt(i);
        }

        const response = await postUploadChunk(tabId, {
          uploadId: transfer.uploadId,
          offset: transfer.receivedBytes,
          bytes
        });
        transfer.receivedBytes = Number(response?.receivedBytes ?? (transfer.receivedBytes + bytes.byteLength));
        transfer.nextChunkIndex++;

        sendTransferProgressToTab(tabId, {
          phase: "SERVER_UPLOAD",
          fileName: transfer.fileName,
          transferredBytes: transfer.receivedBytes,
          totalBytes: transfer.totalBytes,
          uploadId: transfer.uploadId
        });

        port.postMessage({
          type: "FILE_CHUNK_ACK",
          transferId,
          chunkIndex: message.chunkIndex,
          ok: true,
          receivedBytes: transfer.receivedBytes
        });
        return;
      }

      if (message.type === "END_FILE_TRANSFER") {
        const transfer = incomingTransfers.get(transferId);
        if (!transfer || transfer.tabId !== tabId) {
          throw new Error("UNKNOWN_FILE_TRANSFER");
        }

        if (transfer.totalBytes !== transfer.receivedBytes) {
          throw new Error(`TRANSFER_SIZE_MISMATCH expected=${transfer.totalBytes} received=${transfer.receivedBytes}`);
        }

        const server = await finishChunkedUpload(tabId, transfer.uploadId);
        if (transfer.sha256 && server?.sha256 && transfer.sha256.toLowerCase() !== String(server.sha256).toLowerCase()) {
          throw new Error(`SHA256_MISMATCH client=${transfer.sha256} server=${server.sha256}`);
        }

        incomingTransfers.delete(transferId);
        sendTransferProgressToTab(tabId, {
          phase: "SERVER_COMPLETE",
          fileName: transfer.fileName,
          transferredBytes: transfer.receivedBytes,
          totalBytes: transfer.totalBytes,
          sha256: server?.sha256 || null
        });

        port.postMessage({
          type: "FILE_UPLOAD_RESULT",
          transferId,
          result: {
            ok: true,
            byteLength: transfer.receivedBytes,
            sha256: server?.sha256 || transfer.sha256 || null,
            server
          }
        });
      }
    } catch (error) {
      const transfer = incomingTransfers.get(transferId);
      if (transfer?.uploadId) {
        await abortChunkedUpload(tabId, transfer.uploadId, error?.message || error);
      }
      incomingTransfers.delete(transferId);
      try {
        port.postMessage({
          type: "FILE_UPLOAD_RESULT",
          transferId,
          result: {
            ok: false,
            error: String(error?.message || error)
          }
        });
      } catch (_) {}
    }
  });

  port.onDisconnect.addListener(() => {
    for (const [transferId, transfer] of incomingTransfers.entries()) {
      if (transfer.tabId === tabId) {
        incomingTransfers.delete(transferId);
        abortChunkedUpload(tabId, transfer.uploadId, "TRANSFER_PORT_DISCONNECTED").catch(() => {});
      }
    }
  });
});

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  (async () => {
    const senderTabId = sender.tab?.id || message.tabId || null;

    if (message.type === "CHAT_TURN_FINISHED" || message.type === "CLAUDE_TURN_FINISHED") {
      const tabId = sender.tab?.id;
      if (!tabId) {
        sendResponse({ok:false, error:"NO_SENDER_TAB"});
        return;
      }

      if (!(await isTabEnabled(tabId))) {
        sendResponse({ok:false, error:"TAB_NOT_ENABLED"});
        return;
      }

      const tab = await chrome.tabs.get(tabId);
      if (!isSupportedUrl(tab.url)) {
        sendResponse({ok:false, error:"UNSUPPORTED_URL"});
        return;
      }

      await setTabStatus(tabId, {
        state:"ARMED",
        stage:"CHAT_TURN_FINISHED",
        reason:"SPA_DOM_TURN_FINISHED",
        chatType:message.chatType || chatInfoForUrl(tab.url).type,
        chatLabel:message.chatLabel || chatInfoForUrl(tab.url).label,
        turnKey:message.turnKey || null,
        rowIndex:message.rowIndex || null,
        url:tab.url || null,
        error:null
      });

      await chrome.tabs.sendMessage(tabId, {
        type:"SCHEDULE_AUTORUN",
        reason:"CHAT_TURN_FINISHED",
        turnKey:message.turnKey || null,
        rowIndex:message.rowIndex || null
      });

      sendResponse({
        ok:true,
        scheduled:true,
        turnKey:message.turnKey || null
      });
      return;
    }

    if (message.type === "GET_TAB_STATE") {
      sendResponse(await getTabState(message.tabId));
      return;
    }

    if (message.type === "ENABLE_TAB") {
      const tab = await chrome.tabs.get(message.tabId);
      if (!isSupportedUrl(tab.url)) {
        sendResponse({ ok: false, error: "UNSUPPORTED_URL", url: tab.url || null });
        return;
      }

      const chat = chatInfoForUrl(tab.url);
      await setTabEnabled(message.tabId, true);
      await setTabStatus(message.tabId, {
        state: "ARMED",
        stage: "ENABLED_BY_USER",
        chatType:chat.type,
        chatLabel:chat.label,
        url: tab.url || null,
        error: null
      });

      const runtime = await ensureChatRuntimeInjected(message.tabId, tab.url);

      await setTabStatus(message.tabId, {
        state: "ARMED",
        stage: "CURRENT_PAGE_RUNTIME_INJECTED",
        url: tab.url || null,
        error: null,
        runtime
      });

      await chrome.tabs.sendMessage(
        message.tabId,
        { type: "TAB_ENABLED" }
      ).catch(() => {});

      sendResponse({
        ok: true,
        runtimeInjected: true,
        runtime,
        state: await getTabState(message.tabId)
      });
      return;
    }

    if (message.type === "DISABLE_TAB") {
      await setTabEnabled(message.tabId, false);
      cancelRequestsForTab(message.tabId, "TAB_DISABLED_BY_USER");
      await setTabStatus(message.tabId, {
        state: "OFF",
        stage: "DISABLED_BY_USER",
        error: null
      });
      await chrome.tabs.sendMessage(message.tabId, { type: "TAB_DISABLED" }).catch(() => {});
      sendResponse({ ok: true, state: await getTabState(message.tabId) });
      return;
    }

    if (message.type === "RUN_TAB_NOW") {
      const state = await getTabState(message.tabId);
      if (!state.enabled) {
        sendResponse({ ok: false, error: "TAB_NOT_ENABLED" });
        return;
      }
      if (!state.supported) {
        sendResponse({ ok: false, error: "UNSUPPORTED_URL" });
        return;
      }
      const runtime = await ensureChatRuntimeInjected(message.tabId, state.url);
      await chrome.tabs.sendMessage(message.tabId, { type: "RUN_NOW" });
      sendResponse({ ok: true, runtimeInjected: true, runtime });
      return;
    }

    if (message.type === "GET_RUNTIME_CONFIG") {
      if (!sender.tab?.id) {
        sendResponse({ ok: false, error: "NO_SENDER_TAB" });
        return;
      }
      const enabled = await isTabEnabled(sender.tab.id);
      const settings = await getSettings();
      const chat = chatInfoForUrl(sender.tab.url);
      sendResponse({
        ok: true,
        enabled,
        supported: Boolean(chat.supported),
        chatType:chat.type,
        chatLabel:chat.label,
        conversationId:chat.conversationId || null,
        tabId: sender.tab.id,
        settings
      });
      return;
    }

    if (message.type === "CHECK_TAB_ALLOWED") {
      if (!sender.tab?.id) {
        sendResponse({ ok: false, allowed: false, error: "NO_SENDER_TAB" });
        return;
      }
      const chat = chatInfoForUrl(sender.tab.url);
      sendResponse({
        ok: true,
        allowed: (await isTabEnabled(sender.tab.id)) && Boolean(chat.supported),
        enabled: await isTabEnabled(sender.tab.id),
        supported: Boolean(chat.supported),
        chatType:chat.type,
        chatLabel:chat.label
      });
      return;
    }

    if (message.type === "SET_TAB_STATUS") {
      if (!senderTabId) {
        sendResponse({ ok: false, error: "NO_TAB_ID" });
        return;
      }
      const status = await setTabStatus(senderTabId, message.status || {});
      sendResponse({ ok: true, status });
      return;
    }

    if (message.type === "POST_PARSE_RESULT") {
      if (!sender.tab?.id) {
        sendResponse({ ok: false, error: "NO_SENDER_TAB" });
        return;
      }
      if (!(await isTabEnabled(sender.tab.id)) || !isSupportedUrl(sender.tab.url)) {
        sendResponse({ ok: false, error: "TAB_NOT_ALLOWED" });
        return;
      }
      await assertServerCompatibility(sender.tab.id);
      const settings = await getSettings();
      const chat = chatInfoForUrl(sender.tab.url);
      const papPayload = {
        ...(message.payload || {}),
        chatType:(message.payload && message.payload.chatType) || chat.type,
        chatLabel:(message.payload && message.payload.chatLabel) || chat.label,
        chatConversationId:(message.payload && message.payload.chatConversationId) || chat.conversationId || null,
        papSource: {
          ...((message.payload && message.payload.papSource) || {}),
          tabId: sender.tab.id,
          url: sender.tab.url || null,
          chatType:chat.type,
          chatLabel:chat.label
        }
      };
      const result = await postJson(sender.tab.id, "/api/chat-result", papPayload, settings.uploadTimeoutMs);
      sendResponse({ ok: true, ...result.body });
      return;
    }

    if (message.type === "POST_RUN_STATUS") {
      if (!senderTabId) {
        sendResponse({ ok: false, error: "NO_TAB_ID" });
        return;
      }
      const settings = await getSettings();
      const result = await postJson(senderTabId, "/api/chat-status", message.payload, settings.uploadTimeoutMs);
      sendResponse({ ok: true, ...result.body });
      return;
    }

    if (message.type === "ARM_BROWSER_DOWNLOAD") {
      if (!sender.tab?.id) {
        sendResponse({ ok: false, error: "NO_SENDER_TAB" });
        return;
      }
      const settings = await getSettings();
      const watchId = armBrowserDownload(
        sender.tab.id,
        message.expectedName,
        message.startTimeoutMs ?? settings.downloadStartTimeoutMs,
        message.stallTimeoutMs ?? settings.downloadStallTimeoutMs
      );
      sendResponse({ ok: true, watchId });
      return;
    }

    if (message.type === "CANCEL_BROWSER_DOWNLOAD") {
      if (message.watchId) {
        finishDownloadWatch(message.watchId, {
          ok: false,
          error: "DOWNLOAD_WATCH_CANCELLED",
          stage: "CANCELLED"
        });
      }
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "DOWNLOAD_WATCH_HEARTBEAT") {
      if (!message.watchId || !downloadWatches.has(message.watchId)) {
        sendResponse({ ok: false, error: "DOWNLOAD_WATCH_NOT_FOUND" });
        return;
      }
      await pollDownloadWatch(message.watchId);
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "TRANSFER_HEARTBEAT") {
      await chrome.runtime.getPlatformInfo();
      sendResponse({ ok: true });
      return;
    }

    if (message.type === "UPLOAD_FILE_FROM_URL") {
      if (!sender.tab?.id) {
        sendResponse({ ok: false, error: "NO_SENDER_TAB" });
        return;
      }
      const result = await uploadFileFromUrl(sender.tab.id, message.payload);
      sendResponse(result);
      return;
    }

    if (message.type === "PAP_CHAT_BRIDGE_HTTP") {
      if (!sender.tab?.id) {
        sendResponse({ ok: false, error: "NO_SENDER_TAB" });
        return;
      }
      if (!isSupportedUrl(sender.tab.url)) {
        sendResponse({ ok: false, error: "TAB_NOT_SUPPORTED_FOR_DELIVERY" });
        return;
      }
      const method = String(message.method || "GET").toUpperCase();
      const path = String(message.path || "");
      if (!path.startsWith("/api/")) {
        sendResponse({ ok: false, error: "BRIDGE_PATH_NOT_ALLOWED" });
        return;
      }
      if (!["GET", "POST"].includes(method)) {
        sendResponse({ ok: false, error: "BRIDGE_METHOD_NOT_ALLOWED" });
        return;
      }
      const settings = await getSettings();
      const base = new URL(settings.serverBaseUrl);
      base.port = "8871";
      base.pathname = "";
      base.search = "";
      base.hash = "";
      const headers = {"Authorization": `Bearer ${settings.serverToken}`};
      const options = {method, headers};
      if (method === "POST") {
        headers["Content-Type"] = "application/json";
        options.body = JSON.stringify(message.body || {});
      }
      const response = await fetch(`${base.origin}${path}`, options);
      const text = await response.text();
      let body = text;
      try { body = text ? JSON.parse(text) : null; } catch (_) {}
      sendResponse({
        ok: response.ok,
        status: response.status,
        body,
        error: response.ok ? null : (body?.error || text || `HTTP ${response.status}`)
      });
      return;
    }

    sendResponse({ ok: false, error: "UNKNOWN_MESSAGE" });
  })().catch((error) => {
    sendResponse({
      ok: false,
      error: String(error?.message || error),
      httpStatus: error?.httpStatus || null,
      serverBody: error?.serverBody || null
    });
  });

  return true;
});
