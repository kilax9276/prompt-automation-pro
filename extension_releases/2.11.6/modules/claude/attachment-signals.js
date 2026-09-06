(() => {
  'use strict';

  if (globalThis.PAPClaudeAttachmentSignals) return;

  const VERSION = '1.1.0';

  const normalize = (value) =>
    String(value || '').replace(/\s+/g, ' ').trim();

  const normalizeName = (value) =>
    normalize(value).toLocaleLowerCase();

  function exactValue(value, fileName) {
    return normalizeName(value) === normalizeName(fileName);
  }

  function exactNameInNode(node, fileName) {
    if (!node) return false;

    if (exactValue(node.textContent || '', fileName)) return true;
    if (exactValue(node.getAttribute?.('aria-label') || '', fileName)) return true;
    if (exactValue(node.getAttribute?.('title') || '', fileName)) return true;

    return false;
  }

  function structuredExactName(tile, fileName) {
    if (!tile || !fileName) return false;

    // Claude has used several ready-card variants over time:
    // - role=button with exact title/text
    // - h3 containing exact filename
    // - bdi/truncated filename pieces
    // - sr-only exact filename
    // We require an exact structured filename token, never arbitrary page text.
    const selectors = [
      '[role="button"]',
      'button',
      '[title]',
      'h3',
      'bdi',
      '.sr-only'
    ];

    for (const selector of selectors) {
      for (const node of tile.querySelectorAll?.(selector) || []) {
        if (exactNameInNode(node, fileName)) return true;
      }
    }

    return false;
  }

  function thumbnailMatchesFile(tile, fileName) {
    if (!tile || !tile.matches?.('[data-testid="file-thumbnail"]')) {
      return false;
    }

    const wanted = normalizeName(fileName);
    if (!wanted) return false;

    if (structuredExactName(tile, fileName)) {
      return true;
    }

    // Pending tile variants may include the filename as plain text.
    // Accept this ONLY inside an actual file-thumbnail and only while pending.
    const text = normalizeName(tile.textContent || '');
    const pending = Boolean(
      String(tile.getAttribute?.('data-state') || '') === 'pending' ||
      String(tile.getAttribute?.('aria-busy') || '') === 'true' ||
      /(^|\s)loading(\s|$)/i.test(text)
    );

    if (pending && text.includes(wanted)) {
      return true;
    }

    return false;
  }

  function safeDraftTiles(doc = document) {
    const all = [...doc.querySelectorAll('[data-testid="file-thumbnail"]')];

    return all.filter((tile) => {
      // Historical/user/assistant message attachments live inside transcript rows.
      // Current unsent composer attachments do not.
      if (tile.closest?.('[data-testid="transcript-row"]')) return false;

      // Do not use invisible remnants.
      try {
        const rect = tile.getBoundingClientRect();
        if (rect.width <= 0 || rect.height <= 0) return false;
      } catch {}

      return true;
    });
  }

  function findFileThumbnail(composerRoot, fileName, doc = document) {
    if (!fileName) return null;

    // First choice: strict search inside the caller's current composer root.
    if (composerRoot) {
      const localTiles = [
        ...(composerRoot.matches?.('[data-testid="file-thumbnail"]')
          ? [composerRoot]
          : []),
        ...(composerRoot.querySelectorAll?.('[data-testid="file-thumbnail"]') || [])
      ];

      const local = localTiles.find((tile) =>
        thumbnailMatchesFile(tile, fileName)
      );
      if (local) return local;
    }

    // Claude's editor node and attachment strip are not always under the same
    // shallow composerRoot. Safe fallback: actual file-thumbnail nodes outside
    // transcript rows only. This does NOT reintroduce the old arbitrary-text bug.
    return safeDraftTiles(doc).find((tile) =>
      thumbnailMatchesFile(tile, fileName)
    ) || null;
  }

  function inspectFileThumbnail(tile, fileName) {
    if (!tile || !thumbnailMatchesFile(tile, fileName)) {
      return {
        observed:false,
        pending:false,
        ready:false,
        dataState:'',
        ariaBusy:'',
        hasLoadingText:false,
        structuredName:false,
        token:'NO_STRICT_FILE_THUMBNAIL'
      };
    }

    const dataState = String(tile.getAttribute?.('data-state') || '');
    const ariaBusy = String(tile.getAttribute?.('aria-busy') || '');
    const text = normalize(tile.textContent || '');
    const hasLoadingText = /(^|\s)Loading(\s|$)/i.test(text);

    const structuredName = structuredExactName(tile, fileName);

    const pending = Boolean(
      dataState === 'pending' ||
      ariaBusy === 'true' ||
      hasLoadingText
    );

    // Ready means:
    // - exact structured filename belongs to this real thumbnail
    // - pending/busy/loading is gone
    const ready = Boolean(
      structuredName &&
      !pending
    );

    return {
      observed:true,
      pending,
      ready,
      dataState,
      ariaBusy,
      hasLoadingText,
      structuredName,
      token:normalize(
        `${fileName}|${dataState}|${ariaBusy}|` +
        `${hasLoadingText ? 'loading' : ''}|` +
        `${structuredName ? 'structured-name' : ''}|${text}`
      ).slice(0, 3000)
    };
  }

  globalThis.PAPClaudeAttachmentSignals = Object.freeze({
    version:VERSION,
    exactNameInNode,
    structuredExactName,
    thumbnailMatchesFile,
    safeDraftTiles,
    findFileThumbnail,
    inspectFileThumbnail
  });
})();
