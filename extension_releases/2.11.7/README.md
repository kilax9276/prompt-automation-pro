# Prompt Automation Pro 2 extension v2.11.5 (fork of Prompt Automation Pro 2.11.5)

## v2.11.5 — Chrome download size can be unknown at creation

- Fixes ChatGPT direct-download files where Chrome reports `totalBytes=0` while the download is still valid and completes normally.
- Missing `Content-Length` is no longer converted to a real zero-byte expectation during URL refetch/upload.
- A completed Chrome download now carries `fileSize` to the content script, with `totalBytes`/`bytesReceived` as fallbacks.
- Unknown-length streamed uploads are accepted until the real byte count is known; the Receiver still rejects empty uploads and validates the final SHA-256.


## v2.11.4 — delayed ChatGPT preview Download + live DOM rebinding

- ChatGPT preview files are no longer treated as complete merely because preview rendering fetched `estuary/content`. When a flyout opens, PAP waits for the real `button[aria-label="Download"]` inside that exact flyout and clicks it before accepting the file.
- The preview-ready wait is state-based and may wait up to 30 seconds; it does not use a fixed sleep and it ignores unrelated global `Download file` buttons.
- After a preview closes, required-file targets are rebound against the current assistant DOM before each next file. This handles ChatGPT React remounts that invalidate the original node reference and previously prevented file 2/N from being clicked.
- Inline `entity-underline` controls whose visible text/aria is already a filename (for example `something.zip`) are now accepted as generated-file controls even when they have no file icon or the words "download/file/archive".
- ChatGPT adapter version is `1.4.1`; parser schema, Receiver 2.10.0, and Web Console 4.3.2 are unchanged.

## v2.11.3 — direct-download ChatGPT files + runtime invalidation guard

- ChatGPT inline generated-file buttons no longer require an artifact preview to appear. Some files download directly on the first React-button activation; those capture/browser results are accepted immediately.
- A late preview remains supported: if capture did not complete, the adapter resolves the current preview `Download` control dynamically instead of re-clicking the original inline button.
- `modules/chat/runtime-guard.js` centralizes extension-context invalidation detection. The generic turn watcher disconnects its observer and timers after an extension Reload invalidates the old content-script context, preventing repeated `Extension context invalidated` errors.
- ChatGPT adapter version is `1.3.0`; parser schema and Receiver API are unchanged.

## v2.11.2 — ChatGPT capture-first generated-file transfer

- ChatGPT file acquisition no longer requires a Chrome Downloads event when the page hook already captured the exact generated-file response.
- For inline React file controls that open artifact preview, the extension gives the initial `interpreter/download -> estuary/content` fetch a short capture window and can upload those captured bytes directly to Receiver.
- ChatGPT artifact rows with a dedicated `button[aria-label="Download file"]` are now recognized as direct download controls and their nearby filename is resolved from the card.
- The preview `button[aria-label="Download"]` remains a fallback for file types that do not yield bytes during the initial activation.
- Browser download and page capture are raced after the final Download click; either path may complete the transfer instead of page capture being blocked behind a Chrome-download timeout.


## v2.11.1 — ChatGPT generated-file preview flow

- ChatGPT inline generated files may be React buttons with no `href`; they are now detected in the ChatGPT adapter.
- `COMMAND_PUT_FILES id=N` can bind to the file button in the local DOM segment immediately before that command instead of relying on filename text.
- The adapter opens ChatGPT artifact preview, resolves artifact-flyout `button[aria-label="Download"]`, and closes the preview after transfer.
- Browser/page capture is armed before the inline activation click so the initial `interpreter/download -> estuary/content` response is not missed.
- Parser schema version is now `6.1.0`; server protocol commands are unchanged.

## v2.11.0 — multi-chat adapter layer + ChatGPT

