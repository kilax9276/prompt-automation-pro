# Prompt Automation Pro 2 Platform 4.3.5

Stable ports remain unchanged:
- Receiver: `0.0.0.0:8867` — receiver 2.10.0
- Web Console: `0.0.0.0:8871` — console release 4.3.5


## 4.3.5 — effective result after AUTO ERROR ignore

- Fixes the Web Console result banner after the dedicated AUTO ERROR ignore action. The workflow was already unblocked correctly in 4.3.4, but the criteria panel still rendered the detector's historical red `ИТОГ: СТОП`, which was misleading.
- When the step is `OVERRIDDEN` specifically because AUTO ERROR was ignored and the declared STOP/CONTINUE criteria themselves allow continuation, the banner now turns green and reads `ИТОГ: ПРОДОЛЖИТЬ — AUTO ERROR ПРОИГНОРИРОВАН`.
- The original AUTO ERROR card, matched signature, declared condition result, operator timestamp and note remain visible for audit. No stored detector decision is erased or rewritten.
- General overrides and cases where declared criteria themselves require STOP are unchanged.

## 4.3.4 — operator ignore for AUTO ERROR

- Adds a dedicated **Игнорировать AUTO ERROR и продолжить** button when an automatic error is the only blocker and declared STOP/CONTINUE criteria themselves allow continuation.
- Ignoring is explicit and audited: the original AUTO ERROR remains visible, while execution state records `automaticErrorIgnored`, timestamp, note, and matched reason IDs.
- The dedicated action is rejected when the declared criteria also require STOP; in that case only the existing general override can continue the workflow.
- Keeps all 4.3.3 automatic execution-error detection and smart ZIP delivery behavior.

## 4.3.3 — automatic execution error stop

- `COMMAND_RUN` no longer treats matched STOP/CONTINUE criteria as the only source of truth. A non-zero main shell return code now always makes the step STOP, even when explicit criteria would otherwise say NO_STOP.
- The executor scans raw combined stdout+stderr with a conservative high-confidence error-signature detector. Detected runtime/toolchain failures override a satisfied `CONTINUE_RUN` and force STOP.
- Initial signatures cover Node.js module-resolution / missing-export / fatal errors, Python import/syntax failures, shell command/path-not-found errors, Git fatal errors, segmentation faults and process aborts.
- Ordinary assertion-failure text is deliberately not classified as a hard infrastructure error, so intentional RED-phase tests remain possible.
- Web Console shows `AUTO ERROR` cards with the matched signature and excerpt. Executor criteria record `automaticErrorDetected`, `automaticErrorOverride`, `automaticErrorReasons`, `declaredDecision`, and `declaredDecisionBasis`.
- The signature list is isolated in `execution_error_detector.py` so new production cases can be added incrementally without changing the directive protocol.


## 4.3.2 — deterministic smart ZIP policy

- Normal Web Console delivery is always prepared with `smart_zip`; stale/legacy UI mode values cannot fan a group of small files out as raw individual attachments.
- Small non-archive files are first tested as one real ZIP and split only if the **actual compressed archive** exceeds the configured limit. Raw source-size sums no longer cause premature splitting.
- Existing archives remain separate and are never nested. Files at or above the limit remain separate large attachments.
- The hard ceiling remains 30 MiB per generated ZIP part.
- Packaging metadata is now `smart_zip_v2` with `splitBasis=actual_zip_size`.

## 4.3.1 — automatic ZIP delivery

- New default delivery mode `smart_zip`.
- Existing archives (`.zip`, `.tar.gz`, `.7z`, `.rar`, etc.) are always sent separately and are never nested.
- Files at or above the ZIP limit are sent separately as large files.
- Remaining ordinary files are grouped into `pap-files-<runId>-partNN.zip` when there is more than one.
- The default/hard ceiling for automatic ZIP parts is 30 MiB. Every generated ZIP is measured; oversized groups are split until every part is within the limit.
- A single ordinary small file is left as-is rather than wrapped unnecessarily.
- Delivery job metadata records `packagingPolicy`, bundle members, and why a file was sent separately.
- Recovery replay preserves chat type/label and packaging metadata.

