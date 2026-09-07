# Chat adapter architecture

Current extension: **2.11.5**. Supported chat types: `claude`, `chatgpt`.

The extension core must not learn site-specific selectors. A layout change should normally be fixed in one adapter file.

## Layers

1. `modules/chat/sites.js` — URL -> stable chat identity (`type`, `label`, `conversationId`). No DOM selectors.
2. `modules/chat/adapter-core.js` — adapter registry and generic DOM utilities.
3. `modules/chat/runtime-guard.js` — shared MV3 extension-context lifecycle detection; long-lived observers/timers must stop after invalidation.
4. `modules/<chat>/adapter.js` — all selectors and DOM interpretation for one chat UI.
5. Generic consumers: `content.js`, `modules/chat/turn-watcher.js`, `chat-bridge.js`, `background.js`.
6. Claude-only recovery remains in `modules/claude/last-response-recovery.js` and is enabled through adapter capability `failedResponseRecovery`.

## Adapter contract

An adapter registers a stable `type`, human `label`, `version`, `capabilities`, and normalized operations:

- transcript: `transcriptRows`, `assistantRows`, `lastTranscriptRow`, `rowRole`, `rowKey`, `rowMeta`;
- readiness: `inspectParserGate`, `inspectTurnState`;
- composer: `findComposer`, `composerRoot`, `findSendButton`, `findFileInput`;
- parser: `logicalMessageNodes`;
- generated files: `artifactNodes`, `downloadControl`, `parseArtifact`, optional `bindRequiredArtifacts`, `prepareArtifactDownload`, optional `resolvePreparedDownloadButton`, `cleanupArtifactDownload`;
- outgoing attachments: `findAttachmentCard`, `inspectAttachmentCard`.

Generic code should use these operations and must not add selectors for a specific provider.

## Adding another chat

1. Add URL classification to `modules/chat/sites.js` with a new stable type, for example `gemini`.
2. Add `modules/gemini/adapter.js` implementing the contract. Keep fallback selectors in that file, ordered from the most stable attributes to weaker fallbacks.
3. Add that adapter's runtime files to `CHAT_RUNTIME_FILES` in `background.js` and content-script matches in `manifest.json`.
4. Add DOM fixture tests to `tests/test_chat_adapters.py`.
5. Only add provider-specific recovery modules when behavior cannot be represented by the common adapter contract; expose them through a capability flag.

## When a site changes markup

Start in `modules/<chat>/adapter.js`. Update selectors/signals there and extend the fixture reproducing the changed DOM. Do not patch `content.js` or `chat-bridge.js` unless the normalized behavior itself has changed for every chat.

`chatType`, `chatLabel`, and `chatConversationId` are protocol metadata. They are sent to Receiver and persisted in `result.json`/`status.json`; delivery jobs also carry the target chat identity. This is intentionally separate from selectors so server-side features can branch on chat type without knowing the browser DOM.

## Compatibility

Receiver 2.10.0 exposes generic `/api/chat-*` routes. Historical `/api/claude-*` routes remain aliases. Web Console 4.3.2 accepts both new `CHAT_UPLOADING` and persisted legacy `CLAUDE_UPLOADING` delivery states, so existing unfinished jobs are not invalidated by the rename.


## Chrome download size semantics (2.11.5)

Chrome may emit a valid `downloads.DownloadItem` with `totalBytes=0` when the server does not expose `Content-Length`. Zero in this state means “unknown”, not an empty file. The transfer layer therefore prefers final `fileSize`, then positive `totalBytes`/`bytesReceived`, and otherwise streams with an unknown length until completion.


## ChatGPT generated-file flow (2.11.4)

ChatGPT may render generated files as inline React `<button>` controls with no `href`. Filename-only `entity-underline` buttons are accepted in addition to explicit `Download file` cards. The adapter binds required artifacts to the local `COMMAND_PUT_FILES id=N` segment and generic transport arms browser/page capture before activation.

If the inline activation opens `section[data-testid="screen-threadFlyOut"]`, the initial interpreter/estuary request is treated as preview preparation rather than final user download. PAP scopes itself to that exact flyout, waits for its enabled `button[aria-label="Download"]` for up to 30 seconds, re-arms capture, and clicks the real Download control. Direct-download files still use the original capture/browser race without requiring a preview.

Opening/closing a ChatGPT flyout can remount the assistant message. Before each next required file, generic transport rebuilds the required-file plan against the current assistant DOM so stale detached React nodes cannot silently swallow the next click. Generic parser/transport code still contains no provider selectors; the flyout selectors remain in the ChatGPT adapter.

---

Copyright (c) 2026 Kolobov Aleksei (@kilax9276). All rights reserved. See LICENSE at the repository root.
