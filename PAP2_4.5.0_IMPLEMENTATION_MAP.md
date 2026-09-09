# PAP2 4.5.0 — FINAL IMPLEMENTATION MAP

Статус: **implementation map only**. Сервер/стенд не изменялись, сборка/активация не выполнялись. Основание: `Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6`.

- **Редакция дизайна:** `c7bcb8651a15419424603443239ff93b0347c4a849f814c63d79cf6dd0a690fa` / 2742 строк
- **Историческая точка 4.4.0:** `830ab8c6453fa58ab1fd1339e210a41857e16df6` — не заменяется никогда. Каталоги `console_releases/4.3.5`, `console_releases/4.4.0` и корневой `server.py` заморожены: срез 1 не правил их на месте, а создал свои каталоги релизов. Поэтому строки закрытых срезов не устаревают — байты, которые они описывают, не изменятся.
- **Статусы якорей:** строка закрытого среза помечена `HISTORICAL` и по байтам не сверяется; строка будущего среза помечена `ACTIVE` и её якоря выпущены на рабочем основании.
- **Рабочее основание:** три поддерева git, перечисленные ниже. Коммит здесь не называется намеренно: поддерево живёт дольше любого коммита, а объявленный номер коммита устаревает при первой же несвязанной правке и начинает описывать не то дерево, которое проверяется. Идентичность даёт git, а не собственный дайджест: он уже строит Merkle-дерево по всем байтам. Именно поддеревья, а не `HEAD` и не корневое дерево — несвязанный коммит вроде правки README сдвигает корень, не сдвигая ни одного якоря, и значение, требующее ручной правки при каждом таком коммите, перестаёт описывать дерево.

| роль | путь | tree sha |
|---|---|---|
| `console` | `console_releases/4.5.0-s1` | `425bc1a8b77ab23b69997d98125f909f821b9a42` |
| `receiver` | `receivers/2.11.0-s1` | `f5ceaabab02513da2eafab9c593420918708fe63` |
| `extension` | `extension_releases/2.11.6` | `65b0db4ed31d36f68bb3f6b832797d4e524edebc` |

Дизайн — живой контракт, а не константа: он меняется с каждой записью журнала решений, чаще, чем закрываются срезы. Карта объявляет редакцию, против которой построена, а оснастка сверяет объявленное с фактическим файлом. Расхождение означает «карту не обновили после решения», а не «дизайн трогать нельзя». Проверка чистоты рабочего дерева на `docs/` не распространяется.

Документ построен по фактическим байтам handoff. Номера строк и SHA-256 ниже подставлены из `inventory.json`, а не набраны вручную. `verify_inventory.py` заново выводит диапазоны из source bytes (Python через AST, text anchors через needle/баланс) и запускается перед `verify_map.py`, поэтому цепочка проверки: bytes → inventory → map. Для Python start включает все строки декораторов символа. Архитектурные решения не добавляются; при обнаружении факта, делающего контракт невыполнимым, соответствующий срез блокируется.

## 1. Проверенное основание — 18 файлов

### 1.1. Рабочее основание — 18 файлов

Таблица описывает то основание, против которого выпущены якоря строк ACTIVE. Историческая точка `830ab8c6` названа выше отдельно и остаётся замороженной; путь каждого файла в ней указан в поле `mapPath` инвентаря и в самой строке карты.

| файл | SHA-256 | строк |
|---|---|---|
| `console_releases/4.5.0-s1/chat_bindings.py` | `3129ebe1336a589176f5164b5639ac248826f52fb6e6d0a7ab0d45809ec42f0c` | 186 |
| `console_releases/4.5.0-s1/console_server.py` | `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a` | 1127 |
| `console_releases/4.5.0-s1/delivery_manager.py` | `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896` | 1536 |
| `console_releases/4.5.0-s1/endpoint_registry.py` | `e7aea1faa752dab6fdacb5f3e6572097006cc95d078368b3097d576206242c19` | 276 |
| `console_releases/4.5.0-s1/execution_error_detector.py` | `b6d182c1e1579ca4e2fc45606f1ecdefd8677a776b9458478f88cf096e3ed8b9` | 120 |
| `console_releases/4.5.0-s1/executor.py` | `cceb102e0af7a3f25faa9a634b0f6135e6a52ab3a40b0d958b94ce5b580b7b25` | 1416 |
| `console_releases/4.5.0-s1/profile_resolver.py` | `e316c0cf61203d3bd5f822bb949c24eacec6730547cc233528e3bab2f18aae20` | 102 |
| `console_releases/4.5.0-s1/profile_store.py` | `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019` | 834 |
| `console_releases/4.5.0-s1/protocol_engine.py` | `c436b29afd873fd78c8c37187a6d6baba05e7a257a81c721d5514abe57d5ba20` | 324 |
| `console_releases/4.5.0-s1/run_profile_context.py` | `1d833de7d454791effa0073af66996bdc1d0bb9758ef6a4a254748b23187e542` | 393 |
| `console_releases/4.5.0-s1/static/app.js` | `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110` | 1575 |
| `console_releases/4.5.0-s1/static/index.html` | `19056b796757ae25e434fc113c9b3c8ea486c3fdc5fd0d321a8c26a4a09f300f` | 276 |
| `console_releases/4.5.0-s1/static/style.css` | `82d30017d76392534317d92a8ab8dc1851fbee3736af72d4d45a2eb2974e5779` | 267 |
| `extension_releases/2.11.6/background.js` | `30830c99ec58a33b1ee7ba7fa190b374cecfc6c266a82cb1a11444d900eb87e7` | 1491 |
| `extension_releases/2.11.6/chat-bridge.js` | `71272004262ef21e19cc75d0c2ce19fb242bf5d04afde1c1213f9d4b43a2c7e4` | 1957 |
| `extension_releases/2.11.6/content.js` | `b85583e200ab88b6fadeadd99c053f4104020ecc9c14a952b41d12f3cf6335b1` | 2302 |
| `extension_releases/2.11.6/manifest.json` | `741453d48162ed8df785c09b6058146bf9513a4d19e6538397ac4b56a8d2278e` | 88 |
| `receivers/2.11.0-s1/server.py` | `ff3ed887453f767e898983a8ea87ab15181486bb3a955742dd2b1c196a888463` | 808 |


| Файл | SHA-256 основания | Строк |
|---|---|---:|

### 1.2. Историческая точка 4.4.0 — доказательство, не проверка

Байты основания `830ab8c6`. Каталог заморожен и не изменится, поэтому строки HISTORICAL по нему не сверяются.

| файл | SHA-256 | строк |
|---|---|---|
| `console_releases/4.4.0/executor.py` | `f9092de771b693bd555c7b651758617186f9ad0830cb0f06549eeb75900f7ca7` | 1414 |
| `console_releases/4.4.0/protocol_engine.py` | `1ef2fd6684851d25d5826a757f44c9cfe570c7d79a3d861aad57e6a59337a9dd` | 322 |
| `console_releases/4.4.0/console_server.py` | `b313552f6d82eff3ca0f596681fcee63efa1d0193299e0793b718613cb5dda2c` | 986 |
| `console_releases/4.4.0/endpoint_registry.py` | `e4635929f645a9fb0394cdddaef9f7ef7a03caa021a8ab3bf315c2d90dac2867` | 274 |
| `console_releases/4.4.0/run_profile_context.py` | `30409e1d3400c55424042eb55f1fc8fefc2de4d1e6f874dd40fd5c44f4a14ec4` | 268 |
| `console_releases/4.4.0/delivery_manager.py` | `3fc3469a1219d646d5ac480fb314ddadfa9e2180ce2fdd45b12ef4cc3a02d3a4` | 1534 |
| `extension/chat-bridge.js` | `71272004262ef21e19cc75d0c2ce19fb242bf5d04afde1c1213f9d4b43a2c7e4` | 1957 |
| `extension/background.js` | `30830c99ec58a33b1ee7ba7fa190b374cecfc6c266a82cb1a11444d900eb87e7` | 1491 |
| `extension/content.js` | `b85583e200ab88b6fadeadd99c053f4104020ecc9c14a952b41d12f3cf6335b1` | 2302 |
| `console_releases/4.4.0/static/app.js` | `4e1a5e494e74dfda8e4fc78056b6dbca79d1e8fd4d71a30061e4411b02bcf009` | 1538 |
| `console_releases/4.4.0/static/index.html` | `3f8bf767668161e33934defba41bfad59c9fd318d79c09f5a7dfd5cd2d67fe99` | 258 |
| `console_releases/4.4.0/static/style.css` | `1dc41455e9d94f9ea59af1419264dc4f60fe4c3384a0bde126d61014623f0f28` | 260 |
| `extension/manifest.json` | `741453d48162ed8df785c09b6058146bf9513a4d19e6538397ac4b56a8d2278e` | 88 |
| `server.py` | `0f3d79249e98928391a1b009c1b414e0f758cda9cc29c3037547fc0990408a21` | 472 |
| `console_releases/4.4.0/execution_error_detector.py` | `eb81b5c565767e3cd5fac72e186280d7d4dec563da14bb29670c699a1de39618` | 118 |
| `console_releases/4.4.0/profile_store.py` | `6a1f5db725f23d2f0dd209681e0af3fe93b4609d0074214103f82174a8283bd2` | 568 |
| `console_releases/4.4.0/chat_bindings.py` | `58c883c66ed8a168b3ec8bd17640d2faa0de9f764276d5623c0e04fc3bdff1eb` | 184 |
| `console_releases/4.4.0/profile_resolver.py` | `8a746fc11ea8325a52e1334e57705311c883ff913236cf940c6c4508434d3741` | 100 |

## 2. Закрытые факты, используемые картой

### 2.1. Точный предикат тишины

**DRAIN**: приём новых Run закрыт на ломающей операции; новая выдача delivery/новый `CLAIM` закрыты; события job, уже имевшего lease до начала DRAIN, принимаются до терминального исхода. **Local quiet** доказана только если одновременно нет шага `status=RUNNING` и нет живого subprocess в `RunExecutor._processes`. **Browser quiet** доказана только если для всех незавершённых job нет активного захвата (`claimLeaseToken` непустой и `claimExpiresAt > server now`) и нет attachment со state `FETCHING`, `CHAT_UPLOADING` или `CLAUDE_UPLOADING`.

Критический отрицательный случай: lease, который **истёк во время DRAIN**, выставляет unsafe latch. `recover_expired_leases()` может очистить token, но это не доказывает отсутствие внешнего эффекта; cutover/rollback останавливается до явного сброса соответствующего browser context. Только после local quiet + browser quiet + отсутствия unsafe latch разрешён переход в **BARRIER**.

### 2.2. Версионный/ownership barrier в `api_delivery_poll`

Историческое доказательство на `830ab8c6`: `console_releases/4.4.0/console_server.py` `b313552f6d82eff3ca0f596681fcee63efa1d0193299e0793b718613cb5dda2c`, `api_delivery_poll` 628–648, `observe()` внутри `try/except Exception: pass` на 638–641. Эти координаты не проверяются на рабочем основании — байты переехали, а сдвигать старые константы на новые строки как тот же факт запрещено.

Активная проверка на рабочем основании closed-S1: `console_releases/4.5.0-s1/console_server.py` `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`, тот же проглатывающий блок на 778–781. Поэтому version/pollKind/ownership/barrier checks обязаны быть **до строки 778 и вне этого try**. Иначе отказ будет проглочен либо несогласованный клиент успеет изменить endpoint state. После выполнения соответствующей части среза 2 проверка уходит из активных.

### 2.3. Переименование `endpointWaitTimeoutSec`

Фактическое основание: 10 текстовых вхождений на 9 строках в 4 файлах; `run_profile_context.py:266` одновременно читает старое имя и пишет старое имя в результат. Новое имя: `delivery.endpointWaitTimeoutSeconds`; default новой схемы **3600 s**, минимум **15**, максимум **604800**. Пять состояний ниже определяются наличием ключа, а не truthiness: default применяется только при отсутствии обоих имён.

| Файл | Строка(и) | Текстовых hits | Роль |
|---|---|---:|---|
| `profile_store.py` | 313, 315, 317, 360 | 4 | read/default, validation messages, canonical write |
| `run_profile_context.py` | 266 | 2 | old-key read + old-key write on one line; separate `ACC-MIG-015/016` |
| `console_server.py` | 515 | 1 | consume authorization key into internal `timeoutSec` |
| `static/app.js` | 1108, 1132, 1250 | 3 | UI default/load/save |

| Состояние | Преобразование | Acceptance |
|---|---|---|
| старое есть, нового нет | перенести candidate в новое; старое удалить только после успешной валидации | `ACC-MIG-010` |
| оба есть, равны | оставить новое; старое удалить только после успешной валидации | `ACC-MIG-011` |
| оба есть, различаются | остановить migration; не угадывать и не сохранять | `ACC-MIG-012` |
| старого нет, новое есть | оставить новое и валидировать canonical value | `ACC-MIG-013` |
| ни одного нет | создать новое со schema default 3600 | `ACC-MIG-014` |

**Значения:** наличие определяется оператором membership (`key in delivery`), а не `get(...) or default`. Явно присутствующие `0`, `false`, `""` и `null` считаются присутствующими значениями и **не** получают default 3600; migration останавливается до сохранения как на невалидном canonical candidate (`ACC-MIG-018`). Это намеренно fail-closed: только реальное отсутствие обоих ключей активирует schema default.

## 3. Точки врезки

Каждая строка имеет точный base SHA и диапазон существующего anchor. Для новых функций диапазон указывает место интеграции в существующем файле. `content.js` — guard row: файл входит в 18-file basis, но 4.5 не требует его менять.

### MAP-001 — срез 1 HISTORICAL — `server.py` / `_result`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `0f3d79249e98928391a1b009c1b414e0f758cda9cc29c3037547fc0990408a21`
- **Точный диапазон:** `280–306`
- **Текущая обязанность:** Безусловно создаёт публичный Run сразу после JSON; SHA будущих вложений в этот момент ещё неизвестны.
- **Обязанность 4.5:** Создать intake transaction/staging token, вычислить parse-component fingerprint без времён/Run id; если expectedFiles=0 — финализировать сразу, иначе не публиковать Run до полного fingerprint по завершённым files/status.
- **Изменение:** замена
- **Контракты:** §9 п.10; §10l «Приём Run»
- **Что менять нельзя:** Не считать provisional fingerprint достаточным для dedupe; generatedAt/runId/turnId=null не входят в ключ.
- **Миграция:** Старые Run не мигрируются; staging — не Run и не попадает в list_runs.
- **Acceptance:** `ACC-S1-001`, `ACC-S1-014`
- **Откат:** Откат удаляет незавершённые intake staging; существующие каталоги Run не переписываются.

### MAP-002 — срез 1 HISTORICAL — `server.py` / `_file_start`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `0f3d79249e98928391a1b009c1b414e0f758cda9cc29c3037547fc0990408a21`
- **Точный диапазон:** `314–346`
- **Текущая обязанность:** File upload требует существующий run_dir/result.json.
- **Обязанность 4.5:** Разрешить upload в intake staging token до финализации Run; сохранять порядок/имя/expected sha и фактический sha без создания public Run.
- **Изменение:** замена
- **Контракты:** §9 п.10; установленный факт timing hashes
- **Что менять нельзя:** Не менять байты и порядок; staging path не должен выглядеть как завершённый Run для console.
- **Миграция:** Используется только в slice1 receiver intake protocol.
- **Acceptance:** `ACC-S1-014`, `ACC-S1-015`
- **Откат:** Незавершённый staging удаляется при rollback.

### MAP-003 — срез 1 HISTORICAL — `server.py` / `ReceiverServer`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `0f3d79249e98928391a1b009c1b414e0f758cda9cc29c3037547fc0990408a21`
- **Точный диапазон:** `113–130`
- **Текущая обязанность:** Receiver знает только data_dir/token/uploads; привязка не приходит из extension payload.
- **Обязанность 4.5:** Добавить read-only lookup текущей binding identity из sibling config/chat-bindings.json по точному chatType+conversationId для dedupe fingerprint; включать bindingId, а отсутствие binding представлять явным null sentinel.
- **Изменение:** добавление
- **Контракты:** §9 п.10; §10l «Приём Run»
- **Что менять нельзя:** Не считать URL привязкой; не мутировать config из receiver; malformed/ambiguous binding state не угадывать.
- **Миграция:** Схема chat-bindings остаётся источником bindingId; lookup нужен только для fingerprint на момент финализации intake.
- **Acceptance:** `ACC-S1-016`
- **Откат:** Кодовый rollback; dedupe index/staging удалить, config не менять.

### MAP-004 — срез 1 HISTORICAL — `server.py` / `_status`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `0f3d79249e98928391a1b009c1b414e0f758cda9cc29c3037547fc0990408a21`
- **Точный диапазон:** `308–312`
- **Текущая обязанность:** Status patch просто обновляет уже созданный Run.
- **Обязанность 4.5:** На terminal status финализировать intake: собрать normalized parse + ordered attachment names/hashes + chat identity + bindingId/null из read-only binding lookup; в dedupe window либо atomically promote staging в новый Run, либо merge duplicateCount/journal в существующий canonical Run и удалить staging.
- **Изменение:** замена
- **Контракты:** §9 п.10; §10l
- **Что менять нельзя:** Не публиковать два Run и потом скрывать второй; duplicate определяется только после полного fingerprint; изменение bindingId меняет fingerprint.
- **Миграция:** Финальный ответ/status может содержать canonicalRunId для диагностики, не требуя изменения extension semantics.
- **Acceptance:** `ACC-S1-001`, `ACC-S1-002`, `ACC-S1-015`, `ACC-S1-016`
- **Откат:** Rollback удаляет только staging/index; promoted Run остаются обычными one-shot Run.

### MAP-005 — срез 5 — `receivers/2.11.0-s1/server.py` / `_result`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `ff3ed887453f767e898983a8ea87ab15181486bb3a955742dd2b1c196a888463`
- **Точный диапазон:** `600–632`
- **Текущая обязанность:** Приём всегда открыт.
- **Обязанность 4.5:** Закрытый приём для второй атомарной границы: при gate=CLOSED новый каталог Run не создаётся.
- **Изменение:** добавление
- **Контракты:** §10l; §12 «Атомарность ломающего выката»
- **Что менять нельзя:** Ответ должен быть явным; нельзя принять JSON и «закрыть» после создания каталога.
- **Миграция:** Используется при 5+3b до очистки data/.
- **Acceptance:** `ACC-S5-001`, `ACC-MIG-001`
- **Откат:** При откате также закрыть приём до разрушения новой схемы.

