// Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
// All rights reserved. See LICENSE at the repository root.
(() => {
  'use strict';

  if (globalThis.PAPClaudeDomSignals) return;

  const normalize = (value) =>
    String(value || '').replace(/\s+/g, ' ').trim();

  function transcriptRows(doc = document) {
    return [...doc.querySelectorAll('[data-testid="transcript-row"]')];
  }

  function lastTranscriptRow(doc = document) {
    const explicit = doc.querySelector(
      '[data-testid="transcript-row"][data-last-message="true"]'
    );
    if (explicit) return explicit;

    const rows = transcriptRows(doc);
    return rows.length ? rows[rows.length - 1] : null;
  }

  function buttonText(button) {
    return normalize(
      `${button?.textContent || ''} ${button?.getAttribute?.('aria-label') || ''} ${button?.title || ''}`
    );
  }

  function inspectLastAssistantLoadFailure(doc = document) {
    const row = lastTranscriptRow(doc);

    if (!row) {
      return {failed:false, reason:'NO_LAST_ROW', row:null};
    }

    // Recovery is intentionally allowed ONLY for the explicit current last row.
    // Old failed messages in Claude's virtualized transcript must not refresh.
    if (row.getAttribute('data-last-message') !== 'true') {
      return {failed:false, reason:'LAST_ROW_NOT_EXPLICIT', row};
    }

    if (row.getAttribute('data-perf-row') !== 'assistant') {
      return {failed:false, reason:'LAST_ROW_NOT_ASSISTANT', row};
    }

    const warning = row.querySelector(
      '[data-testid="message-warning"][role="status"]'
    );

    if (!warning) {
      return {
        failed:false,
        reason:'NO_MESSAGE_WARNING',
        row,
        rowIndex:row.getAttribute('data-index') || ''
      };
    }

    const warningText = normalize(warning.textContent);
    const retryButton = [...warning.querySelectorAll('button')].find((button) =>
      /(^|\s)try again(\s|$)/i.test(buttonText(button))
    );

    const responseDidNotLoad =
      /this response didn['’]?t load/i.test(warningText);

    const failed = Boolean(responseDidNotLoad && retryButton);

    return {
      failed,
      reason:failed ? 'LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD' : 'WARNING_NOT_MATCHED',
      row,
      warning,
      retryButton:retryButton || null,
      rowIndex:row.getAttribute('data-index') || '',
      rowRsIndex:row.getAttribute('data-rs-index') || '',
      rowStreaming:row.getAttribute('data-perf-row-streaming') || '',
      warningText
    };
  }

  function inspectParserGate(doc = document) {
    const row = lastTranscriptRow(doc);

    if (!row) {
      return {
        blocked:true,
        reason:'NO_LAST_TRANSCRIPT_ROW',
        row:null,
        failure:null
      };
    }

    const role = String(row.getAttribute?.('data-perf-row') || '');
    if (role !== 'assistant') {
      return {
        blocked:true,
        reason:'LAST_ROW_NOT_ASSISTANT',
        row,
        failure:null
      };
    }

    const failure = inspectLastAssistantLoadFailure(doc);
    if (failure.failed) {
      return {
        blocked:true,
        reason:'LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD',
        row,
        failure
      };
    }

    return {
      blocked:false,
      reason:'OK',
      row,
      failure
    };
  }

  function findComposer(doc = document) {
    const selectors = [
      '[data-testid="chat-input"][contenteditable="true"][data-cds="Editor"]',
      '[data-testid="chat-input"][contenteditable="true"]',
      'div.ProseMirror[contenteditable="true"]',
      '[contenteditable="true"][role="textbox"]',
      'textarea'
    ];

    for (const selector of selectors) {
      const nodes = [...doc.querySelectorAll(selector)];
      const visible = nodes.find((node) => {
        try {
          const rect = node.getBoundingClientRect();
          return rect.width > 0 && rect.height > 0;
        } catch {
          return true;
        }
      });
      if (visible) return visible;
    }

    return null;
  }

  function assistantRowKey(row) {
    if (!row) return '';

    const dataIndex = String(row.getAttribute?.('data-index') || '');
    const rsIndex = String(row.getAttribute?.('data-rs-index') || '');
    const role = String(row.getAttribute?.('data-perf-row') || '');

    return [dataIndex, rsIndex, role].join(':');
  }

  function inspectTurnState(doc = document) {
    const row = lastTranscriptRow(doc);

    if (!row) {
      return {
        kind:'NO_ROW',
        ready:false,
        busy:false,
        failed:false,
        row:null,
        rowKey:'',
        signals:['NO_LAST_TRANSCRIPT_ROW']
      };
    }

    const role = String(row.getAttribute?.('data-perf-row') || '');
    const rowKey = assistantRowKey(row);

    if (role === 'human') {
      return {
        kind:'HUMAN',
        ready:false,
        busy:false,
        failed:false,
        row,
        rowKey,
        signals:['LAST_ROW_HUMAN']
      };
    }

    if (role !== 'assistant') {
      return {
        kind:'UNKNOWN',
        ready:false,
        busy:true,
        failed:false,
        row,
        rowKey,
        signals:['LAST_ROW_UNKNOWN_ROLE']
      };
    }

    const failure = inspectLastAssistantLoadFailure(doc);
    if (failure.failed) {
      return {
        kind:'ASSISTANT_FAILED',
        ready:false,
        busy:false,
        failed:true,
        row,
        rowKey,
        failure,
        signals:['LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD']
      };
    }

    const signals = [];
    const rowStreaming = String(
      row.getAttribute?.('data-perf-row-streaming') || ''
    );

    if (rowStreaming === 'true') {
      signals.push('ROW_STREAMING');
    }

    if (row.querySelector?.('[data-is-streaming="true"]')) {
      signals.push('INNER_STREAMING');
    }

    if (
      row.querySelector?.(
        '[role="article"][aria-label="Currently streaming message"]'
      )
    ) {
      signals.push('STREAMING_ARTICLE');
    }

    if (doc.querySelector?.('button[aria-label="Stop response"]')) {
      signals.push('STOP_RESPONSE_PRESENT');
    }

    const responding = [...doc.querySelectorAll('[role="status"]')].some(
      (node) => /Claude is responding/i.test(String(node.textContent || ''))
    );
    if (responding) {
      signals.push('CLAUDE_RESPONDING_STATUS');
    }

    const composer = findComposer(doc);
    if (!composer) {
      signals.push('COMPOSER_NOT_READY');
    }

    // Fail closed: a completed turn must explicitly report streaming=false.
    if (rowStreaming !== 'false') {
      signals.push('ROW_STREAMING_STATE_NOT_FALSE');
    }

    const ready = signals.length === 0;

    return {
      kind:ready ? 'ASSISTANT_READY' : 'ASSISTANT_BUSY',
      ready,
      busy:!ready,
      failed:false,
      row,
      rowKey,
      composer,
      rowStreaming,
      signals
    };
  }

  globalThis.PAPClaudeDomSignals = Object.freeze({
    version:'1.2.0',
    transcriptRows,
    lastTranscriptRow,
    inspectLastAssistantLoadFailure,
    inspectParserGate,
    findComposer,
    assistantRowKey,
    inspectTurnState
  });
})();