- Supports Claude and ChatGPT (`chatgpt.com`, legacy `chat.openai.com`).
- Detects a stable `chatType`/`chatLabel`/conversation id and sends it with every new Run.
- Site-specific DOM selectors are isolated in `modules/<chat>/adapter.js`; parser, turn watcher and delivery bridge consume one normalized adapter contract.
- ChatGPT adapter covers transcript roles, completion/streaming state, composer/send/file input, generated-file links and attachment-card observation.
- Generic Receiver endpoints are `/api/chat-result`, `/api/chat-status`, `/api/chat-file/*`; old `/api/claude-*` names remain server aliases.
- See `CHAT_ADAPTER_ARCHITECTURE.md` before changing selectors or adding another provider.
- Receiver requirement: 2.10.0. Older extensions remain compatible with Receiver 2.10.0 through `/api/claude-*` aliases.

This build requires Python receiver v2.10.0 and checks `/health` before creating a run. If the extension is accidentally pointed at an older receiver (for example v2.7 on port 8765), it stops immediately with `SERVER_INCOMPATIBLE` instead of creating a run and failing later during chunk upload.

Required server URL for the current installation: `http://192.168.10.78:8867` (Prompt Automation Pro 2 receiver).

# Prompt Automation Pro — browser extension v2.8

Install the unpacked extension directly from:

`D:\work\extentions\prompt_automation_pro\`

The directory must contain `manifest.json`, `background.js`, `content.js`, `page-hook.js`, `popup.js`, `popup.html`, and `popup.css` directly at its root.

The extension runs only on a supported Claude/ChatGPT tab explicitly enabled from the popup.

Default Python receiver URL: `http://192.168.10.78:8767`.

## File handling

- Files are processed one at a time in page order.
- The download start must appear within the configured start timeout.
- There is no fixed maximum duration for an active download.
- Chrome `bytesReceived` is polled while the download is active. The download may run for minutes or hours as long as bytes keep arriving.
- `downloadStallTimeoutMs` is only a no-progress timeout.
- Local completion is accepted only when Chrome reports the download state as `complete`.
- If Chrome provides an HTTP(S) `finalUrl`, the extension uses it immediately after local completion; it does not wait for the page-capture timeout.
- The second transfer is streamed to Python in chunks. The server writes a `.part` file while data arrives and renames it only after a successful finish.
- `uploadStallTimeoutMs` applies to lack of progress for an individual source read/server chunk, not to total file duration.
- Fail-fast is always enabled and automatic retries are disabled.

The older settings `downloadCompleteTimeoutMs` and `uploadTimeoutMs` are migrated automatically where possible. `uploadTimeoutMs` remains only for small control/JSON requests.


## v2.9.1

Изменения:
- parser ждёт завершения ответа Claude и 2.5 секунды стабильного DOM;
- 15-секундная настройка delay теперь только минимальная задержка до проверки готовности;
- скачиваются только файлы из COMMAND_PUT_FILES самого нового assistant-ответа;
- старые artifact-карточки и пользовательские вложения не скачиваются;
- один нескачавшийся нужный файл становится предупреждением и не останавливает остальные;
- status содержит expectedFiles/completedFiles/fileErrors/allRequiredFilesReady;
- улучшено сопоставление имени protocol target с реальным Chrome download;
- если Claude отдаёт непредсказуемое CDN-имя, один свежий download watcher может привязать download по факту клика.


## v2.10.3

- Includes the chat delivery bridge directly in the full extension package.
- Every new run carries exact `papSource.tabId` and source Claude URL.
- Web Console on port 8771 can poll the source tab, attach files, insert operator text, show upload errors/stalls, retry failed/stalled files, and send on explicit operator command.
- Keeps v2.9.1 readiness waiting and COMMAND_PUT_FILES-only download behavior.


## v2.10.4

Исправлена обратная вставка текста из Web Console в Claude composer.