The 4.3.1 release still contains the historical manual modes; 4.3.2 normal Web Console preparation deliberately enforces the automatic policy.
Use `activate_console_release.sh 4.3.5` to activate the current release.

## 4.3.0 — chat identity and generic API

- Receiver normalizes and persists `chatType`, `chatLabel`, `chatConversationId`.
- New generic routes: `/api/chat-result`, `/api/chat-status`, `/api/chat-file/*`; historical `/api/claude-*` routes remain aliases.
- Run list/detail shows chat type and conversation id.
- Delivery job target carries chat identity; Web Console labels delivery using the source chat name instead of hard-coding Claude.
- New delivery events use `CHAT_UPLOADING`; legacy `CLAUDE_UPLOADING` jobs are still accepted.
- `install_platform_requirements.sh` now installs into the release selected by `VERSION-platform`.
- `start_platform.sh` is checkout-path independent. Existing `runtime/console-current.json` is intentionally not overwritten; use `activate_console_release.sh 4.3.0` to switch an existing installation.

## 4.2.0 changes

- `COMMAND_GET_REPORTS` is an always-run finalizer. A STOP/error in an earlier operational step no longer blocks report collection. It only waits if an earlier `COMMAND_RUN` is still actively running, to avoid snapshotting a file while it is still being written.
- Report collection can finish with warnings when requested files are missing. Missing paths are preserved.
- New Web Console delivery panel can send a typed message + terminal log + collected reports to the exact Claude tab that created the run (requires extension bridge v2.10.0 and a new run carrying `papSource.tabId`).
- If requested reports are missing, the generated suffix is appended to the message and shown in the Web UI:
  `Такие файлы отсутствуют: path1, path2`
- Attachment states are visible: PENDING / FETCHING / CLAUDE_UPLOADING / UPLOADED / ERROR / STALLED.
- Retry affects only ERROR/STALLED attachments.
- The Send action is unavailable until every available attachment is UPLOADED and the message is inserted into Claude.
- Delivery modes:
  - `open`: terminal log and reports as-is;
  - `packed`: each non-archive file becomes its own ZIP; already archived reports stay as-is;
  - `single_archive`: terminal log + non-archive reports become one `.tar.gz`; already archived reports are sent separately and never nested/recompressed.
- Aggregate archive has a configurable maximum size (default 20 MiB). If the generated aggregate exceeds it, the job is not created and the operator can select another mode or raise the limit.

## Upgrade

Extract this archive over `/home/ext_disk/prompt_automation_pro2`, activate release 4.3.5, then run `start_platform.sh`. The platform manager keeps the same ports; no additional console ports are created.


## 4.2.1

- Delivery composer moved directly under the Run header and enlarged.
- Missing paths from completed `COMMAND_GET_REPORTS` are visibly and automatically appended to the editable Web Console message field using exactly: `Такие файлы отсутствуют: path1, path2`.
- The suffix is idempotent: rerenders/repeated Prepare do not duplicate it, and rerunning reports removes stale missing paths.
- Server recomputes the same suffix when a delivery job is created, including any report snapshot that disappeared after collection.
- Requires full extension v2.10.3+ for source-tab delivery.


## v4.2.2
- Poll returns the newest unfinished delivery job, not the oldest.
- New Prepare supersedes older unfinished jobs for the same Claude tab.
- Old ERROR/STALLED jobs can no longer block all later file/message deliveries.
- Late events for superseded jobs are ignored.


## v4.2.3 — только последний assistant-блок в Web

Расширение и Receiver не меняются: result.json сохраняется полностью, как и раньше.

