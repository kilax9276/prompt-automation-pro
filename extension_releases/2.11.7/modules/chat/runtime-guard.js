// Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
// All rights reserved. See LICENSE at the repository root.
(() => {
  'use strict';

  if (globalThis.PAPRuntimeGuard) return;

  let invalidated = false;
  let invalidatedReason = '';

  function messageOf(error) {
    return String(error?.message || error || '');
  }

  function isContextInvalidated(error) {
    const text = messageOf(error);
    return /Extension context invalidated/i.test(text) ||
      /Cannot access a chrome:\/\/ URL/i.test(text) ||
      /The message port closed before a response was received/i.test(text) && !globalThis.chrome?.runtime?.id;
  }

  function markInvalidated(error = 'EXTENSION_CONTEXT_INVALIDATED') {
    invalidated = true;
    invalidatedReason = messageOf(error) || 'EXTENSION_CONTEXT_INVALIDATED';
    return invalidatedReason;
  }

  function runtimeAvailable() {
    if (invalidated) return false;
    try {
      if (!globalThis.chrome?.runtime?.id) {
        invalidated = true;
        invalidatedReason = 'EXTENSION_CONTEXT_INVALIDATED';
        return false;
      }
      return true;
    } catch (error) {
      if (isContextInvalidated(error)) markInvalidated(error);
      return false;
    }
  }

  function observeError(error) {
    if (isContextInvalidated(error)) {
      markInvalidated(error);
      return true;
    }
    return false;
  }

  globalThis.PAPRuntimeGuard = Object.freeze({
    version:'1.0.0',
    isContextInvalidated,
    markInvalidated,
    runtimeAvailable,
    observeError,
    snapshot:() => Object.freeze({invalidated, reason:invalidatedReason})
  });
})();