- Сначала выбирается живой редактор Claude: data-testid="chat-input", contenteditable, data-cds="Editor".
- Поддержан фактический Tiptap/ProseMirror composer.
- Вставка больше не считается успешной только по возврату execCommand.
- После каждой стратегии содержимое редактора проверяется.
- Стратегии: synthetic paste -> execCommand insertText -> ProseMirror DOM/input fallback.
- MESSAGE_STATE=INSERTED отправляется серверу только после фактической проверки текста в composer.
- Если текст не появился, Web Console получает MESSAGE_STATE=ERROR с диагностикой, а кнопка Send остаётся заблокированной.
- Загрузка файлов остаётся без изменений.


## v2.10.5
- Delivery bridge no longer depends on parser enabled state.
- Extension reload no longer silently disables Web Console delivery.
- Supports claude.ai and *.claude.ai chat pages.


## v2.10.6 — message-first delivery

Исправлена причина, по которой файл появлялся в Claude сразу, а текст Web Console
появлялся только после перезагрузки расширения/сервера.

Старая последовательность:
  CLAIM -> FILE UPLOAD -> ожидание определения конца upload -> MESSAGE INSERT

Если файл уже визуально был в Claude, но детектор upload ещё ждал/зависал,
код до MESSAGE INSERT вообще не доходил. После Reload старый вызов прерывался,
bridge заново забирал job и уже доходил до сообщения — поэтому текст внезапно
появлялся после рестарта.

Новая последовательность:
  CLAIM -> MESSAGE INSERT+VERIFY -> FILE UPLOAD -> MESSAGE LIVE VERIFY
        -> следующий FILE -> MESSAGE LIVE VERIFY -> FINAL MESSAGE VERIFY

Дополнительно:
- server messageState=INSERTED больше не считается достаточным доказательством;
- bridge каждый раз проверяет живой Tiptap/ProseMirror DOM;
- если Claude перемонтировал/очистил composer при добавлении attachment,
  тот же текст автоматически вставляется снова;
- зависший upload больше не может блокировать первичную вставку сообщения.


## v2.10.7
- delivery uses per-attempt leaseToken;
- runtime/http calls have hard timeouts;
- chunk fetch has its own timeout;
- poll loop no longer blocks on a long processJob;
- local ACTIVE lock has a watchdog;
- stuck FETCHING/CLAUDE_UPLOADING becomes recoverable without restart;
- recovery first checks whether Claude already has the attachment;
- stale async callbacks from an old attempt cannot mutate a fresh attempt.


## v2.10.8
- waits for Claude to finish streaming/responding and for a stable composer;
- heartbeat reports WAITING_CLAUDE_IDLE / CLAUDE_IDLE without requiring refresh;
- persists a stable conversation baseline before insertion;
- detects manual Enter/send after confirmed insertion and marks the job CONSUMED;
- CONSUMED stops all future replay/reinsertion of text and reports;
- upload loops also detect a submitted turn, so a log cannot be attached again later.


## v2.10.9 — upload completion + duplicate protection

Исправлен сценарий: файл уже виден в Claude, Web Console остаётся CLAUDE_UPLOADING,
затем auto-recovery прикрепляет тот же файл ещё раз.

Изменения:
- progressbar с 100% считается завершённым, а не busy;
- fileCard выбирает локальный attachment subtree, а не общий composer;
- готовый Remove/Delete file control считается сильным признаком завершения;
- стабильная attachment card без реального hard-busy признака считается UPLOADED;
- перед КАЖДОЙ попыткой fetch/attach bridge сначала ищет тот же файл в Claude;
- если matching card уже существует, повторный attach запрещён;
- если существующая card остаётся неоднозначной до stall timeout, состояние становится
  STALLED / EXISTING_CLAUDE_CARD_NOT_CONFIRMED, но второй файл НЕ добавляется;
- automatic RECOVER_PENDING разрешает повторный attach только если matching card
  действительно отсутствует;
- последний guard выполняется непосредственно перед DataTransfer/change, чтобы DOM race
  тоже не мог создать дубликат.


