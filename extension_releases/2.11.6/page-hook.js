(() => {
  if (window.__PAP2_PROTOCOL_DOWNLOAD_HOOK_V3__) {
    return;
  }

  window.__PAP2_PROTOCOL_DOWNLOAD_HOOK_V3__ = true;

  const SOURCE_CONTENT = "PAP2_PROTOCOL_PARSER_CONTENT_V3";
  const SOURCE_PAGE = "PAP2_PROTOCOL_PARSER_PAGE_V3";

  const originalFetch = window.fetch.bind(window);
  const originalCreateObjectURL = URL.createObjectURL.bind(URL);
  const originalAnchorClick = HTMLAnchorElement.prototype.click;
  const originalXhrOpen = XMLHttpRequest.prototype.open;
  const originalXhrSend = XMLHttpRequest.prototype.send;
  const originalWindowOpen = window.open.bind(window);

  const blobByUrl = new Map();
  let active = null;

  const nameVariants = (value) => {
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
  };

  const nameMatches = (expected, candidate) => {
    const a = nameVariants(expected);
    const b = nameVariants(candidate);

    if (!a.size || !b.size) {
      return false;
    }

    for (const key of a) {
      if (b.has(key)) return true;
    }

    return false;
  };

  const parseContentDispositionFilename = (value) => {
    const text = String(value || "");

    let match = text.match(/filename\*\s*=\s*UTF-8''([^;]+)/i);
    if (match) {
      try {
        return decodeURIComponent(match[1].trim().replace(/^"|"$/g, ""));
      } catch (_) {
        return match[1].trim().replace(/^"|"$/g, "");
      }
    }

    match = text.match(/filename\s*=\s*"([^"]+)"/i);
    if (match) {
      return match[1];
    }

    match = text.match(/filename\s*=\s*([^;]+)/i);
    return match ? match[1].trim().replace(/^"|"$/g, "") : null;
  };

  const post = (payload, transfer = []) => {
    try {
      window.postMessage(
        {
          source: SOURCE_PAGE,
          ...payload
        },
        "*",
        transfer
      );
    } catch (error) {
      window.postMessage({
        source: SOURCE_PAGE,
        type: "HOOK_ERROR",
        captureId: active?.captureId || null,
        error: String(error?.message || error)
      }, "*");
    }
  };

  const clearActive = (captureId = null) => {
    if (!active) {
      return;
    }

    if (captureId && active.captureId !== captureId) {
      return;
    }

    if (active.finalizeTimer) {
      clearTimeout(active.finalizeTimer);
    }

    active = null;
  };

  const emitCandidate = (candidate) => {
    if (!active || active.captureId !== candidate.captureId) {
      return;
    }

    const current = active;

    if (!current.best || candidate.priority > current.best.priority) {
      current.best = candidate;
    }

    if (current.finalizeTimer) {
      clearTimeout(current.finalizeTimer);
    }

    const delay = candidate.priority >= 110 ? 0 : candidate.priority >= 90 ? 120 : 800;

    current.finalizeTimer = setTimeout(async () => {
      if (!active || active.captureId !== current.captureId || !current.best) {
        return;
      }

      const best = current.best;
      clearActive(current.captureId);

      try {
        if (best.kind === "bytes") {
          const buffer = best.buffer;
          post({
            type: "DOWNLOAD_CAPTURED",
            captureId: current.captureId,
            kind: "bytes",
            sourceKind: best.sourceKind,
            fileName: best.fileName || current.expectedName || null,
            mimeType: best.mimeType || "application/octet-stream",
            url: best.url || null,
            byteLength: buffer.byteLength,
            buffer
          }, [buffer]);
          return;
        }

        if (best.kind === "url") {
          post({
            type: "DOWNLOAD_CAPTURED",
            captureId: current.captureId,
            kind: "url",
            sourceKind: best.sourceKind,
            fileName: best.fileName || current.expectedName || null,
            mimeType: best.mimeType || null,
            url: best.url
          });
        }
      } catch (error) {
        post({
          type: "HOOK_ERROR",
          captureId: current.captureId,
          error: String(error?.message || error)
        });
      }
    }, delay);
  };

  const considerBytes = ({
    captureId,
    buffer,
    sourceKind,
    fileName,
    mimeType,
    url,
    priority
  }) => {
    if (!(buffer instanceof ArrayBuffer) || buffer.byteLength === 0) {
      return;
    }

    emitCandidate({
      captureId,
      kind: "bytes",
      buffer,
      sourceKind,
      fileName,
      mimeType,
      url,
      priority
    });
  };

  const responsePriority = (capture, response) => {
    const disposition = response.headers?.get?.("content-disposition") || "";
    const fileName = parseContentDispositionFilename(disposition);
    const contentType = response.headers?.get?.("content-type") || "";
    const url = response.url || "";

    if (fileName && nameMatches(capture.expectedName, fileName)) {
      return { priority: 108, fileName, contentType };
    }

    if (/attachment/i.test(disposition)) {
      return { priority: 100, fileName, contentType };
    }

    if (nameMatches(capture.expectedName, url)) {
      return { priority: 92, fileName, contentType };
    }

    if (/application\/(octet-stream|zip|gzip|x-gzip|x-tar|pdf)/i.test(contentType)) {
      return { priority: 82, fileName, contentType };
    }

    // Plain-text API traffic is too ambiguous to capture by MIME alone.
    // Text files are still caught by Content-Disposition/name matching,
    // Blob/createObjectURL, anchor URL, or Chrome finalUrl fallback.
    return { priority: 0, fileName, contentType };
  };

  window.addEventListener("message", (event) => {
    if (event.source !== window) {
      return;
    }

    const data = event.data;
    if (!data || data.source !== SOURCE_CONTENT) {
      return;
    }

    if (data.type === "ARM_DOWNLOAD_CAPTURE") {
      clearActive();
      active = {
        captureId: data.captureId,
        expectedName: data.expectedName || "",
        armedAt: performance.now(),
        best: null,
        finalizeTimer: null
      };

      post({
        type: "DOWNLOAD_CAPTURE_ARMED",
        captureId: data.captureId
      });
      return;
    }

    if (data.type === "CANCEL_DOWNLOAD_CAPTURE") {
      clearActive(data.captureId || null);
    }
  });

  window.fetch = async function (...args) {
    const capture = active
      ? {
          captureId: active.captureId,
          expectedName: active.expectedName
        }
      : null;

    const response = await originalFetch(...args);

    if (capture && active?.captureId === capture.captureId) {
      try {
        const info = responsePriority(capture, response);
        if (info.priority > 0) {
          const clone = response.clone();
          clone.arrayBuffer().then((buffer) => {
            if (active?.captureId !== capture.captureId) {
              return;
            }

            considerBytes({
              captureId: capture.captureId,
              buffer,
              sourceKind: "fetch",
              fileName: info.fileName,
              mimeType: info.contentType,
              url: response.url || null,
              priority: info.priority
            });
          }).catch(() => {});
        }
      } catch (_) {
        // Never break the page's fetch path.
      }
    }

    return response;
  };

  URL.createObjectURL = function (object) {
    const url = originalCreateObjectURL(object);

    if (object instanceof Blob) {
      blobByUrl.set(url, object);

      if (active && !/^(image|audio|video)\//i.test(object.type || "")) {
        const captureId = active.captureId;
        object.arrayBuffer().then((buffer) => {
          if (active?.captureId !== captureId) {
            return;
          }

          considerBytes({
            captureId,
            buffer,
            sourceKind: "createObjectURL",
            fileName: active.expectedName || null,
            mimeType: object.type || null,
            url,
            priority: 88
          });
        }).catch(() => {});
      }
    }

    return url;
  };

  HTMLAnchorElement.prototype.click = function (...args) {
    if (active) {
      try {
        const captureId = active.captureId;
        const href = this.href || "";
        const fileName = this.download || active.expectedName || null;
        const blob = blobByUrl.get(href);

        if (blob) {
          blob.arrayBuffer().then((buffer) => {
            if (active?.captureId !== captureId) {
              return;
            }

            considerBytes({
              captureId,
              buffer,
              sourceKind: "anchor-blob",
              fileName,
              mimeType: blob.type || null,
              url: href,
              priority: 120
            });
          }).catch(() => {});
        } else if (/^https?:/i.test(href)) {
          emitCandidate({
            captureId,
            kind: "url",
            sourceKind: "anchor-url",
            fileName,
            mimeType: null,
            url: href,
            priority: nameMatches(active.expectedName, fileName) ? 96 : 72
          });
        }
      } catch (_) {
        // Preserve normal anchor behavior.
      }
    }

    return originalAnchorClick.apply(this, args);
  };


  window.open = function (url, ...rest) {
    if (active && /^https?:/i.test(String(url || ""))) {
      emitCandidate({
        captureId: active.captureId,
        kind: "url",
        sourceKind: "window-open-url",
        fileName: active.expectedName || null,
        mimeType: null,
        url: String(url),
        priority: 74
      });
    }
    return originalWindowOpen(url, ...rest);
  };

  XMLHttpRequest.prototype.open = function (method, url, ...rest) {
    this.__cppRequestUrl = String(url || "");
    return originalXhrOpen.call(this, method, url, ...rest);
  };

  XMLHttpRequest.prototype.send = function (...args) {
    const capture = active
      ? {
          captureId: active.captureId,
          expectedName: active.expectedName
        }
      : null;

    if (capture) {
      this.addEventListener("load", () => {
        if (active?.captureId !== capture.captureId) {
          return;
        }

        try {
          const disposition = this.getResponseHeader("content-disposition") || "";
          const contentType = this.getResponseHeader("content-type") || "";
          const fileName = parseContentDispositionFilename(disposition);
          const url = this.responseURL || this.__cppRequestUrl || "";

          let priority = 0;
          if (fileName && nameMatches(capture.expectedName, fileName)) {
            priority = 108;
          } else if (/attachment/i.test(disposition)) {
            priority = 100;
          } else if (nameMatches(capture.expectedName, url)) {
            priority = 92;
          } else if (/application\/(octet-stream|zip|gzip|x-gzip|x-tar|pdf)/i.test(contentType)) {
            priority = 82;
          }

          if (!priority) {
            return;
          }

          const responseType = this.responseType;

          if (responseType === "arraybuffer" && this.response instanceof ArrayBuffer) {
            considerBytes({
              captureId: capture.captureId,
              buffer: this.response.slice(0),
              sourceKind: "xhr-arraybuffer",
              fileName,
              mimeType: contentType,
              url,
              priority
            });
            return;
          }

          if (responseType === "blob" && this.response instanceof Blob) {
            this.response.arrayBuffer().then((buffer) => {
              if (active?.captureId !== capture.captureId) {
                return;
              }

              considerBytes({
                captureId: capture.captureId,
                buffer,
                sourceKind: "xhr-blob",
                fileName,
                mimeType: contentType || this.response.type,
                url,
                priority
              });
            }).catch(() => {});
            return;
          }

          if ((!responseType || responseType === "text") && typeof this.responseText === "string") {
            const buffer = new TextEncoder().encode(this.responseText).buffer;
            considerBytes({
              captureId: capture.captureId,
              buffer,
              sourceKind: "xhr-text",
              fileName,
              mimeType: contentType || "text/plain",
              url,
              priority
            });
          }
        } catch (_) {
          // Never disturb the original XHR.
        }
      }, { once: true });
    }

    return originalXhrSend.apply(this, args);
  };

  post({ type: "HOOK_READY" });
})();
