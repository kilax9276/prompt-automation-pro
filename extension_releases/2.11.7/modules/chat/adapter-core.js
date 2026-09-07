// Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
// All rights reserved. See LICENSE at the repository root.
(() => {
  'use strict';

  if (globalThis.PAPChatAdapters) return;

  const VERSION = '1.0.0';
  const registry = new Map();

  function visible(node) {
    if (!node || !node.isConnected) return false;
    try {
      const style = globalThis.getComputedStyle?.(node);
      if (style?.display === 'none' || style?.visibility === 'hidden') return false;
      const rect = node.getBoundingClientRect?.();
      if (rect && (rect.width <= 0 || rect.height <= 0)) return false;
    } catch {}
    return true;
  }

  function firstVisible(selectors, root = document) {
    for (const selector of selectors || []) {
      const nodes = [...(root?.querySelectorAll?.(selector) || [])];
      const match = nodes.find(visible);
      if (match) return match;
    }
    return null;
  }

  function lastVisible(selectors, root = document) {
    for (const selector of selectors || []) {
      const nodes = [...(root?.querySelectorAll?.(selector) || [])].filter(visible);
      if (nodes.length) return nodes[nodes.length - 1];
    }
    return null;
  }

  function normalize(value) {
    return String(value || '').replace(/\u00a0/g, ' ').replace(/\s+/g, ' ').trim();
  }

  function basename(value) {
    let text = String(value || '').trim();
    if (!text) return '';
    try {
      const u = new URL(text, location.href);
      text = decodeURIComponent(u.pathname.split('/').pop() || '');
    } catch {
      text = text.split(/[?#]/, 1)[0].replace(/^.*[\\/]/, '');
      try { text = decodeURIComponent(text); } catch {}
    }
    return text;
  }

  function register(adapter) {
    if (!adapter?.type) throw new Error('PAP adapter requires type');
    registry.set(String(adapter.type), Object.freeze(adapter));
    return registry.get(String(adapter.type));
  }

  function forType(type) {
    return registry.get(String(type || '')) || null;
  }

  function current(url = location.href) {
    const site = globalThis.PAPChatSites?.identify?.(url);
    if (!site?.supported) return null;
    return forType(site.type);
  }

  function describe(url = location.href) {
    const site = globalThis.PAPChatSites?.identify?.(url) || {
      type:'unknown', label:'Unknown', supported:false, conversationId:''
    };
    const adapter = site.supported ? forType(site.type) : null;
    return {
      ...site,
      adapterVersion:adapter?.version || '',
      domReady:Boolean(adapter?.findComposer?.(document))
    };
  }

  globalThis.PAPChatAdapters = Object.freeze({
    version:VERSION,
    register,
    forType,
    current,
    describe,
    utils:Object.freeze({visible, firstVisible, lastVisible, normalize, basename})
  });
})();