## v2.10.10
- 100%/ready attachment-card completion detection from v2.10.9 is preserved.
- After a Claude attach attempt starts, timeout/error becomes STALLED; automatic second attach is forbidden.
- CLAUDE_UPLOADING without a confirmable card also becomes STALLED.
- COMMAND_PUT_FILES transfer to Receiver uses the exact basename from the protocol path.


## v2.10.11 — detectors derived from real Claude DOM probe

File upload (observed on three independent manual uploads):
- upload start: [data-testid=file-thumbnail][data-state=pending][aria-busy=true]
  and text "Loading";
- upload finish: pending/loading content disappears and the filename is exposed
  as a clickable [role=button] inside the same file-thumbnail;
- this exact transition is now the primary UPLOADED criterion;
- progressbar is only a fallback, not the main criterion.

Claude response readiness (observed across three responses):
- busy begins with data-perf-row-streaming=true and "Claude is responding";
- Stop response appears shortly after;
- inner [data-is-streaming=true] appears during generation;
- ready requires latest assistant row data-perf-row-streaming=false,
  no data-is-streaming=true, no Stop response, no "Claude is responding",
  and a live composer;
- only 400 ms stable confirmation is used after those exact signals agree.

Important probe finding:
- transcript DOM rowCount is virtualized and changed inside a single response
  (5->3 and 5->4), so rowCount is no longer used to detect a new turn or reset
  readiness timers. Monotonic data-index is used for real turn advancement.


## v2.10.12 — Claude page hydration gate

Fixes delivery starting before a Claude conversation page has finished loading/hydrating.

Before the extension polls a delivery job it now requires:
- document.readyState == complete;
- live Claude composer exists;
- for /chat/<id>, a transcript row exists;
- latest transcript row has numeric data-index;
- latest row has data-perf-row;
- latest row is marked data-last-message=true;
- the meaningful page fingerprint stays unchanged for 1.8 seconds.

The fingerprint intentionally does NOT use transcript rowCount because the DOM probe
proved Claude virtualizes row counts during normal operation.

The same gate is checked again after a job is claimed, so a route change/remount between
poll and claim cannot cause early insertion.

Web Console heartbeat phases:
- WAITING_PAGE_READY
- PAGE_READY_CONFIRMED
then the existing:
- WAITING_CLAUDE_READY
- CLAUDE_READY_CONFIRMED


## v2.10.13 — modular recovery for the current last failed Claude response

Observed failure DOM:
- current row is `[data-testid="transcript-row"][data-last-message="true"][data-perf-row="assistant"]`;
- inside it Claude renders `[data-testid="message-warning"][role="status"]`;
- the warning contains `This response didn't load.` and a `Try again` button.

Recovery:
- ONLY that explicit current last assistant row can trigger refresh;
- old failed rows are ignored;
- failure must remain stable for 700 ms;
- the current tab is refreshed with `location.reload()`;
- refresh is rate-limited to once per 120 seconds per browser tab;
- cooldown survives page reload through `sessionStorage`;
- while the broken last response remains visible, Web Console -> Claude delivery is blocked;
- after refresh the existing PAGE_READY and CLAUDE_READY gates still run.

Module layout:
- `content.js` — existing protocol parser and Claude->Receiver transfer; unchanged here.
- `modules/claude/dom-signals.js` — pure Claude DOM recognition only.
- `modules/claude/last-response-recovery.js` — failure watcher, cooldown and refresh only.
- `chat-bridge.js` — Web Console->Claude delivery; it only consumes the recovery state.
- `background.js` — browser download/background transport.
- `page-hook.js` — existing page-world hooks.

The response-failure logic is intentionally not merged into the parser or chat bridge.


## v2.10.14 — "Enable current page" injects the actual current runtime

Root cause of v2.10.13:
- after Chrome extension Reload/update, an already-open Claude page does NOT
  automatically receive the new manifest content scripts;
- the popup's "Enable current page" previously injected only `page-hook.js`
  and then sent `TAB_ENABLED`;