### MAP-006 — срез 3a — `console_releases/4.5.0-s1/console_server.py` / `watcher`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `219–238`
- **Текущая обязанность:** Watcher видит изменения Run/status и delivery, но не публикует incoming attachments в ProfileFileStore.
- **Обязанность 4.5:** После появления RESOLVED profile-context импортировать completed incoming attachments из status/files в ProfileFileStore: объект публикуется atomically по profileId+sha256, затем artifact record; повторный watcher idempotent.
- **Изменение:** добавление
- **Контракты:** §9 п.2; §9d
- **Что менять нельзя:** Receiver не знает profileId при upload completion; поэтому публикация ProfileFileStore не живёт в server.py::_record_completed.
- **Миграция:** Старые файлы Run не импортируются автоматически.
- **Acceptance:** `ACC-S3A-001`, `ACC-S3A-002`
- **Откат:** Откат удаляет только новые artifact indices/objects, не имеющие surviving references.

### MAP-007 — срез 1 HISTORICAL — `console_releases/4.4.0/profile_store.py` / `_validate_profile`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `6a1f5db725f23d2f0dd209681e0af3fe93b4609d0074214103f82174a8283bd2`
- **Точный диапазон:** `253–368`
- **Текущая обязанность:** Схема v1 пересобирает профиль из известных полей; отдельного immutable snapshot schema/foundation нет.
- **Обязанность 4.5:** Нормализовать только slice-1 поля, необходимые immutable profile/run snapshots и activation foundation; неизвестные поля по-прежнему не сохранять. Переименование delivery timeout в slice1 не выполнять.
- **Изменение:** замена
- **Контракты:** §4.2–4.2a; §9c; §10 slice1
- **Что менять нельзя:** Значения secrets не входят в снимок; не менять delivery.endpointWaitTimeoutSec до атомарной границы slice2.
- **Миграция:** Config migration отсутствует в slice1; timeout alias остаётся старым до slice2.
- **Acceptance:** `ACC-S1-003`
- **Откат:** Кодовый rollback slice1; timeout config не затрагивается.

### MAP-008 — срез 2 — `console_releases/4.5.0-s1/profile_store.py` / `endpoint timeout read`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `315–315`
- **Текущая обязанность:** Читает старое имя через delivery.get(... ) or 3600, поэтому отсутствие ключа и явные falsy 0/false/""/null неразличимы.
- **Обязанность 4.5:** Выполнить пятисостоянийную миграцию по факту наличия ключей (membership, не truthiness) и получить canonical endpointWaitTimeoutSeconds candidate. Только отсутствие обоих имён получает default 3600. Явно присутствующие 0/false/""/null не считаются отсутствием и должны остановить миграцию как невалидные до сохранения.
- **Изменение:** замена
- **Контракты:** §10l «Миграция конфигурации»; §10 «Требования к конечному комплекту»
- **Что менять нельзя:** Не использовать `or 3600` для определения присутствия; при конфликте двух имён не угадывать; не сохранять частично мигрированный профиль.
- **Миграция:** Атомарная config migration границы slice2.
- **Acceptance:** `ACC-MIG-010`, `ACC-MIG-011`, `ACC-MIG-012`, `ACC-MIG-013`, `ACC-MIG-014`, `ACC-MIG-018`
- **Откат:** Восстановить pre-migration backup config; не синтезировать alias.

### MAP-009 — срез 2 — `console_releases/4.5.0-s1/profile_store.py` / `endpoint timeout min`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `317–317`
- **Текущая обязанность:** Минимум проверяется после legacy truthy/default coercion; сообщение использует старое имя.
- **Обязанность 4.5:** Проверять canonical endpointWaitTimeoutSeconds не ниже CLAIM_LEASE_SECONDS=15; explicit falsy candidate не получает default. Ошибка называет новое canonical имя.
- **Изменение:** замена
- **Контракты:** §10l «Миграция конфигурации»
- **Что менять нельзя:** Не ослаблять минимум 15 и не превращать явно заданный 0 в default.
- **Миграция:** Атомарная config migration границы slice2.
- **Acceptance:** `ACC-MIG-014`, `ACC-MIG-018`
- **Откат:** Восстановить pre-migration backup config.

### MAP-010 — срез 2 — `console_releases/4.5.0-s1/profile_store.py` / `endpoint timeout max`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `319–319`
- **Текущая обязанность:** Максимум 7*24*3600 проверяется для старого имени.
- **Обязанность 4.5:** Проверять canonical endpointWaitTimeoutSeconds не выше 604800; ошибка называет новое canonical имя.
- **Изменение:** замена
- **Контракты:** §10l «Миграция конфигурации»
- **Что менять нельзя:** Не менять фактический максимум 604800.
- **Миграция:** Атомарная config migration границы slice2.
- **Acceptance:** `ACC-MIG-014`, `ACC-MIG-018`
- **Откат:** Восстановить pre-migration backup config.

### MAP-011 — срез 2 — `console_releases/4.5.0-s1/profile_store.py` / `endpoint timeout write`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `362–362`
- **Текущая обязанность:** Canonical profile write сохраняет старое имя endpointWaitTimeoutSec.
- **Обязанность 4.5:** После успешной пятисостоянийной миграции и валидации сохранять только endpointWaitTimeoutSeconds; старое имя не переживает canonical write.
- **Изменение:** замена
- **Контракты:** §10l «Миграция конфигурации»
- **Что менять нельзя:** Не сохранять оба имени и не удалять старое до успешной проверки всей migration transaction.
- **Миграция:** Атомарная config migration границы slice2.
- **Acceptance:** `ACC-MIG-010`, `ACC-MIG-011`, `ACC-MIG-012`, `ACC-MIG-013`, `ACC-MIG-014`, `ACC-MIG-018`
- **Откат:** Восстановить pre-migration backup config; не угадывать обратное значение.

### MAP-012 — срез 3a — `console_releases/4.5.0-s1/profile_store.py` / `_validate_profile`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `255–370`
- **Текущая обязанность:** files.attentionTimeoutSeconds отсутствует.
- **Обязанность 4.5:** Валидатор принимает и сохраняет files.attentionTimeoutSeconds; значение входит в snapshot.
- **Изменение:** добавление
- **Контракты:** §9 п.2; §4.2a
- **Что менять нельзя:** Не читать значение из живого профиля после создания Run.
- **Миграция:** Поле появляется только в новой схеме профиля.
- **Acceptance:** `ACC-S3A-003`
- **Откат:** Rollback требует восстановить профиль из pre-slice backup либо удалить поле осознанно.

### MAP-013 — срез 5 — `console_releases/4.5.0-s1/profile_store.py` / `_validate_profile`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `255–370`
- **Текущая обязанность:** directives — произвольный объект с ключами COMMAND_.
- **Обязанность 4.5:** Валидировать generic command definitions и настройки mirror input/output files для конкретной команды.
- **Изменение:** замена
- **Контракты:** §9 п.1,5; §9f; §9g
- **Что менять нельзя:** Не создавать отдельную глобальную модель команд.
- **Миграция:** К началу среза 5 `_validate_profile` уже несёт изменения среза 1; после среза 2 canonical `delivery.endpointWaitTimeoutSeconds` уже заменил старое имя, после среза 3a уже существует `files.attentionTimeoutSeconds`. Замена всего диапазона 253–368 обязана сохранить эти ранее внесённые байты и не откатывать их к baseline 4.4.0; новая command schema вступает только на границе 5+3b.
- **Acceptance:** `ACC-S5-002`
- **Откат:** Rollback разрушителен вместе с data/ новой схемы; config возвращается из backup.

### MAP-014 — срез 1 HISTORICAL — `console_releases/4.4.0/run_profile_context.py` / `RunProfileContext`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30409e1d3400c55424042eb55f1fc8fefc2de4d1e6f874dd40fd5c44f4a14ec4`
- **Точный диапазон:** `25–268`
- **Текущая обязанность:** Единственный создатель `profile-context.json` — сам `get:60`, который при отсутствии RESOLVED резолвит из result/status и пишет файл через `atomic_write_json:81`. Отдельного создателя нет; receiver его создать не может, так как `server.py` импортирует только stdlib и не имеет доступа к ProfileStore/ProfileResolver.
- **Обязанность 4.5:** Добавить явный создатель контекста Run на стороне console: разрешить binding/profile/session, получить или атомарно опубликовать immutable snapshot по §4.2a, затем записать `profile-context.json` со `snapshotDigest` и session provenance. Публикация снимка предшествует записи ссылки. Создатель идемпотентен и вызывается при первом обнаружении Run без контекста; после записи контекст неизменяем.
- **Изменение:** добавление
- **Контракты:** §4.2a «Публикация снимка атомарна… и только затем запись ссылки в Run»; §5.1
- **Что менять нельзя:** Создание контекста не переносится в receiver — это отдельный процесс релиза 2.10.0 без доступа к профилям; `list_runs:98` продолжает считать Run публичным по `result.json`, поэтому окно «Run виден, контекста ещё нет» существует и должно представляться состоянием разрешения, а не разрешением; при неудаче создания контекст не фабрикуется, `list_runs:106` не подменяет отказ псевдоконтекстом.
- **Миграция:** Старые Run не мигрируются; контекст создаётся только для Run новой схемы.
- **Acceptance:** `ACC-S1-004`, `ACC-S1-005`
- **Откат:** Откат удаляет только контексты и snapshot-объекты без выживших ссылок; каталоги Run не переписываются.

### MAP-015 — срез 1 HISTORICAL — `console_releases/4.4.0/run_profile_context.py` / `get`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30409e1d3400c55424042eb55f1fc8fefc2de4d1e6f874dd40fd5c44f4a14ec4`
- **Точный диапазон:** `60–85`
- **Текущая обязанность:** profile-context собирается из текущих файлов/полей Run.
- **Обязанность 4.5:** Читать неизменяемый data/<run>/profile-context.json со snapshotDigest и session provenance; Run без сессии допустим.
- **Изменение:** замена
- **Контракты:** §4.2a; §5.1
- **Что менять нельзя:** Не переписывать provenance после остановки/новой сессии.
- **Миграция:** Новые Run получают контекст при приёме; старые не мигрируются.
- **Acceptance:** `ACC-S1-004`, `ACC-S1-005`
- **Откат:** Rollback среза 1 возможен только до ломающей очистки; новые snapshot refs можно удалить по reachability.

### MAP-016 — срез 1 HISTORICAL — `console_releases/4.4.0/run_profile_context.py` / `authorize_execution`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30409e1d3400c55424042eb55f1fc8fefc2de4d1e6f874dd40fd5c44f4a14ec4`
- **Точный диапазон:** `87–148`
- **Текущая обязанность:** Проверяет профиль/привязку и текущий контекст.
- **Обязанность 4.5:** Серверная часть составного бизнес-шлюза: live profile enabled; binding exists+enabled и неизменность pinned profileId, role, chatType, conversationId, projectId; семантика исполнения берётся только из immutable snapshot Run.
- **Изменение:** замена
- **Контракты:** §5.1; §10k
- **Что менять нельзя:** ProfileSession.state не является входным шлюзом; остановленный session не отзывает уже принятый Run. Manual/effective tab-enabled здесь не проверяется и из присутствия endpoint не выводится: истина о `manual` принадлежит расширению (решение 2026-09-06). Перевод вкладки в OFF не отзывает локальное исполнение уже принятого Run.
- **Миграция:** Нет миграции старых Run.
- **Acceptance:** `ACC-S1-006`
- **Откат:** Rollback возвращает прежний шлюз только после удаления data/ новой схемы на breaking rollback.

### MAP-017 — срез 2 — `console_releases/4.5.0-s1/run_profile_context.py` / `endpoint timeout read/write`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/run_profile_context.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `1d833de7d454791effa0073af66996bdc1d0bb9758ef6a4a254748b23187e542`
- **Точный диапазон:** `391–391`
- **Текущая обязанность:** Одна строка одновременно читает delivery.endpointWaitTimeoutSec из snapshot/context source и пишет endpointWaitTimeoutSec в authorization result.
- **Обязанность 4.5:** Разделить доказательство обеих сторон переименования: читать только endpointWaitTimeoutSeconds из snapshot и выдавать только endpointWaitTimeoutSeconds наружу.
- **Изменение:** замена
- **Контракты:** §4.2a; §10l «Миграция конфигурации»
- **Что менять нельзя:** Не оставлять mixed old-read/new-write или new-read/old-write; обе стороны проверяются отдельно.
- **Миграция:** После profile migration Run snapshot новой схемы содержит только новое имя.
- **Acceptance:** `ACC-MIG-015`, `ACC-MIG-016`
- **Откат:** Rollback config/context from pre-migration backup; не угадывать alias.

### MAP-018 — срез 4 — `console_releases/4.5.0-s1/run_profile_context.py` / `authorize_delivery`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/run_profile_context.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `1d833de7d454791effa0073af66996bdc1d0bb9758ef6a4a254748b23187e542`
- **Точный диапазон:** `324–393`
- **Текущая обязанность:** Разрешает доставку через binding/endpoint и старую pinned-tab модель.
- **Обязанность 4.5:** Разрешать действие по правилу 5.3: текущая session только при совпадении profileId,snapshotDigest,bindingId,role,identity; иначе явное решение.
- **Изменение:** замена
- **Контракты:** §5.3; §9e; §10k
- **Что менять нельзя:** Не проверять browser ownership здесь; это уровень API poll.
- **Миграция:** К началу среза 4 строка 266 после среза 2 уже читает и выдаёт только `endpointWaitTimeoutSeconds`; замена `authorize_delivery` 199–268 обязана сохранить это новое имя и не восстановить `endpointWaitTimeoutSec`. Использует только Run новой схемы.
- **Acceptance:** `ACC-S4-001`, `ACC-S4-002`
- **Откат:** Rollback среза 4 возвращает старую маршрутизацию только при согласованной схеме endpoints.

### MAP-019 — срез 5 — `console_releases/4.5.0-s1/run_profile_context.py` / `RunProfileContext`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/run_profile_context.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `1d833de7d454791effa0073af66996bdc1d0bb9758ef6a4a254748b23187e542`
- **Точный диапазон:** `28–393`
- **Текущая обязанность:** К срезу 5 файл уже несёт создатель контекста среза 1, canonical `endpointWaitTimeoutSeconds` из среза 2 (`endpoint timeout read/write`) и правило 5.3 из среза 4 (`authorize_delivery`). Создатель фиксирует профиль, снимок, привязку и роль; активного сценария в провенансе нет.
- **Обязанность 4.5:** Фиксировать в провенансе Run активный сценарий и провенанс источника переключения — роль и bindingId. Run доигрывает под сценарием, с которым начался.
- **Изменение:** замена
- **Контракты:** §4.2a; §5.1; §5.3; журнал 2026-09-06
- **Что менять нельзя:** Замена диапазона не имеет права восстановить baseline 4.4.0: изменения срезов 1, 2 и 4 в этом файле сохраняются. Правило 5.3 сценарий не сравнивает: расхождение сценария Run и активного сценария профиля штатно сразу после переключения. Источником провенанса не является endpointId или вкладка — они не переживают перезапуск браузера.
- **Миграция:** Только Run новой схемы; старые не мигрируются.
- **Acceptance:** `ACC-S5-020`, `ACC-S5-021`
- **Откат:** Откат удаляет поля сценария в контекстах Run без выживших ссылок; каталоги Run не переписываются.

### MAP-020 — срез 1 HISTORICAL — `console_releases/4.4.0/console_server.py` / `ConsoleServer`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `b313552f6d82eff3ca0f596681fcee63efa1d0193299e0793b718613cb5dda2c`
- **Точный диапазон:** `31–905`
- **Текущая обязанность:** ConsoleServer wiring знает executor/delivery/profile/bindings/endpoints, но не ProfileSession/snapshot stores.
- **Обязанность 4.5:** Подключить foundation stores для immutable profile snapshots, ProfileSession и ProfileActivation; в slice1 не открывать вкладки и не запускать browser reconciler.
- **Изменение:** добавление
- **Контракты:** §4.2–4.2a; §6; §9c; §10 slice1
- **Что менять нельзя:** Секреты остаются только refs; profile edit не мутирует running session snapshot; profile.enabled остаётся live gate.
- **Миграция:** Создаются новые runtime/storage namespaces; old Run не мигрируются.
- **Acceptance:** `ACC-S1-011`, `ACC-S1-012`
- **Откат:** Удалить только session/snapshot state, не имеющее surviving references; config не трогать.

### MAP-021 — срез 1 HISTORICAL — `console_releases/4.4.0/console_server.py` / `list_runs`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `b313552f6d82eff3ca0f596681fcee63efa1d0193299e0793b718613cb5dda2c`
- **Точный диапазон:** `93–155`
- **Текущая обязанность:** Возвращает список всех Run без серверного profile filter.
- **Обязанность 4.5:** Поддержать profileId filter и duplicate metadata.
- **Изменение:** замена
- **Контракты:** §9 п.6,10; §10j
- **Что менять нельзя:** WebSocket filter не заменяет API filter.
- **Миграция:** Нет преобразования data.
- **Acceptance:** `ACC-S1-007`
- **Откат:** Кодовый rollback без миграции.

### MAP-022 — срез 1 HISTORICAL — `console_releases/4.4.0/console_server.py` / `run_detail`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `b313552f6d82eff3ca0f596681fcee63efa1d0193299e0793b718613cb5dda2c`
- **Точный диапазон:** `157–189`
- **Текущая обязанность:** Возвращает detail и большие логи без 50KiB presentation contract.
- **Обязанность 4.5:** Detail отдаёт укороченное UTF-8-safe представление >50KiB: 25KiB head + omitted byte count + 25KiB tail; полный лог отдельным endpoint.
- **Изменение:** замена
- **Контракты:** §9 п.9; §10i
- **Что менять нельзя:** Не обрезать полный download; AUTO ERROR excerpt/positions возвращаются отдельно.
- **Миграция:** Нет миграции.
- **Acceptance:** `ACC-S1-008`, `ACC-S1-009`
- **Откат:** Кодовый rollback без состояния.

