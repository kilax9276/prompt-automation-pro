(() => {
  'use strict';

  const registry = globalThis.PAPChatAdapters;
  if (!registry || registry.forType('claude')) return;

  const utils = registry.utils;

  function assistantRows(doc = document) {
    return [...doc.querySelectorAll('[data-testid="transcript-row"][data-perf-row="assistant"]')];
  }

  function transcriptRows(doc = document) {
    return globalThis.PAPClaudeDomSignals?.transcriptRows?.(doc) ||
      [...doc.querySelectorAll('[data-testid="transcript-row"]')];
  }

  function lastTranscriptRow(doc = document) {
    return globalThis.PAPClaudeDomSignals?.lastTranscriptRow?.(doc) ||
      transcriptRows(doc).at(-1) || null;
  }

  function rowRole(row) {
    const role = String(row?.getAttribute?.('data-perf-row') || '');
    if (role === 'human') return 'user';
    if (role === 'assistant') return 'assistant';
    return role || 'unknown';
  }

  function rowKey(row) {
    return globalThis.PAPClaudeDomSignals?.assistantRowKey?.(row) || [
      row?.getAttribute?.('data-index') || '',
      row?.getAttribute?.('data-rs-index') || '',
      rowRole(row)
    ].join(':');
  }

  function rowMeta(row) {
    return {
      dataIndex: row?.getAttribute?.('data-index') ?? null,
      rsIndex: row?.getAttribute?.('data-rs-index') ?? null,
      fromTail: row?.getAttribute?.('data-perf-row-from-tail') ?? null,
      streaming: row?.getAttribute?.('data-perf-row-streaming') ?? null,
      lastMessage: row?.getAttribute?.('data-last-message') ?? null,
      turnId:null
    };
  }

  function findComposer(doc = document) {
    return globalThis.PAPClaudeDomSignals?.findComposer?.(doc) || utils.lastVisible([
      '[data-testid="chat-input"][contenteditable="true"][data-cds="Editor"]',
      '[data-testid="chat-input"][contenteditable="true"]',
      'div.ProseMirror[contenteditable="true"]',
      '[contenteditable="true"][role="textbox"]',
      'textarea'
    ], doc);
  }

  function composerRoot(composer) {
    return composer?.closest('form') ||
      composer?.closest('[data-testid*="composer"]') ||
      composer?.parentElement?.parentElement ||
      document.body;
  }

  function findFileInput(composer) {
    const root = composerRoot(composer);
    return [
      ...root.querySelectorAll('input[type="file"]'),
      ...document.querySelectorAll('input[type="file"]')
    ].find((node) => !node.disabled) || null;
  }

  function findSendButton(composer) {
    const root = composerRoot(composer);
    return [...root.querySelectorAll('button')].find((button) => {
      const key = `${button.getAttribute('aria-label') || ''} ${button.getAttribute('data-testid') || ''} ${button.title || ''} ${button.textContent || ''}`;
      return /(send|отправ)/i.test(key) && !button.disabled && button.getAttribute('aria-disabled') !== 'true';
    }) || null;
  }

  function logicalMessageNodes(row) {
    const nodes = new Set();
    const proseElements = [...row.querySelectorAll('[data-cds="Prose"]')];

    for (const prose of proseElements) {
      let roots = [...prose.querySelectorAll('.standard-markdown, .progressive-markdown')];
      roots = roots.filter((root) => !roots.some((other) => other !== root && other.contains(root)));
      if (!roots.length) roots = prose.firstElementChild ? [prose.firstElementChild] : [prose];
      for (const root of roots) for (const child of root.children) nodes.add(child);
    }

    for (const artifact of artifactNodes(row)) {
      const covered = [...nodes].some((node) => node !== artifact && node.contains?.(artifact));
      if (!covered) nodes.add(artifact);
    }

    return [...nodes];
  }

  function artifactNodes(row) {
    return [...(row?.querySelectorAll?.('[data-sheet-kind]') || [])];
  }

  function downloadControl(artifact) {
    return [...(artifact?.querySelectorAll?.('button') || [])].find((button) =>
      /^Download\s+(?!all\b)/i.test(utils.normalize(button.getAttribute('aria-label')))
    ) || null;
  }

  function parseArtifact(artifact) {
    const buttons = [...artifact.querySelectorAll('button')];
    const viewButton = buttons.find((button) => /^View\s+/i.test(utils.normalize(button.getAttribute('aria-label'))));
    const button = downloadControl(artifact);
    const name =
      utils.normalize(artifact.querySelector('.text-heading')?.textContent) ||
      utils.normalize(viewButton?.getAttribute('aria-label')?.replace(/^View\s+/i, '')) ||
      utils.normalize(button?.getAttribute('aria-label')?.replace(/^Download\s+/i, '')) ||
      null;
    const extension = [...artifact.querySelectorAll('.text-footnote')]
      .map((element) => utils.normalize(element.textContent))
      .find((value) => /^[A-Z0-9]{1,10}$/i.test(value)) || null;

    return {
      type:'FILE',
      name,
      fileKind:artifact.getAttribute('data-sheet-kind') || null,
      extension,
      download:{
        available:Boolean(button),
        text:utils.normalize(button?.innerText) || null,
        ariaLabel:utils.normalize(button?.getAttribute('aria-label')) || null,
        url:null,
        urlAvailableInDOM:false
      }
    };
  }

  function findAttachmentCard(root, fileName, doc = document) {
    return globalThis.PAPClaudeAttachmentSignals?.findFileThumbnail?.(root, fileName, doc) || null;
  }

  function inspectAttachmentCard(card, fileName) {
    return globalThis.PAPClaudeAttachmentSignals?.inspectFileThumbnail?.(card, fileName) || {
      observed:false, pending:false, ready:false, token:'CLAUDE_ATTACHMENT_SIGNALS_UNAVAILABLE'
    };
  }

  registry.register({
    type:'claude',
    label:'Claude',
    version:'1.0.0',
    capabilities:Object.freeze({
      parser:true,
      delivery:true,
      attachments:true,
      generatedFileDownload:true,
      failedResponseRecovery:true
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
    findAttachmentCard,
    inspectAttachmentCard,
    inspectParserGate:(doc = document) => globalThis.PAPClaudeDomSignals?.inspectParserGate?.(doc) || {blocked:true, reason:'CLAUDE_DOM_SIGNALS_UNAVAILABLE'},
    inspectTurnState:(doc = document) => globalThis.PAPClaudeDomSignals?.inspectTurnState?.(doc) || {kind:'UNKNOWN', ready:false, busy:true, failed:false, row:null, rowKey:'', signals:['CLAUDE_DOM_SIGNALS_UNAVAILABLE']}
  });
})();