- if `content.js`, `dom-signals.js`, `last-response-recovery.js` and
  `chat-bridge.js` were absent, that message had no receiver and the recovery
  detector never existed on the page.

Fix:
- Enable current page explicitly injects:
  1. `content.js`
  2. `modules/claude/dom-signals.js`
  3. `modules/claude/last-response-recovery.js`
  4. `chat-bridge.js`
  into the ISOLATED world;
- then injects `page-hook.js` into MAIN world;
- verifies that parser, DOM signals, recovery and bridge are actually present
  before the popup operation reports success;
- RUN NOW performs the same runtime repair;
- `content.js` and `chat-bridge.js` now have idempotence guards, so manual
  injection is safe even when manifest content scripts already ran;
- the recovery module scans the already-present DOM immediately after injection,
  so a currently visible "This response didn't load" does not need another DOM
  mutation before being detected.

Module separation remains:
- content.js = COMMAND parser / Claude->Receiver;
- modules/claude/dom-signals.js = DOM recognition only;
- modules/claude/last-response-recovery.js = last-response refresh/cooldown only;
- chat-bridge.js = Web Console->Claude delivery only;
- background.js = browser lifecycle/injection/download transport.


## v2.10.15 — refresh first, then restore the last PAP draft if Claude is still broken

Recovery sequence:
1. Current last assistant row shows `This response didn't load` + `Try again`.
2. The tab refreshes, still no more often than once per 120 seconds.
3. After the refresh, the extension waits `responseFailureReplayDelayMs`
   (default 15 seconds, configurable in the popup).
4. If the SAME current failed assistant row is still present, the bridge requests
   a recovery clone of the exact PAP delivery job that was last submitted.
5. That recovery job inserts the same message into the composer and uploads the
   same materialized PAP attachment files again.
6. The message is NOT auto-sent. The user still presses Enter / Send manually.
7. Once the recovery draft is restored for that failed response, automatic
   refresh is suppressed so the restored draft is not wiped out.

Safety / idempotency:
- only the exact most recently submitted PAP runId/jobId stored in this browser
  tab is eligible; there is no fallback to an arbitrary older job;
- the source reference expires after 2 hours;
- platform clones the source job and files into a fresh delivery job;
- existing attachment-card checks still prevent duplicate cards if Claude kept
  something through the refresh;
- a successfully queued replay is remembered per exact failed response key.

This restores PAP-managed text/files. Local files that were manually selected in
Claude outside a PAP delivery job are not reconstructed by this mechanism.


## v2.10.16 — failed response is a hard parser gate, including after refresh

Root cause of the screenshot where `CLAUDE PARSER — DONE` appeared while
`This response didn’t load` was still visible:

- `content.js` had its own readiness logic;
- it accepted `latest assistant + data-perf-row-streaming=false` as parseable;
- the separate recovery module correctly saw the warning, but only the
  Web Console -> Claude bridge consumed that recovery state;
- therefore the Claude -> Receiver parser could still publish a run and show DONE.

Fix:
- `modules/claude/dom-signals.js` is now loaded at `document_start` BEFORE
  `content.js`;
- warning recognition remains only in the DOM module;
- `content.js` consumes `inspectParserGate()` and fails closed if the DOM module
  is not present;
- an exact current-last response warning blocks parser readiness:
  `LAST_ASSISTANT_RESPONSE_DID_NOT_LOAD`;
- parser shows `CLAUDE PARSER — RECOVERY`, never READY/DONE;
- parser rechecks the gate at the PARSE boundary and again immediately before
  POST_PARSE_RESULT;
- after a browser refresh, `document.readyState=complete` means only that the
  browser document loaded. It no longer means the Claude chat is usable;
- if the warning is already present after refresh, autorun skips the normal
  delay and enters recovery waiting immediately.