### MAP-023 — срез 1 HISTORICAL — `console_releases/4.4.0/console_server.py` / `api_execute_step`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `b313552f6d82eff3ca0f596681fcee63efa1d0193299e0793b718613cb5dda2c`
- **Точный диапазон:** `338–365`
- **Текущая обязанность:** Запуск шага опирается на текущие plan/state/profile context.
- **Обязанность 4.5:** Перед запуском применяет бизнес-шлюз и snapshot provenance новой схемы.
- **Изменение:** замена
- **Контракты:** §4.2a; §10k
- **Что менять нельзя:** Не переносить generic pipeline сюда раньше среза 5.
- **Миграция:** Только новые Run.
- **Acceptance:** `ACC-S1-010`
- **Откат:** Кодовый rollback до границы 5.

### MAP-024 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `api_delivery_poll`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `768–788`
- **Текущая обязанность:** Аутентификация → parse tab → observe внутри swallowed try → poll_for_tab. Версии/pollKind/ownership нет.
- **Обязанность 4.5:** После auth валидировать extensionVersion+pollKind; CONTROL_AGENT арбитрирует lease; ENDPOINT требует ownership; version/ownership/barrier отказ — до observe; observe остаётся вне swallowed version errors.
- **Изменение:** замена
- **Контракты:** §9a; §9c; §10i; §10k; §10l
- **Что менять нельзя:** Барьер версии нельзя помещать в try 638–641; CONTROL_AGENT никогда не получает delivery.
- **Миграция:** Атомарная граница с extension 4.5; старый протокол отвергается до browser state mutation.
- **Acceptance:** `ACC-S2-001`, `ACC-S2-002`, `ACC-S2-003`, `ACC-S2-004`, `ACC-S2-005`, `ACC-S2-006`
- **Откат:** Rollback только согласованной парой server+extension после тишины.

### MAP-025 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `api_delivery_event`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `790–804`
- **Текущая обязанность:** События принимаются для job по старому lease token.
- **Обязанность 4.5:** В DRAIN принимать события только ранее захваченных jobs; не разрешать новый CLAIM; в BARRIER отвергать browser-state mutations старого/несогласованного protocol.
- **Изменение:** замена
- **Контракты:** §10l «Тишина»; §12
- **Что менять нельзя:** DRAIN не должен превращаться в полный barrier раньше доказанной тишины.
- **Миграция:** Миграционный gate, состояния DRAIN/BARRIER.
- **Acceptance:** `ACC-MIG-002`, `ACC-MIG-003`, `ACC-MIG-004`
- **Откат:** Rollback использует тот же двухфазный gate до уничтожения состояния.

### MAP-026 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `endpoint timeout consume`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `655–655`
- **Текущая обязанность:** api_delivery_prepare читает authorization.endpointWaitTimeoutSec и сохраняет внутренний job.profileDelivery.timeoutSec.
- **Обязанность 4.5:** Читать authorization.endpointWaitTimeoutSeconds; внутреннее поле timeoutSec может остаться внутренним, но старое profile key за границу не проходит.
- **Изменение:** замена
- **Контракты:** §10l «Миграция конфигурации»
- **Что менять нельзя:** Не путать schema key профиля с внутренним job timeoutSec.
- **Миграция:** Только новые authorization payload после slice2.
- **Acceptance:** `ACC-MIG-017`
- **Откат:** Rollback paired with config/context migration.

### MAP-027 — срез 1 HISTORICAL — `console_releases/4.4.0/console_server.py` / `create_app`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `b313552f6d82eff3ca0f596681fcee63efa1d0193299e0793b718613cb5dda2c`
- **Точный диапазон:** `919–965`
- **Текущая обязанность:** Нет явного API намеренного повторного Run.
- **Обязанность 4.5:** Добавить explicit repeatAsNew route для существующего canonical Run: создать новый Run с audit repeatOf/dedupeBypass, новым immutable snapshot/profile-context и теми же входными parse/file bytes; это единственный UI/API bypass dedupe.
- **Изменение:** добавление
- **Контракты:** §9 п.10; §4.2a; §10j
- **Что менять нельзя:** Не реализовывать repeat путём удаления dedupe index или изменения fingerprint canonical Run; новый Run получает новый provenance snapshot.
- **Миграция:** Нет миграции; действует только для new-schema Run.
- **Acceptance:** `ACC-S1-002`, `ACC-S1-018`
- **Откат:** Кодовый rollback; уже созданный intentional repeat остаётся обычным Run.

### MAP-028 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `create_app`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `1059–1106`
- **Текущая обязанность:** Маршруты Runs/profiles/bindings/endpoints/delivery; выбор endpoint выражен только устаревшим api_endpoint_pin.
- **Обязанность 4.5:** Зарегистрировать серверный route selectEndpoint(sessionId,bindingId,endpointId) как session-binding relation атомарной границы среза 2: live identity/auth check при вызове, запись только в session selection state.
- **Изменение:** добавление
- **Контракты:** §9a; §9e; §10i «Выбор endpoint — не переименование закрепления»
- **Что менять нельзя:** api_endpoint_pin нельзя просто переименовать в selectEndpoint; не писать approvedEndpointId в endpoint или binding; UI этой операции появляется только в 3a и не является условием её работы.
- **Миграция:** Старые pin/approved значения не переносятся в selection; выкатывается одной границей с endpoint/epoch моделью среза 2.
- **Acceptance:** `ACC-S2-007`, `ACC-LIVE-001`
- **Откат:** Rollback вместе с endpoint-space среза 2; selections не восстанавливаются как pins.

### MAP-029 — срез 3a — `console_releases/4.5.0-s1/console_server.py` / `create_app`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `1059–1106`
- **Текущая обязанность:** Маршруты Runs/profiles/bindings/endpoints/delivery; серверный selectEndpoint уже зарегистрирован в срезе 2.
- **Обязанность 4.5:** Добавить семейство artifact/file API и ProfileSession/activation API; зарегистрировать новые stores; UI-потребление уже существующего selectEndpoint не создаёт второй route.
- **Изменение:** добавление
- **Контракты:** §9d; §10i «четыре семейства»; §10j
- **Что менять нельзя:** Не дублировать и не переопределять selectEndpoint среза 2; выбор endpoint остаётся session-binding relation, а не свойством endpoint.
- **Миграция:** Новые state dirs создаются атомарно; старые Run не читаются.
- **Acceptance:** `ACC-S3A-004`, `ACC-S3A-005`
- **Откат:** При rollback удалить/игнорировать новые runtime stores только после тишины и reachability checks.

### MAP-030 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `api_endpoint_pin`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `948–972`
- **Текущая обязанность:** Глобально pin endpoint/tab.
- **Обязанность 4.5:** Удалить старую семантику pin из публичного API; выбор становится session-binding relation через отдельный route.
- **Изменение:** удаление
- **Контракты:** §10i «Выбор endpoint — не переименование закрепления»
- **Что менять нельзя:** Не писать approvedEndpointId в endpoint/binding.
- **Миграция:** Старые pin/approved значения не переносятся.
- **Acceptance:** `ACC-S2-008`
- **Откат:** Rollback не восстанавливает старые pins из новых selections.

### MAP-031 — срез 2 — `console_releases/4.5.0-s1/endpoint_registry.py` / `observe`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/endpoint_registry.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `e7aea1faa752dab6fdacb5f3e6572097006cc95d078368b3097d576206242c19`
- **Точный диапазон:** `100–178`
- **Текущая обязанность:** Реестр преимущественно tabId/page, допускает pin/approved/stale semantics.
- **Обязанность 4.5:** Ключ endpointId; browserEpoch; ONLINE/OFFLINE/CLOSED/EXPIRED; поздний pulse terminal endpoint не воскрешает; observe хранит только факты браузера.
- **Изменение:** замена
- **Контракты:** §9a
- **Что менять нельзя:** В endpoint не хранить bindingId/approved/identityConflict/stale; URL не участвует в identity evaluation.
- **Миграция:** Старые endpoints/pins не мигрируются как selections.
- **Acceptance:** `ACC-S2-009`, `ACC-S2-010`, `ACC-S2-011`, `ACC-S2-012`
- **Откат:** Rollback инвалидирует всё endpoint-space 4.5 и выключает legacy enabledTabs.

### MAP-032 — срез 2 — `console_releases/4.5.0-s1/endpoint_registry.py` / `list`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/endpoint_registry.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `e7aea1faa752dab6fdacb5f3e6572097006cc95d078368b3097d576206242c19`
- **Точный диапазон:** `188–192`
- **Текущая обязанность:** Декорирует старые endpoints/pin state.
- **Обязанность 4.5:** Возвращает observable endpoint state + epoch/presence без policy fields.
- **Изменение:** замена
- **Контракты:** §9a; §10j
- **Что менять нельзя:** Не скрывать OFFLINE на сервере — hide offline только UI filter.
- **Миграция:** Нет преобразования.
- **Acceptance:** `ACC-S2-013`
- **Откат:** Кодовый rollback после invalidation endpoint-space.

### MAP-033 — срез 2 — `console_releases/4.5.0-s1/endpoint_registry.py` / `pin`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/endpoint_registry.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `e7aea1faa752dab6fdacb5f3e6572097006cc95d078368b3097d576206242c19`
- **Точный диапазон:** `210–227`
- **Текущая обязанность:** Создаёт старое глобальное закрепление.
- **Обязанность 4.5:** Удалить.
- **Изменение:** удаление
- **Контракты:** §9a; §10i
- **Что менять нельзя:** Не преобразовывать pin в session selection.
- **Миграция:** Не переносится.
- **Acceptance:** `ACC-S2-008`
- **Откат:** Старый pin не восстанавливается автоматически.

### MAP-034 — срез 4 — `console_releases/4.5.0-s1/endpoint_registry.py` / `select_for_binding`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/endpoint_registry.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `e7aea1faa752dab6fdacb5f3e6572097006cc95d078368b3097d576206242c19`
- **Точный диапазон:** `252–276`
- **Текущая обязанность:** Выбор по старой binding/pin/tab политике.
- **Обязанность 4.5:** Разделить evaluate(target,endpoint) и select(target,candidates) по таблице 9a; session-owned endpoint имеет приоритет, ambiguity явная.
- **Изменение:** замена
- **Контракты:** §4.8; §9a; §9e
- **Что менять нельзя:** Никакого выбора по min tabId/first candidate.
- **Миграция:** Только endpointId новой схемы.
- **Acceptance:** `ACC-S4-003`, `ACC-S4-004`, `ACC-S4-005`
- **Откат:** Rollback требует старой endpoint schema.

### MAP-035 — срез 4 — `console_releases/4.5.0-s1/delivery_manager.py` / `create_job`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `281–614`
- **Текущая обязанность:** Target фиксируется по tabId/url; delivery files материализуются в job dir.
- **Обязанность 4.5:** Создавать immutable delivery manifest и logicalDeliveryId/sideEffect identity; target разрешён до endpointId, но bytes/names фиксируются манифестом.
- **Изменение:** замена
- **Контракты:** §9 п.4; §9e; §9f; §9g
- **Что менять нельзя:** Не брать «новейший файл» при последующей выгрузке sent attachments.
- **Миграция:** Новая delivery schema только для новых jobs.
- **Acceptance:** `ACC-S4-006`, `ACC-S4-007`
- **Откат:** Rollback с data cleanup на breaking boundary.

### MAP-036 — срез 4 — `console_releases/4.5.0-s1/delivery_manager.py` / `supersede_older_jobs_for_tab`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `1036–1069`
- **Текущая обязанность:** Вытесняет все nonterminal jobs по tabId.
- **Обязанность 4.5:** Вытеснять только предыдущую незавершённую попытку той же logical delivery, не все отправки в conversation: критерием становится идентичность logical delivery и её побочных эффектов (`logicalDeliveryId`), а не общий признак `tabId`.
- **Изменение:** замена
- **Контракты:** §10e «S4 final semantics»
- **Что менять нельзя:** Две законные последовательные отправки в один чат не конкурируют: они не вытесняют друг друга, а при необходимости исполняются в browser plane последовательно. Замена в срезе 4 перекрывает те же байты `1036–1069`, что и строка среза 2 `MAP-083` / `supersede_older_jobs_for_tab` — это намеренное последовательное изменение одного символа разными срезами, а не скрытое пересечение. Replacement в срезе 4 ОБЯЗАН сохранить введённую срезом 2 защиту аренды и односместности, пока новая машина состояний logical delivery не даст эквивалентного или более сильного доказательства. Отменить `ACC-S2-033` срез 4 не вправе.
- **Миграция:** Новая job identity.
- **Acceptance:** `ACC-S4-008`
- **Откат:** Rollback вместе с delivery schema.

### MAP-037 — срез 2 — `console_releases/4.5.0-s1/delivery_manager.py` / `_lease_is_active`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `1102–1105`
- **Текущая обязанность:** Активность lease = claimLeaseToken && claimExpiresAt>now.
- **Обязанность 4.5:** Сохранить как компонент quiescence predicate; во время DRAIN фиксировать факт lease-expired-during-drain как unsafe latch.
- **Изменение:** добавление
- **Контракты:** §10l «Тишина»
- **Что менять нельзя:** Само истечение lease не доказывает тишину.
- **Миграция:** Drain marker относится только к окну миграции.
- **Acceptance:** `ACC-MIG-005`, `ACC-MIG-006`
- **Откат:** Rollback также запрещён при unsafe latch.

### MAP-038 — срез 2 — `console_releases/4.5.0-s1/delivery_manager.py` / `poll_for_tab`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `1208–1243`
- **Текущая обязанность:** recover expired lease → выбирает newest candidate by tabId/page.
- **Обязанность 4.5:** В DRAIN не выдаёт новых jobs; в normal mode выдача после endpoint ownership/business authorization и по endpointId. Дополнительно несёт односместность вкладки, введённую строкой `MAP-083`: к выдаче допускается только `NO_LEASE`, любой другой след — `ACTIVE`, `EXPIRED`, `INVALID` — блокирует текущую итерацию, а нечитаемое сохранённое задание считает вкладку занятой, а не свободной. Кандидат берётся из доказанного порядка Prepare, а не из сортировки `createdAt` как строки. Восстановление, отложенное вытеснение и решение выполняются под одним замком: доказав, что вкладка свободна от аренды, опрос применяет вытеснение, пропущенное при создании новых заданий, и только потом выбирает кандидата.
- **Изменение:** замена
- **Контракты:** §10i; §10l; §10e «S2 transitional safety»
- **Что менять нельзя:** recover_expired_leases не должен снять unsafe и тем самым разрешить cutover. Односместность не заменяет отчётности слива: захваченное задание остаётся в `outstanding`. `EXPIRED` не пропускается на том основании, что восстановление уже отработало: между проходом и решением часы читаются заново. Отложенное вытеснение выполняется только над доказанным `NO_LEASE` и только после ворот — это не повод вернуть вытеснение поверх `ACTIVE`, `EXPIRED` или `INVALID`. Порядок Prepare не берётся из строкового сравнения и не разрешается обходом каталогов: недоказуемый порядок — это отказ, а не выбор наугад.
- **Миграция:** Первый compatibility boundary.
- **Acceptance:** `ACC-MIG-007`, `ACC-S2-014`, `ACC-S2-033`
- **Откат:** Rollback после browser quiet.

### MAP-039 — срез 2 — `console_releases/4.5.0-s1/delivery_manager.py` / `update_from_client`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `1245–1381`
- **Текущая обязанность:** CLAIM/heartbeat/state transitions на старой tabId lease модели.
- **Обязанность 4.5:** DRAIN: existing lease events разрешены, новый CLAIM запрещён; BARRIER: старый protocol не меняет state. Авторизация вызывающего по `target.tabId` стоит выше идемпотентного возврата терминального и `PAUSED_AFTER_RESTART` задания.
- **Изменение:** замена
- **Контракты:** §10l; §10i «Порядок проверок»
- **Что менять нельзя:** Не закрывать канал событий ранее, чем existing claimed jobs завершатся. Терминальное состояние — причина ничего не делать, а не причина не спрашивать, кто звонит: идемпотентный возврат не должен стоять раньше авторизации. Принадлежность вкладке доказывается общим классификатором цели, а не собственным `int()` над сохранённым значением: `int(True)` равен 1, поэтому повреждённая цель отвечала как исправный номер вкладки, а `int('bad')` уходил исключением мимо отказа.
- **Миграция:** Gate transition DRAIN→BARRIER.
- **Acceptance:** `ACC-MIG-002`, `ACC-MIG-003`, `ACC-S2-034`
- **Откат:** Rollback same.

### MAP-040 — срез 5 — `console_releases/4.5.0-s1/delivery_manager.py` / `pause_unfinished_jobs_after_restart`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `974–1034`
- **Текущая обязанность:** Все незавершённые jobs становятся PAUSED_AFTER_RESTART без причины.
- **Обязанность 4.5:** Восстановление по delivery journal: SENT=no repeat; PREPARED=continue; DISPATCHING→OUTCOME_UNKNOWN.
- **Изменение:** замена
- **Контракты:** §9g; §12 «Срез 5»
- **Что менять нельзя:** OUTCOME_UNKNOWN не повторяется автоматически.
- **Миграция:** Вторая атомарная граница server+extension.
- **Acceptance:** `ACC-S5-003`, `ACC-S5-004`, `ACC-S5-005`
- **Откат:** Rollback очищает journal только после quiescence.

### MAP-041 — срез 5 — `console_releases/4.5.0-s1/protocol_engine.py` / `EXECUTABLE_TYPES`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/protocol_engine.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `c436b29afd873fd78c8c37187a6d6baba05e7a257a81c721d5514abe57d5ba20`
- **Точный диапазон:** `12–20`
- **Текущая обязанность:** Жёсткий перечень COMMAND_* типов.
- **Обязанность 4.5:** Generic directive/action definitions компилируются в immutable action plan; legacy names возможны только как transitional parser input.
- **Изменение:** замена
- **Контракты:** §9f; §9g
- **Что менять нельзя:** Не менять файл до среза 5.
- **Миграция:** Breaking plan schema; old Run data очищается.
- **Acceptance:** `ACC-S5-006`
- **Откат:** Rollback требует data cleanup.

