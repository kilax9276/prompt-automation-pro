(() => {
  'use strict';

  if (globalThis.PAPChatSites) return;

  const VERSION = '1.0.0';

  const SITES = Object.freeze([
    Object.freeze({
      type:'claude',
      label:'Claude',
      hosts:['claude.ai'],
      matchesUrl(url) {
        try {
          const u = new URL(String(url || ''));
          return /(^|\.)claude\.ai$/i.test(u.hostname) && /\/chat\/[^/?#]+/i.test(u.pathname);
        } catch {
          return false;
        }
      },
      conversationId(url) {
        try {
          const u = new URL(String(url || ''));
          const match = u.pathname.match(/\/chat\/([^/?#]+)/i);
          return match ? match[1] : '';
        } catch {
          return '';
        }
      }
    }),
    Object.freeze({
      type:'chatgpt',
      label:'ChatGPT',
      hosts:['chatgpt.com', 'chat.openai.com'],
      matchesUrl(url) {
        try {
          const u = new URL(String(url || ''));
          const host = u.hostname.toLowerCase();
          if (host !== 'chatgpt.com' && host !== 'www.chatgpt.com' && host !== 'chat.openai.com') {
            return false;
          }

          // ChatGPT keeps the composer both on / (new chat) and on /c/<id>.
          // Custom GPT/project routes can also host a live composer, so URL
          // classification is intentionally host-first. DOM capability is
          // verified by the adapter before any parser/delivery action.
          return !/^\/(?:auth|settings|admin)(?:\/|$)/i.test(u.pathname);
        } catch {
          return false;
        }
      },
      conversationId(url) {
        try {
          const u = new URL(String(url || ''));
          const direct = u.pathname.match(/\/c\/([^/?#]+)/i);
          if (direct) return direct[1];
          return '';
        } catch {
          return '';
        }
      }
    })
  ]);

  function identify(url) {
    for (const site of SITES) {
      if (site.matchesUrl(url)) {
        return Object.freeze({
          type:site.type,
          label:site.label,
          supported:true,
          conversationId:site.conversationId(url)
        });
      }
    }
    return Object.freeze({
      type:'unknown',
      label:'Unknown',
      supported:false,
      conversationId:''
    });
  }

  globalThis.PAPChatSites = Object.freeze({
    version:VERSION,
    sites:SITES,
    identify,
    isSupportedUrl:(url) => identify(url).supported
  });
})();