Module boundaries:
- `modules/claude/dom-signals.js` = selectors/DOM interpretation;
- `modules/claude/last-response-recovery.js` = refresh/cooldown/replay trigger;
- `content.js` = COMMAND parser/Claude->Receiver, consumes DOM gate only;
- `chat-bridge.js` = Web Console->Claude, consumes recovery state;
- `background.js` = injection/browser/download transport.


## v2.10.17 — exactly one refresh, then replay; never a refresh loop

The failed-response recovery is now a strict persisted state machine:

`DETECTED -> ONE REFRESH -> WAIT REPLAY DELAY -> REPLAY SAME PAP DRAFT`

For the same exact failed last assistant response:
- only ONE automatic refresh is allowed;
- after that refresh, the state can never transition back to refresh;
- default wait before replay is 15 seconds (popup setting);
- if replay creation fails, only the replay request is retried every 5 seconds;
- a replay failure NEVER triggers another refresh;
- once a replay job is queued, the bridge keeps retrying that SAME job if needed;
- no second recovery clone is created for the same source;
- the overlay now shows whether the first refresh already happened and the
  approximate seconds remaining before draft/file restoration.

Source recovery was also hardened:
- the browser's remembered runId/jobId is now only a hint;
- Platform 4.2.12 can find the latest submitted PAP job for the exact same
  browser tab + Claude page if the extension was upgraded/reloaded and the
  browser-side source reference is missing.


## v2.10.18 — normal Claude turns are detected from SPA DOM, not page refresh

Root cause:
- the parser autorun was scheduled by extension/page lifecycle events:
  `CONTENT_READY`, `TAB_ENABLED`, `tabs.onUpdated(status=complete/url)`;
- pressing Send in Claude does NOT reload the browser page;
- Claude updates its transcript inside the existing SPA document;
- therefore after a manual Send -> Claude response -> response finished, no
  browser navigation event existed to start the next parse.

Fix:
- new standalone module `modules/claude/turn-watcher.js`;
- it watches the live transcript DOM with MutationObserver + 200ms fallback scan;
- it consumes `modules/claude/dom-signals.js` and does not duplicate Claude selectors;
- lifecycle:
    HUMAN last row
    -> ASSISTANT_BUSY
    -> ASSISTANT_READY stable for 700ms
    -> one `CLAUDE_TURN_FINISHED` event;
- assistant readiness requires:
    latest assistant row,
    `data-perf-row-streaming=false`,
    no `[data-is-streaming=true]`,
    no Stop response,
    no `Claude is responding`,
    live composer,
    no `This response didn't load`;
- turn identity uses `data-index/data-rs-index`, not transcript rowCount;
- emitted turn keys are de-duplicated in sessionStorage across DOM remounts/reloads;
- a ready assistant row that already existed when the watcher was loaded is only
  a baseline and is not emitted as a fake new turn;
- if the extension is injected while Claude is already generating, the watcher
  follows that active turn and emits when it finishes.

Parser scheduling:
- `CLAUDE_TURN_FINISHED` bypasses the old page-load delay (default 15s);
- parser starts immediately;
- because the watcher already confirmed a stable turn, parser uses a 600ms final
  readiness confirmation for this path;
- actual page loads/recovery refreshes still use the separate page lifecycle path.

Module boundaries:
- `modules/claude/dom-signals.js` = Claude DOM interpretation;
- `modules/claude/turn-watcher.js` = normal in-page turn lifecycle only;
- `modules/claude/last-response-recovery.js` = failed-response refresh/replay only;
- `content.js` = COMMAND parser / Claude -> Receiver;
- `chat-bridge.js` = Web Console -> Claude;
- `background.js` = browser events, injection and routing.


## v2.10.19 — strict composer attachment identity

Bug reproduced from the operator screenshot:
- Web Console showed `ui_frontend.log` as:
  `UPLOADED / CLAUDE_READY_EXISTING_CARD / 0 B of 810 B`;