### MAP-042 — срез 5 — `console_releases/4.5.0-s1/protocol_engine.py` / `CONTROL_TYPES`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/protocol_engine.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `c436b29afd873fd78c8c37187a6d6baba05e7a257a81c721d5514abe57d5ba20`
- **Точный диапазон:** `22–26`
- **Текущая обязанность:** Отдельный hard-coded набор control COMMAND_* типов.
- **Обязанность 4.5:** Control semantics выражаются generic action definitions/state, transitional constants удаляются по плану cleanup.
- **Изменение:** замена
- **Контракты:** §9f; §9g
- **Что менять нельзя:** Slice ownership строго 5.
- **Миграция:** Breaking schema.
- **Acceptance:** `ACC-S5-007`
- **Откат:** Rollback requires data cleanup.

### MAP-043 — срез 5 — `console_releases/4.5.0-s1/protocol_engine.py` / `build_plan`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/protocol_engine.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `c436b29afd873fd78c8c37187a6d6baba05e7a257a81c721d5514abe57d5ba20`
- **Точный диапазон:** `51–163`
- **Текущая обязанность:** Строит текущий step plan из parser JSON.
- **Обязанность 4.5:** Компилирует immutable definitions/dependency graph/provenance отдельно от mutable execution state; action/sideEffect identity сохраняется до внешнего вызова.
- **Изменение:** замена
- **Контракты:** §9f; §9g
- **Что менять нельзя:** После restart graph не перекомпилировать.
- **Миграция:** Old plans not migrated.
- **Acceptance:** `ACC-S5-008`, `ACC-S5-009`
- **Откат:** Rollback destroys new data schema.

### MAP-044 — срез 5 — `console_releases/4.5.0-s1/executor.py` / `execute_step`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/executor.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `cceb102e0af7a3f25faa9a634b0f6135e6a52ab3a40b0d958b94ce5b580b7b25`
- **Точный диапазон:** `278–357`
- **Текущая обязанность:** Hard-coded dispatch по COMMAND_RUN/PUT_FILES/GET_REPORTS/...; RUNNING state.
- **Обязанность 4.5:** Исполнять generic action pipeline, lifecycle states и sideEffect boundary; final status derives from new mutable state.
- **Изменение:** замена
- **Контракты:** §9f; §9g
- **Что менять нельзя:** Не менять до среза 5; local execution must remain distinct from browser delivery.
- **Миграция:** Breaking 5+3b.
- **Acceptance:** `ACC-S5-010`, `ACC-S5-011`
- **Откат:** Rollback destroys new data and delivery journal after quiet.

### MAP-045 — срез 5 — `console_releases/4.5.0-s1/executor.py` / `_execute_put_files`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/executor.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `cceb102e0af7a3f25faa9a634b0f6135e6a52ab3a40b0d958b94ce5b580b7b25`
- **Точный диапазон:** `1004–1043`
- **Текущая обязанность:** Берёт source только из files/ текущего Run, проверяет destination и копирует.
- **Обязанность 4.5:** Подключить file resolution ladder: pinned Run artifact → same-Run artifact → NEEDS_ATTENTION parallel paths → fallback latest → FILE_ACQUIRE_FAILED; материализовать requested destination atomically.
- **Изменение:** замена
- **Контракты:** §9 п.2; §9d; §10b
- **Что менять нельзя:** Не использовать objects/<sha> как destination; не молчать при substitution; first resolver wins atomically.
- **Миграция:** Выкатывается только вместе со срезом 5.
- **Acceptance:** `ACC-S3B-001`, `ACC-S3B-002`, `ACC-S3B-003`, `ACC-S3B-004`
- **Откат:** Rollback destroys new run manifests/file-resolution state after quiet.

### MAP-046 — срез 5 — `console_releases/4.5.0-s1/executor.py` / `_execute_command`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/executor.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `cceb102e0af7a3f25faa9a634b0f6135e6a52ab3a40b0d958b94ce5b580b7b25`
- **Точный диапазон:** `735–959`
- **Текущая обязанность:** Feeds ExecutionErrorDetector on raw stdout+stderr.
- **Обязанность 4.5:** Сохранять absolute output match positions/excerpt data для AUTO ERROR и new action state.
- **Изменение:** замена
- **Контракты:** §9 п.3; §10i
- **Что менять нельзя:** Позиции считаются по полномасштабному output, не по truncated UI log.
- **Миграция:** Новая state schema.
- **Acceptance:** `ACC-S5-012`
- **Откат:** Rollback with data cleanup.

### MAP-047 — срез 5 — `console_releases/4.5.0-s1/executor.py` / `_handle_control`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/executor.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `cceb102e0af7a3f25faa9a634b0f6135e6a52ab3a40b0d958b94ce5b580b7b25`
- **Точный диапазон:** `1117–1124`
- **Текущая обязанность:** Управляющая директива лишь помечается обработанной оператором; эффектов уровня профиля нет.
- **Обязанность 4.5:** Применять эффекты команды при обработке шага: переключение сценария, пауза, стоп процесса профиля, прекращение Run. Дублирования команды выполняются до эффектов.
- **Изменение:** замена
- **Контракты:** §9f; §9g; §4.5; §5.1; журнал 2026-09-06
- **Что менять нельзя:** Не менять до среза 5. Эффект не переписывает замороженную семантику идущего Run. `STOP_RUN` и `CONTINUE_RUN` остаются условиями шага и эффектами команды не являются. Прекращение Run — отдельная операция уровня Run, а не частный случай стопа профиля.
- **Миграция:** Ломающая граница 5+3b.
- **Acceptance:** `ACC-S5-022`, `ACC-S5-023`, `ACC-S5-024`
- **Откат:** Rollback разрушает новую схему состояния после доказанной тишины.

### MAP-048 — срез 5 — `console_releases/4.5.0-s1/execution_error_detector.py` / `feed`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/execution_error_detector.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `b6d182c1e1579ca4e2fc45606f1ecdefd8677a776b9458478f88cf096e3ed8b9`
- **Точный диапазон:** `89–113`
- **Текущая обязанность:** Хранит id/description/excerpt без абсолютных позиций.
- **Обязанность 4.5:** Возвращать устойчивые offsets matchStart/matchEnd и excerpt range по полному потоку с учётом rolling tail.
- **Изменение:** замена
- **Контракты:** §9 п.3; §10i
- **Что менять нельзя:** Не считать offset относительно только текущего chunk/tail.
- **Миграция:** Нет отдельной миграции, результаты новых Run.
- **Acceptance:** `ACC-S5-013`
- **Откат:** Кодовый rollback только вместе с state schema.

### MAP-049 — срез 2 — `console_releases/4.5.0-s1/chat_bindings.py` / `_validate`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/chat_bindings.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `3129ebe1336a589176f5164b5639ac248826f52fb6e6d0a7ab0d45809ec42f0c`
- **Точный диапазон:** `69–114`
- **Текущая обязанность:** Нормализует endpointPolicy и approvedEndpointId; approved_endpoint reserved.
- **Обязанность 4.5:** Удалить endpointPolicy/approvedEndpointId из binding schema; binding описывает chat identity/profile/role/enabled.
- **Изменение:** замена
- **Контракты:** §9a; §10i; §10l
- **Что менять нельзя:** Не переносить approvedEndpointId как session selection.
- **Миграция:** Старые поля отбрасываются при migration с backup; их значение не интерпретируется.
- **Acceptance:** `ACC-S2-015`
- **Откат:** Rollback не реконструирует approved state.

### MAP-050 — срез 2 — `console_releases/4.5.0-s1/profile_resolver.py` / `resolve`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_resolver.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `e316c0cf61203d3bd5f822bb949c24eacec6730547cc233528e3bab2f18aae20`
- **Точный диапазон:** `41–102`
- **Текущая обязанность:** Имеет ветку policy=approved_endpoint → ENDPOINT_NOT_APPROVED.
- **Обязанность 4.5:** Удалить approved_endpoint branch; resolver определяет binding/profile identity, endpoint selection выполняется отдельной 9a/9e логикой.
- **Изменение:** удаление
- **Контракты:** §9a; §9e; §10l
- **Что менять нельзя:** Не смешивать profile resolution с endpoint selection.
- **Миграция:** Согласовано с binding migration.
- **Acceptance:** `ACC-S2-016`
- **Откат:** Rollback needs old binding config backup.

### MAP-051 — срез 2 — `extension_releases/2.11.6/manifest.json` / `permissions`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/manifest.json`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `741453d48162ed8df785c09b6058146bf9513a4d19e6538397ac4b56a8d2278e`
- **Точный диапазон:** `6–6`
- **Текущая обязанность:** storage, activeTab, tabs, scripting, downloads.
- **Обязанность 4.5:** Добавить permission alarms.
- **Изменение:** добавление
- **Контракты:** §10e; §10g
- **Что менять нельзя:** Не менять host permissions без отдельной причины.
- **Миграция:** Extension package 4.5 only.
- **Acceptance:** `ACC-S2-017`
- **Откат:** Rollback extension package removes alarms permission.

### MAP-052 — срез 2 — `extension_releases/2.11.6/background.js` / `isTabEnabled`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/background.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30830c99ec58a33b1ee7ba7fa190b374cecfc6c266a82cb1a11444d900eb87e7`
- **Точный диапазон:** `74–77`
- **Текущая обязанность:** Булево enabledTabs[tabId] в storage.session.
- **Обязанность 4.5:** effective enabled = manual OR profile-session:<id>; epoch-bound tabId→endpointId/manual state в storage.local, session lease cache non-authoritative.
- **Изменение:** замена
- **Контракты:** §4.3; §10e–10g
- **Что менять нельзя:** Не переносить manual reason на reused tabId/new epoch.
- **Миграция:** 2.11.6 enabledTabs migration conditional table below.
- **Acceptance:** `ACC-S2-018`, `ACC-S2-019`
- **Откат:** Rollback invalidates 4.5 epoch mappings/manual/session lease cache and forces legacy enabledTabs OFF.

### MAP-053 — срез 2 — `extension_releases/2.11.6/background.js` / `tabs.onRemoved`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/background.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30830c99ec58a33b1ee7ba7fa190b374cecfc6c266a82cb1a11444d900eb87e7`
- **Точный диапазон:** `956–960`
- **Текущая обязанность:** Удаляет legacy session tab/status.
- **Обязанность 4.5:** Если owner epoch: послать CLOSED, удалить tabId→endpointId и manual reason; non-owner не меняет server browser state.
- **Изменение:** замена
- **Контракты:** §9a; §10i
- **Что менять нельзя:** CLOSED terminal; late pulse same endpoint ignored server-side.
- **Миграция:** New epoch mapping only.
- **Acceptance:** `ACC-S2-020`, `ACC-S2-021`
- **Откат:** Rollback invalidates mapping.

### MAP-054 — срез 2 — `extension_releases/2.11.6/background.js` / `GET_RUNTIME_CONFIG`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/background.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30830c99ec58a33b1ee7ba7fa190b374cecfc6c266a82cb1a11444d900eb87e7`
- **Точный диапазон:** `1293–1312`
- **Текущая обязанность:** Отдаёт legacy enabled/tab config.
- **Обязанность 4.5:** Отдаёт browserEpoch, endpointId, extensionVersion, effectiveEnabled; только после initialization barrier.
- **Изменение:** замена
- **Контракты:** §10f–10i
- **Что менять нельзя:** До ready не запускать pulse/poll/reconcile.
- **Миграция:** ensureEpoch handles 2.11.6→4.5.
- **Acceptance:** `ACC-S2-022`, `ACC-S2-023`
- **Откат:** Rollback clears 4.5 state.

### MAP-055 — срез 2 — `extension_releases/2.11.6/background.js` / `SESSION_TABS_KEY`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/background.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30830c99ec58a33b1ee7ba7fa190b374cecfc6c266a82cb1a11444d900eb87e7`
- **Точный диапазон:** `24–24`
- **Текущая обязанность:** enabledTabs key session storage.
- **Обязанность 4.5:** Добавить startup/onInstalled/alarms reconciler рядом с state bootstrap: onStartup=new epoch; onInstalled ensure existing epoch; alarm CONTROL_AGENT heartbeat even zero tabs.
- **Изменение:** добавление
- **Контракты:** §10e–10h
- **Что менять нельзя:** onInstalled update не объявляет browser restart; reconciler не исполняет chat actions.
- **Миграция:** Initial epoch created on update if absent.
- **Acceptance:** `ACC-S2-024`, `ACC-S2-025`, `ACC-S2-026`
- **Откат:** Rollback cancels alarms by old package and invalidates local 4.5 keys.

### MAP-056 — срез 2 — `extension_releases/2.11.6/chat-bridge.js` / `runtimeConfig`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/chat-bridge.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `71272004262ef21e19cc75d0c2ce19fb242bf5d04afde1c1213f9d4b43a2c7e4`
- **Точный диапазон:** `161–171`
- **Текущая обязанность:** Получает tabId/enabled; legacy bridge polls by tabId/page.
- **Обязанность 4.5:** Получает/проверяет endpointId,browserEpoch,extensionVersion,effectiveEnabled; OFF прекращает endpoint poll without changing endpointId during same epoch.
- **Изменение:** замена
- **Контракты:** §9a; §10g–10i
- **Что менять нельзя:** Refresh/OFF не должен сам включать вкладку.
- **Миграция:** Requires background 4.5 same boundary.
- **Acceptance:** `ACC-S2-027`, `ACC-LIVE-002`, `ACC-LIVE-003`
- **Откат:** Rollback only paired extension/server.

### MAP-057 — срез 2 — `extension_releases/2.11.6/chat-bridge.js` / `loop`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/chat-bridge.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `71272004262ef21e19cc75d0c2ce19fb242bf5d04afde1c1213f9d4b43a2c7e4`
- **Точный диапазон:** `1853–1927`
- **Текущая обязанность:** GET poll с tabId/page, затем process delivery.
- **Обязанность 4.5:** pollKind=ENDPOINT + epoch/endpoint identity; delivery только своему endpoint; NOT_CONTROL_OWNER triggers control-agent reacquire path, conflict blocks. Пока браузер держит `ACTIVE` аренду доставки и выполняет потенциально долгую операцию с вложением, он шлёт `HEARTBEAT` с интервалом не более 5 секунд и независимо от ожидания ответа chunk: аренда 15 секунд, максимальный интервал отправки — треть срока. Ответ chunk аренду не обновляет и продлением не считается. Неуспешный `HEARTBEAT` продлением тоже не считается: при утрате доказательства живой аренды цикл не продолжает работу так, будто аренда продлена. Требование относится к каденции отправки браузером, а не к величине разрыва между сохранёнными на сервере продлениями — задержанный или потерянный ответ не делает исправное расширение нарушителем. Цикл прекращается только после терминального принятого исхода или `RELEASE`, либо после явного отказа сервера, после которого доставка этому браузеру больше не принадлежит.
- **Изменение:** замена
- **Контракты:** §10i
- **Что менять нельзя:** Обратный забор не опирается на код ответа: сервер среза 1 на CONTROL_AGENT без `tabId` отвечает `200 {"ok":true,"job":null}`, а состояние не меняет лишь потому, что `EndpointRegistry.observe` отвергает отрицательный `tabId` (строки 102–103) и отказ проглатывается. Полагаться на это совпадение нельзя — разрешением служит только положительное доказательство владения. Legacy fallback на протокол 2.11.6 запрещён. Не выводить pollKind из отсутствия tabId; old epoch cannot observe.
- **Миграция:** First atomic boundary.
- **Acceptance:** `ACC-S2-028`, `ACC-S2-029`, `ACC-S2-030`, `ACC-S2-032`, `ACC-S2-036`
- **Откат:** Rollback paired.

### MAP-058 — срез 5 — `extension_releases/2.11.6/chat-bridge.js` / `RECOVERY_SOURCE_KEY`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/chat-bridge.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `71272004262ef21e19cc75d0c2ce19fb242bf5d04afde1c1213f9d4b43a2c7e4`
- **Точный диапазон:** `15–15`
- **Текущая обязанность:** Хранит только last submitted recovery source.
- **Обязанность 4.5:** Отдельный durable delivery journal PREPARED→DISPATCHING→SENT, не привязанный к browserEpoch; sideEffectKey persisted before first DOM external effect.
- **Изменение:** замена
- **Контракты:** §9g; §10f; §12
- **Что менять нельзя:** Не очищать journal до quiescence; DISPATCHING не retry automatically.
- **Миграция:** Second atomic boundary.
- **Acceptance:** `ACC-S5-014`, `ACC-S5-015`
- **Откат:** Rollback clears journal only after quiet.

### MAP-059 — срез 1 HISTORICAL — `console_releases/4.4.0/static/app.js` / `refreshRuns`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `4e1a5e494e74dfda8e4fc78056b6dbca79d1e8fd4d71a30061e4411b02bcf009`
- **Точный диапазон:** `166–170`
- **Текущая обязанность:** GET /api/runs без profile filter.
- **Обязанность 4.5:** Передавать выбранный profileId filter и показывать duplicate metadata.
- **Изменение:** замена
- **Контракты:** §9 п.6,10; §10j
- **Что менять нельзя:** UI не фильтрует единственно локально — сервер тоже фильтрует.
- **Миграция:** Нет.
- **Acceptance:** `ACC-S1-007`
- **Откат:** Кодовый rollback.

### MAP-060 — срез 1 HISTORICAL — `console_releases/4.4.0/static/app.js` / `renderRuns`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `4e1a5e494e74dfda8e4fc78056b6dbca79d1e8fd4d71a30061e4411b02bcf009`
- **Точный диапазон:** `177–194`
- **Текущая обязанность:** Рисует базовую строку Run.
- **Обязанность 4.5:** Показывать profile/session provenance и «повтор уже принят как Run X»/duplicateCount; для canonical Run дать явное действие «Повторить как новый Run», вызывающее только repeatAsNew API.
- **Изменение:** замена
- **Контракты:** §9 п.10; §10j
- **Что менять нельзя:** Не выдавать duplicate как новый Run; обычный refresh/открытие detail не bypass dedupe.
- **Миграция:** Нет.
- **Acceptance:** `ACC-S1-002`, `ACC-S1-018`
- **Откат:** Кодовый rollback.