Web Console / executor:
- показывает и выполняет команды только из последнего элемента result.messages;
- старые assistant-блоки не показываются как шаги и не участвуют в блокировках;
- COMMAND_RUN / COMMAND_PUT_FILES / COMMAND_GET_REPORTS / USER_ACTION / control
  берутся только из последнего assistant-блока;
- Raw JSON в Web UI также показывает только последний messages[];
- исходный data/<runId>/result.json остаётся полным;
- старые cached plan.json мигрируют без потери stepId последнего блока.


## v4.2.4 — стабильный порядок Runs и защита от replay после рестарта

1. Runs теперь сортируются по времени создания run в его server-generated runId.
   Изменение workflow/status/state больше не двигает карточку вверх/вниз.
   Самый новый run всегда сверху.

2. ensure_state больше не перезаписывает state.json на каждом watcher scan,
   если реальных изменений нет. Это убирает постоянный mtime/WebSocket churn.

3. Незавершённые delivery jobs привязаны к конкретному запуску Console backend.
   После рестарта backend все старые незавершённые jobs переходят в
   PAUSED_AFTER_RESTART и НЕ выдаются extension bridge через poll.

4. Старое сообщение/файл после рестарта не может самопроизвольно появиться
   в Claude. Для старого job требуется явное действие пользователя:
   «Продолжить после рестарта» либо создание нового Prepare job.

5. Если restart произошёл во время FETCHING/CLAUDE_UPLOADING, такой attachment
   переводится в STALLED и может быть явно повторён.

6. SEND_REQUESTED при рестарте сбрасывается в NOT_REQUESTED, поэтому старый
   клик Send тоже никогда не replay-ится автоматически.

Расширение менять для этих двух исправлений не требуется.


## v4.2.5
- CLAIM lease = 15 sec;
- every mutation requires the current leaseToken;
- expired lease is automatically released;
- interrupted FETCHING/CLAUDE_UPLOADING becomes RECOVER_PENDING;
- no-progress stall also revokes the lease and schedules automatic recovery;
- max 3 automatic recoveries, then STALLED;
- stale callbacks from an old browser attempt are rejected by lease mismatch;
- restart is no longer the recovery mechanism.


## v4.2.6 — startup fix

Исправлена ошибка запуска Console v4.2.5.

Причина:
console_server.py использует re.fullmatch() в list_runs() для стабильной сортировки Runs,
но модуль re не был импортирован. py_compile это не обнаруживает, потому что NameError
возникает только во время выполнения list_runs(), а startup вызывает scan_fingerprint()
-> list_runs(). Из-за этого Console на 8771 не становилась healthy, и start_platform.sh
заканчивался ERROR::PLATFORM_NOT_READY.

v4.2.6 добавляет import re и проходит реальный runtime smoke test с HTTP /health.
Функциональность lease/self-recovery v4.2.5 сохранена без изменений.


## v4.2.7
- CONSUMED terminal state prevents any replay after manual Enter/send;
- client phase shows WAITING_CLAUDE_IDLE / CLAUDE_IDLE;
- delivery panel moved to the very bottom;
- COMMAND_GET_REPORTS button added next to Prepare/Retry/Send.


## v4.2.8 — no-cache frontend and visible release

The 4.2.7 package already contained the final delivery panel and COMMAND_GET_REPORTS
button, but an older cached index.html/app.js could keep showing the 4.2.6 layout.