- Claude composer visually contained only the terminal-log attachment;
- the assistant transcript itself contained the text/path `ui_frontend.log`;
- old `fileCard()` had a broad visible-text fallback and therefore treated
  transcript text as an already existing attachment card.

Fix:
- new module `modules/claude/attachment-signals.js`;
- attachment existence is now scoped ONLY to the CURRENT composer root;
- a positive match requires `[data-testid="file-thumbnail"]`;
- the exact target filename must match inside that thumbnail;
- the bridge NEVER falls back to arbitrary page/transcript text;
- searching `document` for an attachment is forbidden;
- generic "stable card", arbitrary role=button and generic progressbar heuristics
  can no longer declare an attachment UPLOADED;
- current Claude ready state must match the probe-derived exact transition:
    file-thumbnail pending/busy/loading
    -> pending/busy/loading gone
    -> exact filename exposed as the ready role/button;
- before every file dispatch the reusable file input is cleared, so the second
  and later file selections reliably fire as new changes.

This means a missing second file is now actually uploaded rather than being
incorrectly skipped because its filename happened to appear in Claude's text.

Module boundaries:
- `modules/claude/attachment-signals.js` = attachment DOM identity/state only;
- `modules/claude/dom-signals.js` = transcript/turn DOM state;
- `modules/claude/turn-watcher.js` = normal SPA turn lifecycle;
- `modules/claude/last-response-recovery.js` = failed-response recovery;
- `chat-bridge.js` = delivery orchestration only.


## v2.10.20 — attachment monitor follows Claude composer remounts

The v2.0.1 attachment probe captured the failure precisely:

- only ONE `FILE_INPUT_INPUT` / `FILE_INPUT_CHANGE` happened;
- it contained only the terminal-log file;
- Claude created a pending `file-thumbnail`:
  `data-state=pending`, `aria-busy=true`, text `Loading attachment`;
- about 116 ms after the file-input event, Claude replaced that pending tile
  with the final ready terminal-log card;
- during the rest of the probe there was never a second file-input event, so
  `ui_backend.log` was never even dispatched to Claude.

Why v2.10.19 still waited:
- `attachFile()` captured `const root = composerRoot(composer)` BEFORE dispatch;
- its monitoring loop kept querying that same root object;
- Claude can remount/replace the composer attachment subtree during the
  pending->ready transition;
- the real ready card existed in the CURRENT composer, but the bridge could
  continue watching the stale pre-remount root and therefore never finish file 1;
- because file 1 never returned `UPLOADED`, the sequential loop never reached
  file 2.

Fix:
- new `liveAttachmentContext(fileName)` resolves the CURRENT composer, CURRENT
  root and strict matching file-thumbnail every observation;
- both new uploads and recovery monitoring reacquire that context on every loop;
- stale root/card references are not used as upload-completion evidence;
- a transient remount gap is tolerated for 2 seconds in existing-upload
  recovery;
- strict composer-only attachment identity from v2.10.19 remains unchanged;
- file 2 is dispatched only after the live current composer confirms file 1.

Platform is unchanged; this is extension-only.


## v2.10.21 — current draft attachments are not always descendants of the editor root

The latest operator screenshot proves the first terminal-log file is already
visibly attached in Claude while Web Console still reports `CLAUDE_UPLOADING`.
The second file remains `PENDING`, so the sequential uploader is still blocked
on completion detection of file 1.

The previous probe also showed an important structural fact: its shallow
"composer root" contained the editor but reported the visible current attachment
tile as outside that root. Therefore reacquiring the same shallow root in
v2.10.20 was not sufficient.

Fix:
- attachment discovery still searches the current composer root first;
- if the editor root does not contain the attachment strip, the detector safely
  searches real `[data-testid=file-thumbnail]` nodes outside transcript rows;
- arbitrary page text is NEVER considered an attachment;
- historical attachments inside `[data-testid=transcript-row]` are excluded;
- ready-card filename recognition supports Claude's structured variants:
  exact role/button title/text, exact `h3`, exact `bdi`, exact `.sr-only`;