### MAP-061 — срез 1 HISTORICAL — `console_releases/4.4.0/static/app.js` / `setView`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `4e1a5e494e74dfda8e4fc78056b6dbca79d1e8fd4d71a30061e4411b02bcf009`
- **Точный диапазон:** `1060–1073`
- **Текущая обязанность:** 4 раздела.
- **Обязанность 4.5:** Расширить view-router до пятого Files view как UI scaffold с явным loading/not-ready состоянием; до slice3a он не должен имитировать локальное file storage или обходить отсутствующий server API.
- **Изменение:** замена
- **Контракты:** §9 п.8; §10d; §10j
- **Что менять нельзя:** Не смешивать Files storage и per-Run source files; команды остаются slice5.
- **Миграция:** Slice1 добавляет только route/view scaffold; рабочие file операции активируются в 3a.
- **Acceptance:** `ACC-S1-017`
- **Откат:** Кодовый rollback.

### MAP-062 — срез 3a — `console_releases/4.5.0-s1/static/app.js` / `setView`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/app.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110`
- **Точный диапазон:** `1093–1106`
- **Текущая обязанность:** Files view scaffold существует после slice1, но file API ещё не подключён.
- **Обязанность 4.5:** Подключить Files view к server artifacts API и operator-attention transitions; убрать not-ready state только после готовности API.
- **Изменение:** замена
- **Контракты:** §9 п.8; §10j
- **Что менять нельзя:** Не делать client-only хранилище; server API остаётся источником истины.
- **Миграция:** Requires 3a artifact API.
- **Acceptance:** `ACC-S3A-006`
- **Откат:** Кодовый rollback.

### MAP-063 — срез 3a — `console_releases/4.5.0-s1/static/app.js` / `renderEndpoints`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/app.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110`
- **Точный диапазон:** `1405–1447`
- **Текущая обязанность:** К срезу 3a `renderEndpoints` уже показывает единственную запись `VERSION_MISMATCH` из среза 2. Показывает endpoints старой модели.
- **Обязанность 4.5:** UI filter «скрыть офлайн» скрывает только benign OFFLINE, но не состояния внимания/конфликтов.
- **Изменение:** замена
- **Контракты:** §9 п.7; §10j
- **Что менять нельзя:** Замена не имеет права убрать отображение `VERSION_MISMATCH` среза 2 и не заводит вторую копию факта. Фильтр не меняет registry state.
- **Миграция:** Нет.
- **Acceptance:** `ACC-S3A-007`
- **Откат:** Кодовый rollback.

### MAP-064 — срез 2 — `console_releases/4.5.0-s1/static/app.js` / `profile delivery default`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/app.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110`
- **Точный диапазон:** `1142–1142`
- **Текущая обязанность:** Default endpointWaitTimeoutSec=3600.
- **Обязанность 4.5:** Новое имя endpointWaitTimeoutSeconds=3600.
- **Изменение:** замена
- **Контракты:** §10l «Миграция конфигурации»
- **Что менять нельзя:** Default должен совпадать с validator migration default.
- **Миграция:** Пять состояний ниже.
- **Acceptance:** `ACC-MIG-014`
- **Откат:** Rollback from config backup.

### MAP-065 — срез 2 — `console_releases/4.5.0-s1/static/app.js` / `profile delivery load`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/app.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110`
- **Точный диапазон:** `1166–1166`
- **Текущая обязанность:** Читает endpointWaitTimeoutSec.
- **Обязанность 4.5:** Читает endpointWaitTimeoutSeconds; migration API не заставляет UI угадывать конфликт двух имён.
- **Изменение:** замена
- **Контракты:** §10l
- **Что менять нельзя:** При конфликте migration должна остановиться до UI save.
- **Миграция:** Config migration.
- **Acceptance:** `ACC-MIG-010`, `ACC-MIG-012`
- **Откат:** Rollback from backup.

### MAP-066 — срез 2 — `console_releases/4.5.0-s1/static/app.js` / `profile delivery save`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/app.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110`
- **Точный диапазон:** `1284–1284`
- **Текущая обязанность:** Пишет endpointWaitTimeoutSec.
- **Обязанность 4.5:** Пишет только endpointWaitTimeoutSeconds.
- **Изменение:** замена
- **Контракты:** §10l
- **Что менять нельзя:** Не сохранять оба имени.
- **Миграция:** Config migration.
- **Acceptance:** `ACC-MIG-011`, `ACC-MIG-013`
- **Откат:** Rollback from backup.

### MAP-067 — срез 5 — `console_releases/4.5.0-s1/static/app.js` / `renderProfileRoles`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/app.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110`
- **Точный диапазон:** `1223–1241`
- **Текущая обязанность:** Profile editor adjacent to raw directives tab.
- **Обязанность 4.5:** Команды — карточки/add/edit/remove, mirror input/output files; direct link from main interface.
- **Изменение:** добавление
- **Контракты:** §9 п.1,5; §10j
- **Что менять нельзя:** Не редактировать global commands outside profile.
- **Миграция:** Profile schema 5.
- **Acceptance:** `ACC-S5-016`
- **Откат:** Rollback profile config from backup.

### MAP-068 — срез 2 — `console_releases/4.5.0-s1/static/app.js` / `renderEndpoints`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/app.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `da78b9663005e780972f8f4973aad5116308b12b0013ab32fe2254de4d86b110`
- **Точный диапазон:** `1405–1447`
- **Текущая обязанность:** Список endpoint без сведений о версии расширения; расхождение версий показать негде.
- **Обязанность 4.5:** Показывать единственную авторитетную запись `VERSION_MISMATCH`: ожидаемая версия, объявленная клиентом, `firstSeenAt`, `lastSeenAt`, идентичность endpoint и `profileId`, если он уже авторитетно разрешён. Профильная сводка строится из этой же записи, а не из второй копии.
- **Изменение:** замена
- **Контракты:** §9a; §10k; журнал 2026-09-07
- **Что менять нельзя:** Не заводить вторую копию факта на профиле — иначе endpoint уже совместим, одна копия очищена, вторая осталась. `VERSION_MISMATCH` не отображается как `PAUSED`: паузы в срезе 2 не существует, и показывать её раньше среза 5 значит показывать несуществующее состояние. Повторные несовместимые опросы обновляют `lastSeenAt` и не плодят события.
- **Миграция:** Нет; запись живёт в состоянии endpoint.
- **Acceptance:** `ACC-S2-031`
- **Откат:** Rollback вместе с границей среза 2; записи расхождения отбрасываются.

### MAP-069 — срез 1 HISTORICAL — `console_releases/4.4.0/static/index.html` / `navigation`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `3f8bf767668161e33934defba41bfad59c9fd318d79c09f5a7dfd5cd2d67fe99`
- **Точный диапазон:** `42–42`
- **Текущая обязанность:** Четыре nav buttons.
- **Обязанность 4.5:** Добавить пятую кнопку Files и slice1 controls для profile Runs filter/session provenance; Files panel до 3a явно not-ready, но navigation/view wiring уже существует.
- **Изменение:** добавление
- **Контракты:** §9 п.6,8; §10d; §10j
- **Что менять нельзя:** Не превращать navigation в источник state; не показывать фиктивные file actions до API.
- **Миграция:** No data migration.
- **Acceptance:** `ACC-S1-007`, `ACC-S1-017`
- **Откат:** HTML rollback.

### MAP-070 — срез 5 — `console_releases/4.5.0-s1/static/index.html` / `profile directives`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/index.html`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `19056b796757ae25e434fc113c9b3c8ea486c3fdc5fd0d321a8c26a4a09f300f`
- **Точный диапазон:** `237–237`
- **Текущая обязанность:** Сырая JSON textarea вкладки directives.
- **Обязанность 4.5:** Заменить на вкладку «Команды» с card editor.
- **Изменение:** замена
- **Контракты:** §9 п.5; §10j
- **Что менять нельзя:** Только slice5.
- **Миграция:** Profile schema 5.
- **Acceptance:** `ACC-S5-016`
- **Откат:** Rollback config+UI together.

### MAP-071 — срез 3a — `console_releases/4.5.0-s1/static/index.html` / `profile delivery`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/index.html`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `19056b796757ae25e434fc113c9b3c8ea486c3fdc5fd0d321a8c26a4a09f300f`
- **Точный диапазон:** `243–243`
- **Текущая обязанность:** Delivery settings panel со старым timeout.
- **Обязанность 4.5:** Новое имя timeout + files.attentionTimeoutSeconds и file-storage controls.
- **Изменение:** замена
- **Контракты:** §9d; §10l
- **Что менять нельзя:** Не сохранять поле, не поддержанное validator.
- **Миграция:** Config migration.
- **Acceptance:** `ACC-S3A-003`, `ACC-MIG-019`
- **Откат:** Rollback from backup.

### MAP-072 — срез 3a — `console_releases/4.5.0-s1/static/index.html` / `profile assigned chats`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/index.html`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `19056b796757ae25e434fc113c9b3c8ea486c3fdc5fd0d321a8c26a4a09f300f`
- **Точный диапазон:** `250–250`
- **Текущая обязанность:** Показывает assigned chats/bindings.
- **Обязанность 4.5:** Показывать session chat state, ambiguity/operator select endpoint, FILE_NEEDS_ATTENTION links.
- **Изменение:** добавление
- **Контракты:** §9b–9e; §10j
- **Что менять нельзя:** Не скрывать REVOKED/CONFIG_CHANGED/AMBIGUOUS.
- **Миграция:** New session state.
- **Acceptance:** `ACC-S3A-008`
- **Откат:** Runtime state can be discarded on rollback after quiet.

### MAP-073 — срез 5 — `console_releases/4.5.0-s1/static/index.html` / `profile assigned chats`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/index.html`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `19056b796757ae25e434fc113c9b3c8ea486c3fdc5fd0d321a8c26a4a09f300f`
- **Точный диапазон:** `250–250`
- **Текущая обязанность:** Панель показывает привязки; слотов сценария и назначений поколения в интерфейсе нет.
- **Обязанность 4.5:** Показывать активный сценарий, слоты и назначения поколения с указанием происхождения — операторская привязка или созданный сценарием чат, — и причину паузы.
- **Изменение:** добавление
- **Контракты:** §9b–9e; §10j; журнал 2026-09-06
- **Что менять нельзя:** Не показывать назначение как привязку: `assignmentId` и `bindingId` — разные сущности. Причина паузы не скрывается.
- **Миграция:** Состояние поколения; данных не мигрирует.
- **Acceptance:** `ACC-S5-025`
- **Откат:** HTML rollback; состояние поколения отбрасывается после тишины.

### MAP-074 — срез 1 HISTORICAL — `console_releases/4.4.0/static/style.css` / `section-nav`

- **Статус якорей:** HISTORICAL — байты замороженного основания `830ab8c6`, с рабочим основанием не сверяются.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `1dc41455e9d94f9ea59af1419264dc4f60fe4c3384a0bde126d61014623f0f28`
- **Точный диапазон:** `201–201`
- **Текущая обязанность:** Стили текущей 4-tab navigation/management panels.
- **Обязанность 4.5:** Добавить layout пятой Files nav/view и slice1 provenance/dedupe/repeat controls; not-ready state видим.
- **Изменение:** добавление
- **Контракты:** §10d; §10j
- **Что менять нельзя:** CSS не должен делать недоступную 3a функцию похожей на рабочую.
- **Миграция:** Нет.
- **Acceptance:** `ACC-S1-017`, `ACC-UI-001`
- **Откат:** CSS rollback.

### MAP-075 — срез 3a — `console_releases/4.5.0-s1/static/style.css` / `section-nav`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/style.css`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `82d30017d76392534317d92a8ab8dc1851fbee3736af72d4d45a2eb2974e5779`
- **Точный диапазон:** `203–203`
- **Текущая обязанность:** После slice1 есть только базовый Files scaffold.
- **Обязанность 4.5:** Добавить стили artifact lists, FILE_NEEDS_ATTENTION, session/conflict/offline filters; actionable states всегда видимы.
- **Изменение:** добавление
- **Контракты:** §9d; §10j
- **Что менять нельзя:** Hide offline не скрывает attention/conflict/revoked/config-changed.
- **Миграция:** Нет.
- **Acceptance:** `ACC-S3A-006`, `ACC-S3A-009`, `ACC-UI-001`
- **Откат:** CSS rollback.

### MAP-076 — срез 5 — `console_releases/4.5.0-s1/static/style.css` / `profile-tab-panel`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/style.css`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `82d30017d76392534317d92a8ab8dc1851fbee3736af72d4d45a2eb2974e5779`
- **Точный диапазон:** `238–238`
- **Текущая обязанность:** Profile panels стилизованы для старой формы/сырой directives textarea.
- **Обязанность 4.5:** Добавить стили command cards/add-edit-remove/mirror file settings без изменения command semantics.
- **Изменение:** добавление
- **Контракты:** §9 п.5; §10j
- **Что менять нельзя:** CSS не должен скрывать validation/error/OUTCOME_UNKNOWN actions.
- **Миграция:** Нет.
- **Acceptance:** `ACC-S5-016`, `ACC-S5-017`, `ACC-UI-001`
- **Откат:** CSS rollback.

### MAP-077 — срез 5 — `console_releases/4.5.0-s1/static/style.css` / `auto-error mark`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/static/style.css`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `82d30017d76392534317d92a8ab8dc1851fbee3736af72d4d45a2eb2974e5779`
- **Точный диапазон:** `121–121`
- **Текущая обязанность:** Есть mark для STOP/CONTINUE, отдельной AUTO ERROR позиции нет.
- **Обязанность 4.5:** Добавить distinct mark around AUTO ERROR excerpt/offset match.
- **Изменение:** добавление
- **Контракты:** §9 п.3; §10i
- **Что менять нельзя:** Не пытаться подсветить offset, которого нет в truncated middle.
- **Миграция:** Нет.
- **Acceptance:** `ACC-S5-013`
- **Откат:** CSS rollback.

### MAP-078 — срез 6 — `console_releases/4.5.0-s1/console_server.py` / `on_startup`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `307–321`
- **Текущая обязанность:** Startup сейчас reconciles текущие runtime обязанности, retention/snapshot GC отсутствуют.
- **Обязанность 4.5:** Подключить отдельный retention cycle и snapshot MARK/SWEEP: mark по всем существующим Run и sessions; sweep только unreachable snapshots старше grace; retention Run и session cleanup остаются отдельными процессами.
- **Изменение:** добавление
- **Контракты:** §10 slice6; §10a
- **Что менять нельзя:** Возраст никогда не удаляет reachable snapshot; reference counter не источник истины.
- **Миграция:** Срез 6 не меняет routing/action schemas.
- **Acceptance:** `ACC-S6-001`, `ACC-S6-002`
- **Откат:** Откат отключает retention/GC; уже удалённые одноразовые Run не восстанавливаются.

### MAP-079 — срез 7 — `console_releases/4.5.0-s1/profile_store.py` / `_validate_profile`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `255–370`
- **Текущая обязанность:** После slice2 временно может существовать migration branch старого timeout name.
- **Обязанность 4.5:** Удалить transitional acceptance старого endpointWaitTimeoutSec только после доказанной миграции всех config; canonical schema остаётся только endpointWaitTimeoutSeconds.
- **Изменение:** удаление
- **Контракты:** §10 slice7; §12 cleanup
- **Что менять нельзя:** Не удалять compatibility раньше стабильности 5+3b/6 и backup evidence.
- **Миграция:** Финальная cleanup после migrations.
- **Acceptance:** `ACC-S7-001`
- **Откат:** Rollback slice7 может вернуть shim, но не старое значение без backup.

### MAP-080 — срез 5 — `console_releases/4.5.0-s1/profile_store.py` / `_validate_profile`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `255–370`
- **Текущая обязанность:** Схема профиля не знает сценариев: нет слотов ролей, входных действий и определений команд со свойствами.
- **Обязанность 4.5:** Валидировать декларативную схему сценариев: слоты ролей, входное действие, определения команд с эффектами и флагами дублирования, ссылки промптов через promptPath. Ошибки возвращаются с точным путём до значения. Активный сценарий профиля — живое поле.
- **Изменение:** добавление
- **Контракты:** §9 п.1,5; §9f; §9g; журнал 2026-09-06
- **Что менять нельзя:** Не проверять здесь наличие реального чата для обязательного слота: привязки меняются независимо, а runtime-чат создаётся только после старта. Промпты не хранить литералом. Имя команды обязано совпадать с `COMMAND_[A-Z0-9_]+`, иначе расширение её не передаст.
- **Миграция:** Схема сценариев появляется только на границе 5+3b; старые профили не мигрируются.
- **Acceptance:** `ACC-S5-018`, `ACC-S5-019`
- **Откат:** Rollback схемы профиля из pre-slice backup; назначения поколения разрушаются вместе с состоянием сессии.

### MAP-081 — срез 7 — `extension_releases/2.11.6/background.js` / `SESSION_TABS_KEY`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/background.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `30830c99ec58a33b1ee7ba7fa190b374cecfc6c266a82cb1a11444d900eb87e7`
- **Точный диапазон:** `24–24`
- **Текущая обязанность:** После slice2 migration code может читать legacy enabledTabs 2.11.6 один раз.
- **Обязанность 4.5:** Удалить one-time legacy enabledTabs import/migration branch; 4.5 state остаётся epoch-bound reasons model.
- **Изменение:** удаление
- **Контракты:** §10 slice7; §10h
- **Что менять нельзя:** Не удалять effective reason model и epoch initialization.
- **Миграция:** Только после завершения перехода fleet/стенда на 4.5.
- **Acceptance:** `ACC-S7-002`
- **Откат:** Rollback shim possible only if legacy source still meaningful; manual reason не угадывать.

