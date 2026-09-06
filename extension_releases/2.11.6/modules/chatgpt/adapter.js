(() => {
  'use strict';

  const registry = globalThis.PAPChatAdapters;
  if (!registry || registry.forType('chatgpt')) return;

  const utils = registry.utils;

  const SELECTORS = Object.freeze({
    composer:[
      '#prompt-textarea[contenteditable="true"]',
      '#prompt-textarea',
      'textarea[name="prompt-textarea"]',
      'div.ProseMirror[contenteditable="true"][role="textbox"]',
      'form [contenteditable="true"][role="textbox"]'
    ],
    turn:[
      'article[data-testid^="conversation-turn-"]',
      'article[data-turn]',
      '[data-testid^="conversation-turn-"]'
    ],
    assistantMessage:[
      '[data-message-author-role="assistant"]',
      '[data-role="assistant"]',
      '[data-message-author="assistant"]'
    ],
    userMessage:[
      '[data-message-author-role="user"]',
      '[data-role="user"]',
      '[data-message-author="user"]'
    ],
    messageContent:[
      '.markdown',
      '.prose',
      '[class*="markdown"]'
    ],
    sendButton:[
      '#composer-submit-button',
      'button[data-testid="send-button"]',
      'button[aria-label="Send prompt"]',
      'button[aria-label="Send message"]',
      'form button[type="submit"]'
    ],
    stopButton:[
      'button[data-testid="stop-button"]',
      'button[aria-label="Stop generating"]',
      'button[aria-label="Stop response"]'
    ],
    fileInput:[
      'input#upload-files[type="file"]',
      'input[type="file"][id*="upload-file"]',
      'input[type="file"]'
    ],
    streaming:[
      '[data-message-streaming="true"]',
      '.result-streaming',
      '[data-is-streaming="true"]'
    ],
    artifactDownloadButton:[
      'button[aria-label="Download file"]',
      'button[aria-label^="Download file" i]'
    ],
    previewRoot:[
      'section[data-testid="screen-threadFlyOut"]',
      '[data-testid="stage-thread-flyout-content"]'
    ],
    previewDownloadButton:[
      'button[aria-label="Download"]',
      'button[data-testid="download-button"][aria-label="Download"]',
      'button[data-testid="download-button"]',
      '[data-testid="stage-thread-flyout-content"] button[aria-label="Download"]'
    ],
    previewCloseButton:[
      'button[data-testid="close-button"][aria-label="Close"]',
      '[data-testid="stage-thread-flyout-content"] button[aria-label="Close"]'
    ]
  });

  function dedupeRows(nodes) {
    const seen = new Set();
    const rows = [];
    for (const node of nodes) {
      const row = node?.matches?.('article,[data-testid^="conversation-turn-"]')
        ? node
        : node?.closest?.('article[data-testid^="conversation-turn-"],article[data-turn],[data-testid^="conversation-turn-"]');
      if (!row || seen.has(row)) continue;
      seen.add(row);
      rows.push(row);
    }
    return rows;
  }

  function transcriptRows(doc = document) {
    for (const selector of SELECTORS.turn) {
      const rows = [...doc.querySelectorAll(selector)].filter((row) =>
        row.querySelector?.(SELECTORS.assistantMessage.join(',')) ||
        row.querySelector?.(SELECTORS.userMessage.join(',')) ||
        ['assistant','user'].includes(String(row.getAttribute?.('data-turn') || ''))
      );
      if (rows.length) return dedupeRows(rows);
    }

    return dedupeRows([
      ...doc.querySelectorAll(SELECTORS.assistantMessage.join(',')),
      ...doc.querySelectorAll(SELECTORS.userMessage.join(','))
    ]);
  }

  function rowRole(row) {
    const direct = String(row?.getAttribute?.('data-turn') || '').toLowerCase();
    if (direct === 'assistant' || direct === 'user') return direct;
    if (row?.querySelector?.(SELECTORS.assistantMessage.join(','))) return 'assistant';
    if (row?.querySelector?.(SELECTORS.userMessage.join(','))) return 'user';
    return 'unknown';
  }

  function assistantRows(doc = document) {
    return transcriptRows(doc).filter((row) => rowRole(row) === 'assistant');
  }

  function lastTranscriptRow(doc = document) {
    return transcriptRows(doc).at(-1) || null;
  }

  function rowKey(row) {
    if (!row) return '';
    const turnId = row.getAttribute?.('data-turn-id') || '';
    const testId = row.getAttribute?.('data-testid') || '';
    const messageId = row.querySelector?.('[data-message-id]')?.getAttribute?.('data-message-id') || '';
    if (turnId) return `turn:${turnId}`;
    if (messageId) return `message:${messageId}`;
    if (testId) return `testid:${testId}`;
    return `${rowRole(row)}:${simpleHash(String(row.textContent || '').slice(-1200))}`;
  }

  function rowMeta(row) {
    const testId = String(row?.getAttribute?.('data-testid') || '');
    const numeric = testId.match(/conversation-turn-(\d+)/i)?.[1] || null;
    return {
      dataIndex:numeric,
      rsIndex:null,
      fromTail:null,
      streaming:isStreaming(row) ? 'true' : 'false',
      lastMessage:row === lastTranscriptRow(document) ? 'true' : 'false',
      turnId:row?.getAttribute?.('data-turn-id') || null
    };
  }

  function findComposer(doc = document) {
    return utils.firstVisible(SELECTORS.composer, doc);
  }

  function composerRoot(composer) {
    return composer?.closest('form') ||
      composer?.closest('[data-type="unified-composer"]') ||
      composer?.parentElement?.parentElement ||
      document.body;
  }

  function findSendButton(composer) {
    const root = composerRoot(composer);
    const candidate = utils.firstVisible(SELECTORS.sendButton, root) || utils.firstVisible(SELECTORS.sendButton, document);
    if (!candidate || candidate.disabled || candidate.getAttribute('aria-disabled') === 'true') return null;
    return candidate;
  }

  function findFileInput(composer) {
    const root = composerRoot(composer);
    for (const selector of SELECTORS.fileInput) {
      const local = [...root.querySelectorAll(selector)].find((node) => !node.disabled);
      if (local) return local;
      const global = [...document.querySelectorAll(selector)].find((node) => !node.disabled);
      if (global) return global;
    }
    return null;
  }

  function isStreaming(row, doc = document) {
    if (!row) return false;
    if (SELECTORS.streaming.some((selector) => row.querySelector?.(selector))) return true;
    return Boolean(utils.firstVisible(SELECTORS.stopButton, doc));
  }

  function inspectParserGate(doc = document) {
    const row = lastTranscriptRow(doc);
    if (!row) return {blocked:true, reason:'NO_LAST_TRANSCRIPT_ROW', row:null, failure:null};
    if (rowRole(row) !== 'assistant') return {blocked:true, reason:'LAST_ROW_NOT_ASSISTANT', row, failure:null};
    if (isStreaming(row, doc)) return {blocked:true, reason:'ASSISTANT_STREAMING', row, failure:null};
    if (!findComposer(doc)) return {blocked:true, reason:'COMPOSER_NOT_READY', row, failure:null};
    return {blocked:false, reason:'OK', row, failure:null};
  }

  function inspectTurnState(doc = document) {
    const row = lastTranscriptRow(doc);
    if (!row) {
      return {kind:'NO_ROW', ready:false, busy:false, failed:false, row:null, rowKey:'', signals:['NO_LAST_TRANSCRIPT_ROW']};
    }

    const role = rowRole(row);
    const key = rowKey(row);
    if (role === 'user') {
      return {kind:'HUMAN', ready:false, busy:false, failed:false, row, rowKey:key, signals:['LAST_ROW_HUMAN']};
    }
    if (role !== 'assistant') {
      return {kind:'UNKNOWN', ready:false, busy:true, failed:false, row, rowKey:key, signals:['LAST_ROW_UNKNOWN_ROLE']};
    }

    const signals = [];
    if (isStreaming(row, doc)) signals.push('ASSISTANT_STREAMING');
    const composer = findComposer(doc);
    if (!composer) signals.push('COMPOSER_NOT_READY');
    const ready = signals.length === 0;
    return {
      kind:ready ? 'ASSISTANT_READY' : 'ASSISTANT_BUSY',
      ready,
      busy:!ready,
      failed:false,
      row,
      rowKey:key,
      composer,
      rowStreaming:ready ? 'false' : 'true',
      signals
    };
  }

  function messageContentRoots(row) {
    const assistant = row.querySelector?.(SELECTORS.assistantMessage.join(',')) || row;
    for (const selector of SELECTORS.messageContent) {
      const roots = [...assistant.querySelectorAll?.(selector) || []]
        .filter((root) => ![...assistant.querySelectorAll?.(selector) || []].some((other) => other !== root && other.contains(root)));
      if (roots.length) return roots;
    }
    return [assistant];
  }

  function isLikelyGeneratedFileLink(anchor) {
    if (!anchor?.matches?.('a[href]')) return false;
    const href = String(anchor.getAttribute('href') || anchor.href || '');
    const downloadName = String(anchor.getAttribute('download') || '');
    const text = utils.normalize(anchor.textContent || '');
    return Boolean(
      downloadName ||
      /^sandbox:/i.test(href) ||
      /\/backend-api\/(?:estuary|files|download)\//i.test(href) ||
      /(?:download|sandbox).*file/i.test(href) ||
      /\.[a-z0-9]{1,10}$/i.test(utils.basename(text))
    );
  }

  function isLikelyGeneratedFileButton(button) {
    if (!button?.matches?.('button')) return false;
    if (button.closest?.('pre,code,[aria-label="Response actions"]')) return false;
    const className = String(button.className || '');
    const text = utils.normalize(button.textContent || '');
    const aria = utils.normalize(button.getAttribute?.('aria-label') || '');
    if (/^Download file(?:\s|$)/i.test(aria)) return true;
    const hasFileIcon = Boolean(
      button.querySelector?.('[data-library-file-icon],svg[data-library-file-icon-kind],svg[data-library-file-icon-key]')
    );
    if (hasFileIcon) return true;
    if (!/\bentity-underline\b/.test(className)) return false;
    if (looksLikeFileName(text) || looksLikeFileName(aria)) return true;
    return Boolean(
      /\b(download|file|archive)\b/i.test(`${text} ${aria}`) ||
      /(скачать|файл|архив)/i.test(`${text} ${aria}`)
    );
  }

  function isDirectDownloadButton(button) {
    return Boolean(button?.matches?.('button') && /^Download file(?:\s|$)/i.test(
      utils.normalize(button.getAttribute?.('aria-label') || '')
    ));
  }

  function looksLikeFileName(value) {
    const text = utils.normalize(value || '');
    if (!text || text.length > 260) return false;
    return /(?:^|[^\s])\.[a-z0-9]{1,12}(?:\.[a-z0-9]{1,12})?$/i.test(text);
  }

  function nearbyArtifactName(control) {
    if (!control) return null;

    let node = control.parentElement;
    for (let depth = 0; node && depth < 7; depth++, node = node.parentElement) {
      const full = node.querySelector?.('[data-file-name-full-text]')?.getAttribute?.('data-file-name-full-text');
      if (looksLikeFileName(full)) return utils.normalize(full);

      const truncated = node.querySelector?.('[data-file-name-truncation-target][aria-label]')?.getAttribute?.('aria-label');
      if (looksLikeFileName(truncated)) return utils.normalize(truncated);

      for (const button of node.querySelectorAll?.('button[aria-label]') || []) {
        if (button === control) continue;
        const aria = utils.normalize(button.getAttribute?.('aria-label') || '');
        if (looksLikeFileName(aria)) return aria;
      }

      for (const candidate of node.querySelectorAll?.('span') || []) {
        const text = utils.normalize(candidate.textContent || '');
        if (looksLikeFileName(text)) return text;
      }
    }
    return null;
  }

  function artifactNodes(row) {
    const roots = messageContentRoots(row);
    const found = [];
    const seen = new Set();
    for (const root of roots) {
      for (const anchor of root.querySelectorAll?.('a[href]') || []) {
        if (!isLikelyGeneratedFileLink(anchor) || seen.has(anchor)) continue;
        seen.add(anchor);
        found.push(anchor);
      }
      for (const button of root.querySelectorAll?.('button') || []) {
        if (!isLikelyGeneratedFileButton(button) || seen.has(button)) continue;
        seen.add(button);
        found.push(button);
      }
    }
    return found.sort((a, b) => {
      if (a === b) return 0;
      const rel = a.compareDocumentPosition?.(b) || 0;
      if (rel & Node.DOCUMENT_POSITION_FOLLOWING) return -1;
      if (rel & Node.DOCUMENT_POSITION_PRECEDING) return 1;
      return 0;
    });
  }

  function logicalMessageNodes(row) {
    const nodes = new Set();
    for (const root of messageContentRoots(row)) {
      const children = root.children?.length ? [...root.children] : [root];
      for (const child of children) nodes.add(child);
    }
    for (const artifact of artifactNodes(row)) {
      const covered = [...nodes].some((node) => node !== artifact && node.contains?.(artifact));
      if (!covered) nodes.add(artifact);
    }
    return [...nodes];
  }

  function downloadControl(artifact) {
    if (!artifact) return null;
    if (artifact.matches?.('a[href]')) return artifact;
    if (isLikelyGeneratedFileButton(artifact)) return artifact;
    return artifact.querySelector?.('a[href],button[aria-label*="download" i]') || null;
  }

  function parseArtifact(artifact) {
    const control = downloadControl(artifact);
    const href = String(control?.href || control?.getAttribute?.('href') || '');
    const text = utils.normalize(control?.textContent || artifact?.textContent || '');
    const aria = utils.normalize(control?.getAttribute?.('aria-label') || '');
    const explicit = utils.normalize(control?.getAttribute?.('download') || '');
    const nearbyName = isDirectDownloadButton(control) ? nearbyArtifactName(control) : null;
    const ariaName = /^Download file(?:\s|$)/i.test(aria) ? '' : aria.replace(/^Download\s+/i, '');
    const candidate = explicit || nearbyName || ariaName || utils.basename(text) || utils.basename(href) || null;
    const extension = candidate?.match(/\.([A-Za-z0-9]{1,10})$/)?.[1]?.toUpperCase() || null;
    const activationRequired = Boolean(
      control?.matches?.('button') &&
      isLikelyGeneratedFileButton(control) &&
      !isDirectDownloadButton(control)
    );
    return {
      type:'FILE',
      name:candidate,
      fileKind:'chatgpt-generated-file',
      extension,
      download:{
        available:Boolean(control),
        text:text || null,
        ariaLabel:aria || null,
        url:href || null,
        urlAvailableInDOM:Boolean(href),
        activationRequired
      }
    };
  }

  function commandHeadingNodes(row) {
    const assistant = row?.querySelector?.(SELECTORS.assistantMessage.join(',')) || row;
    return [...(assistant?.querySelectorAll?.('h1,h2,h3,h4,h5,h6,p') || [])]
      .map((node) => {
        const text = utils.normalize(node.textContent || '');
        const match = text.match(/^(COMMAND_[A-Z0-9_]+)(?:\s+id\s*=\s*([A-Z0-9._:-]+))?\s*$/i);
        return match ? {node, type:match[1].toUpperCase(), commandId:match[2] || null} : null;
      })
      .filter(Boolean);
  }

  function bindRequiredArtifacts({row, requests, candidates}) {
    if (!row || !Array.isArray(requests) || !Array.isArray(candidates)) return [];
    const headings = commandHeadingNodes(row);
    const result = [];
    const usedArtifacts = new Set();
    const groups = new Map();
    for (const request of requests) {
      const key = String(request.commandId ?? '');
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(request);
    }

    for (const [commandKey, group] of groups.entries()) {
      if (!commandKey) continue;
      const headingIndex = headings.findIndex((entry) =>
        entry.type === 'COMMAND_PUT_FILES' && String(entry.commandId ?? '') === commandKey
      );
      if (headingIndex < 0) continue;
      const heading = headings[headingIndex].node;
      const previousHeading = headingIndex > 0 ? headings[headingIndex - 1].node : null;
      const local = candidates.filter((candidate) => {
        if (!candidate?.artifact || usedArtifacts.has(candidate.artifact)) return false;
        const beforeHeading = Boolean(candidate.artifact.compareDocumentPosition?.(heading) & Node.DOCUMENT_POSITION_FOLLOWING);
        if (!beforeHeading) return false;
        if (!previousHeading) return true;
        return Boolean(previousHeading.compareDocumentPosition?.(candidate.artifact) & Node.DOCUMENT_POSITION_FOLLOWING);
      });
      if (local.length < group.length) continue;

      const remaining = [...local];
      const selected = new Array(group.length).fill(null);

      // Prefer an exact visible filename when ChatGPT exposes one (for example
      // the artifact-row "Download file" control). Inline prose buttons such as
      // "этот архив" have no filename, so unmatched requests still fall back to
      // stable local DOM order below.
      group.forEach((request, index) => {
        const wanted = utils.normalize(utils.basename(request.requiredPath || '')).toLowerCase();
        if (!wanted) return;
        const matchIndex = remaining.findIndex((candidate) =>
          utils.normalize(utils.basename(candidate?.meta?.name || '')).toLowerCase() === wanted
        );
        if (matchIndex < 0) return;
        selected[index] = remaining.splice(matchIndex, 1)[0];
      });

      const unboundIndexes = selected
        .map((candidate, index) => candidate ? -1 : index)
        .filter((index) => index >= 0);
      const fallback = remaining.slice(-unboundIndexes.length);
      if (fallback.length !== unboundIndexes.length) continue;
      unboundIndexes.forEach((index, offset) => {
        selected[index] = fallback[offset];
      });

      group.forEach((request, index) => {
        const candidate = selected[index];
        if (!candidate) return;
        usedArtifacts.add(candidate.artifact);
        result.push({
          requestIndex:request.requestIndex,
          artifact:candidate.artifact,
          binding:'COMMAND_LOCAL_PRECEDING'
        });
      });
    }
    return result;
  }

  function visiblePreviewRoot(expectedName = '') {
    const wanted = utils.normalize(expectedName || '').toLowerCase();
    for (const selector of SELECTORS.previewRoot) {
      const roots = [...document.querySelectorAll(selector)]
        .filter((node) => utils.visible(node))
        .map((node) => {
          if (node.matches?.('section[aria-label]')) return node;
          const nested = [...(node.querySelectorAll?.('section[aria-label]') || [])].find((candidate) => utils.visible(candidate));
          return nested || node;
        });
      if (!roots.length) continue;
      if (!wanted) return roots.at(-1) || null;
      const exact = roots.find((node) => {
        const label = utils.normalize(node.getAttribute?.('aria-label') || '').toLowerCase();
        return label && (label === wanted || utils.basename(label) === utils.basename(wanted));
      });
      if (exact) return exact;
      return roots.at(-1) || null;
    }
    return null;
  }

  function visiblePreviewDownloadButton(preview = null) {
    const scope = preview || document;
    const button = utils.firstVisible(SELECTORS.previewDownloadButton, scope);
    if (!button || button.disabled || button.getAttribute('aria-disabled') === 'true') return null;
    return button;
  }

  function previewSession(preview, button = null) {
    if (!preview) return null;
    return {
      button,
      activated:true,
      activationMayCapture:true,
      captureGraceMs:0,
      requiresExplicitDownloadClick:true,
      preview,
      previewLabel:utils.normalize(preview?.getAttribute?.('aria-label') || '') || null,
      activationMode:button ? 'PREVIEW_READY' : 'PREVIEW_WAIT_DOWNLOAD'
    };
  }

  async function prepareArtifactDownload(artifact, options = {}) {
    if (!artifact) return {button:null, activated:false};
    if (artifact.matches?.('a[href]')) return {button:artifact, activated:false};
    if (!isLikelyGeneratedFileButton(artifact)) {
      return {button:downloadControl(artifact), activated:false};
    }

    if (isDirectDownloadButton(artifact)) {
      return {
        button:artifact,
        activated:false,
        activationMayCapture:false,
        directDownload:true,
        activationMode:'DIRECT_BUTTON'
      };
    }

    // Live ChatGPT currently has two behaviours for inline generated files:
    // some open an artifact preview, others start the real download immediately.
    // content.js arms page/browser capture before this activation click, so the
    // absence of a preview is not an error and must not discard a valid download.
    artifact.click();

    const timeoutMs = Math.max(1000, Number(options.timeoutMs) || 15000);
    const previewProbeMs = Math.max(250, Math.min(timeoutMs, Number(options.previewProbeMs) || 2500));
    const deadline = Date.now() + previewProbeMs;
    while (Date.now() < deadline) {
      const preview = visiblePreviewRoot(options.expectedDownloadName || '');
      if (preview) return previewSession(preview, visiblePreviewDownloadButton(preview));
      await new Promise((resolve) => setTimeout(resolve, 75));
    }

    return {
      button:null,
      activated:true,
      activationMayCapture:true,
      captureGraceMs:Math.max(1500, Math.min(timeoutMs, 8000)),
      preview:null,
      previewLabel:null,
      activationMode:'DIRECT_OR_LATE_PREVIEW'
    };
  }

  async function resolvePreparedDownloadButton(session, artifact, options = {}) {
    if (session?.button && session.button.isConnected && utils.visible(session.button) && !session.button.disabled) return session.button;

    const direct = isDirectDownloadButton(artifact) ? artifact : null;
    if (direct && direct.isConnected && utils.visible(direct)) return direct;

    const timeoutMs = Math.max(0, Number(options.timeoutMs) || 0);
    const deadline = Date.now() + timeoutMs;
    while (true) {
      const livePreview = session?.preview?.isConnected && utils.visible(session.preview)
        ? session.preview
        : visiblePreviewRoot(options.expectedDownloadName || session?.previewLabel || '');
      const previewButton = visiblePreviewDownloadButton(livePreview);
      if (previewButton) return previewButton;

      const control = downloadControl(artifact);
      if (control && control !== artifact && control.isConnected && utils.visible(control)) return control;

      if (Date.now() >= deadline) return null;
      await new Promise((resolve) => setTimeout(resolve, 75));
    }
  }

  async function cleanupArtifactDownload(session) {
    if (!session?.activated) return;
    const scope = session?.preview?.isConnected ? session.preview : document;
    const button = utils.firstVisible(SELECTORS.previewCloseButton, scope) || utils.firstVisible(SELECTORS.previewCloseButton, document);
    if (!button) return;
    try { button.click(); } catch {}
    const deadline = Date.now() + 2000;
    while (Date.now() < deadline) {
      if (!button.isConnected || !utils.visible(button)) return;
      await new Promise((resolve) => setTimeout(resolve, 50));
    }
  }

  function attachmentCandidates(root, doc = document) {
    const selectors = [
      '[data-testid*="attachment"]',
      '[data-testid*="file"]',
      '[data-state][aria-label*="file" i]',
      '[aria-label*="remove file" i]',
      '[aria-label*="remove attachment" i]'
    ];
    const scope = root || doc;
    const nodes = new Set();
    for (const selector of selectors) {
      for (const node of scope.querySelectorAll?.(selector) || []) {
        if (node.closest?.('article[data-testid^="conversation-turn-"]')) continue;
        nodes.add(node.closest?.('[data-testid*="attachment"], [data-testid*="file"]') || node);
      }
    }
    return [...nodes];
  }

  function exactFilenameInNode(node, fileName) {
    const wanted = utils.normalize(fileName).toLowerCase();
    if (!wanted || !node) return false;
    const values = [
      node.getAttribute?.('aria-label'),
      node.getAttribute?.('title'),
      node.textContent
    ].map((value) => utils.normalize(value).toLowerCase()).filter(Boolean);
    return values.some((value) => value === wanted || value.includes(wanted));
  }

  function findAttachmentCard(root, fileName, doc = document) {
    return attachmentCandidates(root, doc).find((node) => exactFilenameInNode(node, fileName)) || null;
  }

  function inspectAttachmentCard(card, fileName) {
    if (!card || !exactFilenameInNode(card, fileName)) {
      return {observed:false, pending:false, ready:false, token:'NO_CHATGPT_ATTACHMENT_CARD'};
    }
    const text = utils.normalize(card.textContent || '');
    const pending = Boolean(
      card.getAttribute?.('aria-busy') === 'true' ||
      /uploading|loading|processing/i.test(text) ||
      card.querySelector?.('[role="progressbar"], [aria-busy="true"]')
    );
    const removeControl = [...(card.querySelectorAll?.('button') || [])].some((button) =>
      /(remove|delete).*(file|attachment)|(file|attachment).*(remove|delete)/i.test(
        `${button.getAttribute('aria-label') || ''} ${button.title || ''}`
      )
    );
    const ready = Boolean(!pending && (removeControl || exactFilenameInNode(card, fileName)));
    return {observed:true, pending, ready, token:`${fileName}|${pending ? 'pending' : 'ready'}|${text}`.slice(0, 3000)};
  }

  function simpleHash(text) {
    let h = 2166136261;
    const s = String(text || '');
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return (h >>> 0).toString(16);
  }

  registry.register({
    type:'chatgpt',
    label:'ChatGPT',
    version:'1.4.1',
    selectors:SELECTORS,
    capabilities:Object.freeze({
      parser:true,
      delivery:true,
      attachments:true,
      generatedFileDownload:true,
      failedResponseRecovery:false
    }),
    assistantRows,
    transcriptRows,
    lastTranscriptRow,
    rowRole,
    rowKey,
    rowMeta,
    findComposer,
    composerRoot,
    findFileInput,
    findSendButton,
    logicalMessageNodes,
    artifactNodes,
    downloadControl,
    parseArtifact,
    bindRequiredArtifacts,
    prepareArtifactDownload,
    resolvePreparedDownloadButton,
    cleanupArtifactDownload,
    findAttachmentCard,
    inspectAttachmentCard,
    inspectParserGate,
    inspectTurnState
  });
})();
