(() => {
  if (globalThis.__PAP_PROTOCOL_CONTENT_ACTIVE__) {
    return;
  }
  globalThis.__PAP_PROTOCOL_CONTENT_ACTIVE__ = true;
  // Legacy probe flag retained for old diagnostics.
  globalThis.__PAP_CLAUDE_PROTOCOL_CONTENT_ACTIVE__ = true;

  const SOURCE_CONTENT = "PAP2_PROTOCOL_PARSER_CONTENT_V3";
  const SOURCE_PAGE = "PAP2_PROTOCOL_PARSER_PAGE_V3";
  const runtimeGuard = globalThis.PAPRuntimeGuard || null;

  const currentAdapter = () => globalThis.PAPChatAdapters?.current?.(location.href) || null;
  const currentChatInfo = () => globalThis.PAPChatAdapters?.describe?.(location.href) || {
    type:"unknown", label:"Unknown", supported:false, conversationId:"", adapterVersion:""
  };
  const chatLabel = () => currentChatInfo().label || "Chat";
  const parserTitle = (suffix) => `PAP ${chatLabel().toUpperCase()} PARSER — ${suffix}`;

  const EXECUTION_COMMANDS = new Set([
    "COMMAND_RUN",
    "COMMAND_RUN_WORKER",
    "COMMAND_RUN_INSERVER"
  ]);

  const BASE64_VALUE_COMMANDS = new Set([
    "COMMAND_USER_ACTION_REQ",
    "COMMAND_CURRENT_DEV_COMPLETE",
    "COMMAND_RUN_WORKER",
    "COMMAND_RUN_INSERVER"
  ]);

  const state = {
    enabled: false,
    supported: false,
    settings: null,
    runToken: 0,
    runInProgress: false,
    scheduleTimer: null,
    pendingAutorun: null,
    activeAssistantRowKey: "",
    lastParsedAssistantRowKey: "",
    captureWaiters: new Map(),
    downloadWaiters: new Map(),
    overlay: null,
    overlayBody: null,
    currentStage: "IDLE",
    activeFile: null
  };

  const clean = (value) =>
    String(value ?? "")
      .replace(/\u00A0/g, " ")
      .replace(/\r/g, "")
      .trim();

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, Math.max(0, Number(ms) || 0)));
  const log = (...args) => console.log(`[PAP ${chatLabel()} Parser]`, ...args);

  const sendMessage = (message) => new Promise((resolve, reject) => {
    if (runtimeGuard && !runtimeGuard.runtimeAvailable()) {
      reject(new Error("EXTENSION_CONTEXT_INVALIDATED"));
      return;
    }
    try {
      chrome.runtime.sendMessage(message, (response) => {
        const lastError = chrome.runtime.lastError;
        if (lastError) {
          const error = new Error(lastError.message);
          runtimeGuard?.observeError?.(error);
          reject(error);
          return;
        }
        resolve(response);
      });
    } catch (error) {
      runtimeGuard?.observeError?.(error);
      reject(error);
    }
  });

  const parseValue = (text) => {
    const value = clean(text);
    if (!value) return null;

    if (
      (value.startsWith("[") && value.endsWith("]")) ||
      (value.startsWith("{") && value.endsWith("}"))
    ) {
      try {
        return JSON.parse(value);
      } catch (_) {}
    }

    return value;
  };

  const parseCommandId = (value) => {
    const id = clean(value);
    if (!id) return null;
    return /^\d+$/.test(id) ? Number(id) : id;
  };

  const toBase64Utf8 = (text) => {
    const bytes = new TextEncoder().encode(String(text ?? ""));
    return bytesToBase64(bytes);
  };

  const bytesToBase64 = (bytes) => {
    let binary = "";
    const chunkSize = 0x8000;
    for (let i = 0; i < bytes.length; i += chunkSize) {
      binary += String.fromCharCode(...bytes.subarray(i, i + chunkSize));
    }
    return btoa(binary);
  };

  const getPre = (node) => {
    if (!node) return null;
    if (node.tagName === "PRE") return node;
    return node.querySelector?.("pre") || null;
  };

  const getCode = (node) => {
    const pre = getPre(node);
    if (!pre) return "";
    const code = pre.querySelector("code");
    return clean(code?.textContent ?? pre.textContent ?? "");
  };

  const getRawCodeText = (node) => {
    const pre = getPre(node);
    if (!pre) return null;
    const code = pre.querySelector("code");
    return code ? (code.textContent ?? "") : (pre.textContent ?? "");
  };

  const getPossibleUrl = (element, scope) => {
    if (!element) return null;
    if (element.tagName === "A" && element.href) return element.href;

    const closestLink = element.closest?.("a[href]");
    if (closestLink?.href) return closestLink.href;

    const link = scope?.querySelector?.('a[download][href], a[href*="download"], a[href]');
    if (link?.href) return link.href;

    for (const el of scope ? [scope, ...scope.querySelectorAll("*")] : [element]) {
      for (const attr of ["data-download-url", "data-file-url", "data-url", "data-href", "href"]) {
        const value = el.getAttribute?.(attr);
        if (value && /^(https?:\/\/|blob:|data:|\/)/i.test(value)) {
          try {
            return new URL(value, location.href).href;
          } catch (_) {
            return value;
          }
        }
      }
    }

    return null;
  };

  const getDownloadButton = (artifact) => {
    const adapterControl = currentAdapter()?.downloadControl?.(artifact);
    if (adapterControl) return adapterControl;
    return [...artifact.querySelectorAll("button")].find((button) =>
      /^Download\s+(?!all\b)/i.test(clean(button.getAttribute("aria-label")))
    ) || null;
  };

  const parseArtifact = (artifact) => {
    const adapterParsed = currentAdapter()?.parseArtifact?.(artifact);
    if (adapterParsed) return adapterParsed;
    const buttons = [...artifact.querySelectorAll("button")];
    const viewButton = buttons.find((button) => /^View\s+/i.test(clean(button.getAttribute("aria-label"))));
    const downloadButton = getDownloadButton(artifact);

    const name =
      clean(artifact.querySelector(".text-heading")?.textContent) ||
      clean(viewButton?.getAttribute("aria-label")?.replace(/^View\s+/i, "")) ||
      clean(downloadButton?.getAttribute("aria-label")?.replace(/^Download\s+/i, "")) ||
      null;

    const extension =
      [...artifact.querySelectorAll(".text-footnote")]
        .map((element) => clean(element.textContent))
        .find((value) => /^[A-Z0-9]{1,10}$/i.test(value)) || null;

    const url = getPossibleUrl(downloadButton, artifact);

    return {
      type: "FILE",
      name,
      fileKind: artifact.getAttribute("data-sheet-kind") || null,
      extension,
      download: {
        available: Boolean(downloadButton),
        text: clean(downloadButton?.innerText) || null,
        ariaLabel: clean(downloadButton?.getAttribute("aria-label")) || null,
        url,
        urlAvailableInDOM: Boolean(url)
      }
    };
  };

  const parseMarker = (node) => {
    const tag = node.tagName?.toUpperCase();
    if (tag !== "P" && !/^H[1-6]$/.test(tag)) return null;

    const text = clean(node.innerText || node.textContent);
    if (!text) return null;

    if (/^H[1-6]$/.test(tag)) {
      const structured = text.match(/^(COMMAND_[A-Z0-9_]+)(?:\s+id\s*=\s*([A-Z0-9._:-]+))?\s*$/i);
      if (structured) {
        return {
          kind: "COMMAND",
          type: structured[1].toUpperCase(),
          commandId: parseCommandId(structured[2]),
          inlineValue: null
        };
      }
    }

    const oldCommand = text.match(/^(COMMAND_[A-Z0-9_]+)(?:\s+id\s*=\s*([A-Z0-9._:-]+))?\s*::\s*(.*)$/i);
    if (oldCommand) {
      return {
        kind: "COMMAND",
        type: oldCommand[1].toUpperCase(),
        commandId: parseCommandId(oldCommand[2]),
        inlineValue: clean(oldCommand[3]) || null
      };
    }

    const control = text.match(/^(STOP_RUN|CONTINUE_RUN|STOP_CONDITION|CONDITION_RUN)\s*::\s*(.*)$/i);
    if (control) {
      const sourceType = control[1].toUpperCase();
      return {
        kind: "CONTROL",
        type: sourceType === "CONDITION_RUN" || sourceType === "STOP_CONDITION" ? "STOP_CONDITION" : sourceType,
        sourceType,
        inlineValue: clean(control[2]) || null
      };
    }

    const humanCondition = text.match(/^(?:Условие\s+остановки|Критерий\s+остановки|Stop\s+condition)\s*(?::|：|[-–—])\s*(.+)$/i);
    if (humanCondition) {
      return {
        kind: "CONTROL",
        type: "STOP_CONDITION",
        sourceType: "TEXT_STOP_CONDITION",
        inlineValue: clean(humanCondition[1])
      };
    }

    return null;
  };

  const parseCompositeRunBlock = (raw) => {
    const text = String(raw ?? "").replace(/\r/g, "");
    const regexp = /^[ \t]*(STOP_RUN|CONTINUE_RUN|CONDITION_RUN|STOP_CONDITION)\s*::/gmi;
    const markers = [];
    let match;

    while ((match = regexp.exec(text)) !== null) {
      markers.push({
        sourceType: match[1].toUpperCase(),
        index: match.index,
        valueStart: regexp.lastIndex
      });
    }

    if (!markers.length) {
      return { command: clean(text), controls: [] };
    }

    const command = clean(text.slice(0, markers[0].index));
    const controls = [];

    for (let i = 0; i < markers.length; i++) {
      const current = markers[i];
      const next = markers[i + 1];
      const rawValue = clean(text.slice(current.valueStart, next ? next.index : text.length));
      const type = current.sourceType === "CONDITION_RUN" || current.sourceType === "STOP_CONDITION"
        ? "STOP_CONDITION"
        : current.sourceType;

      controls.push({
        type,
        sourceType: current.sourceType,
        value: type === "STOP_CONDITION" ? rawValue : parseValue(rawValue)
      });
    }

    return { command, controls };
  };

  const collectLogicalNodes = (row) => {
    const adapterNodes = currentAdapter()?.logicalMessageNodes?.(row);
    const sourceNodes = Array.isArray(adapterNodes) ? adapterNodes : [];
    const nodes = new Set(sourceNodes);

    // Last-resort fallback keeps old Claude markup and simple Markdown chats
    // parseable even if an adapter temporarily loses a selector.
    if (!nodes.size) {
      const proseElements = [...row.querySelectorAll('[data-cds="Prose"], .markdown, .prose')];
      for (const prose of proseElements) {
        const roots = prose.firstElementChild ? [prose] : [prose];
        for (const root of roots) for (const child of root.children) nodes.add(child);
      }
    }

    for (const artifact of currentAdapter()?.artifactNodes?.(row) || []) {
      const covered = [...nodes].some((node) => node !== artifact && node.contains?.(artifact));
      if (!covered) nodes.add(artifact);
    }

    return [...nodes].sort((a, b) => {
      if (a === b) return 0;
      const relation = a.compareDocumentPosition(b);
      if (relation & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
      if (relation & Node.DOCUMENT_POSITION_PRECEDING) return 1;
      return 0;
    });
  };

  const parseMessage = (row, messagePosition) => {
    const items = [];
    let runCounter = 0;
    let currentRun = null;
    let pendingCommand = null;
    let pendingBase64Command = null;

    const createRun = (type, commandId) => {
      runCounter++;
      const commandItem = { type, value: null };
      const run = {
        type: "RUN",
        runIndex: runCounter,
        commandId,
        runType: type,
        items: [commandItem]
      };
      items.push(run);
      currentRun = run;
      return { run, commandItem };
    };

    const addControl = (type, value, sourceType = null, targetRun = currentRun) => {
      const item = { type, value };
      if (sourceType && sourceType !== type) item.sourceType = sourceType;
      if (targetRun) targetRun.items.push(item);
      else items.push({ ...item, orphan: true });
      return item;
    };

    const nodes = collectLogicalNodes(row);

    for (const node of nodes) {
      const marker = parseMarker(node);

      if (marker) {
        pendingCommand = null;
        pendingBase64Command = null;

        if (marker.kind === "COMMAND") {
          const type = marker.type;

          if (EXECUTION_COMMANDS.has(type)) {
            const { run, commandItem } = createRun(type, marker.commandId);

            if (marker.inlineValue !== null) {
              if (BASE64_VALUE_COMMANDS.has(type)) {
                commandItem.value = toBase64Utf8(marker.inlineValue);
                commandItem.valueEncoding = "base64-utf8";
                commandItem.valueFormat = "text/plain";
                commandItem.valueLength = marker.inlineValue.length;
              } else {
                commandItem.value = parseValue(marker.inlineValue);
              }
            } else if (BASE64_VALUE_COMMANDS.has(type)) {
              pendingBase64Command = { run, commandItem };
            } else {
              pendingCommand = { type, run, target: commandItem };
            }
            continue;
          }

          currentRun = null;
          const command = {
            type,
            commandId: marker.commandId,
            value: null
          };
          items.push(command);

          if (marker.inlineValue !== null) {
            if (BASE64_VALUE_COMMANDS.has(type)) {
              command.value = toBase64Utf8(marker.inlineValue);
              command.valueEncoding = "base64-utf8";
              command.valueFormat = "text/plain";
              command.valueLength = marker.inlineValue.length;
            } else {
              command.value = parseValue(marker.inlineValue);
            }
          } else if (BASE64_VALUE_COMMANDS.has(type)) {
            pendingBase64Command = { commandItem: command };
          } else {
            pendingCommand = { type, run: null, target: command };
          }
          continue;
        }

        if (marker.kind === "CONTROL") {
          const value = marker.type === "STOP_CONDITION"
            ? marker.inlineValue
            : marker.inlineValue !== null ? parseValue(marker.inlineValue) : null;
          const control = addControl(marker.type, value, marker.sourceType);
          if (marker.inlineValue === null && marker.type !== "STOP_CONDITION") {
            pendingCommand = { type: marker.type, run: currentRun, target: control };
          }
          continue;
        }
      }

      if (pendingBase64Command) {
        const rawText = getRawCodeText(node);
        if (rawText !== null) {
          pendingBase64Command.commandItem.value = toBase64Utf8(rawText);
          pendingBase64Command.commandItem.valueEncoding = "base64-utf8";
          pendingBase64Command.commandItem.valueFormat = "text/plain";
          pendingBase64Command.commandItem.valueLength = rawText.length;
          pendingBase64Command = null;
          continue;
        }
      }

      if (pendingCommand) {
        const pre = getPre(node);
        if (pre) {
          const raw = getCode(node);
          if (pendingCommand.type === "COMMAND_RUN") {
            const parsed = parseCompositeRunBlock(raw);
            pendingCommand.target.value = parseValue(parsed.command);
            for (const control of parsed.controls) {
              addControl(control.type, control.value, control.sourceType, pendingCommand.run);
            }
          } else {
            pendingCommand.target.value = parseValue(raw);
          }
          pendingCommand = null;
          continue;
        }
      }

      const adapter = currentAdapter();
      const nodeArtifacts = adapter?.artifactNodes?.(row) || [];
      if (node.matches?.("[data-sheet-kind]") || nodeArtifacts.includes(node)) {
        items.push(parseArtifact(node));
      }
    }

    // Some chat UIs render generated-file controls inside a paragraph/card that
    // is already a logical text node. Append any adapter-declared artifacts that
    // were not represented as standalone logical nodes. This keeps FILE items
    // independent of site-specific DOM nesting.
    const adapterArtifacts = currentAdapter()?.artifactNodes?.(row) || [];
    const knownFileKeys = new Set(items.filter((item) => item?.type === "FILE").map((item) => `${item.name || ""}|${item.download?.url || ""}`));
    for (const artifact of adapterArtifacts) {
      const parsed = parseArtifact(artifact);
      const key = `${parsed?.name || ""}|${parsed?.download?.url || ""}`;
      if (!knownFileKeys.has(key)) {
        items.push(parsed);
        knownFileKeys.add(key);
      }
    }

    items.forEach((item, index) => {
      item.position = index + 1;
      if (item.type === "RUN") {
        item.items.forEach((runItem, runItemIndex) => {
          runItem.position = runItemIndex + 1;
        });
      }
    });

    return {
      messagePosition,
      row: currentAdapter()?.rowMeta?.(row) || {
        dataIndex: row.getAttribute("data-index") ?? null,
        rsIndex: row.getAttribute("data-rs-index") ?? null,
        fromTail: row.getAttribute("data-perf-row-from-tail") ?? null,
        streaming: row.getAttribute("data-perf-row-streaming") ?? null,
        lastMessage: row.getAttribute("data-last-message") ?? null,
        turnId:null
      },
      items
    };
  };

  const parsePage = (maxAssistantMessages) => {
    const adapter = currentAdapter();
    const info = currentChatInfo();
    if (!adapter?.assistantRows) {
      throw new Error(`CHAT_ADAPTER_UNAVAILABLE:${info.type || "unknown"}`);
    }

    const allAssistantMessages = adapter.assistantRows(document);
    const selectedRows = allAssistantMessages.slice(-Math.max(1, Number(maxAssistantMessages) || 4));
    const messages = selectedRows.map((row, index) => parseMessage(row, index + 1));

    return {
      result: {
        parserVersion: "6.1.0",
        chatType: info.type,
        chatLabel: info.label,
        chatConversationId: info.conversationId || null,
        chatAdapterVersion: info.adapterVersion || null,
        page: location.href,
        generatedAt: new Date().toISOString(),
        order: "DOM_TOP_TO_BOTTOM",
        maxAssistantMessages: Math.max(1, Number(maxAssistantMessages) || 4),
        totalAssistantMessages: allAssistantMessages.length,
        scannedAssistantMessages: selectedRows.length,
        messages
      },
      allAssistantMessages,
      selectedRows
    };
  };

  const basenameFromProtocolPath = (value) => {
    const text = String(value || "").replace(/\\/g, "/");
    const parts = text.split("/");
    return parts[parts.length - 1] || text;
  };

  const canonicalFileKey = (value) =>
    basenameFromProtocolPath(value)
      .toLowerCase()
      .replace(/^download\s+/i, "")
      .replace(/[^a-z0-9а-яё]+/gi, "");

  const fileStemKey = (value) => {
    let name = basenameFromProtocolPath(value).toLowerCase();
    const known = /\.(?:gz|zip|tar|tgz|bz2|xz|7z|rar|txt|log|json|diff|patch|sh|csv|pdf|js|mjs|py)$/i;
    while (known.test(name)) {
      name = name.replace(known, "");
    }
    return name.replace(/[^a-z0-9а-яё]+/gi, "");
  };

  const artifactCandidateKeys = (meta) => {
    const exact = new Set();
    const stems = new Set();
    const name = clean(meta?.name);
    const aria = clean(meta?.download?.ariaLabel).replace(/^Download\s+/i, "");
    const ext = clean(meta?.extension).toLowerCase();

    for (const raw of [name, aria]) {
      if (!raw) continue;

      exact.add(canonicalFileKey(raw));
      stems.add(fileStemKey(raw));

      if (ext && !raw.toLowerCase().endsWith(`.${ext}`)) {
        const combined = `${raw}.${ext}`;
        exact.add(canonicalFileKey(combined));
        stems.add(fileStemKey(combined));
      }
    }

    return { exact, stems };
  };

  const latestCommandPutFileRequests = (parsedResult) => {
    const messages = Array.isArray(parsedResult?.messages) ? parsedResult.messages : [];
    const latest = messages.length ? messages[messages.length - 1] : null;
    if (!latest) return [];

    const requests = [];
    const seen = new Set();
    for (const item of Array.isArray(latest.items) ? latest.items : []) {
      if (item?.type !== "COMMAND_PUT_FILES" || !Array.isArray(item.value)) continue;

      item.value.forEach((value, fileIndex) => {
        const requiredPath = clean(value);
        if (!requiredPath || seen.has(requiredPath)) return;
        seen.add(requiredPath);
        requests.push({
          requestIndex: requests.length,
          requiredPath,
          commandId: item.commandId ?? null,
          commandPosition: item.position ?? null,
          fileIndex
        });
      });
    }

    return requests;
  };

  const buildRequiredDownloadPlan = (parsedResult, selectedRows) => {
    const requests = latestCommandPutFileRequests(parsedResult);
    const requiredPaths = requests.map((entry) => entry.requiredPath);
    const latestRow = selectedRows.length ? selectedRows[selectedRows.length - 1] : null;

    const candidates = [];
    if (latestRow) {
      for (const artifact of currentAdapter()?.artifactNodes?.(latestRow) || []) {
        const meta = parseArtifact(artifact);
        candidates.push({
          candidateIndex: candidates.length,
          artifact,
          button: getDownloadButton(artifact),
          meta,
          keys: artifactCandidateKeys(meta)
        });
      }
    }

    const used = new Set();
    const targets = [];
    const missingRequired = [];
    const adapterMatches = new Map();
    const siteMatches = currentAdapter()?.bindRequiredArtifacts?.({
      row: latestRow,
      requests,
      candidates
    }) || [];
    for (const match of siteMatches) {
      if (match?.requestIndex == null || !match?.artifact) continue;
      adapterMatches.set(Number(match.requestIndex), match);
    }

    for (const request of requests) {
      const {requiredPath} = request;
      const exactKey = canonicalFileKey(requiredPath);
      const stemKey = fileStemKey(requiredPath);
      let binding = null;
      let match = null;

      const siteMatch = adapterMatches.get(request.requestIndex);
      if (siteMatch && !used.has(siteMatch.artifact)) {
        match = candidates.find((candidate) => candidate.artifact === siteMatch.artifact) || null;
        binding = siteMatch.binding || "ADAPTER_LOCAL";
      }

      if (!match) {
        match = candidates.find((candidate) =>
          !used.has(candidate.artifact) && candidate.keys.exact.has(exactKey)
        );
        if (match) binding = "EXACT_NAME";
      }

      if (!match) {
        match = candidates.find((candidate) =>
          !used.has(candidate.artifact) &&
          stemKey &&
          candidate.keys.stems.has(stemKey)
        );
        if (match) binding = "STEM_NAME";
      }

      if (!match) {
        missingRequired.push({
          requiredPath,
          commandId: request.commandId,
          error: "REQUIRED_ARTIFACT_NOT_FOUND"
        });
        continue;
      }

      used.add(match.artifact);
      targets.push({
        artifact: match.artifact,
        button: match.button,
        meta: match.meta,
        requiredPath,
        commandId: request.commandId,
        binding
      });
    }

    return {
      requiredPaths,
      requests,
      targets,
      missingRequired,
      ignoredArtifacts: Math.max(0, candidates.length - targets.length)
    };
  };

  const waitForRequiredDownloadButtons = async (plan, token) => {
    if (!plan.targets.length) return plan;

    const deadline = Date.now() + Math.max(
      1000,
      Number(state.settings.downloadStartTimeoutMs) || 15000
    );

    while (true) {
      await assertAllowed();
      if (token !== state.runToken) throw new Error("RUN_CANCELLED");

      let missingButtons = 0;
      for (const target of plan.targets) {
        if (!target.artifact?.isConnected) continue;
        target.button = getDownloadButton(target.artifact);
        if (!target.button) missingButtons++;
      }

      if (!missingButtons || Date.now() >= deadline) {
        return plan;
      }

      await setStatus({
        state: "RUNNING",
        stage: "WAITING_REQUIRED_FILES",
        requiredFiles: plan.requiredPaths.length,
        matchedArtifacts: plan.targets.length,
        missingDownloadButtons: missingButtons,
        ignoredArtifacts: plan.ignoredArtifacts,
        url: location.href
      });

      showOverlay(
        parserTitle("WAITING"),
        `Нужных файлов по COMMAND_PUT_FILES: ${plan.requiredPaths.length}\n` +
        `Найдено карточек: ${plan.targets.length}\n` +
        `Ожидают кнопку Download: ${missingButtons}\n` +
        `Лишних артефактов игнорируется: ${plan.ignoredArtifacts}`
      );

      await readinessTick();
    }
  };

  const ensureOverlay = () => {
    if (state.overlay?.isConnected) return;

    const box = document.createElement("div");
    box.id = "pap-protocol-parser-status";
    box.style.cssText = [
      "position:fixed",
      "right:16px",
      "bottom:16px",
      "z-index:2147483647",
      "max-width:420px",
      "font:13px/1.45 system-ui,-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif",
      "background:#111827",
      "color:#f9fafb",
      "border:1px solid rgba(255,255,255,.18)",
      "border-radius:10px",
      "box-shadow:0 10px 30px rgba(0,0,0,.35)",
      "padding:12px 14px",
      "white-space:pre-wrap"
    ].join(";");

    document.documentElement.appendChild(box);
    state.overlay = box;
    state.overlayBody = box;
  };

  const showOverlay = (title, body, kind = "info") => {
    ensureOverlay();
    state.overlay.style.borderColor = kind === "error" ? "#ef4444" : kind === "done" ? "#22c55e" : "rgba(255,255,255,.18)";
    state.overlay.textContent = `${title}\n${body || ""}`.trim();
  };

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
    const received = formatBytes(done);
    const totalNumber = Number(total);
    if (Number.isFinite(totalNumber) && totalNumber > 0) {
      const pct = Math.min(100, Math.max(0, (Number(done || 0) / totalNumber) * 100));
      return `${received} / ${formatBytes(totalNumber)} (${pct.toFixed(1)}%)`;
    }
    return `${received} получено`;
  };

  const hideOverlay = () => {
    state.overlay?.remove();
    state.overlay = null;
    state.overlayBody = null;
  };

  const setStatus = async (patch) => {
    if (patch?.stage) state.currentStage = patch.stage;
    try {
      await sendMessage({ type: "SET_TAB_STATUS", status: patch });
    } catch (_) {}
  };

  const assertAllowed = async () => {
    const response = await sendMessage({ type: "CHECK_TAB_ALLOWED" });
    if (!response?.allowed) {
      throw new Error(response?.enabled ? "UNSUPPORTED_URL" : "TAB_DISABLED_BY_USER");
    }
  };

  const waitForLoad = async () => {
    if (document.readyState === "complete") return;
    await new Promise((resolve) => window.addEventListener("load", resolve, { once: true }));
  };

  const readinessTick = (ms = 250) =>
    new Promise((resolve) => setTimeout(resolve, Math.max(50, Number(ms) || 250)));

  const latestTranscriptRow = () => currentAdapter()?.lastTranscriptRow?.(document) || null;

  const chatReadinessSnapshot = () => {
    const adapter = currentAdapter();
    const info = currentChatInfo();
    const latest = adapter?.lastTranscriptRow?.(document) || null;
    const signals = [];

    if (!adapter?.inspectTurnState || !adapter?.inspectParserGate) {
      signals.push('CHAT_ADAPTER_SIGNALS_UNAVAILABLE');
      return {latest, assistantRow:null, signals, parserGate:null, turnState:null, chatInfo:info};
    }

    const parserGate = adapter.inspectParserGate(document);
    const turnState = adapter.inspectTurnState(document);

    if (!latest) {
      signals.push('NO_TRANSCRIPT_ROW');
      return {latest:null, assistantRow:null, signals, parserGate, turnState, chatInfo:info};
    }

    if (adapter.rowRole?.(latest) !== 'assistant') {
      signals.push('LATEST_ROW_IS_NOT_ASSISTANT');
      return {latest, assistantRow:null, signals, parserGate, turnState, chatInfo:info};
    }

    const assistantRow = latest;

    if (parserGate?.blocked) {
      const reason = parserGate.reason || 'CHAT_PARSER_GATE_BLOCKED';
      if (!signals.includes(reason)) signals.push(reason);
    }

    if (turnState && !turnState.ready) {
      for (const signal of turnState.signals || []) {
        if (!signals.includes(signal)) signals.push(signal);
      }
    }

    return {latest, assistantRow, signals, parserGate, turnState, chatInfo:info};
  };

  const assistantRowFingerprint = (row) => {
    if (!row) return '';
    const adapter = currentAdapter();
    const text = String(row.textContent || '');
    const artifacts = (adapter?.artifactNodes?.(row) || [])
      .map((node) => {
        const meta = parseArtifact(node);
        return `${meta?.fileKind || ''}:${meta?.name || ''}:${meta?.download?.ariaLabel || meta?.download?.url || ''}`;
      })
      .join('|');

    return JSON.stringify([
      adapter?.rowKey?.(row) || '',
      text.length,
      text.slice(-1024),
      artifacts
    ]);
  };

  const waitForChatReady = async (token, quietMs = 2500) => {
    let lastFingerprint = '';
    let stableSince = 0;
    let lastUiKey = '';

    while (true) {
      await assertAllowed();
      if (token !== state.runToken) throw new Error('RUN_CANCELLED');

      const snapshot = chatReadinessSnapshot();
      const label = snapshot.chatInfo?.label || chatLabel();

      if (!snapshot.assistantRow || snapshot.signals.length) {
        lastFingerprint = '';
        stableSince = 0;

        const latestIsUser = snapshot.signals.includes('LATEST_ROW_IS_NOT_ASSISTANT');
        const responseDidNotLoad = snapshot.signals.includes('LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD');
        const canRecover = Boolean(
          currentAdapter()?.capabilities?.failedResponseRecovery &&
          globalThis.PAPClaudeLastResponseRecovery?.snapshot
        );
        const recoveryState = canRecover
          ? globalThis.PAPClaudeLastResponseRecovery.snapshot()
          : null;

        let recoveryDetail = 'Ожидаю, пока чат снова станет готов.';
        if (responseDidNotLoad && recoveryState) {
          if (recoveryState.refreshAttempted) {
            if (recoveryState.replayQueued) {
              recoveryDetail = 'Refresh уже был выполнен один раз. Восстанавливаю тот же текст и те же файлы.';
            } else if (recoveryState.replayRequested) {
              recoveryDetail = 'Refresh уже был выполнен один раз. Запрашиваю восстановление текста и файлов.';
            } else {
              const seconds = Math.max(0, Math.ceil(Number(recoveryState.replayDelayRemainingMs || 0) / 1000));
              recoveryDetail = `Refresh уже был выполнен один раз. Повторная вставка через ~${seconds} сек.`;
            }
            if (recoveryState.lastReplayError) recoveryDetail += `\nПоследняя попытка восстановления: ${recoveryState.lastReplayError}`;
          } else if (Number(recoveryState.refreshCooldownRemainingMs || 0) > 0) {
            recoveryDetail = `Жду ограничение refresh: ~${Math.ceil(Number(recoveryState.refreshCooldownRemainingMs || 0) / 1000)} сек.`;
          } else {
            recoveryDetail = 'Сейчас будет выполнен один автоматический refresh.';
          }
        }

        const body = responseDidNotLoad
          ? `Последний ответ ${label} не загрузился. Парсинг и DONE запрещены.\n${recoveryDetail}`
          : latestIsUser
            ? `Последнее сообщение пользовательское. Ожидаю завершённый ответ ${label}…`
            : `${label} ещё формирует ответ.\nСигналы: ${snapshot.signals.join(', ') || 'WAITING'}`;

        const stage = responseDidNotLoad ? 'WAITING_RESPONSE_RECOVERY' : 'WAITING_CHAT';
        const reason = responseDidNotLoad ? 'LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD' : 'CHAT_RESPONSE_NOT_COMPLETE';
        const uiKey = `${stage}:${body}`;

        if (uiKey !== lastUiKey) {
          lastUiKey = uiKey;
          await setStatus({state:'RUNNING', stage, reason, readinessSignals:snapshot.signals, chatType:snapshot.chatInfo?.type, url:location.href});
          showOverlay(parserTitle(responseDidNotLoad ? 'RECOVERY' : 'WAITING'), body, responseDidNotLoad ? 'info' : undefined);
        }

        await readinessTick();
        continue;
      }

      const fingerprint = assistantRowFingerprint(snapshot.assistantRow);
      if (fingerprint !== lastFingerprint) {
        lastFingerprint = fingerprint;
        stableSince = Date.now();
      } else if (!stableSince) {
        stableSince = Date.now();
      }

      const stableFor = Date.now() - stableSince;
      if (stableFor >= quietMs) {
        await setStatus({state:'RUNNING', stage:'CHAT_READY', readinessQuietMs:quietMs, chatType:snapshot.chatInfo?.type, url:location.href});
        showOverlay(parserTitle('READY'), `Ответ ${label} завершён.\nDOM стабилен ${quietMs} ms.\nНачинаю разбор.`);
        return snapshot.assistantRow;
      }

      const uiKey = 'WAITING_DOM';
      if (uiKey !== lastUiKey) {
        lastUiKey = uiKey;
        await setStatus({state:'RUNNING', stage:'WAITING_DOM', readinessQuietMs:quietMs, chatType:snapshot.chatInfo?.type, url:location.href});
        showOverlay(parserTitle('WAITING'), `Стриминг завершён. Жду стабильный DOM ${quietMs} ms…`);
      }

      await readinessTick();
    }
  };

  const armPageCapture = (expectedName, timeoutMs) => {
    const captureId = crypto.randomUUID();
    let armedResolve;
    let armedReject;
    const armedPromise = new Promise((resolve, reject) => {
      armedResolve = resolve;
      armedReject = reject;
    });

    const promise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const waiter = state.captureWaiters.get(captureId);
        if (waiter?.armTimer) clearTimeout(waiter.armTimer);
        state.captureWaiters.delete(captureId);
        window.postMessage({ source: SOURCE_CONTENT, type: "CANCEL_DOWNLOAD_CAPTURE", captureId }, "*");
        armedReject(new Error("FILE_CAPTURE_ARM_TIMEOUT"));
        reject(new Error("FILE_CAPTURE_TIMEOUT"));
      }, Math.max(1000, Number(timeoutMs) || 60000));

      const armTimer = setTimeout(() => {
        const waiter = state.captureWaiters.get(captureId);
        if (!waiter || waiter.armed) return;
        clearTimeout(waiter.timer);
        state.captureWaiters.delete(captureId);
        window.postMessage({ source: SOURCE_CONTENT, type: "CANCEL_DOWNLOAD_CAPTURE", captureId }, "*");
        const error = new Error("FILE_CAPTURE_ARM_TIMEOUT");
        armedReject(error);
        reject(error);
      }, Math.max(500, Math.min(3000, Number(timeoutMs) || 60000)));

      state.captureWaiters.set(captureId, {
        resolve,
        reject,
        timer,
        armTimer,
        armed:false,
        armedResolve,
        armedReject
      });
    });

    window.postMessage({
      source: SOURCE_CONTENT,
      type: "ARM_DOWNLOAD_CAPTURE",
      captureId,
      expectedName: expectedName || ""
    }, "*");

    return { captureId, promise, armedPromise };
  };

  const cancelPageCapture = (captureId, reason = "CAPTURE_CANCELLED") => {
    const waiter = state.captureWaiters.get(captureId);
    if (waiter) {
      clearTimeout(waiter.timer);
      clearTimeout(waiter.armTimer);
      state.captureWaiters.delete(captureId);
      const error = new Error(reason);
      waiter.armedReject?.(error);
      waiter.reject(error);
    }
    window.postMessage({ source: SOURCE_CONTENT, type: "CANCEL_DOWNLOAD_CAPTURE", captureId }, "*");
  };

  const armBrowserDownload = async (expectedName) => {
    const response = await sendMessage({
      type: "ARM_BROWSER_DOWNLOAD",
      expectedName,
      startTimeoutMs: state.settings.downloadStartTimeoutMs,
      stallTimeoutMs: state.settings.downloadStallTimeoutMs
    });

    if (!response?.ok || !response.watchId) {
      throw new Error(response?.error || "DOWNLOAD_WATCH_ARM_FAILED");
    }

    const promise = new Promise((resolve, reject) => {
      const heartbeatTimer = setInterval(() => {
        sendMessage({ type: "DOWNLOAD_WATCH_HEARTBEAT", watchId: response.watchId }).catch(() => {});
      }, 5000);
      state.downloadWaiters.set(response.watchId, { resolve, reject, heartbeatTimer });
    });

    return { watchId: response.watchId, promise };
  };

  const cancelBrowserDownload = async (watchId) => {
    const waiter = state.downloadWaiters.get(watchId);
    if (waiter) {
      clearInterval(waiter.heartbeatTimer);
      state.downloadWaiters.delete(watchId);
      waiter.reject(new Error("DOWNLOAD_WATCH_CANCELLED"));
    }
    try {
      await sendMessage({ type: "CANCEL_BROWSER_DOWNLOAD", watchId });
    } catch (_) {}
  };

  const sha256Hex = async (buffer) => {
    const digest = await crypto.subtle.digest("SHA-256", buffer);
    return [...new Uint8Array(digest)].map((b) => b.toString(16).padStart(2, "0")).join("");
  };

  const uploadBytesToBackground = async ({ runId, fileName, mimeType, buffer, sha256 }) => {
    const port = chrome.runtime.connect({ name: "pap-file-transfer" });
    const transferId = crypto.randomUUID();
    const bytes = new Uint8Array(buffer);
    const chunkSize = 4 * 1024 * 1024;
    const chunkWaiters = new Map();
    let readyResolve;
    let readyReject;
    let resultResolve;
    let resultReject;
    let settled = false;

    const readyPromise = new Promise((resolve, reject) => {
      readyResolve = resolve;
      readyReject = reject;
    });
    const resultPromise = new Promise((resolve, reject) => {
      resultResolve = resolve;
      resultReject = reject;
    });

    const failAll = (error) => {
      if (settled) return;
      settled = true;
      const err = error instanceof Error ? error : new Error(String(error || "FILE_UPLOAD_FAILED"));
      readyReject(err);
      resultReject(err);
      for (const waiter of chunkWaiters.values()) waiter.reject(err);
      chunkWaiters.clear();
    };

    port.onMessage.addListener((message) => {
      if (message?.transferId !== transferId) return;

      if (message.type === "FILE_TRANSFER_READY") {
        readyResolve(message);
        return;
      }

      if (message.type === "FILE_CHUNK_ACK") {
        const waiter = chunkWaiters.get(message.chunkIndex);
        if (waiter) {
          chunkWaiters.delete(message.chunkIndex);
          if (message.ok === false) waiter.reject(new Error(message.error || "FILE_CHUNK_FAILED"));
          else waiter.resolve(message);
        }
        return;
      }

      if (message.type === "FILE_UPLOAD_RESULT") {
        if (message.result?.ok) {
          settled = true;
          resultResolve(message.result);
        } else {
          failAll(new Error(message.result?.error || "FILE_UPLOAD_FAILED"));
        }
      }
    });

    port.onDisconnect.addListener(() => {
      if (!settled) {
        failAll(new Error(chrome.runtime.lastError?.message || "FILE_TRANSFER_PORT_DISCONNECTED"));
      }
    });

    try {
      port.postMessage({
        type: "BEGIN_FILE_TRANSFER",
        transferId,
        runId,
        fileName,
        mimeType: mimeType || "application/octet-stream",
        sha256,
        totalBytes: bytes.byteLength
      });

      await readyPromise;

      let chunkIndex = 0;
      for (let offset = 0; offset < bytes.byteLength; offset += chunkSize, chunkIndex++) {
        const chunk = bytes.subarray(offset, Math.min(offset + chunkSize, bytes.byteLength));
        const ackPromise = new Promise((resolve, reject) => {
          chunkWaiters.set(chunkIndex, { resolve, reject });
        });
        port.postMessage({
          type: "FILE_CHUNK",
          transferId,
          chunkIndex,
          offset,
          base64: bytesToBase64(chunk)
        });
        await ackPromise;
      }

      port.postMessage({ type: "END_FILE_TRANSFER", transferId });
      return await resultPromise;
    } finally {
      try { port.disconnect(); } catch (_) {}
    }
  };

  const processOneFile = async (target, index, total, runId, token) => {
    const name = target.meta.name || target.meta.download.ariaLabel?.replace(/^Download\s+/i, "") || `file-${index + 1}`;
    const expectedDownloadName = basenameFromProtocolPath(target.requiredPath) || name;
    const adapter = currentAdapter();
    let preparedSession = null;
    let browserWatch = null;
    let pageCapture = null;

    await assertAllowed();
    if (token !== state.runToken) throw new Error("RUN_CANCELLED");

    state.activeFile = {
      index: index + 1,
      total,
      name,
      browserBytes: 0,
      browserTotalBytes: 0,
      uploadBytes: 0,
      uploadTotalBytes: 0
    };

    log(`FILE ${index + 1}/${total}: preparing`, {name, binding:target.binding || null, commandId:target.commandId ?? null});
    await setStatus({
      state: "RUNNING",
      stage: "DOWNLOAD_FILE",
      currentFile: name,
      currentFileIndex: index + 1,
      expectedFiles: total,
      fileBytesReceived: 0,
      fileTotalBytes: 0
    });
    showOverlay(parserTitle("RUNNING"), `Файл ${index + 1}/${total}\n${name}\nПодготовка скачивания…`);

    try {
      // Arm both browser-level and page-level capture before a provider-specific
      // activation click. ChatGPT first opens an artifact preview and fetches
      // the sandbox file at that moment; the actual Download button is inside
      // the preview. Arming here preserves that first, highly useful response.
      browserWatch = await armBrowserDownload(expectedDownloadName);
      const browserSettled = browserWatch.promise.then(
        (value) => ({ ok: true, value }),
        (error) => ({ ok: false, error })
      );
      const armFreshPageCapture = async () => {
        pageCapture = armPageCapture(expectedDownloadName, state.settings.captureTimeoutMs);
        await pageCapture.armedPromise;
        captureOutcome = null;
        captureSettled = pageCapture.promise.then(
          (value) => {
            captureOutcome = { ok: true, value };
            return captureOutcome;
          },
          (error) => {
            captureOutcome = { ok: false, error };
            return captureOutcome;
          }
        );
      };

      let captureOutcome = null;
      let captureSettled = null;
      await armFreshPageCapture();

      if (adapter?.prepareArtifactDownload) {
        preparedSession = await adapter.prepareArtifactDownload(target.artifact, {
          expectedDownloadName,
          timeoutMs: state.settings.downloadStartTimeoutMs
        });
        if (preparedSession && Object.prototype.hasOwnProperty.call(preparedSession, 'button')) {
          target.button = preparedSession.button || null;
        }
        log(`FILE ${index + 1}/${total}: adapter prepared download`, {
          activated:Boolean(preparedSession?.activated),
          activationMode:preparedSession?.activationMode || null,
          previewLabel:preparedSession?.previewLabel || null
        });
      }

      let browserResult;
      let captureResult;
      let acquisitionSource = null;
      let activationBrowserCompletedWithoutUrl = false;

      const useCaptured = async (captured, source) => {
        if (!captured?.ok || !captured.value) return false;
        captureResult = captured.value;
        acquisitionSource = source;
        if (browserWatch?.watchId) {
          await cancelBrowserDownload(browserWatch.watchId).catch(() => {});
          browserWatch = null;
        }
        const capturedBytes = Number(captureResult.buffer?.byteLength || 0);
        browserResult = {
          ok:true,
          skipped:true,
          source,
          fileName:captureResult.fileName || name,
          finalUrl:captureResult.url || null,
          bytesReceived:capturedBytes,
          totalBytes:capturedBytes || null,
          state:'captured'
        };
        return true;
      };

      const useBrowser = async (browser, source) => {
        if (!browser?.ok || !browser.value?.ok) return false;
        browserResult = browser.value;
        acquisitionSource = source;
        if (/^https?:/i.test(browserResult?.finalUrl || '')) {
          if (pageCapture?.captureId) {
            cancelPageCapture(pageCapture.captureId, 'USING_CHROME_FINAL_URL');
            pageCapture = null;
          }
          captureResult = {
            kind:'url',
            sourceKind:'chrome-download-final-url',
            fileName:browserResult.fileName || name,
            mimeType:null,
            url:browserResult.finalUrl
          };
          return true;
        }
        return false;
      };

      if (preparedSession?.requiresExplicitDownloadClick) {
        // Opening ChatGPT's text/markdown artifact preview performs its own
        // interpreter/download -> estuary/content request. That request is
        // useful for preview rendering, but it is not proof that the user-facing
        // Download action ran. Discard the provisional capture, re-arm capture,
        // wait for the Download control inside this exact flyout, then click it.
        // This also prevents a stale global "Download file" button elsewhere on
        // the page from being mistaken for the preview control.
        if (pageCapture?.captureId) {
          cancelPageCapture(pageCapture.captureId, 'REARM_FOR_PREVIEW_DOWNLOAD');
        }
        await armFreshPageCapture();
      } else if (preparedSession?.activationMayCapture) {
        const graceMs = Math.max(
          250,
          Math.min(
            Number(preparedSession.captureGraceMs) || 6000,
            Number(state.settings.downloadStartTimeoutMs) || 15000
          )
        );
        const activationWinner = await Promise.race([
          captureSettled.then((result) => ({kind:'capture', result})),
          browserSettled.then((result) => ({kind:'browser', result})),
          sleep(graceMs).then(() => ({kind:'timeout', result:null}))
        ]);

        if (activationWinner.kind === 'capture') {
          await useCaptured(activationWinner.result, 'provider-activation-page-capture');
        } else if (activationWinner.kind === 'browser') {
          const used = await useBrowser(activationWinner.result, 'provider-activation-browser-download');
          activationBrowserCompletedWithoutUrl = Boolean(
            !used && activationWinner.result?.ok && activationWinner.result?.value?.ok
          );
        }
      }

      if (!captureResult && activationBrowserCompletedWithoutUrl) {
        const captured = captureOutcome || await captureSettled;
        if (!(await useCaptured(captured, 'provider-activation-browser-then-page-capture'))) {
          throw captured?.error || new Error(`FILE_CAPTURE_REQUIRED_AFTER_PROVIDER_ACTIVATION: ${name}`);
        }
      }

      if (!captureResult) {
        if ((!target.button || preparedSession?.requiresExplicitDownloadClick) && adapter?.resolvePreparedDownloadButton) {
          target.button = await adapter.resolvePreparedDownloadButton(preparedSession, target.artifact, {
            expectedDownloadName,
            timeoutMs:preparedSession?.requiresExplicitDownloadClick
              ? Math.max(30000, Number(state.settings.downloadStartTimeoutMs) || 15000)
              : Math.min(2500, Number(state.settings.downloadStartTimeoutMs) || 15000)
          });
          if (target.button) {
            log(`FILE ${index + 1}/${total}: late provider Download control resolved`, {
              activationMode:preparedSession?.activationMode || null,
              ariaLabel:target.button.getAttribute?.('aria-label') || null
            });
          }
        }

        if (!target.button) {
          throw new Error(`DOWNLOAD_BUTTON_NOT_FOUND: ${target.requiredPath || name}`);
        }

        log(`FILE ${index + 1}/${total}: click Download`, name);
        target.button.click();

        const first = await Promise.race([
          browserSettled.then((result) => ({kind:'browser', result})),
          captureSettled.then((result) => ({kind:'capture', result}))
        ]);

        let firstUsed = false;
        if (first.kind === 'capture') {
          firstUsed = await useCaptured(first.result, 'download-click-page-capture');
        } else {
          firstUsed = await useBrowser(first.result, 'download-click-browser-download');
        }

        if (!firstUsed) {
          const second = first.kind === 'capture'
            ? await browserSettled.then((result) => ({kind:'browser', result}))
            : await captureSettled.then((result) => ({kind:'capture', result}));

          if (second.kind === 'capture') {
            if (!(await useCaptured(second.result, 'download-click-page-capture-fallback'))) {
              throw second.result?.error || first.result?.error || new Error(`FILE_ACQUISITION_FAILED: ${name}`);
            }
          } else if (!(await useBrowser(second.result, 'download-click-browser-download-fallback'))) {
            throw second.result?.error || first.result?.error || new Error(`FILE_ACQUISITION_FAILED: ${name}`);
          }
        }
      }

      if (!captureResult && browserResult?.ok && !/^https?:/i.test(browserResult?.finalUrl || '')) {
        const captured = captureOutcome || await captureSettled;
        if (!(await useCaptured(captured, 'browser-complete-page-capture'))) {
          throw captured?.error || new Error(`FILE_CAPTURE_REQUIRED_AFTER_BROWSER_DOWNLOAD: ${name}`);
        }
      }

      log(`FILE ${index + 1}/${total}: acquisition complete`, {
        acquisitionSource,
        browser:browserResult,
        captureKind:captureResult?.kind || null,
        captureSource:captureResult?.sourceKind || null,
        captureFileName:captureResult?.fileName || null,
        captureBytes:captureResult?.buffer?.byteLength ?? null,
        captureUrl:captureResult?.url || null
      });

      await assertAllowed();
      if (token !== state.runToken) throw new Error("RUN_CANCELLED");

      const basename = (value) => String(value || "").split(/[\\/]/).pop() || "";
      const downloadedName = basename(captureResult?.fileName) || basename(browserResult?.fileName) || name;
      const transferName = basename(expectedDownloadName) || downloadedName;
      const browserBytes = Number(browserResult?.bytesReceived || 0);
      const browserReportedTotal = Number(browserResult?.totalBytes || 0);
      const browserFileSize = Number(browserResult?.fileSize || 0);
      const browserTotal = browserFileSize > 0
        ? browserFileSize
        : (browserReportedTotal > 0 ? browserReportedTotal : (browserBytes > 0 ? browserBytes : 0));

      await setStatus({
        state: "RUNNING",
        stage: "UPLOAD_FILE",
        currentFile: transferName,
        currentFileIndex: index + 1,
        expectedFiles: total,
        fileBytesReceived: browserBytes,
        fileTotalBytes: browserTotal,
        uploadBytesConfirmed: 0
      });
      showOverlay(
        parserTitle("RUNNING"),
        `Файл ${index + 1}/${total}\n${transferName}\nЛокально скачан: ${formatProgress(browserBytes, browserTotal)}\nПередача на сервер: 0 B`
      );

      if (captureResult.kind === "bytes") {
        if (!(captureResult.buffer instanceof ArrayBuffer) || captureResult.buffer.byteLength === 0) {
          throw new Error(`CAPTURED_FILE_EMPTY: ${name}`);
        }

        const sha256 = await sha256Hex(captureResult.buffer);
        log(`FILE ${index + 1}/${total}: uploading captured bytes`, { fileName: transferName, bytes: captureResult.buffer.byteLength, sha256 });
        const uploadResult = await uploadBytesToBackground({
          runId,
          fileName: transferName,
          mimeType: captureResult.mimeType || "application/octet-stream",
          buffer: captureResult.buffer,
          sha256
        });

        log(`FILE ${index + 1}/${total}: upload confirmed`, uploadResult);
        return {
          name: transferName,
          downloadedName,
          browser: browserResult,
          capture: {
            kind: "bytes",
            sourceKind: captureResult.sourceKind,
            byteLength: captureResult.buffer.byteLength,
            sha256
          },
          upload: uploadResult
        };
      }

      if (captureResult.kind === "url" && captureResult.url) {
        log(`FILE ${index + 1}/${total}: streaming refetch/upload by URL`, captureResult.url);
        const transferHeartbeat = setInterval(() => {
          sendMessage({ type: "TRANSFER_HEARTBEAT" }).catch(() => {});
        }, 10000);
        let response;
        try {
          response = await sendMessage({
            type: "UPLOAD_FILE_FROM_URL",
            payload: {
              runId,
              fileName: transferName,
              mimeType: captureResult.mimeType || null,
              url: captureResult.url,
              totalBytes: browserTotal > 0 ? browserTotal : null
            }
          });
        } finally {
          clearInterval(transferHeartbeat);
        }

        if (!response?.ok) {
          throw new Error(response?.error || `FILE_URL_UPLOAD_FAILED: ${name}`);
        }

        log(`FILE ${index + 1}/${total}: URL upload confirmed`, response);
        return {
          name: transferName,
          downloadedName,
          browser: browserResult,
          capture: {
            kind: "url",
            sourceKind: captureResult.sourceKind,
            url: captureResult.url
          },
          upload: response
        };
      }

      throw new Error(`FILE_CAPTURE_UNSUPPORTED: ${name}`);
    } catch (error) {
      if (browserWatch?.watchId) {
        await cancelBrowserDownload(browserWatch.watchId).catch(() => {});
      }
      if (pageCapture?.captureId) {
        cancelPageCapture(pageCapture.captureId, "FILE_DOWNLOAD_FAILED");
      }
      throw error;
    } finally {
      if (adapter?.cleanupArtifactDownload && preparedSession) {
        try { await adapter.cleanupArtifactDownload(preparedSession); } catch (error) {
          log(`FILE ${index + 1}/${total}: preview cleanup warning`, String(error?.message || error));
        }
      }
    }
  };

  const reportRunStatus = async (runId, status, { bestEffort = false } = {}) => {
    if (!runId) return;
    try {
      const response = await sendMessage({
        type: "POST_RUN_STATUS",
        payload: {
          runId,
          ...status,
          page: location.href,
          chatType: currentChatInfo().type,
          chatLabel: currentChatInfo().label,
          clientTime: new Date().toISOString()
        }
      });
      if (!response?.ok) {
        throw new Error(response?.error || "STATUS_UPLOAD_FAILED");
      }
    } catch (error) {
      if (!bestEffort) throw error;
    }
  };

  const currentAssistantRowKey = () => {
    try {
      const snapshot = currentAdapter()?.inspectTurnState?.(document);
      if (!snapshot || snapshot.kind === "HUMAN") return "";
      return String(snapshot.rowKey || "");
    } catch {
      return "";
    }
  };

  const queueAutorunAfterCurrentRun = (reason, meta = {}) => {
    const rowKey = String(meta.rowKey || "");

    // Same turn currently being parsed -> duplicate scheduler event.
    if (
      rowKey &&
      (
        rowKey === state.activeAssistantRowKey ||
        rowKey === state.lastParsedAssistantRowKey
      )
    ) {
      log("AUTORUN DUPLICATE IGNORED WHILE RUNNING", {
        reason,
        rowKey,
        activeAssistantRowKey:state.activeAssistantRowKey,
        lastParsedAssistantRowKey:state.lastParsedAssistantRowKey
      });
      return;
    }

    // PAGE_COMPLETE / CONTENT_READY / TAB_ENABLED are lifecycle noise while an
    // actual parser run is active. They must never invalidate runToken.
    if (reason !== "CHAT_TURN_FINISHED" && reason !== "CLAUDE_TURN_FINISHED") {
      log("AUTORUN LIFECYCLE EVENT IGNORED WHILE RUNNING", {reason});
      return;
    }

    // A genuinely newer completed assistant turn is allowed to wait for the
    // current run. Latest wins; do not build an unbounded queue.
    state.pendingAutorun = {
      reason,
      meta:{
        turnKey:String(meta.turnKey || ""),
        rowKey,
        rowIndex:String(meta.rowIndex || "")
      }
    };

    log("AUTORUN QUEUED AFTER CURRENT RUN", state.pendingAutorun);
  };

  const runPipeline = async (reason = "AUTO", meta = {}) => {
    if (state.runInProgress) {
      return;
    }

    const token = ++state.runToken;
    state.runInProgress = true;
    state.activeAssistantRowKey =
      String(meta.rowKey || "") ||
      currentAssistantRowKey();

    let runId = null;
    let completedFiles = 0;
    let expectedFiles = 0;
    let fileErrors = [];

    try {
      await assertAllowed();
      await waitForLoad();

      const readyQuietMs =
        (reason === "CHAT_TURN_FINISHED" || reason === "CLAUDE_TURN_FINISHED")
          ? 600
          : 2500;

      await waitForChatReady(token, readyQuietMs);

      const liveReadyRowKey = currentAssistantRowKey();
      if (liveReadyRowKey) {
        state.activeAssistantRowKey = liveReadyRowKey;
      }

      // Re-check the shared DOM gate at the parse boundary.
      // Never rely on "page was refreshed" or "streaming=false" as proof.
      let parseBoundary = chatReadinessSnapshot();
      if (parseBoundary.signals.length) {
        await waitForChatReady(token, readyQuietMs);
        parseBoundary = chatReadinessSnapshot();
      }
      if (parseBoundary.signals.length) {
        throw new Error(
          `CHAT_NOT_PARSEABLE:${parseBoundary.signals.join(",")}`
        );
      }

      await setStatus({
        state: "RUNNING",
        stage: "PARSE",
        reason,
        error: null,
        url: location.href
      });
      showOverlay(parserTitle("RUNNING"), "Парсинг завершённого ответа…");

      const parsed = parsePage(state.settings.maxAssistantMessages);
      let requiredPlan = buildRequiredDownloadPlan(parsed.result, parsed.selectedRows);
      requiredPlan = await waitForRequiredDownloadButtons(requiredPlan, token);

      const targets = requiredPlan.targets;
      expectedFiles = requiredPlan.requiredPaths.length;
      fileErrors = [...requiredPlan.missingRequired];

      log("PARSE OK", {
        messages: parsed.result.scannedAssistantMessages,
        requiredFiles: expectedFiles,
        matchedArtifacts: targets.length,
        ignoredArtifacts: requiredPlan.ignoredArtifacts,
        unresolvedRequiredFiles: requiredPlan.missingRequired.length
      });

      parsed.result.fileTransfer = {
        expectedFiles,
        scope: "LATEST_ASSISTANT_COMMAND_PUT_FILES",
        failFast: false,
        retries: 0,
        progressAware: true,
        downloadStallTimeoutMs: state.settings.downloadStallTimeoutMs,
        uploadStallTimeoutMs: state.settings.uploadStallTimeoutMs,
        streamedUpload: true,
        requiredPaths: requiredPlan.requiredPaths,
        ignoredArtifacts: requiredPlan.ignoredArtifacts,
        unresolvedRequiredPaths: requiredPlan.missingRequired.map((entry) => entry.requiredPath)
      };

      await assertAllowed();

      await setStatus({
        state: "RUNNING",
        stage: "POST_JSON",
        parsedMessages: parsed.result.scannedAssistantMessages,
        expectedFiles,
        completedFiles: 0,
        failedFiles: fileErrors.length
      });

      showOverlay(
        parserTitle("RUNNING"),
        `Командный JSON готов.\n` +
        `Нужных файлов: ${expectedFiles}\n` +
        `Найдено карточек: ${targets.length}\n` +
        `Лишних артефактов игнорируется: ${requiredPlan.ignoredArtifacts}\n` +
        `Отправка JSON…`
      );

      // Final gate immediately before Receiver gets any parsed result.
      // If the chat remounted into a failed/incomplete state after parsing,
      // wait for recovery instead of publishing stale/empty data as DONE.
      let postBoundary = chatReadinessSnapshot();
      if (postBoundary.signals.length) {
        await waitForChatReady(token, readyQuietMs);
        postBoundary = chatReadinessSnapshot();
      }
      if (postBoundary.signals.length) {
        throw new Error(
          `CHAT_NOT_POSTABLE:${postBoundary.signals.join(",")}`
        );
      }

      log("POST JSON -> Python");
      const server = await sendMessage({
        type: "POST_PARSE_RESULT",
        payload: parsed.result
      });

      if (!server?.ok || !server.runId) {
        throw new Error(server?.error || "SERVER_DID_NOT_RETURN_RUN_ID");
      }

      runId = server.runId;
      log("POST JSON OK", { runId });

      await reportRunStatus(runId, {
        status: "FILES_PENDING",
        expectedFiles,
        completedFiles: 0,
        failedFiles: fileErrors.length,
        requiredPaths: requiredPlan.requiredPaths,
        fileErrors
      });

      const fileResults = [];

      const resolveLiveRequiredTarget = (originalTarget) => {
        const rows = currentAdapter()?.assistantRows?.(document) || [];
        const latestRow = rows.at(-1) || null;
        if (!latestRow) return originalTarget;

        const livePlan = buildRequiredDownloadPlan(parsed.result, [latestRow]);
        const liveTarget = livePlan.targets.find((candidate) =>
          candidate.requiredPath === originalTarget.requiredPath &&
          String(candidate.commandId ?? '') === String(originalTarget.commandId ?? '')
        ) || livePlan.targets.find((candidate) => candidate.requiredPath === originalTarget.requiredPath);

        if (liveTarget) {
          if (liveTarget.artifact !== originalTarget.artifact) {
            log('REBOUND REQUIRED FILE TO LIVE DOM', {
              requiredPath:originalTarget.requiredPath,
              previousConnected:Boolean(originalTarget.artifact?.isConnected),
              binding:liveTarget.binding || null
            });
          }
          return liveTarget;
        }

        return originalTarget;
      };

      for (let i = 0; i < targets.length; i++) {
        await assertAllowed();
        if (token !== state.runToken) throw new Error("RUN_CANCELLED");

        const target = resolveLiveRequiredTarget(targets[i]);

        try {
          if (!target.artifact?.isConnected) {
            throw new Error(`REQUIRED_ARTIFACT_STALE_AFTER_DOM_REMOUNT: ${target.requiredPath}`);
          }
          const result = await processOneFile(target, i, targets.length, runId, token);
          result.requiredPath = target.requiredPath;
          fileResults.push(result);
          completedFiles++;
          state.activeFile = null;

          await reportRunStatus(runId, {
            status: "FILES_PENDING",
            expectedFiles,
            completedFiles,
            failedFiles: fileErrors.length,
            lastFile: result.name,
            lastRequiredPath: target.requiredPath
          });
        } catch (fileError) {
          state.activeFile = null;

          const message = String(fileError?.message || fileError);
          const entry = {
            requiredPath: target.requiredPath,
            name: target.meta?.name || null,
            error: message
          };
          fileErrors.push(entry);

          log("REQUIRED FILE FAILED; CONTINUING", entry);

          await reportRunStatus(runId, {
            status: "FILES_PENDING",
            expectedFiles,
            completedFiles,
            failedFiles: fileErrors.length,
            lastRequiredPath: target.requiredPath,
            lastFileError: message,
            fileErrors
          }, { bestEffort: true });

          await setStatus({
            state: "RUNNING",
            stage: "FILE_WARNING",
            runId,
            expectedFiles,
            completedFiles,
            failedFiles: fileErrors.length,
            currentFile: target.meta?.name || basenameFromProtocolPath(target.requiredPath),
            error: null,
            fileWarning: message
          });

          showOverlay(
            parserTitle("FILE WARNING"),
            `Не удалось получить: ${target.requiredPath}\n` +
            `Ошибка: ${message}\n` +
            `Продолжаю остальные нужные файлы.`
          );
        }

        if (i < targets.length - 1) {
          await sleep(state.settings.downloadGapMs);
        }
      }

      const allRequiredFilesReady = completedFiles === expectedFiles;

      await reportRunStatus(runId, {
        status: "DONE",
        expectedFiles,
        completedFiles,
        failedFiles: fileErrors.length,
        allRequiredFilesReady,
        requiredPaths: requiredPlan.requiredPaths,
        fileErrors,
        files: fileResults.map((entry) => ({
          name: entry.name,
          requiredPath: entry.requiredPath,
          byteLength: entry.capture?.byteLength ?? entry.upload?.byteLength ?? null,
          sha256: entry.capture?.sha256 ?? entry.upload?.sha256 ?? null
        }))
      });

      await setStatus({
        state: "DONE",
        stage: fileErrors.length ? "DONE_WITH_FILE_WARNINGS" : "DONE",
        runId,
        completedFiles,
        expectedFiles,
        failedFiles: fileErrors.length,
        allRequiredFilesReady,
        fileErrors,
        error: null
      });

      showOverlay(
        fileErrors.length ? parserTitle("DONE WITH FILE WARNINGS") : parserTitle("DONE"),
        `Run: ${runId}\n` +
        `Нужных файлов получено: ${completedFiles}/${expectedFiles}\n` +
        `Лишних артефактов проигнорировано: ${requiredPlan.ignoredArtifacts}` +
        (fileErrors.length
          ? `\nНе получены: ${fileErrors.map((entry) => entry.requiredPath).join(", ")}`
          : ""),
        fileErrors.length ? "info" : "done"
      );

      if (state.activeAssistantRowKey) {
        state.lastParsedAssistantRowKey = state.activeAssistantRowKey;
      }

      console.log(`[PAP ${chatLabel()} Parser] DONE`, {
        runId,
        parsed: parsed.result,
        files: fileResults,
        fileErrors,
        allRequiredFilesReady,
        assistantRowKey:state.lastParsedAssistantRowKey
      });
    } catch (error) {
      const message = String(error?.message || error);
      const controlledCancellation =
        message === "RUN_CANCELLED" ||
        message === "TAB_NAVIGATED" ||
        message === "TAB_DISABLED_BY_USER" ||
        message === "UNSUPPORTED_URL";

      ++state.runToken;

      if (controlledCancellation) {
        await reportRunStatus(runId, {
          status:"CANCELLED",
          stage:state.currentStage || "CANCELLED",
          error:message,
          completedFiles,
          expectedFiles,
          fileErrors
        }, {bestEffort:true});

        await setStatus({
          state:"ARMED",
          stage:"CANCELLED",
          runId,
          completedFiles,
          expectedFiles,
          fileErrors,
          error:null,
          cancelReason:message
        });

        log("PROCESS CANCELLED", {reason:message});
      } else {
        await reportRunStatus(runId, {
          status: "ERROR",
          stage: state.currentStage || "STOPPED",
          error: message,
          completedFiles,
          expectedFiles,
          fileErrors
        }, { bestEffort: true });

        await setStatus({
          state: "ERROR",
          stage: state.currentStage || "STOPPED",
          runId,
          completedFiles,
          expectedFiles,
          fileErrors,
          error: message
        });

        showOverlay(
          parserTitle("STOPPED"),
          `Ошибка инфраструктуры/парсинга: ${message}\n` +
          `Получено нужных файлов: ${completedFiles}/${expectedFiles}`,
          "error"
        );

        console.error(`[PAP ${chatLabel()} Parser] PROCESS STOPPED`, error);
      }
    } finally {
      state.activeFile = null;
      state.runInProgress = false;
      state.activeAssistantRowKey = "";

      const pending = state.pendingAutorun;
      state.pendingAutorun = null;

      if (pending) {
        setTimeout(() => {
          scheduleAutorun(pending.reason, pending.meta).catch(() => {});
        }, 0);
      }
    }
  };

  const scheduleAutorun = async (reason, meta = {}) => {
    if (state.runInProgress) {
      queueAutorunAfterCurrentRun(reason, meta);
      return;
    }

    clearTimeout(state.scheduleTimer);
    state.scheduleTimer = null;

    const rowKey = String(meta.rowKey || "");
    if (
      rowKey &&
      rowKey === state.lastParsedAssistantRowKey
    ) {
      log("AUTORUN DUPLICATE COMPLETED TURN IGNORED", {reason, rowKey});
      return;
    }

    const token = ++state.runToken;
    const config = await sendMessage({ type: "GET_RUNTIME_CONFIG" });
    if (!config?.ok || token !== state.runToken) return;

    state.enabled = Boolean(config.enabled);
    state.supported = Boolean(config.supported);
    state.settings = config.settings;
    state.chatType = config.chatType || currentChatInfo().type;
    state.chatLabel = config.chatLabel || currentChatInfo().label;

    if (!state.enabled || !state.supported) {
      return;
    }

    // The configured delay starts only AFTER window.load has completed.
    await waitForLoad();
    if (token !== state.runToken) return;
    await assertAllowed();

    const initialReadiness = chatReadinessSnapshot();
    const responseDidNotLoad = initialReadiness.signals.includes(
      "LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD"
    );

    const isFinishedChatTurn = (reason === "CHAT_TURN_FINISHED" || reason === "CLAUDE_TURN_FINISHED");

    const delayMs = responseDidNotLoad
      ? 0
      : isFinishedChatTurn
        ? 0
        : Math.max(0, Number(state.settings.delayMs) || 0);

    if (responseDidNotLoad) {
      log("PAGE DOCUMENT LOADED BUT CHAT RESPONSE FAILED", {
        reason,
        url:location.href,
        readinessSignals:initialReadiness.signals
      });
      await setStatus({
        state:"RUNNING",
        stage:"WAITING_RESPONSE_RECOVERY",
        reason:"LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD",
        readinessSignals:initialReadiness.signals,
        url:location.href
      });
      showOverlay(
        parserTitle("RECOVERY"),
        "Документ браузера загрузился, но чат НЕ готов.\n" +
        "Последний блок: «This response didn’t load».\n" +
        "Парсер не будет считать страницу готовой и не отправит DONE."
      );
    } else if (isFinishedChatTurn) {
      log("CHAT TURN FINISHED; parser scheduled from DOM lifecycle", {
        reason,
        delayMs,
        url:location.href
      });
      await setStatus({
        state:"ARMED",
        stage:"TURN_FINISHED_READY",
        delayMs:0,
        reason:"CHAT_TURN_FINISHED",
        url:location.href
      });
      showOverlay(
        parserTitle("TURN READY"),
        `${chatLabel()} закончил очередной ответ внутри SPA-чата.\n` +
        "Полного refresh страницы НЕ было и он НЕ нужен.\n" +
        "Запускаю парсер нового assistant-блока."
      );
    } else {
      log("PAGE DOCUMENT LOADED; autorun armed", { reason, delayMs, url:location.href });
      await setStatus({
        state:"ARMED",
        stage:"WAIT_DELAY",
        delayMs,
        reason,
        url:location.href
      });
      showOverlay(
        parserTitle("ARMED"),
        `Документ браузера загрузился. Проверка готовности чата через ${delayMs} ms\n${location.href}`
      );
    }

    state.scheduleTimer = setTimeout(() => {
      state.scheduleTimer = null;
      if (token !== state.runToken) return;
      runPipeline(reason, meta).catch(() => {});
    }, delayMs);
  };

  window.addEventListener("message", (event) => {
    if (event.source !== window) return;
    const data = event.data;
    if (!data || data.source !== SOURCE_PAGE) return;

    if (data.type === "DOWNLOAD_CAPTURE_ARMED") {
      const waiter = state.captureWaiters.get(data.captureId);
      if (!waiter) return;
      waiter.armed = true;
      clearTimeout(waiter.armTimer);
      waiter.armTimer = null;
      waiter.armedResolve?.({ captureId:data.captureId });
      return;
    }

    if (data.type === "DOWNLOAD_CAPTURED") {
      const waiter = state.captureWaiters.get(data.captureId);
      if (!waiter) return;
      clearTimeout(waiter.timer);
      clearTimeout(waiter.armTimer);
      state.captureWaiters.delete(data.captureId);
      waiter.armedResolve?.({ captureId:data.captureId });
      waiter.resolve({
        kind: data.kind,
        sourceKind: data.sourceKind,
        fileName: data.fileName,
        mimeType: data.mimeType,
        url: data.url,
        buffer: data.buffer instanceof ArrayBuffer ? data.buffer : null
      });
      return;
    }

    if (data.type === "HOOK_ERROR") {
      const waiter = state.captureWaiters.get(data.captureId);
      if (!waiter) return;
      clearTimeout(waiter.timer);
      clearTimeout(waiter.armTimer);
      state.captureWaiters.delete(data.captureId);
      const error = new Error(data.error || "PAGE_HOOK_ERROR");
      waiter.armedReject?.(error);
      waiter.reject(error);
    }
  });

  chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
    if (message?.type === "BROWSER_DOWNLOAD_PROGRESS") {
      const active = state.activeFile;
      const progress = message.progress || {};
      if (active) {
        active.browserBytes = Number(progress.bytesReceived || 0);
        active.browserTotalBytes = Number(progress.totalBytes || 0);
        const titleName = progress.fileName ? String(progress.fileName).split(/[\\/]/).pop() : active.name;
        showOverlay(
          parserTitle("RUNNING"),
          `Файл ${active.index}/${active.total}\n${titleName}\nСкачивание: ${formatProgress(active.browserBytes, active.browserTotalBytes)}`
        );
        setStatus({
          state: "RUNNING",
          stage: "DOWNLOAD_FILE",
          currentFile: titleName,
          currentFileIndex: active.index,
          expectedFiles: active.total,
          fileBytesReceived: active.browserBytes,
          fileTotalBytes: active.browserTotalBytes
        }).catch(() => {});
      }
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "FILE_TRANSFER_PROGRESS") {
      const active = state.activeFile;
      if (active) {
        active.uploadBytes = Number(message.transferredBytes || 0);
        active.uploadTotalBytes = Number(message.totalBytes || 0);
        const label = message.phase === "SERVER_COMPLETE" ? "Передача на сервер завершена" : "Передача на сервер";
        showOverlay(
          parserTitle("RUNNING"),
          `Файл ${active.index}/${active.total}\n${message.fileName || active.name}\nЛокально скачан: ${formatProgress(active.browserBytes, active.browserTotalBytes)}\n${label}: ${formatProgress(active.uploadBytes, active.uploadTotalBytes)}`
        );
        setStatus({
          state: "RUNNING",
          stage: message.phase === "SERVER_COMPLETE" ? "UPLOAD_COMPLETE" : "UPLOAD_FILE",
          currentFile: message.fileName || active.name,
          currentFileIndex: active.index,
          expectedFiles: active.total,
          fileBytesReceived: active.browserBytes,
          fileTotalBytes: active.browserTotalBytes,
          uploadBytesConfirmed: active.uploadBytes,
          uploadTotalBytes: active.uploadTotalBytes
        }).catch(() => {});
      }
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "BROWSER_DOWNLOAD_RESULT") {
      const waiter = state.downloadWaiters.get(message.watchId);
      if (waiter) {
        clearInterval(waiter.heartbeatTimer);
        state.downloadWaiters.delete(message.watchId);
        if (message.result?.ok) waiter.resolve(message.result);
        else waiter.reject(new Error(message.result?.error || "BROWSER_DOWNLOAD_FAILED"));
      }
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "TAB_ENABLED") {
      scheduleAutorun("TAB_ENABLED").catch(() => {});
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "SCHEDULE_AUTORUN") {
      scheduleAutorun(
        message.reason || "PAGE_COMPLETE",
        {
          turnKey:String(message.turnKey || ""),
          rowKey:String(message.rowKey || ""),
          rowIndex:String(message.rowIndex || "")
        }
      ).catch(() => {});
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "RUN_NOW") {
      clearTimeout(state.scheduleTimer);
      state.scheduleTimer = null;
      ++state.runToken;
      sendMessage({ type: "GET_RUNTIME_CONFIG" }).then((config) => {
        state.enabled = Boolean(config?.enabled);
        state.supported = Boolean(config?.supported);
        state.settings = config?.settings || state.settings;
        state.chatType = config?.chatType || currentChatInfo().type;
        state.chatLabel = config?.chatLabel || currentChatInfo().label;
        runPipeline("MANUAL").catch(() => {});
      }).catch(() => {});
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "TAB_NAVIGATING") {
      clearTimeout(state.scheduleTimer);
      state.scheduleTimer = null;
      ++state.runToken;

      for (const [captureId, waiter] of state.captureWaiters.entries()) {
        clearTimeout(waiter.timer);
        clearTimeout(waiter.armTimer);
        const error = new Error("TAB_NAVIGATED");
        waiter.armedReject?.(error);
        waiter.reject(error);
        window.postMessage({ source: SOURCE_CONTENT, type: "CANCEL_DOWNLOAD_CAPTURE", captureId }, "*");
      }
      state.captureWaiters.clear();

      for (const [watchId, waiter] of state.downloadWaiters.entries()) {
        clearInterval(waiter.heartbeatTimer);
        waiter.reject(new Error("TAB_NAVIGATED"));
        sendMessage({ type: "CANCEL_BROWSER_DOWNLOAD", watchId }).catch(() => {});
      }
      state.downloadWaiters.clear();

      showOverlay(parserTitle("ARMED"), "Страница загружается. Текущий процесс отменён.");
      sendResponse({ ok: true });
      return;
    }

    if (message?.type === "TAB_DISABLED" || message?.type === "TAB_BECAME_UNSUPPORTED") {
      clearTimeout(state.scheduleTimer);
      state.scheduleTimer = null;
      ++state.runToken;
      state.enabled = false;

      for (const [captureId, waiter] of state.captureWaiters.entries()) {
        clearTimeout(waiter.timer);
        clearTimeout(waiter.armTimer);
        const error = new Error(message.type === "TAB_DISABLED" ? "TAB_DISABLED_BY_USER" : "UNSUPPORTED_URL");
        waiter.armedReject?.(error);
        waiter.reject(error);
        window.postMessage({ source: SOURCE_CONTENT, type: "CANCEL_DOWNLOAD_CAPTURE", captureId }, "*");
      }
      state.captureWaiters.clear();

      for (const [watchId, waiter] of state.downloadWaiters.entries()) {
        clearInterval(waiter.heartbeatTimer);
        waiter.reject(new Error(message.type === "TAB_DISABLED" ? "TAB_DISABLED_BY_USER" : "UNSUPPORTED_URL"));
        sendMessage({ type: "CANCEL_BROWSER_DOWNLOAD", watchId }).catch(() => {});
      }
      state.downloadWaiters.clear();

      if (message.type === "TAB_DISABLED") {
        showOverlay(parserTitle("OFF"), "Работа на этой вкладке отключена.");
        setTimeout(hideOverlay, 2500);
      } else {
        showOverlay(parserTitle("IDLE"), "Открыт неподдерживаемый URL. Ничего не выполняется.");
      }

      sendResponse({ ok: true });
      return;
    }
  });

  // On initial load we only arm if this concrete tab was explicitly enabled.
  sendMessage({ type: "GET_RUNTIME_CONFIG" }).then((config) => {
    if (!config?.ok) return;
    state.enabled = Boolean(config.enabled);
    state.supported = Boolean(config.supported);
    state.settings = config.settings;
    state.chatType = config.chatType || currentChatInfo().type;
    state.chatLabel = config.chatLabel || currentChatInfo().label;

    if (state.enabled && state.supported) {
      scheduleAutorun("CONTENT_READY").catch(() => {});
    }
  }).catch(() => {});
})();