### MAP-082 — срез — — `extension_releases/2.11.6/content.js` / `parseMessage`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `extension/content.js`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `b85583e200ab88b6fadeadd99c053f4104020ecc9c14a952b41d12f3cf6335b1`
- **Точный диапазон:** `328–500`
- **Текущая обязанность:** Parser отдаёт messagePosition; fallback row.turnId=null.
- **Обязанность 4.5:** Не менять в 4.5 implementation slices; это зафиксированное основание для fingerprint dedupe.
- **Изменение:** — (инвариант)
- **Контракты:** §9 п.10; §10l
- **Что менять нельзя:** Не объявлять turnId стабильным; SOURCE_* и parserVersion не менять попутно.
- **Миграция:** Нет.
- **Acceptance:** `ACC-GUARD-001`
- **Откат:** Нечего откатывать.

### MAP-083 — срез 2 — `console_releases/4.5.0-s1/delivery_manager.py` / `supersede_older_jobs_for_tab`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `1036–1069`
- **Текущая обязанность:** Вытесняет все nonterminal jobs по tabId, не глядя на аренду.
- **Обязанность 4.5:** Только S2 safety interlock, понадобившийся для корректного DRAIN/BARRIER: перед решением выполняется восстановление истёкших аренд; задание с любым следом аренды — `ACTIVE`, `EXPIRED`, `INVALID` — в `SUPERSEDED` не переводится; вытеснение разрешено только при `NO_LEASE`; пока на вкладке есть любой след аренды кроме `NO_LEASE`, доставка на вкладку односместна и новое задание не выдаётся; нечитаемое или невалидное сохранённое задание не считается свободной вкладкой. Восстановление и решение образуют одну критическую секцию, а `EXPIRED`, возникший уже после прохода восстановления, блокирует текущую итерацию, а не открывает вкладку: классификация берётся дважды от двух разных показаний часов. Пропущенное вытеснение — отложенное, а не отменённое: как только вкладка доказанно свободна от аренды, вытеснение применяется к её заданиям на месте решения о выдаче, оставляя только новейший Prepare. Иначе защищённое арендой старое задание переживало новое и снова становилось кандидатом после его успешной доставки. Порядок Prepare берётся из доказанного времени, а не из строкового сравнения `createdAt`: непригодное к решению время и одинаковые метки у двух заданий означают, что новейшего доказать нельзя, и тогда вкладка не выдаёт ничего и не вытесняет ничего. `SUPERSEDED` терминален, поэтому терминальная запись на недоказанном порядке уничтожает доставку, а не просто путает очередь. Реализуется в том числе новыми вспомогательными символами (`outstanding_lease_for_tab`, `prepare_order_for_tab`, `_retire_superseded_for_tab`, `_select_job_for_tab`, `classify_target`), которых в основании `830ab8c6` нет и якорей у них быть не может. Семантику вытеснения этот ряд не меняет — она принадлежит `MAP-036` в срезе 4.
- **Изменение:** добавление
- **Контракты:** §10e «S2 transitional safety»; §10l «Тишина»
- **Что менять нельзя:** Аренду вытесняемого задания нельзя очищать: исход неизвестен, и стирание следа — подстановка отсутствия вместо неизвестного. Односместность не заменяет отчётности: захваченное задание обязано оставаться в `outstanding` слива.
- **Миграция:** Правило действует с первой атомарной границы и переживает срез 4.
- **Acceptance:** `ACC-S2-033`
- **Откат:** Rollback вместе с атомарной границей среза 2.

### MAP-084 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `api_delivery_chunk`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `806–818`
- **Текущая обязанность:** Аутентификация и чтение байтов вложения по run/job/attachment; ни версии, ни эпохи, ни владения, ни аренды.
- **Обязанность 4.5:** Порядок: браузерный барьер → доверенная идентичность endpoint → авторизация по target задания → `ACTIVE` аренда с совпадающим `leaseToken` → и только потом байты вложения. Вкладка берётся из проверенного endpoint, не из запроса. Chunk не является продлением аренды.
- **Изменение:** замена
- **Контракты:** §10i «Порядок проверок»; §10e «S2 transitional safety»
- **Что менять нельзя:** Отказ обязан стоять до чтения байтов. Chunk не продлевает аренду ни при каких условиях: продление персистится только событиями доставки и `HEARTBEAT`.
- **Миграция:** Первая атомарная граница.
- **Acceptance:** `ACC-S2-035`
- **Откат:** Rollback вместе с атомарной границей среза 2.

### MAP-085 — срез 2 — `console_releases/4.5.0-s1/delivery_manager.py` / `attachment_chunk`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `1430–1457`
- **Текущая обязанность:** Отдаёт байты вложения без вкладки, без аренды и без доказательства принадлежности.
- **Обязанность 4.5:** Требует вкладку проверенного endpoint и живую аренду с совпадающим токеном, проверяя их только на чтение. Оба доказательства — обязательные параметры метода, а проверка безусловна: значений по умолчанию у них нет и ветки, в которой проверка пропускается, не существует. Проверка вынесена в отдельный `_require_live_lease`; мутирующий `_touch_lease` (`1107–1116`) остаётся исключительно на пути событий, которые сохраняют задание.
- **Изменение:** замена
- **Контракты:** §10e «S2 transitional safety»; §10l «Тишина»
- **Что менять нельзя:** Принадлежность вкладке доказывается общим классификатором цели, а не собственным `int()` над сохранённым значением — иначе обязательность обоих доказательств сохраняется, а само доказательство вкладки берётся более слабым способом. Не вызывать здесь мутирующий helper. Этот метод задание не сохраняет, поэтому любое продление в нём остаётся в отброшенном словаре и выглядит heartbeat'ом, которым не является. Не возвращать проверке необязательность: обязанность, действующая только когда вызывающий передал нужные аргументы, обязанностью не является — маршрут HTTP их передаёт, а следующий вызывающий может и не передать.
- **Миграция:** Первая атомарная граница.
- **Acceptance:** `ACC-S2-035`
- **Откат:** Rollback вместе с атомарной границей среза 2.

### MAP-086 — срез 2 — `console_releases/4.5.0-s1/delivery_manager.py` / `find_latest_submitted_job`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `673–736`
- **Текущая обязанность:** Возвращает задание или `None`, сравнивая сохранённое время без проверки смещения и разрешая равные метки порядком обхода каталога.
- **Обязанность 4.5:** Только временная обязанность блока 2+5, не будущая семантика среза 4: ответ становится трёхзначным — найдено, отсутствует, недоказуемо с причиной. Недоказуемость дают непригодное к сравнению сохранённое время, две максимальные одинаковые метки, нечитаемое сохранённое задание доставки, отправленное задание без единой метки времени, время отправки в будущем и непригодная к прочтению цель задания — отсутствующая, не объект, без `tabId`, с `tabId` не числом, без `url` или с `url` не строкой. Отсутствие ключа `url` и каноническая пустая строка — разные состояния: writer сохраняет `url` на каждой цели, поэтому пустая строка совпадает, а отсутствие означает недоказуемую страницу. Законных пропусков кандидата ровно два, и оба — доказанные факты о доставке, а не пробелы в знании о ней: доказанно другая вкладка или страница и доказанно старше окна восстановления. Решение о цели принимает один общий помощник, поэтому обход и явно названный источник отвечают одинаково. `resolve_recovery_source` на недоказуемость отказывает и не откатывается к названному браузером источнику. Символ каталогизирован в §10e «Доставка» за срезом 4, и настоящая строка его туда не переносит: восстановление источника переписывается там целиком.
- **Изменение:** замена
- **Контракты:** §10e «S2 transitional safety»; §10l «Тишина»
- **Что менять нельзя:** UNKNOWN не сводить к отсутствию: `None` для «нечего вернуть» и `None` для «не могу доказать» — это и есть тот дефект, и он возвращается через любую ветку, которая молча пропускает кандидата. Нечитаемое задание читать снисходительным загрузчиком нельзя: `{}` не совпадает ни с одной вкладкой, и повреждённое доказательство исчезает вместо того, чтобы остановить вывод. То же про цель: непрочитанный адрес — не чужой адрес, а `int()` над сохранённым значением без проверки уходит мимо трёхзначного ответа исключением. Отсутствующее поле цели не приравнивать к каноническому пустому значению: так недоказуемая страница становится подходящей к любой. Названный источник не становится верным просто потому, что он назван. Замена в срезе 4 обязана сохранить трёхзначный отказ, пока новая модель источника не даст эквивалентного или более сильного доказательства; строка среза 4 для этого символа ещё не выпущена, поэтому пересечение здесь объявлено словами, а `verify_overlaps` его пока не проверяет — когда строка появится, она обязана назвать `MAP-086`.
- **Миграция:** Правило действует с первой атомарной границы и переживает срез 4.
- **Acceptance:** `ACC-S2-037`
- **Откат:** Rollback вместе с атомарной границей среза 2.

### MAP-087 — срез 5 — `console_releases/4.5.0-s1/delivery_manager.py` / `create_recovery_replay`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/delivery_manager.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `8a1575aa1e22e8f3903fd1cf4cfa866c7e98df95b9af993e1cd01a4c90d8d896`
- **Точный диапазон:** `801–972`
- **Текущая обязанность:** Клонирует терминальную доставку в новый черновик-повтор; идемпотентность решается двузначным ответом вспомогательного `_existing_recovery_replay`, где `None` означает и «повтора нет», и «повтор есть, но его принадлежность нельзя прочитать».
- **Обязанность 4.5:** Ответ о существующем повторе становится трёхзначным — найден, отсутствует, недоказуем с причиной. Принадлежность доказывается целым writer-контрактом, а не независимыми фильтрами: обычная доставка несёт одновременно **ни** `recoveryReplay`, **ни** `recoveryOf`; recovery replay атомарно несёт `recoveryReplay: True`, пригодный `recoveryOf`, цель, канонический `status` и согласованную с lifecycle `dispatchEpoch`. Половинчатая пара (`recoveryOf` есть, marker отсутствует), marker любого значения кроме именно `True`, непригодные типы `recoveryOf.runId/jobId`, непригодный `status`, непригодная либо противоречивая lifecycle-форма `dispatchEpoch` — `UNPROVABLE`, а не отсутствие. Законные identity-пропуски ровно два: writer-обычная доставка без обоих recovery-полей и replay, чей пригодный `recoveryOf` доказанно называет другой source. Но второй skip разрешён только после проверки всей replay-строки: `target` обязан быть пригодным, `status` каноническим, а `dispatchEpoch` согласованной с lifecycle; раннее `recoveryOf != source` не обходит companion-поля writer-контракта. После того как `recoveryOf` доказал именно этот источник, адрес повтора обязан совпадать с адресом источника: другая вкладка или страница — противоречие сохранённого состояния, а не законный пропуск. Проверка существующего повтора принимает `page_url` и пользуется общим классификатором цели на обеих координатах. Активный нетерминальный replay обязан нести текущую непустую `dispatchEpoch`; чужая/пустая/нестроковая эпоха означает противоречие. Канонический `PAUSED_AFTER_RESTART` имеет `dispatchEpoch: null` и остаётся **FOUND**. Терминальные `SENT`/`CONSUMED` несут непустую сохранённую epoch. `SUPERSEDED`/`CANCELLED` могут законно нести либо непустую сохранённую epoch, либо `dispatchEpoch: null`, но null допустим только при доказанной writer-provenance рестарт-паузы (`pauseReason=BACKEND_RESTART`, пригодный `pausedAt`, присутствующий `pausedFromDispatchEpoch` с null либо непустой строкой). Голый terminal-null без этой provenance — `UNPROVABLE`. Существование terminal row не тождественно существованию доставленного результата: `SUPERSEDED`/`CANCELLED` с `sendState=SENT|MANUAL_SENT` остаются **FOUND**; с доказанно недоставленным `sendState=NOT_REQUESTED|SEND_ERROR` законно пропускаются как историческая, но не доставленная попытка, чтобы при отсутствии более нового replay ответ стал **ABSENT**; `SEND_REQUESTED` имеет неизвестный исход и даёт `UNPROVABLE`, а не absence. При недоказуемости `create_recovery_replay` отказывает **до** создания каталога нового задания и до любой записи: ни второго повтора, ни перевода прежнего в `SUPERSEDED`. Проверка возраста источника выполняется общим `_job_submitted_at`, а не собственной копией правила.
- **Изменение:** замена
- **Контракты:** §10e «S2 transitional safety»; §10l «Тишина»
- **Что менять нельзя:** Недоказуемость не сводить к отсутствию: на неполном доказательстве нельзя ни создавать доставку, ни выполнять терминальную запись. Обычным считается только writer-состояние, где одновременно отсутствуют и `recoveryReplay`, и `recoveryOf`; отсутствие одного при наличии второго не даёт права на skip. Нельзя приводить сохранённые identity/lifecycle-поля через `str()`/truthiness: `1`, `"true"`, `42`, пустая или чужая эпоха не становятся каноническими значениями. Нельзя пропускать replay по `recoveryOf != source`, пока его собственные `target`, `status` и `dispatchEpoch` не признаны пригодными: повреждение foreign-source replay тоже `UNPROVABLE`, а не законный skip. После доказанного same-source другая цель, непригодный status и несогласованная `dispatchEpoch` останавливают вывод. `PAUSED_AFTER_RESTART` не считается отсутствием уже созданного replay: его каноническая форма — `status=PAUSED_AFTER_RESTART`, `dispatchEpoch=null`. Нельзя применять правило «terminal => непустая epoch»: writer сам производит `PAUSED_AFTER_RESTART -> SUPERSEDED` с `dispatchEpoch=null`, и такая строка канонична только вместе с доказуемой pause-provenance. Нельзя также применять правило «terminal => FOUND»: ретированный replay без доказательства отправки не является доставленным результатом; `NOT_REQUESTED`/`SEND_ERROR` позволяют искать следующий replay или ответить `ABSENT`, тогда как `SEND_REQUESTED` остаётся неизвестным исходом и обязан остановить вывод как `UNPROVABLE`.
- **Миграция:** Правило действует с первой атомарной границы.
- **Acceptance:** `ACC-S5-026`
- **Откат:** Rollback вместе с атомарной границей блока 2+5.

### MAP-088 — срез 2 — `console_releases/4.5.0-s1/profile_store.py` / `ProfileSessionStore`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/profile_store.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`
- **Точный диапазон:** `773–834`
- **Текущая обязанность:** Хранит foundation ProfileSession: identity профиля/снимка, bindingIds, restartGeneration и lifecycle; endpoint/tab effects отсутствуют.
- **Обязанность 4.5:** Добавить session-local `endpointSelections` и writer явного выбора `bindingId → endpointId` для `selectEndpoint`; существующая session без поля читается как пустая selection-state.
- **Изменение:** добавление
- **Контракты:** §4.8; §9a; §10i «Выбор endpoint — не переименование закрепления»
- **Что менять нельзя:** Не копировать observed endpoint state и не писать `approvedEndpointId`/pin semantics; writer хранит только relation и audit (`selectedAt`, `selectedBy`, `reason`). Не реализовывать здесь автоматическую delivery selection policy `MAP-034`.
- **Миграция:** Старые sessions получают пустое состояние чтением по умолчанию; legacy pins/approved values не переносятся.
- **Acceptance:** `ACC-S2-007`
- **Откат:** Rollback среза 2 игнорирует/удаляет session selection state вместе с новой endpoint-space; старые pins из него не восстанавливаются.

### MAP-089 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `create_app`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `1059–1106`
- **Текущая обязанность:** Browser protocol имеет CONTROL_AGENT/ENDPOINT и delivery routes, но явного HTTP-пути для terminal `CLOSED` нет; внутренний `EndpointRegistry.close()` недостижим расширением.
- **Обязанность 4.5:** Добавить browser-authenticated `POST /api/endpoints/close` с обязательными `extensionVersion=2.12.0`, `browserEpoch`, `endpointId`; до endpoint mutation доказать текущее CONTROL ownership и принадлежность endpoint той же epoch. `CLOSED`/`EXPIRED` terminal и идемпотентны. Операция является control-plane cleanup, не delivery event, не меняет delivery jobs и остаётся доступной при delivery `BARRIER`.
- **Изменение:** добавление
- **Контракты:** §9a; §10i «Закрытие вкладки»; `MAP-053`
- **Что менять нельзя:** Не кодировать `CLOSED` обычным ENDPOINT heartbeat/poll; non-owner/foreign epoch не меняет endpoint state; terminal endpoint не воскрешать; route не получает права на CLAIM/SEND/retry/chunk/job mutation.
- **Миграция:** Серверная поддержка устанавливается до extension 2.12.0, но считается частью той же slice-2 compatibility boundary; старые клиенты route не вызывают.
- **Acceptance:** `ACC-S2-038`
- **Откат:** Rollback только вместе с парным server+extension boundary; route исчезает вместе с server slice 2, endpoint state отдельно не реконструируется.

### MAP-090 — срез 2 — `console_releases/4.5.0-s1/console_server.py` / `api_delivery_poll`

- **Статус якорей:** ACTIVE на рабочем основании closed-S1; путь основания `830ab8c6` был `console_releases/4.4.0/console_server.py`.
- **Релиз-основание:** Console 4.4.0 r7 + Extension 2.11.6 + receiver 2.10.0; git 830ab8c6453fa58ab1fd1339e210a41857e16df6
- **Полный SHA-256:** `565e8558d0a3607f9351c7246f44e7b38713d21ede23e4fdcb46bccbdcc3716a`
- **Точный диапазон:** `768–788`
- **Текущая обязанность:** `CONTROL_AGENT` арбитрирует ownership, но успешный owner получает только lease metadata; авторитетного плана `ProfileSession → ChatBinding` для восстановления `profile-session:<sessionId>` причин нет. Presentation `ProfileSessionStore.list()` при этом пропускает нечитаемые rows и непригоден как fail-closed источник.
- **Обязанность 4.5:** Успешный CONTROL owner получает read-only `reconcilePlan` из доказуемых live `ProfileSession` (`STARTING/RUNNING/DEGRADED`) и принадлежащих им enabled `ChatBinding`. Сессии канонически сортируются по `sessionId`, bindings по `bindingId`; `revision` — `sha256:` канонического JSON без самого revision. Missing/deleted или disabled binding не создаёт reason. Malformed/ambiguous session/binding, profileId drift или повреждённый binding store делают весь plan `RECONCILE_PLAN_UNPROVABLE`, без частичного ответа. Конфликтующая epoch plan не получает.
- **Изменение:** добавление
- **Контракты:** §9c; §10e–10f; §10g; §10i; `MAP-052`; `MAP-055`
- **Что менять нельзя:** Не выводить session reasons из `/api/endpoints`, legacy `enabledTabs`, storage cache или открытых tabs. Plan не выбирает endpoint, не исполняет chat actions и не пишет ProfileSession/ChatBinding. Не использовать `ProfileSessionStore.list()` как доказательство: нечитаемая row — UNKNOWN, не отсутствие. `CONTROL_AGENT_CONFLICT` не получает plan. Отсутствующий plan не означает пустой plan.
- **Миграция:** Нет. Browser cache строится extension 2.12.0 заново из успешного server plan; старые cache values авторитетными не становятся.
- **Acceptance:** `ACC-S2-002`, `ACC-S2-003`, `ACC-S2-039`
- **Откат:** Rollback только вместе с атомарной server+extension границей среза 2; plan исчезает вместе с новым CONTROL protocol, локальный session cache отбрасывается.