- ready still requires no `data-state=pending`, no `aria-busy=true`,
  and no Loading text.

This keeps the false-positive protection from v2.10.19 while allowing the
actual unsent draft attachment strip to be recognized even when Claude places it
as a sibling of the editor subtree rather than a descendant.

Platform update is not required.


## v2.10.22 — parser RUN_CANCELLED race + bridge watchdog + performance

Two independent races were visible in the operator screenshots.

### 1. Parser RUN_CANCELLED was self-inflicted

`scheduleAutorun()` incremented `state.runToken` immediately for every automatic
scheduler event. Therefore a harmless duplicate event such as PAGE_COMPLETE,
TAB_ENABLED, CONTENT_READY or a repeated turn notification could arrive while
`runPipeline()` was already working and invalidate the token of the live parser.

Result:
- the already successful/working parser threw `RUN_CANCELLED`;
- green DONE from one run and red STOPPED from another could overlap;
- cancellation was incorrectly shown as an infrastructure/parser error.

Fix:
- automatic scheduler events never invalidate a running parser;
- page-lifecycle events are ignored while a parser run is active;
- the same assistant `rowKey` is de-duplicated;
- a genuinely newer completed Claude turn is queued once and starts after the
  current parser finishes;
- `RUN_CANCELLED` / navigation / disable are controlled cancellation states and
  are no longer rendered as infrastructure failures.

### 2. Chat Bridge local watchdog could create overlapping delivery attempts

Old behavior:
- watchdog timer expired;
- `ACTIVE.delete(jobKey)` ran while the original `processJob()` was still alive;
- poll loop was then free to start the SAME backend job again.

That could produce competing waits/DOM operations and contributes to sluggishness.

New behavior:
- watchdog is diagnostic only;
- it never unlocks a live attempt;
- the same backend job remains single-flight until the original promise actually
  finishes;
- warning was changed to an informational diagnostic.

### 3. DOM watcher load reduced

The normal turn watcher previously combined:
- MutationObserver -> immediate full scan on every matching DOM mutation;
- plus another full scan every 200 ms.

Claude streaming creates many DOM mutations, so this was unnecessarily expensive.

v2.10.22:
- turn watcher mutations are debounced by 120 ms;
- fallback scan is once per 1000 ms;
- overlapping scans are serialized/coalesced;
- recovery watcher mutations are debounced by 150 ms;
- recovery fallback scan is once per 1500 ms.

The diagnostic PAP Claude Attachment Probe is intentionally much heavier (100 ms
snapshots + outerHTML). It should be disabled when not actively collecting a log.


## v2.10.23 — one delivery job may write its message only once

Repeated Web Console text insertion was a real bug.

Old behavior:
- the job already had `messageState=INSERTED`;
- later the exact text disappeared from Claude's composer;
- if `conversationAdvanced()` / Claude-busy signals were missed at that instant,
  `ensureMessage()` could call `setTextValue()` again;
- this let the same text reappear after the user manually sent it, after Claude
  had already finished, after an editor remount, or on a later poll attempt.

New invariant:
`PENDING -> first write -> INSERTED -> never auto-write this job again`

After INSERTED:
- PAP is read-only with respect to that message;
- it waits up to 1.2 seconds for a transient editor remount;
- if the exact PAP text does not return, the job becomes `CONSUMED` with reason
  `INSERTED_MESSAGE_LEFT_COMPOSER`;
- Platform 4.2.12 already treats CONSUMED as terminal, so poll will not return it;
- PAP never overwrites user edits and never re-populates a normal submitted job.

Failed-response recovery remains separate:
- an explicit `This response didn't load` recovery creates a NEW recoveryReplay
  job with its own `messageState=PENDING`;
- that new job is also one-shot: one automatic text write maximum.

---

Copyright (c) 2026 Kolobov Aleksei (@kilax9276). All rights reserved. See LICENSE at the repository root.