v4.2.8:
- sends Cache-Control: no-store/no-cache for / and /static/*;
- adds X-PAP-Console-Version;
- uses ?v=4.2.8 on app.js/style.css;
- displays "Web Console v4.2.8" in the top bar;
- forces deliveryCard to be the final section inside #runView;
- shows the button as "Выполнить COMMAND_GET_REPORTS".


## v4.2.9
- 01_/02_ are internal snapshot prefixes only, never user-visible filenames.
- Browser report download and Claude attachment use the exact original basename.
- Old prefixed report snapshots are downloaded without the numeric prefix.
- Auto-recovery is allowed before Claude attach (FETCHING), but CLAUDE_UPLOADING
  timeout/lease expiry becomes STALLED and requires explicit manual retry.


## v4.2.10 — nohup/background completion and downloadable stopped logs

Reproduced root cause:
`cd ... && setsid nohup service ... >log 2>&1 < /dev/null & disown; ...`

Because `&` can background the whole `cd && ...` asynchronous list, a background
Bash/descendant may inherit the executor stdout descriptor. The main COMMAND_RUN
Bash already exits with rc=0 and prints all RET_VALUE lines, but waiting for stdout
EOF can hang until the background service itself exits.

v4.2.10:
- checks the main Bash `proc.returncode` every 100 ms instead of using pipe EOF as
  the definition of command completion;
- after main Bash exits, drains stdout for 750 ms;
- if a background descendant still holds the pipe, detaches the read transport and
  completes COMMAND_RUN from the main Bash return code;
- saves logPath immediately when COMMAND_RUN starts, so full-log/download works
  while RUNNING and after operator cancellation;
- discovers old executor/logs/sNNN.log even if an older state file lacks logPath;
- restart reconciles stale RUNNING -> INTERRUPTED_BY_BACKEND_RESTART, so
  COMMAND_GET_REPORTS is no longer blocked forever;
- operator Stop metadata is kept in state/events, not injected into the terminal-only log.


## v4.2.11 — clone a submitted delivery for failed-response draft recovery

New bridge endpoint:
`POST /api/chat-delivery/recovery/requeue`

It accepts the exact source `runId/jobId` remembered by the browser tab and:
- requires the source to have actually been submitted (`CONSUMED` / `SENT`);
- verifies the same tab and Claude page;
- rejects sources older than 2 hours;
- copies the exact materialized attachment files into a NEW job directory;
- preserves user-visible filenames;
- resets message/attachments to PENDING;
- sets `recoveryReplay=true` and `recoveryOf={runId,jobId}`;
- never reactivates/mutates the terminal source job;
- de-duplicates active recovery clones for the same source job;
- supersedes unrelated unfinished jobs for the same browser tab.

The recovery clone is a normal delivery job except that the extension may start it
while the current last assistant row still shows `This response didn't load`.
It restores the composer and files only; send remains manual.


## v4.2.12 — recovery source survives extension reloads

`/api/chat-delivery/recovery/requeue` no longer requires the browser to remember
the exact source runId/jobId.

The Platform resolves the most recently SUBMITTED PAP delivery for:
- the same browser tabId;
- the same Claude chat URL;
- not older than 2 hours.

If the browser does provide a runId/jobId, it is treated as a hint. If the
Platform has a newer submitted delivery for the same tab/page, the newer source
wins. This fixes recovery after extension upgrade/reload where sessionStorage did
not contain the job that produced the failed Claude response.

Recovery replay de-duplication remains unchanged: the same source job cannot
create an endless series of active clones.


## v4.2.13 — message field belongs to one Run

Fixed cross-Run text leakage in the delivery form.

Before:
- a Run without an in-memory draft could fall back to the textarea's current
  value;
- that textarea could still contain text from the previously selected Run.

Now:
- a new/unseen Run starts with an empty message field;
- text is stored under the exact `runId`;
- switching to another Run immediately swaps the textarea to that Run's own text;
- switching back restores the previous Run's text;
- drafts persist across Web Console reloads in browser `localStorage`;
- if no browser draft exists but this same Run already has a prepared delivery
  job, only that Run's own `job.message` may be restored;
- the automatic missing-files suffix is saved into the same Run-specific draft.

Drafts are local to the browser profile and are not shared between browsers.

---

Copyright (c) 2026 Kolobov Aleksei (@kilax9276). All rights reserved. See LICENSE at the repository root.