## 4. Миграция ломающих границ

### 4.1. Граница среза 2

Server endpoint ownership/registry, Extension endpointId/epoch/alarms и canonical config rename `endpointWaitTimeoutSec → endpointWaitTimeoutSeconds` устанавливаются одной согласованной границей. Config migration выполняется transactionally из pre-migration backup: пять состояний по membership, затем canonical validation; explicit falsy не подменяется default. До появления product intake-gate среза 5 закрытие приёма для границы 2 обеспечивается операционно остановленным/недоступным receiver; в самой карте серверных команд нет. Во время замены browser plane проходит `DRAIN → доказанная тишина → BARRIER`; несовместимый protocol отвергается до observe. До перехода extension 2.11.6 manual `enabledTabs[tabId]=true` переносится только если старое значение фактически доступно, true и вкладка существует; если недоступно — reason не угадывается; false/absent → reason нет.

### 4.2. Граница 5+3b

Последовательность: закрыть intake → DRAIN delivery → дождаться local/browser quiet без unsafe lease expiry → повторно убедиться, что intake закрыт и новых Run нет → BARRIER → очистить `data/` старой схемы → установить server + file resolution + extension delivery journal согласованно → подтвердить protocol compatibility до первой новой delivery → открыть intake. Старые Run не читаются, не мигрируются и не исполняются.

### 4.3. Разрушительный rollback breaking slice

Закрыть intake → DRAIN → доказать quiet → очистить `data/` новой схемы → очистить durable delivery journal → инвалидировать browserEpoch/tabId→endpointId/manual/session-lease cache → привести legacy `enabledTabs` к OFF → вернуть согласованные server+extension версии → открыть intake. `config/`, `config/secrets/`, `runtime/token.txt`, `logs/` не стирать; config schema восстанавливать из pre-migration backup.

## 5. Матрица приёмки

| ID | Проверка | Статус до реализации |
|---|---|---|
| `ACC-GUARD-001` | content.js still exposes messagePosition with fallback turnId=null; dedupe does not claim stable turnId. | PLANNED |
| `ACC-LIVE-001` | E2E tabId/identity mismatch block — NOT YET CLAIMED PASSED. | NOT RUN / не выдавать за пройденный |
| `ACC-LIVE-002` | E2E new incoming result while tab OFF → TAB_NOT_ALLOWED — NOT YET CLAIMED PASSED. | NOT RUN / не выдавать за пройденный |
| `ACC-LIVE-003` | E2E refresh page while tab OFF — NOT YET CLAIMED PASSED. | NOT RUN / не выдавать за пройденный |
| `ACC-MIG-001` | Breaking deployment closes Run intake and rechecks no new Run appeared before destructive cleanup. | PLANNED |
| `ACC-MIG-002` | DRAIN issues no new CLAIM/jobs but accepts events from leases already claimed before drain. | PLANNED |
| `ACC-MIG-003` | BARRIER is enabled only after local+browser quiet and then rejects old protocol mutations. | PLANNED |
| `ACC-MIG-004` | Turning BARRIER on early is rejected by acceptance test because existing claimed job must finish reporting. | PLANNED |
| `ACC-MIG-005` | Browser quiet requires no active claimLeaseToken with unexpired claimExpiresAt and no attachment in FETCHING/CHAT_UPLOADING/CLAUDE_UPLOADING. | PLANNED |
| `ACC-MIG-006` | Lease that expires during DRAIN latches unsafe; recover_expired_leases clearing token does not prove quiet; cutover stops pending browser-context reset. | PLANNED |
| `ACC-MIG-007` | Local quiet requires no RUNNING step and no live subprocess in RunExecutor._processes. | PLANNED |
| `ACC-MIG-010` | old present/new absent → copy value to new then remove old. | PLANNED |
| `ACC-MIG-011` | old+new equal → keep new, remove old. | PLANNED |
| `ACC-MIG-012` | old+new differ → stop migration without guessing or saving profile. | PLANNED |
| `ACC-MIG-013` | old absent/new present → keep new unchanged. | PLANNED |
| `ACC-MIG-014` | Оба имени отсутствуют → миграция создаёт canonical `endpointWaitTimeoutSeconds`=3600; canonical значение валидируется диапазоном 15..604800; клиентская модель профиля в `app.js` использует то же canonical имя и тот же default. | PLANNED |
| `ACC-MIG-019` | Панель delivery среза 3a использует только canonical `endpointWaitTimeoutSeconds`, не возрождает `endpointWaitTimeoutSec` и отображает и редактирует значение по canonical схеме, включая default 3600. | PLANNED |
| `ACC-MIG-015` | run_profile_context:266 читает только endpointWaitTimeoutSeconds из frozen delivery snapshot. | PLANNED |
| `ACC-MIG-016` | run_profile_context:266 выдаёт наружу только endpointWaitTimeoutSeconds. | PLANNED |
| `ACC-MIG-017` | console_server:515 потребляет новое authorization key; внутренний job timeoutSec не считается старым profile schema key. | PLANNED |
| `ACC-MIG-018` | Presence для timeout migration определяется наличием ключа, не truthiness: явно присутствующие 0/false/empty-string/null не получают default 3600 и останавливают migration как невалидные до сохранения. | PLANNED |
| `ACC-S1-001` | Два эквивалентных intake после получения полного ordered file-hash set дают один canonical Run; duplicate увеличивает duplicateCount/журнал. | PASS |
| `ACC-S1-002` | Duplicate intake не публикуется как второй Run; UI/metadata указывает canonical Run; explicit repeatAsNew создаёт новый Run. | PASS |
| `ACC-S1-003` | Snapshot публикуется атомарно, содержит точные config/prompts/variables/directives/operational refs и не содержит secret values. | PASS |
| `ACC-S1-004` | Run в session получает тот же snapshotDigest, Run без session получает snapshot текущего profile. | PASS |
| `ACC-S1-005` | Удаление/остановка session не ломает snapshot уже существующего Run. | PASS |
| `ACC-S1-006` | Server-side execution authorization использует live profile + binding existence/enabled/identity gate; semantics исполнения берутся из immutable Run snapshot. Manual/effective tab-enabled сервером из endpoint presence не выводится и server-owned state не является. | PASS — supersedes rev34 wording by 2026-09-06 decision; прежняя формулировка остаётся в журнале как установленный невыполнимый контракт и задним числом в PASS не переименовывается |
| `ACC-S1-007` | GET /api/runs?profileId фильтрует серверно; UI сохраняет выбор. | PASS |
| `ACC-S1-008` | Log <=50KiB полный; >50KiB head25+omitted bytes+tail25 с валидным UTF-8. | PASS |
| `ACC-S1-009` | Full log download остаётся полным и отдельным от presentation log. | PASS |
| `ACC-S1-010` | Запуск шага отвергается server-owned business gate (profile/context/binding authorization) до изменения state и side effects; manual tab state server-side precondition не является. | PASS |
| `ACC-S1-011` | Slice1 создаёт ProfileSession/snapshot foundation без открытия вкладок или browser reconcile side effects. | PASS |
| `ACC-S1-012` | Profile edit не меняет running session snapshot; restartGeneration, а не revision drift сам по себе, создаёт новый session snapshot. | PASS |
| `ACC-S1-014` | При expectedFiles>0 _result создаёт только staging intake; list_runs не видит его до финализации полного fingerprint. | PASS |
| `ACC-S1-015` | File hashes/order берутся из завершённых uploads/final status; provisional JSON fingerprint никогда не используется как окончательный dedupe key. | PASS |
| `ACC-S1-016` | Receiver fingerprint включает exact chatType+conversationId и bindingId из read-only exact binding lookup; unbound кодируется явным null, malformed/ambiguous config не угадывается. | PASS |
| `ACC-S1-017` | Пятая Files navigation/view существует в slice1 как явный not-ready scaffold и не выполняет client-only file operations до 3a API. | PASS |
| `ACC-S1-018` | Явное «Повторить как новый Run» создаёт новый Run через repeatAsNew с repeatOf/dedupeBypass audit и новым snapshot provenance; обычный duplicate path его не вызывает. | PASS |
| `ACC-S2-001` | Несовместимая extensionVersion отвергается до ownership arbitration и endpoint observe. | PLANNED |
| `ACC-S2-002` | CONTROL_AGENT без owner получает lease и reconciliation plan; delivery отсутствует. | PASS |
| `ACC-S2-003` | Вторая живая epoch получает CONTROL_AGENT_CONFLICT без plan/delivery/state mutation. | PASS |
| `ACC-S2-004` | ENDPOINT при отсутствии/истёкшем ownership получает NOT_CONTROL_OWNER до observe. | PLANNED |
| `ACC-S2-005` | ENDPOINT чужой живой epoch получает CONTROL_AGENT_CONFLICT до observe. | PLANNED |
| `ACC-S2-006` | Browser barrier отвергает old/fenced protocol до browser state mutation. | PLANNED |
| `ACC-S2-007` | selectEndpoint(sessionId,bindingId,endpointId) делает live identity/auth check и не пишет approvedEndpointId. | PASS |
| `ACC-S2-008` | Legacy pin/unpin/approved semantics не используются в 4.5 и не мигрируют в selection. | PLANNED |
| `ACC-S2-009` | Page reload сохраняет endpointId в той же browserEpoch. | PLANNED |
| `ACC-S2-010` | Late pulse после CLOSED не воскрешает endpoint. | PLANNED |
| `ACC-S2-011` | Late pulse прежней epoch после EXPIRED не воскрешает endpoint. | PLANNED |
| `ACC-S2-012` | Lease expiry без смены owner не меняет endpointId; transfer owner инвалидирует old epoch endpoints. | PLANNED |
| `ACC-S2-013` | Registry list не смешивает observed state и selection policy. | PLANNED |
| `ACC-S2-014` | Delivery poll адресуется endpointId и не выдаёт job non-owner endpoint. | PLANNED |
| `ACC-S2-015` | Binding schema после migration не содержит endpointPolicy/approvedEndpointId. | PLANNED |
| `ACC-S2-016` | ProfileResolver больше не имеет approved_endpoint decision branch. | PLANNED |
| `ACC-S2-017` | Manifest 4.5 содержит alarms permission. | PLANNED |
| `ACC-S2-018` | effectiveEnabled = manual OR session reasons; stop session снимает только свою reason. | PLANNED |
| `ACC-S2-019` | Manual reason не переносится на reused tabId/new epoch. | PLANNED |
| `ACC-S2-020` | tabs.onRemoved текущего owner посылает CLOSED и удаляет local mapping/reason. | PLANNED |
| `ACC-S2-021` | Non-owner close не меняет server browser state. | PLANNED |
| `ACC-S2-022` | GET_RUNTIME_CONFIG возвращает epoch+endpointId+version+effectiveEnabled только после init ready. | PLANNED |
| `ACC-S2-023` | Initialization barrier не допускает pulse/poll/reconcile до ensureEpoch/invalidation. | PLANNED |
| `ACC-S2-024` | onStartup создаёт новую epoch и инвалидирует old mapping. | PLANNED |
| `ACC-S2-025` | onInstalled update сохраняет существующую epoch; при отсутствии ensureEpoch создаёт initial без объявления restart. | PLANNED |
| `ACC-S2-026` | Alarm reconciler пульсирует CONTROL_AGENT при нуле tabs и не исполняет chat actions. | PLANNED |
| `ACC-S2-027` | OFF останавливает endpoint poll/pulse; ON в той же epoch восстанавливает тот же endpointId без reload. | PLANNED |
| `ACC-S2-028` | Bridge ENDPOINT poll всегда содержит explicit pollKind, epoch, endpointId, tabId identity. | PLANNED |
| `ACC-S2-029` | NOT_CONTROL_OWNER заставляет сначала восстановить CONTROL_AGENT ownership, не получать delivery обходом. | PLANNED |
| `ACC-S2-030` | CONTROL_AGENT_CONFLICT блокирует reconcile/delivery в non-owner browser. | PLANNED |
| `ACC-S3A-001` | Completed upload публикует immutable object по profile+sha256 и artifact record; duplicate bytes dedupe. | PLANNED |
| `ACC-S3A-002` | Same filename in profile сохраняет version list, не перетирает старый artifact. | PLANNED |
| `ACC-S3A-003` | files.attentionTimeoutSeconds валидируется, сохраняется и замораживается snapshot. | PLANNED |
| `ACC-S3A-004` | Artifacts API поддерживает list/filter/sort/download/group download и operator upload/select. | PLANNED |
| `ACC-S3A-005` | ProfileSession/activation API отражает config/schedule/operator intents и restartGeneration. | PLANNED |
| `ACC-S3A-006` | Files view после 3a использует server API и больше не находится в not-ready состоянии. | PLANNED |
| `ACC-S3A-007` | Hide offline скрывает только benign OFFLINE, не actionable states. | PLANNED |
| `ACC-S3A-008` | Session chat UI показывает REVOKED/CONFIG_CHANGED/AMBIGUOUS/attention state и explicit selection. | PLANNED |
| `ACC-S3A-009` | Artifact/session/conflict/attention UI остаётся визуально различимым; hide-offline CSS не скрывает actionable states. | PLANNED |
| `ACC-S3B-001` | File resolution повторно использует уже pinned artifact данного Run. | PLANNED |
| `ACC-S3B-002` | Artifact produced by same Run выигрывает перед attention/fallback. | PLANNED |
| `ACC-S3B-003` | Chat request и operator action идут параллельно в одном timeout; first valid result atomically pins manifest. | PLANNED |
| `ACC-S3B-004` | После timeout fallback-latest помечен substituted; если artifact отсутствует → FILE_ACQUIRE_FAILED; requested destination materialized atomically. | PLANNED |
| `ACC-S4-001` | Old Run action переносится под current session только при полном пятичастном match. | PASS |
| `ACC-S4-002` | Mismatch требует operator resolution; run.sessionId provenance не переписывается, action.deliverySessionId отдельный. | PASS |
| `ACC-S4-003` | Exactly one ELIGIBLE endpoint выбирается; multiple eligible without session ownership → ENDPOINT_AMBIGUOUS. | PASS |
| `ACC-S4-004` | Selected offline endpoint stays bound and waits; transient offline не вызывает silent reselection. | PASS |
| `ACC-S4-005` | Identity/project/chatType mismatch excludes endpoint only for that target; URL не участвует в identity. | PASS |
| `ACC-S4-006` | Delivery manifest immutable and records exact sent attachment names/bytes/artifact ids. | PASS |
| `ACC-S4-007` | Download “files as sent” reconstructs strictly from immutable delivery manifest. | PASS |
| `ACC-S4-008` | Supersede affects previous attempt same logical delivery, not all jobs for same conversation. | PASS |
| `ACC-S5-001` | Intake gate CLOSED rejects result before allocating runId/directory. | PLANNED |
| `ACC-S5-002` | Generic command schema validates per-profile definitions and mirror input/output file settings. | PLANNED |
| `ACC-S5-003` | Journal SENT recovers as sent without duplicate. | PLANNED |
| `ACC-S5-004` | Journal PREPARED can resume safely. | PLANNED |
| `ACC-S5-005` | Journal DISPATCHING becomes OUTCOME_UNKNOWN; only explicit operator “sent”/“retry new attempt” resolves. | PLANNED |
| `ACC-S5-006` | Executable type handling no longer depends on closed hard-coded command list for new schema. | PLANNED |
| `ACC-S5-007` | Control semantics expressed by generic actions/state; transitional constants do not leak after cleanup. | PLANNED |
| `ACC-S5-008` | Plan definitions/dependency graph/provenance immutable across restart; state separate. | PLANNED |
| `ACC-S5-009` | sideEffectKey persisted atomically before first external effect. | PLANNED |
| `ACC-S5-010` | execute_step dispatches generic actions and persists lifecycle state. | PLANNED |
| `ACC-S5-011` | Local RUNNING/process tracking remains distinct from browser delivery state and quiescence checks both. | PLANNED |
| `ACC-S5-012` | AUTO ERROR positions in state correspond to full raw command output. | PLANNED |
| `ACC-S5-013` | Detector returns stable absolute match/excerpt offsets across chunk boundaries. | PLANNED |
| `ACC-S5-014` | Delivery journal survives service worker and browser restart and is not epoch-bound. | PLANNED |
| `ACC-S5-015` | Journal entry transitions PREPARED→DISPATCHING before DOM effect→SENT after confirmed send. | PLANNED |
| `ACC-S5-016` | Commands UI uses cards/add/edit/remove and writes only profile command schema. | PLANNED |
| `ACC-S5-017` | Command-card CSS сохраняет видимыми validation errors и explicit OUTCOME_UNKNOWN operator actions на normal/narrow layout. | PLANNED |
| `ACC-S6-001` | Snapshot GC MARK учитывает каждый существующий new-schema Run и каждую session; reachable snapshot не удаляется независимо от возраста. | PLANNED |
| `ACC-S6-002` | Retention Run, session cleanup и snapshot GC независимы; sweep удаляет только unreachable+grace-expired snapshot. | PLANNED |
| `ACC-S7-001` | После cleanup canonical profile/UI/runtime schema не содержит endpointWaitTimeoutSec transitional alias. | PLANNED |
| `ACC-S7-002` | После cleanup extension не импортирует legacy enabledTabs; epoch/reasons model остаётся единственным источником enabled state. | PLANNED |
| `ACC-S2-031` | Несовместимая extensionVersion отвергается до ownership arbitration и observe; сервер создаёт или обновляет единственную устойчивую запись VERSION_MISMATCH с expected, observed, firstSeenAt, lastSeenAt и идентичностью endpoint; запись видна в endpoint- и профильной сводке; lifecycle профиля не меняется и состояние паузы не вводится; после совместимого handshake активная запись исчезает. | PLANNED |
| `ACC-S2-032` | Расширение среза 2 не начинает ENDPOINT polling, доставку и не включает legacy fallback, пока не получит валидное S2 CONTROL_AGENT ownership proof с `controlState=OWNER` и подтверждением собственной `browserEpoch`. HTTP 2xx сам по себе доказательством не является: сервер среза 1 на такой запрос отвечает `200 {"ok":true,"job":null}`. Доказывается двумя половинами: браузерная — legacy `200` не запускает ENDPOINT loop и не включает fallback; серверная — probe против сервера среза 1 не оставляет устойчивой мутации endpoint state, несмотря на вызов legacy `observe(-1, ...)`. | PLANNED |
| `ACC-S5-018` | Схема сценария валидируется статически: неизвестная роль, ссылка на несуществующий слот, дубль слота, неизвестные from/sendTo, недопустимые флаги и эффекты отвергаются при сохранении профиля. | PLANNED |
| `ACC-S5-019` | Ошибка валидации несёт точный путь до значения и список допустимых вариантов. | PLANNED |
| `ACC-S5-020` | Провенанс Run содержит активный сценарий; Run доигрывает под ним после переключения. | PLANNED |
| `ACC-S5-021` | Провенанс источника переключения переносится ролью и bindingId, не вкладкой и не endpointId. | PLANNED |
| `ACC-S5-022` | Дублирования команды выполняются до её эффектов и не отменяются собственным стопом как SESSION_STOPPED. | PLANNED |
| `ACC-S5-023` | Переключение сценария увеличивает restartGeneration; входное действие нового сценария выполняется ровно один раз на поколение. | PLANNED |
| `ACC-S5-024` | Прекращение Run останавливает только свой Run; пауза процесса профиля переживает перезапуск консоли и снимается только оператором. | PLANNED |
| `ACC-S5-025` | Интерфейс показывает активный сценарий, слоты, происхождение назначений и причину паузы. | PLANNED |
| `ACC-S5-026` | Существующий recovery replay не считается отсутствующим из-за дыры в writer-контракте. Обычный job доказан только одновременным отсутствием `recoveryReplay` и `recoveryOf`; replay требует marker ровно `True`, пригодные строковые `recoveryOf.runId/jobId`, пригодную цель, канонический status и согласованную с lifecycle `dispatchEpoch`. Любое непригодное/противоречивое значение этих доказательств даёт `UNPROVABLE` с причиной. Законные identity-пропуски ровно два: обычный job без обоих recovery-полей и replay, доказанно называющий другой source; второй skip допускается только после того, как target/status/dispatchEpoch самого replay прошли каноническую проверку. Для same-source другая вкладка/страница недоказуема; активный нетерминальный replay требует текущую непустую эпоху; канонический `PAUSED_AFTER_RESTART` имеет `dispatchEpoch=null`. Writer-цепочка `PAUSED_AFTER_RESTART -> SUPERSEDED|CANCELLED` также может законно сохранить null, но только при пригодных `pauseReason=BACKEND_RESTART`, `pausedAt` и присутствующем `pausedFromDispatchEpoch`; terminal null без этой provenance — `UNPROVABLE`. Terminal row считается существующим доставленным replay только если доставка доказана (`status=SENT|CONSUMED` либо для `SUPERSEDED|CANCELLED` `sendState=SENT|MANUAL_SENT`). Ретированный replay с `sendState=NOT_REQUESTED|SEND_ERROR` является исторической недоставленной попыткой и не закрывает source навсегда: после полной валидации он пропускается, и при отсутствии другого replay создаётся свежий. `SEND_REQUESTED` без подтверждённого исхода даёт `UNPROVABLE`. Отказ выдаётся до создания каталога нового задания и до любой записи: второй replay не появляется на недоказуемости, прежний не переводится в `SUPERSEDED`, байты delivery-tree не меняются; после исправления повреждённого поля replay снова классифицируется по доказанному lifecycle. | PLANNED |
| `ACC-S2-033` | Порядок Prepare выводится только из разбираемого времени с часовым поясом: непригодная метка и одинаковые метки у двух заданий дают отказ — ничего не выдаётся и ничего не переводится в `SUPERSEDED`, — а после исправления сохранённого значения вкладка продолжает работу. Доставка, захваченная на вкладке, не вытесняется и не обходится более новым заданием: `ACTIVE` не переводится в `SUPERSEDED` и новое задание вкладке не выдаётся; `EXPIRED` проходит восстановление до принятия решения, а если истёк уже после прохода восстановления — блокирует текущую итерацию, а не открывает вкладку; к выдаче допускается только `NO_LEASE`; `INVALID` и нечитаемое сохранённое состояние отказывают закрыто и вкладку свободной не делают; после того как законная доставка достигает `NO_LEASE` — через `RELEASE` либо через истечение и восстановление — пропущенное вытеснение применяется, следующее задание становится доступным, и после его успешного завершения старое задание в выдаче больше не появляется. | PLANNED |
| `ACC-S2-034` | Авторизация вызывающего по target задания выполняется до идемпотентного возврата терминального или `PAUSED_AFTER_RESTART` задания: чужой endpoint получает отказ, а не успешный no-op с телом задания. Принадлежность доказывается общим классификатором цели: непригодная сохранённая цель даёт контролируемый отказ, а не совпадение с другой вкладкой и не исключение. | PLANNED |
| `ACC-S2-035` | Чтение байтов вложения требует доверенной вкладки endpoint, доказанной общим классификатором цели, и `ACTIVE` аренды с совпадающим `leaseToken`; оба доказательства обязательны на уровне менеджера, а не только на маршруте HTTP — вызова без них не существует. Отказ стоит до чтения, и сам chunk аренду не продлевает: сохранённое продление выполняется только событиями доставки и `HEARTBEAT`. | PLANNED |
| `ACC-S2-036` | Во время передачи вложения браузер шлёт `HEARTBEAT` независимо от ожидания chunk с каденцией отправки не более 5 секунд; неуспешный `HEARTBEAT` продлением не считается; при утрате доказательства живой аренды цикл не продолжает работу так, будто аренда продлена; chunk продлением не считается. Величина разрыва между сохранёнными на сервере продлениями предметом этой приёмки не является: задержанный или потерянный ответ не делает исправное расширение нарушителем. | PLANNED |
| `ACC-S2-037` | Источник восстановления называется только когда он доказан: непригодное сохранённое время отправки, две одинаковые максимальные метки, нечитаемое сохранённое задание, отправленное задание без единой метки времени, время отправки в будущем и непригодная к прочтению цель задания, включая отсутствующий `url`, дают недоказуемость с причиной, а не отсутствие; законные пропуски — только доказанно другая вкладка или страница и доказанно старше окна восстановления; обход и явно названный источник принимают решение о цели одним общим помощником; при недоказуемости названный браузером источник не используется и автоматический источник не выбирается; после исправления сохранённого значения поиск снова работает. | PLANNED |
| `ACC-S2-038` | Browser endpoint close route требует auth + extensionVersion 2.12.0 + текущее CONTROL ownership + endpoint той же browserEpoch до terminal write; owner получает CLOSED, foreign/expired owner не меняет endpoint, CLOSED/EXPIRED идемпотентны, delivery BARRIER не отключает cleanup и route не меняет delivery jobs. | PASS |
| `ACC-S2-039` | Reconciliation plan каноничен и read-only; unreadable/malformed/ambiguous ProfileSession/ChatBinding или profileId drift дают whole-plan `RECONCILE_PLAN_UNPROVABLE` без частичного plan; missing/disabled binding не создаёт reason. | PASS |
| `ACC-UI-001` | New UI states remain visible/actionable at normal and narrow layouts; CSS does not hide failures. | PLANNED |

## 6. Матрица отката по acceptance ID

| ID | Обязательная проверка/действие при rollback |
|---|---|
| `ACC-GUARD-001` | No change was made; verify invariant only. |
| `ACC-LIVE-001` | No state rollback; these are explicitly unexecuted live acceptance scenarios until run on pro2. |
| `ACC-LIVE-002` | No state rollback; these are explicitly unexecuted live acceptance scenarios until run on pro2. |
| `ACC-LIVE-003` | No state rollback; these are explicitly unexecuted live acceptance scenarios until run on pro2. |
| `ACC-MIG-001` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-002` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-003` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-004` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-005` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-006` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-007` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-010` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-011` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-012` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-013` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-014` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-019` | Rollback вместе с границей среза 3a: панель delivery возвращается к состоянию среза 2. |
| `ACC-MIG-015` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-016` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-017` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-MIG-018` | Do not destructively change state until gate conditions pass; config restored from pre-migration backup; unsafe drain aborts instead of rollback-through. |
| `ACC-S1-001` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-002` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-003` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-004` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-005` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-006` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-007` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-008` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-009` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-010` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-011` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-012` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-014` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-015` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-016` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-017` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S1-018` | Revert slice-1 code/state stores; snapshot objects are removed only if unreachable; no old Run migration exists. |
| `ACC-S2-001` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-002` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-003` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-004` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-005` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-006` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-007` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-008` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-009` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-010` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-011` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-012` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-013` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-014` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-015` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-016` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-017` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-018` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-019` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-020` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-021` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-022` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-023` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-024` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-025` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-026` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-027` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-028` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-029` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S2-030` | Close intake/delivery, reach quiescence, invalidate 4.5 endpoint epoch/mappings/manual/session cache, force legacy enabledTabs OFF, rollback server+extension together. |
| `ACC-S3A-001` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-002` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-003` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-004` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-005` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-006` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-007` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-008` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3A-009` | Disable new artifact/session APIs; remove only stores not referenced by surviving new Run/session; otherwise use destructive breaking rollback. |
| `ACC-S3B-001` | Part of 5+3b breaking rollback: close intake, quiesce, clear new data/file-resolution state and journal as specified. |
| `ACC-S3B-002` | Part of 5+3b breaking rollback: close intake, quiesce, clear new data/file-resolution state and journal as specified. |
| `ACC-S3B-003` | Part of 5+3b breaking rollback: close intake, quiesce, clear new data/file-resolution state and journal as specified. |
| `ACC-S3B-004` | Part of 5+3b breaking rollback: close intake, quiesce, clear new data/file-resolution state and journal as specified. |
| `ACC-S4-001` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S4-002` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S4-003` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S4-004` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S4-005` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S4-006` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S4-007` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S4-008` | Rollback routing/delivery code only against matching endpoint/data schema; do not synthesize legacy pins. |
| `ACC-S5-001` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-002` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-003` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-004` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-005` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-006` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-007` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-008` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-009` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-010` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-011` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-012` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-013` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-014` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-015` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-016` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S5-026` | Rollback вместе с атомарной границей блока 2+5: трёхзначный ответ об уже созданном повторе исчезает вместе с сервером; повреждённое сохранённое значение откатом не чинится. |
| `ACC-S5-017` | Breaking rollback: close intake, quiesce local+browser effects, clear data new schema and durable delivery journal, rollback paired extension/server. |
| `ACC-S6-001` | Disable retention/GC; deleted one-shot Run are not reconstructed; never delete reachable snapshots during rollback. |
| `ACC-S6-002` | Disable retention/GC; deleted one-shot Run are not reconstructed; never delete reachable snapshots during rollback. |
| `ACC-S7-001` | Restore transitional shims only if needed; do not synthesize legacy values; canonical 4.5 state remains authoritative. |
| `ACC-S7-002` | Restore transitional shims only if needed; do not synthesize legacy values; canonical 4.5 state remains authoritative. |
| `ACC-S2-031` | Rollback вместе с атомарной границей среза 2: сервер и расширение возвращаются одновременно, записи расхождения отбрасываются. |
| `ACC-S2-032` | Rollback вместе с атомарной границей среза 2; обратный забор исчезает вместе с расширением среза 2. |
| `ACC-S5-018` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S5-019` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S5-020` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S5-021` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S5-022` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S5-023` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S5-024` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S5-025` | Rollback вместе с ломающей границей 5+3b: схема профиля из pre-slice backup, состояние поколения и назначения отбрасываются после доказанной тишины. |
| `ACC-S2-033` | Rollback вместе с атомарной границей среза 2. Односместность и запрет вытеснения поверх аренды снимаются только вместе с сервером среза 2; аренды, оставшиеся незакрытыми, не очищаются откатом. |
| `ACC-S2-034` | Rollback вместе с атомарной границей среза 2: порядок проверок возвращается вместе с сервером, отдельно не откатывается. |
| `ACC-S2-035` | Rollback вместе с атомарной границей среза 2: маршрут chunk возвращается к прежним проверкам вместе с сервером. |
| `ACC-S2-036` | Rollback вместе с атомарной границей среза 2; требование heartbeat исчезает вместе с расширением среза 2. |
| `ACC-S2-037` | Rollback вместе с атомарной границей среза 2: трёхзначный ответ исчезает вместе с сервером среза 2; повреждённое сохранённое время откатом не чинится. |
| `ACC-S2-038` | Rollback вместе с атомарной границей среза 2: browser close route исчезает вместе с сервером; terminal endpoint rows отдельно не реконструируются и old extension не должен вызывать новый route. |
| `ACC-S2-039` | Rollback вместе с атомарной границей среза 2: reconciliation plan исчезает вместе с новым CONTROL protocol; browser session-reason cache отбрасывается и не становится источником истины. |
| `ACC-UI-001` | Code-only rollback if backing API/schema unchanged; otherwise follow owning slice rollback. |

## 7. Порядок реализации после карты

1. Срез 1: schemas/snapshots/ProfileSession foundation, receiver dedupe, Run filter, server-side log truncation. Вкладки не открываются; `executor.py` и `protocol_engine.py` не меняются.
2. Локальная приёмка всех `ACC-S1-*` и guard cases; только после неё — package/live decision.
3. Срез 2 отдельным атомарным циклом server+extension, включая version barrier, epoch/ownership, endpointId и config migration.
4. 3a → 4 → 5+3b отдельными циклами; `executor.py` и `protocol_engine.py` впервые меняются только в срезе 5/границе 5+3b.
5. Срез 6 retention и срез 7 cleanup выполняются только после доказанной стабильности предыдущих схем; transitional fields не удаляются раньше.

## 8. Самопроверка карты

- historical git HEAD: `830ab8c6453fa58ab1fd1339e210a41857e16df6` — историческая точка 4.4.0, не рабочее основание
- рабочее основание: три поддерева git, объявлены в §1 и сверяются с репозиторием
- файлов основания: **18**
- точек врезки/guard rows: **90**
- acceptance definitions: **129**
- `verify_map.py` сверяет эти числа с фактическим содержимым карты: расхождение означает, что самосводку не обновили после правки.
- Рабочее основание пересчитывается после каждого формально закрытого среза. `830ab8c6…` остаётся исторической точкой 4.4.0 и не является рабочим основанием следующего среза после закрытия предыдущего.

### 8.1. Долг по точкам врезки

Решения журнала 2026-09-06 опираются на символы, созданные срезом 1 и отсутствующие в основании `830ab8c6`. Придумывать им якоря по несуществующим байтам нельзя, поэтому точки врезки для них добавляются после формального закрытия среза 1 и первого пересчёта рабочего основания:

- `DEBT-001` — `ANCHORED_UNIMPLEMENTED`. Включение сценарных `promptPath` в снимок и в `snapshotDigest`. Кандидат на рабочем основании: `console_releases/4.5.0-s1/profile_store.py` / `ProfileSnapshotStore` 573–711`, `_source_files` 617–642`, `publish_current` 678–689`, `publish_capture` 691–694`; SHA файла `41302e1953f92e526f6abf676fe8992840ff6e8014d766cc0cd8a526780d3019`. Нужна и приёмка «правка сценарного промпта после создания Run не меняет байты его снимка»; `ACC-S1-003` для этого непригоден — срез 1 принимался до появления сценарных промптов.
- `DEBT-002` — `ANCHORED_UNIMPLEMENTED`. Сборка назначений поколения: `assignmentId`, `slot → target`, `origin` оператор или сценарий. Кандидат: `console_releases/4.5.0-s1/profile_store.py` / `ProfileSessionStore` 773–834`, `ensure` 807–834`.
- `DEBT-003` — `ANCHORED_UNIMPLEMENTED`. Одноразовый маркер выполнения входного действия на поколение. Кандидат: `console_releases/4.5.0-s1/profile_store.py` / `ProfileActivationStore` 714–770`, `put` 748–770` — единственное место, где растёт `restartGeneration`.
- `DEBT-004` — `ANCHORED_UNIMPLEMENTED`. Немедленный `UNFILLABLE_REQUIRED_SLOT` при сборке состава, не таймаут. Кандидат: `console_releases/4.5.0-s1/profile_store.py` / `ProfileSessionStore` 773–834`, `ensure` 807–834`; провенанс Run — `console_releases/4.5.0-s1/run_profile_context.py` / `ensure_run_context` 127–195`.

У долга стабильные идентификаторы, а не слова для поиска: слово может случайно встретиться в чужой строке и закрыть долг, которого никто не реализовал. `verify_map.py` требует, чтобы каждый `DEBT-NNN` встречался ровно один раз — либо здесь, либо в конкретной строке раздела 3. Перенос выполняется сохранением идентификатора в строке карты.

Все четыре долга находятся во втором состоянии: якорь на рабочем основании определён, реализации нет. Наличие якоря долг не разрешает — в раздел 3 они не переезжают и acceptance не получают.

У долга три состояния, а не два:

```
подходящего якоря нет                     остаётся здесь
якорь определён, реализации нет           остаётся здесь, якорь указан рядом
реализация выполнена и acceptance доказан  переходит в строку раздела 3
```

Появление точного якоря само по себе долг не разрешает. Перенос в раздел 3 допустим только после третьего состояния — иначе повторяется случай `ACC-S1-006`, где формулировка считалась выполненной раньше, чем существовало доказательство.
