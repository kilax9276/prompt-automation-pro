# PAP2 4.5.0 — передача работы: срез 2, шаг 4 / S4 delivery semantics

Документ самодостаточен. Новый чат может продолжить работу, не читая исходную
переписку и не получая отдельных файлов: весь новый код среза 2 приведён здесь
дословно, остальное описано с точными хэшами и лежит в приложенном архиве.

---

## 1. Цель

**Prompt Automation Pro 2 (PAP2)** — система исполнения директив из чатов ИИ.
Ассистент пишет команду в чат, расширение браузера её распознаёт, receiver
принимает, консоль превращает в план и оператор проводит его шаг за шагом на
сервере. Результаты и файлы возвращаются в чат тем же расширением.

Идёт разработка релиза **4.5.0**, разбитого на семь срезов. Каждый срез
самостоятельно проверяем и самостоятельно откатываем.

**Непосредственная цель сейчас** — независимо проверить шаг 4: окончательную
семантику доставки среза 4 (`MAP-018`, `MAP-034`, `MAP-035`, `MAP-036`) поверх
опубликованного шага 3. Это re-authorization через совместимую ProfileSession,
endpoint selection policy, immutable delivery manifest и logical-delivery
supersession. Commit/rollout этого шага до независимого CLEAN запрещены.

Срез 2 — первая по-настоящему атомарная граница: сервер и расширение
выкатываются только вместе и откатываются только вместе.

---

## 2. Что уже сделано

### Инфраструктура (закрыто, в git)

Репозиторий `github.com/kilax9276/prompt-automation-pro`, ветка `main`.

```
8fc773c  S2 Step 1: canonical endpoint timeout migration   ← текущее основание работы
5a000f5  Extension release 2.11.7: copyright headers and version bump
10821a7  Add immutable extension 2.11.6 byte baseline
ebe9e37  Version receiver releases, activate slice 1 on the stand
b402317  Add copyright notices and proprietary LICENSE
3c68271  Slice 1 as versioned releases: console 4.5.0-s1, receiver 2.11.0-s1
aa6aa61  Add 4.5.0 design document
9b5e4d3  Platform 4.3.5, console 4.4.0 r7, receiver 2.10.0, extension 2.11.6
```

Срез 1 **закрыт, выкачен и работает на стенде**: консоль `4.5.0-s1`, receiver
`2.11.0-s1`. Откат — одна команда `rollout_slice1.sh rollback`.

### Срез 2, шаг 1 — закоммичен (`8fc773c`)

Переименование `endpointWaitTimeoutSec` → `endpointWaitTimeoutSeconds`,
девять точек врезки. Пятисостоянийная миграция по членству ключа, а не по
истинности. Двухфазная миграция сохранённых профилей preflight/commit.
Закрывает `ACC-MIG-010…018`.

### Срез 2, блок 2+5 — development/code complete, коммит `d943c11`

Независимый review 27 завершён CLEAN. Development-коммит
`d943c11fac675fa3125f92aec23b8ff90363e5e0` создан на ветке `s2-block25`
поверх `8fc773ce531100fb6e0765dfb49a10b3f8b4f2f8` и опубликован в
`origin/s2-block25`; `main` не сдвинут. Выката нет, стенд pro2 остаётся на
срезе 1. Это закрытие по коду, не приёмка всего среза: `ACC-S2-036` остаётся
`PLANNED`, `ACC-LIVE-001/002/003` — `NOT RUN`.

### Срез 2, шаг 3 — `MAP-028`, development complete, коммит `b7d39e3`

Независимый review 2 завершён CLEAN. Development-коммит
`b7d39e350cf47f7b3ef6d6a34f63990f839257db` создан поверх `d943c11` на
ветке `s2-block25` и опубликован в `origin/s2-block25`; `main` не сдвинут.
`selectEndpoint(sessionId,bindingId,endpointId)` хранит только relation
`ProfileSession × ChatBinding`, legacy pin/approved state не мигрирует.
`ACC-S2-007=PASS`, `ACC-S2-008` остаётся `PLANNED`. Выката нет.

### Срез 2, шаг 4 — S4 delivery semantics, текущий review-кандидат

Реализованы все четыре обязанности S4:

- `MAP-018`: `authorize_delivery` переносит действие старого Run под current
  ProfileSession только при доказанном совпадении profileId, snapshotDigest,
  bindingId, role и identity; immutable `run.sessionId` не переписывается;
- `MAP-034`: endpoint policy разделена на pure `evaluate` и `select`; явный
  session-owned endpoint sticky при OFFLINE/identity mismatch и освобождается
  только при CLOSED/EXPIRED; ambiguity явная;
- `MAP-035`: job получает `endpointId`, `deliverySessionId`,
  `logicalDeliveryId`, `sideEffectKey` и immutable manifest. Manifest фиксирует
  deliveryId, target/message и для outgoing attachments — ordinal, artifact
  provenance, outgoingFilename, size, sha256; bundle хранит ordered
  `sourceArtifactIds`;
- `MAP-036`: supersede касается только предыдущих незавершённых попыток той же
  logical delivery и сохраняет S2 lease/single-flight interlock. Независимые
  доставки в один conversation больше не уничтожают друг друга.

Дополнительный негативный проход уже нашёл и закрыл два интеграционных дефекта:
после CLOSED/EXPIRED старая explicit relation больше не блокирует endpoint,
который тот же `select()` только что выбрал автоматически; retry существующего
job отказывает до мутации, если live authorization уже указывает на другой
endpoint. Также закреплены нулевые attachments и immutable files-as-sent.

Текущий regression-файл `tests/test_slice4_delivery_semantics.py` содержит
23 теста. На точных байтах MAP-028 Review 2 он должен быть RED; на кандидате —
23 PASS. Полный набор на текущем дереве: `274 passed, 64 subtests`;
verify_inventory `177/0`, verify_overlaps `10/0`, verify_map `214/0 VERIFIED_CLEAN`.
`ACC-S4-001…008=PASS`. Commit, push нового S4 commit и rollout не выполнялись.

Содержание уже закрытого блока 2+5:

- реестр endpoint переведён на `endpointId` как ключ, добавлены
  `browserEpoch` и состояния `ONLINE/OFFLINE/CLOSED/EXPIRED`;
- владение управляющим агентом на аренде 90 секунд с `CONTROL_AGENT_CONFLICT`;
- общий барьер протокола на `poll`, `event`, `chunk`;
- устойчивая запись `VERSION_MISMATCH` с двумя областями;
- режимы выката DRAIN, защёлка неизвестного исхода, BARRIER;
- строгая классификация следа аренды;
- удалено создание закрепления (`pin`) во всех трёх слоях.

---

## 3. Ключевые данные

### Хэши файлов на момент передачи

```
console_releases/4.5.0-s2/endpoint_registry.py
  99b085d3ff28deced65ce207167ecb4e47e40dd864acd0bd57d3899a8f484ed2
console_releases/4.5.0-s2/console_server.py
  9406472c9a2f5eaafe641628fbd68eec2f4feff5ac1f4918d37667168da97b74
console_releases/4.5.0-s2/delivery_manager.py
  0b56eb9687feb52ccb4022bddabc16d3910db27e1d04ae93c0aeec700e56ce42
console_releases/4.5.0-s2/profile_store.py
  698146ef9d810f483a059387d535c02658c55d1272209141605159ff45cd5e2f
console_releases/4.5.0-s2/run_profile_context.py
  e94031ed9a0e55569347064d8e54db99b91eb2341100d7f37cacc5f684ba3175
console_releases/4.5.0-s2/static/app.js
  d36a8912333f3258ef125637b87807a82b2bdb252521861bb96a46bff59ff922
tests/test_slice1.py         6bb3baef1b5d28dfb3d1c5f3bdf82f96027b5d94aa9fe5ebf839fbc0d0d44d99
tests/test_slice2_step1.py   8dece3d4a62074e2fa128cbb426fb96f83ade6ea52821af0bfd839b21182513e
tests/test_slice2_endpoint.py e36bab185c67c369b5ddc56f1fc77e933c0c4b69cba459a92f5727c7fdc70bc1
tests/test_slice2_rollout.py 99ba66473a5b8beda54c592d2721ad81e37ade0c81f070d3287e79bea905e6d9
tests/test_slice2_review24.py 29f141a56a9d27257ed3b5e0b1ce33e5866290961acb51c7affc97572620b9f1
tests/test_slice2_review25.py b1490c70fcc799a3fcb314025f000653de02c5a6408b8ebdb6826a1c809bfd39
tests/test_slice4_delivery_semantics.py a207cc00661e748966ee0876de87a0e2a735609e8f6650106a4f241a04129042
RUN_TESTS.sh                 7a41c46b4c28250cf866b25a100bf6d2d9535a6fcba3b0fb2f44858b4c9a3292
```

### Рабочее основание карты (закрытый срез 1, поддеревья git в `10821a7`)

```
console    console_releases/4.5.0-s1     425bc1a8b77ab23b69997d98125f909f821b9a42
receiver   receivers/2.11.0-s1           f5ceaabab02513da2eafab9c593420918708fe63
extension  extension_releases/2.11.6     65b0db4ed31d36f68bb3f6b832797d4e524edebc
```

**Важно:** рабочее основание карты остаётся closed-S1 до закрытия всего среза 2.
`console_releases/4.5.0-s2` — это результат среза, а не его основание.

Историческая точка 4.4.0: git `830ab8c6453fa58ab1fd1339e210a41857e16df6`.
Каталоги `console_releases/4.3.5`, `console_releases/4.4.0` и корневой
`server.py` **заморожены навсегда** — срез 1 не правил их на месте.

### Карта реализации и дизайн

```
PAP2_4.5.0_IMPLEMENTATION_MAP.md   88 строк MAP
                                   127 acceptance
docs/PAP2_4.5.0_DESIGN.md          2681 строк, журнал решений включён
цепочка проверки                   verify_inventory 177/0, verify_overlaps 10/0, verify_map 214/0
```

На момент тринадцатого раунда здесь стояло `82 / 121 / 2487` и
`175 / 9 / 203`. Строки карты `MAP-083…087`, приёмки `ACC-S2-033…037` и
`ACC-S5-026`, два новых якоря в каталоге инвентаря и удалённая проверка
`archive sha256` — вот вся разница.

### Порты и окружение

```
receiver  8867   console  8871
сервер    /home/ext_disk/prompt_automation_pro2, хост ecassa, без root
временный /tmp/pap2
расширение (Windows оператора)  d:\work\extentions\prompt_automation_pro2\
git       есть, ssh-ключ id_ed25519_github привязан, аккаунт kilax9276
```

### Версии

```
на стенде сейчас   console 4.5.0-s1, receiver 2.11.0-s1, extension 2.11.6
кандидат среза 2   console 4.5.0-s2, extension 2.12.0 (репозиторный каталог 2.12.0-s2)
REQUIRED_EXTENSION_VERSION = "2.12.0"   ← числовая версия манифеста, без -s2
```

Релиз расширения `2.12.0-s2` **ещё не создан**. Константа указывает на него
намеренно: барьер уже готов, браузерная половина появится в шаге 6.

---

## 4. Ограничения и требования

### Жёсткие правила работы

1. **Ничего не выкатывать и не коммитить**, пока весь серверный блок 2+5 не
   станет внутренне целостным. Стенд работает на срезе 1.
2. **Не править на месте.** Каждый срез получает свой каталог релиза.
   `4.3.5`, `4.4.0`, корневой `server.py`, `extension_releases/2.11.6`
   заморожены.
3. **Чтение не пишет.** `get_profile`, старт консоли, первый опрос не
   выполняют миграций.
4. **Fail-closed везде.** Неизвестное, повреждённое, противоречивое
   состояние — это UNKNOWN, а не отсутствие. Никаких умолчаний вместо
   отказа.
5. **Отказ до мутации.** Проверка, стоящая после изменения состояния, — не
   проверка.
6. **Барьер версии обязан стоять до `observe` и вне проглатывающего `try`.**
7. **Не начинать следующий блок, пока текущий не признан закрытым ревьюером.**

### Инвариант времени (правило проекта, записано в журнал дизайна)

> Всякая сохранённая метка времени, участвующая в решении о протоколе,
> владении, аренде, выкате, порядке или таймауте, обязана быть разбираемой и
> содержать часовой пояс. Некорректное, наивное или противоречивое
> сохранённое время есть UNKNOWN или INVALID — никогда не отсутствие, никогда
> не умолчание, никогда не приведение.

Одна и та же причина проявилась четырежды: реестр endpoint, состояние выката,
аренда доставки, восстановление аренд.

### Инвариант фикстур (выведен, в журнал пока НЕ записан)

> Фикстура, описывающая сохранённое состояние, обязана порождаться настоящим
> writer, а не собираться вручную.

Дважды выдуманная вручную форма скрывала поломку продуктового пути: раскладка
заданий на диске и схема `claimedBy`. Во втором случае строгая модель
отвергала **каждую настоящую аренду**, а сто тестов были зелёными.

### Формат работы с сервером

Оператор исполняет директивы через саму систему PAP2. Ограничения, выясненные
опытом:

- каждая команда выполняется отдельным `bash --noprofile --norc -c` в
  `cwd = корень проекта`; `cd` внутри одной команды работает, **между
  командами состояние не сохраняется**;
- `~/.bashrc` не читается, `PATH` наследуется от процесса консоли;
- **нельзя перезапускать платформу командой, исполняемой этой же платформой** —
  дерево процессов умрёт вместе с выводом. Только отдельный скрипт под
  `setsid`;
- условия остановки не должны содержать подстрок, встречающихся в собственных
  именах полей (голое `FAILED` совпало с `MANIFEST_FAILED`);
- зонды не должны совпадать сами с собой (`pgrep -f 'platform_manager.py'`
  ловит собственную командную строку).

---

## 5. Принятые решения

### По архитектуре среза 2

| Решение | Причина |
|---|---|
| Идентичность endpoint даёт расширение (`endpointId`), а не URL | перезагрузка страницы или редирект молча меняли, какой чат представляет endpoint |
| `CLOSED` и `EXPIRED` терминальны, поздний пульс **игнорируется** | гонка закрытия вкладки безвредна, но воскрешать нельзя |
| Владение — аренда 90 секунд, одна на эпоху браузера | 90 секунд это срок владения, а не обещание частоты пульса |
| Проигравшая эпоха получает `CONTROL_AGENT_CONFLICT` и **не получает план** | иначе два примирителя конкурируют, а конфликт лишь наблюдается |
| Захват владения и истечение endpoint прежней эпохи — **одна запись** | падение между двумя записями оставляло нового владельца с живыми endpoint несуществующей эпохи |
| Мигающая аренда под тем же владельцем идентичности не пересоздаёт | иначе каждая заминка перестраивала бы цели доставки |
| Реестр хранит только факты браузера, политика выбора вынесена | устаревшее одобрение было неотличимо от отсутствующей вкладки |
| Создание закрепления (`pin`) удалено из реестра, маршрутов и интерфейса | выбор стал отношением сессии и привязки |
| Схема реестра 2, схема 1 **не мигрируется, а инвалидируется** | `tabId` не несёт информации о том, каким endpoint была вкладка |
| Общий `_browser_barrier` для `poll`, `event`, `chunk` | три копии проверок — способ однажды забыть одну и получить обход всех |
| Терминальный endpoint не двигает состояние доставки | закрытая вкладка не могла получить то, о чём отчитывается |
| Вкладка берётся из проверенного endpoint, не из тела запроса | иначе идентичность endpoint декоративна |
| `chunk` требует `ACTIVE` аренду с совпадающим токеном | чтение байтов — это работа, а работа требует заявки |
| Расхождение версий — **одна** устойчивая запись, не пауза | пауза это `ACC-S5-024`, тащить её в самый опасный срез нельзя |
| Области записи расхождения: `LEGACY_AGENT` и `ENDPOINT` | настоящий 2.11.6 не присылает идентичности, выдумывать её нельзя |
| `DRAIN` — проход с собственной идентичностью, не «сейчас аренд нет» | пустая очередь не есть доказательство известного исхода |
| Защёлка монотонна, снимает только новый проход | автоматический сброс превратил бы «мы потеряли исход» в «ничего не осталось» |
| `enter_barrier` сам запускает восстановление | безопасность не должна зависеть от порядка внешних вызовов |
| Классификация следа аренды вместо булева «активна» | `False` отвечал и на отсутствие, и на противоречие |
| Успешная отправка завершает аренду в том же сохранении | `RELEASE` приходит после терминального статуса и игнорируется |
| Терминальное задание с арендой — противоречие, а не тишина | либо аренду не закрыли, либо задание прервали под живой арендой |
| Сохранённый `OPEN` невалиден | писатель его не создаёт; иначе порча одного слова в `BARRIER` открывала плоскость |
| У `BARRIER` есть `enteredAt`, у `DRAIN` его быть не должно | симметрия форм не даёт порче превратить одно в другое |

### По процессу

| Решение | Причина |
|---|---|
| Идентичность основания даёт git, собственный `baseId` удалён | самодайджест сверялся сам с собой и о дереве не говорил ничего |
| Объявляются **хэши поддеревьев**, не `HEAD` и не корневое дерево | несвязанный коммит двигает корень, не двигая ни одного якоря |
| Строка закрытого среза помечается `HISTORICAL` и по байтам не сверяется | её байты заморожены навсегда |
| `verify_map.py` доказывает, что экстрактор воспроизводит приложенную inventory | иначе пакет проходил все проверки с артефактами разных поколений |
| Долг имеет три состояния, якорь его не разрешает | иначе повторяется случай `ACC-S1-006` |
| `ACC-MIG-014` разрезан, панель среза 3a получила `ACC-MIG-019` | частично доказанный контракт выглядел доказанным |
| `2.11.7` не переименовывается, `-s2` — метка каталога, не протокола | версия совместимости это числовая версия манифеста |

### Решения оператора по эксплуатации

- расхождение версий ставит на паузу **процесс профиля**, а не консоль;
- пауза снимается только оператором вручную после обновления расширения;
- нужна сводка по всем профилям: объявленная и отвечающая версия, расхождение,
  причина паузы — чтобы одним экраном убедиться, что нигде не забыл;
- профили без активной сессии показываются как «на старой версии, не
  обновляется», без тревоги;
- удаление профиля уносит его Run, снимки и файлы; профиль владеет ими
  единолично, поскольку `id` входит в `snapshot.json` и в дайджест;
- удалению предшествует остановка, оператору показывается объём удаляемого;
- удаление при существующих привязках запрещено.

---

## 5a. Каталог закрытых дефектов блока 2+5

Блок прошёл тринадцать раундов внешней проверки. Каждый пункт ниже — реальный
дефект, воспроизведённый на коде до починки и закреплённый тестом после.

**Это не список украшений.** Многие из этих проверок выглядят избыточными,
пока не знаешь, что именно они ловили. Не упрощай их обратно, не поняв, какой
случай исчезнет вместе с ними.

### Раунд 1–2: барьеры протокола

| Дефект | Что было | Чем закрыт |
|---|---|---|
| Отказ после мутации | версия проверялась после `observe`, и отказ проглатывался `try/except: pass` | все барьеры до `observe` и вне проглатывающего блока |
| Владение без аренды | вторая эпоха получала владение при живой первой | аренда 90 с, `CONTROL_AGENT_CONFLICT`, `control_check` |
| Захват двумя записями | владелец сохранялся, затем отдельно истекали endpoint прежней эпохи | одна запись: владелец и истечения вместе |
| Идентичность из URL | `infer_from_page` выводил `conversationId` из адреса | `chatType`/`conversationId` приходят явно, URL — только подсказка |
| Расхождение версий без области | настоящий 2.11.6 не имеет идентичности, запись нельзя было снять | области `LEGACY_AGENT` и `ENDPOINT` |
| Ложный тест | «отказ реестра не проглатывается» ловил `NOT_CONTROL_OWNER` до `observe` | `observe` подменяется на бросающий, проверяется `ENDPOINT_REJECTED` |

### Раунд 3–6: граница схем реестра

| Дефект | Что было | Чем закрыт |
|---|---|---|
| Схема 1 читалась как схема 2 | строки без `endpointId` становились призраками, доступными выбору | `REGISTRY_MIGRATION_REQUIRED`, явная инвалидация с байтовой копией |
| Битый файл принимался | нечитаемый JSON превращался в пустой валидный реестр | `REGISTRY_INVALID` на JSON, корень, отсутствие `schemaVersion` |
| Повреждение внутри схемы 2 | сломанное поле подгонялось к умолчанию | строгая проверка каждой строки и блока `control` |
| Приведение версии схемы | `int("2")` и `int(2.9)` давали 2 | тип ровно `int`, без приведения |
| Наивное время | падало голым `TypeError` из чужого кода | `require_ts`: разбирается и несёт смещение |
| `pin` стал недействующим | `_load` выбрасывал `pins`, а `pin` продолжал туда писать | создание закрепления удалено из реестра, маршрутов и интерфейса |

### Раунд 7–11: режимы выката

| Дефект | Что было | Чем закрыт |
|---|---|---|
| Событийный маршрут в обход | ни версии, ни эпохи, ни владения | общий `_browser_barrier` на `poll`, `event`, `chunk` |
| `CLAIM` в сливе | запрет стоял только в `poll_for_tab` | правило в менеджере, до проверок конкретного задания |
| Барьер без восстановления | истёкшая аренда переставала быть активной, очередь выглядела тихой | `enter_barrier` сам запускает восстановление |
| Рестарт в ходе слива | `recover_expired_leases` пропускает чужую `dispatchEpoch` | `_drain_reconcile` игнорирует эпоху |
| Противоречивый след аренды | `_lease_is_active` отвечал `False` и на отсутствие, и на противоречие | классификация `NO_LEASE`/`ACTIVE`/`EXPIRED`/`INVALID` |
| Нечитаемое задание исчезало | терпимая загрузка давала `{}` | `_iter_jobs_strict` сообщает об ошибке |
| Повреждённое состояние выката | принималось как безопасный слив | проверка значений, согласованность флага и причин |
| Порча `BARRIER` открывала плоскость | нечитаемое состояние выглядело как слив, а слив разрешает события | `valid: false` отдельно от защёлки, `DELIVERY_ROLLOUT_STATE_INVALID` |
| Аренда из ничего | пустой токен совпадал с пустым, затем писался срок | не-`CLAIM` события требуют `ACTIVE` и совпадающий токен |
| Стирание улики | `RELEASE` чинил срок и очищал аренду, `INVALID` исчезал | отказ плюс защёлка на `EXPIRED` и `INVALID` |
| Вложения вне тишины | проверялась только аренда | `ACTIVE_ATTACHMENT_STATES` входят в `outstanding` |

### Раунд 12–13: идентичность и штатный путь

| Дефект | Что было | Чем закрыт |
|---|---|---|
| Классификатор против writer | ждал строку, `CLAIM` пишет объект — отвергалась **каждая настоящая аренда** | проверка фактической формы `claimedBy` |
| Сохранённый `OPEN` | порча одного слова в `BARRIER` открывала плоскость | сохранённый `OPEN` невалиден: писатель его не создаёт |
| Терминальное задание с вложением в полёте | считалось тишиной | противоречие, блокирует барьер |
| Идентичность endpoint декоративна | `tabId` брался из тела запроса после проверки endpoint | вкладка берётся из проверенного endpoint |
| `chunk` без доказательства | чужая вкладка читала вложения, слив выдавал новые части | доверенная вкладка плюс `ACTIVE` аренда |
| Успешная отправка оставляла аренду | `RELEASE` после терминального статуса игнорировался | аренда снимается в том же сохранении |
| Формы `DRAIN` и `BARRIER` несимметричны | порча слова превращала барьер в допустимый слив | у `BARRIER` есть `enteredAt`, у `DRAIN` его быть не должно |

### Повторяющиеся причины

Три причины дали большинство дефектов. Держи их в голове при любой правке.

1. **Подстановка умолчания вместо отказа.** Неизвестное состояние
   превращалось в допустимое, и отсутствие следа читалось как отсутствие
   события.
2. **Наивное время.** Четыре независимых места, каждое падало голым
   `TypeError` из чужого кода или молча меняло смысл.
3. **Выдуманная форма данных.** Дважды фикстура, собранная руками без чтения
   writer, скрывала поломку продуктового пути — во втором случае строгая
   модель отвергала каждую настоящую аренду, а сто тестов были зелёными.

---

## 5b. Как устроен процесс работы

Пользователь ведёт **два чата параллельно**. Второй — независимый ревьюер: он
получает пакет, воспроизводит SHA и прогоны, ищет дефекты негативными
проходами и возвращает список. Все тринадцать раундов выше пришли оттуда.

Что из этого следует для нового чата:

- **пакет должен быть самодостаточным**: изменённые файлы, тесты, отчёт о
  прогоне, диффы относительно основания, точные SHA. Однажды я приложил
  документ без оснастки, и ревьюер не смог воспроизвести числа;
- **каждый найденный дефект воспроизводится на коде до починки**, а не
  принимается на слово, и повторяется после — оба прогона показываются;
- **своя ошибка называется прямо**, без смягчения. Их было много: раскладка
  заданий на диске, схема `claimedBy`, условие остановки, совпадающее с
  собственным именем поля, перезапуск платформы командой самой платформы;
- **замена может не встать молча** — проверяй результат правки, а не факт её
  применения. Дважды `str.replace` не находил цели, и это обнаруживал только
  упавший тест;
- **не переходить к следующему блоку** без подтверждения ревьюера.

---

## 5c. Контракт следующего шага (шаг 3, `selectEndpoint`)

Когда блок 2+5 будет подтверждён и закоммичен, следующий блок — `MAP-028`.

Суть: выбор endpoint перестаёт быть свойством, записанным на endpoint, и
становится **отношением сессии и привязки**. Маршрут серверный, интерфейс к
нему появляется в срезе 3a.

Порядок внутри шага важен и уже установлен: `selectEndpoint` должен работать
**раньше**, чем удаляются остатки старого выбора (`MAP-030` уже сделан,
остаются `MAP-049` схема привязки и `MAP-050` резолвер). Нельзя убирать способ
выбора раньше, чем появился новый.

На этом шаге появляется новый writer relation и публичный route. Читать эту
relation в delivery-resolver раньше его собственной строки карты нельзя:
`select_for_binding`/`authorize_delivery` остаются до `MAP-034`/`MAP-018`, а
остатки binding/resolver schema — до `MAP-049`/`MAP-050`. Поэтому
`ACC-S2-008` на шаге 3 остаётся `PLANNED`; старые значения в новую relation
не мигрируют и сам `selectEndpoint` их не пишет.

---

## 6. Встроенное содержимое файлов

Здесь приведён **весь новый код среза 2 дословно**. Что сокращено, отмечено
явно в конце раздела.

### 6.1. `console_releases/4.5.0-s2/endpoint_registry.py` — файл целиком

591 строка. Это сердце среза 2, приводится полностью.

```python
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from profile_store import atomic_write_json

ONLINE_GRACE_SECONDS = 6

# Endpoint lifecycle. CLOSED and EXPIRED are terminal for a particular
# endpointId: a heartbeat can race a close event and arrive after it, and
# reviving the endpoint would hand a delivery to a tab that no longer exists.
# A tab that comes back must arrive with a new endpointId.
STATE_ONLINE = "ONLINE"
STATE_OFFLINE = "OFFLINE"
STATE_CLOSED = "CLOSED"
STATE_EXPIRED = "EXPIRED"
TERMINAL_STATES = frozenset({STATE_CLOSED, STATE_EXPIRED})

# Ownership lease. 90 seconds is a term of ownership, not a promise that the
# agent will be heard from that often.
CONTROL_LEASE_SECONDS = 90

# Registry schema. Slice-1 rows are keyed by tabId and carry no endpointId or
# browserEpoch, and that identity cannot be reconstructed — a tab number says
# nothing about which endpoint it was. So the old endpoint space is not
# migrated, it is invalidated at the atomic boundary and rebuilt by the
# extension's first reconciliation.
REGISTRY_SCHEMA_VERSION = 2


class EndpointError(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat().replace("+00:00", "Z")


def iso_after(seconds: int) -> str:
    return utc_iso(utc_now() + timedelta(seconds=seconds))


def parse_utc(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def infer_from_page(page: str) -> dict[str, Any]:
    raw = str(page or "")
    chat_type = "unknown"
    conversation_id = None
    project_id = None
    try:
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        path = parsed.path or ""
        if host == "claude.ai" or host.endswith(".claude.ai"):
            chat_type = "claude"
            m = re.search(r"/chat/([^/?#]+)", path, re.I)
            if m:
                conversation_id = m.group(1)
            pm = re.search(r"/(?:project|projects)/([^/?#]+)", path, re.I)
            if pm:
                project_id = pm.group(1)
        elif host in {"chatgpt.com", "www.chatgpt.com", "chat.openai.com"}:
            chat_type = "chatgpt"
            m = re.search(r"/c/([^/?#]+)", path, re.I)
            if m:
                conversation_id = m.group(1)
            pm = re.search(r"/g/(g-p-[^/?#]+)/c/", path, re.I)
            if pm:
                project_id = pm.group(1)
    except Exception:
        pass
    return {
        "chatType": chat_type,
        "conversationId": conversation_id,
        "projectId": project_id,
        "url": raw,
    }


class EndpointRegistry:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.runtime_root = self.root / "runtime"
        self.path = self.runtime_root / "browser-endpoints.json"
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            atomic_write_json(self.path, self._empty_registry(), mode=0o640)

    @staticmethod
    def _empty_registry() -> dict[str, Any]:
        return {"schemaVersion": REGISTRY_SCHEMA_VERSION, "endpoints": [], "control": {}}

    def invalidate_legacy_registry(self, backup_dir: Path | None = None) -> dict[str, Any]:
        """Replace a slice-1 endpoint space with an empty slice-2 one.

        Called by the rollout inside BARRIER, never lazily. The old file is kept
        as rollback evidence rather than deleted: it is the only record of what
        the browser looked like before the boundary, and rollback needs it.
        """
        if not self.path.is_file():
            atomic_write_json(self.path, self._empty_registry(), mode=0o640)
            return {"migrated": False, "reason": "absent", "backup": None}
        # The backup is rollback evidence, so it keeps the original bytes
        # rather than a re-serialised copy: rollback must be able to restore
        # exactly what was there, not something merely equivalent.
        raw_bytes = self.path.read_bytes()
        try:
            body = json.loads(raw_bytes.decode("utf-8"))
        except Exception:
            body = {}
        version = body.get("schemaVersion") if isinstance(body, dict) else None
        if version == REGISTRY_SCHEMA_VERSION:
            return {"migrated": False, "reason": "already-current", "backup": None}
        if version != 1:
            # Only a proven slice-1 registry is invalidated. A corrupt or
            # unknown file is not silently replaced by a clean one: that would
            # destroy the only evidence of what went wrong.
            raise EndpointError(
                f"REGISTRY_INVALID: refusing to invalidate a registry of unknown "
                f"schemaVersion {version!r}")
        backup = None
        target_dir = backup_dir or self.runtime_root
        backup = target_dir / f"browser-endpoints.schema{version}.{utc_iso().replace(':', '').replace('-', '')}.json"
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(raw_bytes)
        atomic_write_json(self.path, self._empty_registry(), mode=0o640)
        return {"migrated": True, "fromSchemaVersion": version,
                "discardedEndpoints": len(body.get("endpoints") or []),
                "discardedPins": len(body.get("pins") or {}),
                "backup": str(backup)}

    def _load(self) -> dict[str, Any]:
        # Fail closed on damage as well as on version. Turning an unreadable
        # file into a clean empty registry is the opposite of the boundary just
        # introduced: a known foreign schema would be refused while a corrupt
        # file would be accepted and quietly reset.
        try:
            raw = self.path.read_text("utf-8")
        except FileNotFoundError:
            atomic_write_json(self.path, self._empty_registry(), mode=0o640)
            raw = self.path.read_text("utf-8")
        try:
            body = json.loads(raw)
        except Exception as exc:
            raise EndpointError(f"REGISTRY_INVALID: endpoint registry is not valid JSON: {exc}")
        if not isinstance(body, dict):
            raise EndpointError("REGISTRY_INVALID: endpoint registry root is not an object")
        if "schemaVersion" not in body:
            raise EndpointError("REGISTRY_INVALID: endpoint registry has no schemaVersion")
        version = body["schemaVersion"]
        # No coercion. int("2") and int(2.9) both yield 2, which would let a
        # file that is not schema 2 pass a boundary whose whole purpose is to
        # tell schemas apart.
        if isinstance(version, bool) or not isinstance(version, int):
            raise EndpointError(
                f"REGISTRY_INVALID: schemaVersion must be an integer, got {version!r}")
        if version != REGISTRY_SCHEMA_VERSION:
            # Fail closed. Reading slice-1 rows as slice-2 rows produced ghost
            # endpoints with no identity that selection could still pick up.
            # Trusting the rollout to have replaced the file is not enough: a
            # guarantee nobody checks is the kind that fails quietly.
            raise EndpointError(
                f"REGISTRY_MIGRATION_REQUIRED: endpoint registry is schemaVersion "
                f"{version}, expected {REGISTRY_SCHEMA_VERSION}")
        # Selection policy left the registry; a stray pins block from an older
        # file is not carried forward.
        body.pop("pins", None)
        self._validate_registry(body)
        return body

    @staticmethod
    def _validate_registry(body: dict[str, Any]) -> None:
        """Refuse damage inside a schema-2 file as firmly as a foreign schema.

        Coercing a broken field back to a default is the same fail-open the
        version check was introduced to remove: an endpoint row without
        endpointId or browserEpoch cannot exist in schema 2, and quietly
        turning it into an identity-less ghost is how such a row reached
        selection in the first place.

        Unknown extra fields are tolerated on purpose — a schema that breaks on
        every added field is one nobody dares extend.
        """
        def bad(msg: str) -> None:
            raise EndpointError(f"REGISTRY_INVALID: {msg}")

        def require_ts(container: dict[str, Any], field: str, where: str) -> None:
            """A timestamp must be present and carry an offset.

            A naive timestamp parses happily and then meets utc_now() further
            down, where comparing it raises a bare TypeError from inside
            unrelated code. Refusing it here turns a crash into a stated reason.
            """
            value = container.get(field)
            if not isinstance(value, str) or not value.strip():
                bad(f"{where}.{field} must be a timestamp")
            parsed = parse_utc(value)
            if parsed is None:
                bad(f"{where}.{field} is not a valid timestamp: {value!r}")
            if parsed.tzinfo is None or parsed.utcoffset() is None:
                bad(f"{where}.{field} must carry a timezone offset: {value!r}")

        if not isinstance(body.get("endpoints"), list):
            bad("endpoints must be a list")
        if not isinstance(body.get("control"), dict):
            bad("control must be an object")

        seen: set[str] = set()
        for idx, row in enumerate(body["endpoints"]):
            where = f"endpoints[{idx}]"
            if not isinstance(row, dict):
                bad(f"{where} must be an object")
            for field in ("endpointId", "browserEpoch", "chatType", "conversationId"):
                value = row.get(field)
                if not isinstance(value, str) or not value.strip():
                    bad(f"{where}.{field} must be a non-empty string")
            tab = row.get("tabId")
            if isinstance(tab, bool) or not isinstance(tab, int) or tab < 0:
                bad(f"{where}.tabId must be a non-negative integer")
            state = row.get("state")
            if state not in (STATE_ONLINE, STATE_OFFLINE, STATE_CLOSED, STATE_EXPIRED):
                bad(f"{where}.state is not a known endpoint state: {state!r}")
            require_ts(row, "firstSeenAt", where)
            require_ts(row, "lastSeenAt", where)
            if state in TERMINAL_STATES:
                # Slice-2 code always stamps this when it terminates an
                # endpoint, so its absence means the row was not written by it.
                require_ts(row, "terminatedAt", where)
            key = row["endpointId"].strip()
            if key in seen:
                bad(f"duplicate endpointId {key!r}")
            seen.add(key)

        control = body["control"]
        if control:
            epoch = control.get("browserEpoch")
            if not isinstance(epoch, str) or not epoch.strip():
                bad("control.browserEpoch must be a non-empty string")
            for field in ("acquiredAt", "lastSeenAt", "leaseUntil"):
                require_ts(control, field, "control")

    def _save(self, body: dict[str, Any]) -> None:
        atomic_write_json(self.path, body, mode=0o640)

    def observe(self, tab_id: int, page: str, endpoint_id: str | None = None,
                title: str | None = None, browser_epoch: str | None = None,
                chat_type: str | None = None, conversation_id: str | None = None,
                project_id: str | None = None) -> dict[str, Any]:
        """Record what the browser reports about one endpoint. Facts only.

        Keyed by endpointId rather than tabId: a tab number is reused by the
        browser, so keying by it lets a new tab inherit the identity of a dead
        one. The endpointId is minted by the extension and survives a page
        reload within the same epoch, which is what makes a reload keep its
        delivery target instead of silently acquiring a new one.

        No policy is stored here — no binding, no approval, no staleness. The
        registry answers "what does the browser look like", and selection
        answers "what may be used". Mixing the two is how a stale approval
        became indistinguishable from an absent tab.
        """
        tab_id = int(tab_id)
        if tab_id < 0:
            raise EndpointError("invalid tabId")
        endpoint_key = str(endpoint_id).strip() if endpoint_id else None
        if not endpoint_key:
            raise EndpointError("endpointId is required")
        epoch = str(browser_epoch).strip() if browser_epoch else None
        if not epoch:
            raise EndpointError("browserEpoch is required")
        # The browser states its identity; the URL is kept as a launch hint
        # only. Deriving identity from the URL is what let a reload or a
        # redirect quietly change which chat an endpoint claimed to be.
        stated = {
            "chatType": str(chat_type).strip() if chat_type else None,
            "conversationId": str(conversation_id).strip() if conversation_id else None,
            "projectId": str(project_id).strip() if project_id else None,
        }
        if not stated["chatType"] or not stated["conversationId"]:
            raise EndpointError("chatType and conversationId are required")
        now = utc_iso()
        body = self._load()
        rows = list(body.get("endpoints") or [])
        existing = next((x for x in rows if str(x.get("endpointId") or "") == endpoint_key), None)

        if existing and str(existing.get("state") or "") in TERMINAL_STATES:
            # A late pulse for an endpoint that is already CLOSED or EXPIRED.
            # There is no transition back: returning the row unchanged keeps the
            # race harmless without pretending the tab is alive.
            return self._decorate(dict(existing))
        if existing and str(existing.get("browserEpoch") or "") != epoch:
            raise EndpointError("endpointId belongs to another browserEpoch")
        previous_seen = parse_utc(str((existing or {}).get("lastSeenAt") or ""))
        continuity_broken = bool(previous_seen and (utc_now() - previous_seen).total_seconds() > ONLINE_GRACE_SECONDS)
        # Disconnect telemetry: observation only, never an authorization gate.
        history = [str(x) for x in ((existing or {}).get("disconnects") or []) if x]
        if continuity_broken:
            history.append(now)
        cutoff = utc_now() - timedelta(hours=24)
        history = [x for x in history if (parse_utc(x) or utc_now()) >= cutoff][-200:]
        gap_seconds = None
        if continuity_broken and previous_seen:
            gap_seconds = round((utc_now() - previous_seen).total_seconds(), 1)
        row = {
            "disconnects": history,
            "disconnects24h": len(history),
            "lastDisconnectAt": history[-1] if history else (existing or {}).get("lastDisconnectAt"),
            "lastGapSeconds": gap_seconds if gap_seconds is not None else (existing or {}).get("lastGapSeconds"),
            "tabId": tab_id,
            "endpointId": endpoint_key,
            "browserEpoch": epoch,
            "state": STATE_ONLINE,
            "chatType": stated["chatType"],
            "conversationId": stated["conversationId"],
            "projectId": stated["projectId"],
            # Stored, never used to decide identity.
            "url": str(page or "") or None,
            "title": str(title).strip() if title else (existing or {}).get("title"),
            "firstSeenAt": (existing or {}).get("firstSeenAt") if not continuity_broken else now,
            "lastSeenAt": now,
        }
        if not row["firstSeenAt"]:
            row["firstSeenAt"] = now
        replaced = False
        for idx, item in enumerate(rows):
            if str(item.get("endpointId") or "") == endpoint_key:
                rows[idx] = row
                replaced = True
                break
        if not replaced:
            rows.append(row)
        rows.sort(key=lambda x: str(x.get("endpointId") or ""))
        body["endpoints"] = rows
        self._save(body)
        return self._decorate(row)


    # ---- control ownership ------------------------------------------------
    #
    # One control agent per browser epoch, held by a lease. Showing a conflict
    # is not enough: if both epochs receive a reconciliation plan we merely
    # observe the conflict and still end up with two competing reconcilers, so
    # the loser gets no plan and changes nothing.
    #
    # Ownership follows a real change of owner, not any lease gap: an epoch
    # that reappears before anyone took over reacquires its own endpoints
    # rather than minting new identities for them.

    def control_state(self) -> dict[str, Any]:
        body = self._load()
        control = body.get("control") if isinstance(body.get("control"), dict) else {}
        until = parse_utc(str(control.get("leaseUntil") or ""))
        return {"browserEpoch": control.get("browserEpoch"),
                "acquiredAt": control.get("acquiredAt"),
                "lastSeenAt": control.get("lastSeenAt"),
                "leaseUntil": control.get("leaseUntil"),
                "leaseLive": bool(until and until > utc_now())}

    def acquire_control(self, browser_epoch: str) -> dict[str, Any]:
        """Acquire, renew or refuse control for an epoch.

        Refusal is a value, not an exception: the caller must be able to answer
        CONTROL_AGENT_CONFLICT without the refusal itself having written
        anything.

        Takeover is a single write. Marking the new owner first and expiring the
        previous endpoints second leaves, if the process dies between them, a
        new owner holding live endpoints of an epoch that no longer exists.
        """
        epoch = str(browser_epoch or "").strip()
        if not epoch:
            raise EndpointError("browserEpoch is required")
        body = self._load()
        control = body.get("control") if isinstance(body.get("control"), dict) else {}
        current = str(control.get("browserEpoch") or "")
        until = parse_utc(str(control.get("leaseUntil") or ""))
        now = utc_now()
        lease_live = bool(until and until > now)

        if current and current != epoch and lease_live:
            return {"owner": False, "conflict": True, "browserEpoch": epoch,
                    "heldBy": current, "leaseUntil": control.get("leaseUntil"),
                    "transferred": False, "expiredEndpoints": []}

        now_iso = utc_iso()
        lease_until = iso_after(CONTROL_LEASE_SECONDS)
        takeover = bool(current and current != epoch)
        rows = list(body.get("endpoints") or [])
        expired: list[str] = []
        if takeover:
            for idx, item in enumerate(rows):
                if str(item.get("browserEpoch") or "") == epoch:
                    continue
                if str(item.get("state") or "") in TERMINAL_STATES:
                    continue
                row = dict(item)
                row["state"] = STATE_EXPIRED
                row["terminatedAt"] = now_iso
                rows[idx] = row
                expired.append(str(row.get("endpointId") or ""))
            body["endpoints"] = rows

        body["control"] = {
            "browserEpoch": epoch,
            "acquiredAt": now_iso if (takeover or not current) else (control.get("acquiredAt") or now_iso),
            "lastSeenAt": now_iso,
            "leaseUntil": lease_until,
        }
        # One save: owner and expiries commit together or not at all.
        self._save(body)
        return {"owner": True, "conflict": False, "browserEpoch": epoch,
                "leaseUntil": lease_until, "transferred": takeover,
                "reacquired": bool(current == epoch and not lease_live),
                "expiredEndpoints": expired}

    def control_check(self, browser_epoch: str) -> dict[str, Any]:
        """Answer whether this epoch may act, without writing anything."""
        epoch = str(browser_epoch or "").strip()
        state = self.control_state()
        current = str(state.get("browserEpoch") or "")
        if not epoch or not current:
            return {"owner": False, "conflict": False}
        if current == epoch:
            return {"owner": bool(state["leaseLive"]), "conflict": False}
        # A foreign epoch while the owner's lease is alive is a conflict, not a
        # plain "not owner": the two answers point the operator at different
        # problems.
        return {"owner": False, "conflict": bool(state["leaseLive"]), "heldBy": current}

    def _decorate(self, row: dict[str, Any]) -> dict[str, Any]:
        """Derive presence from the last heartbeat. Terminal states never move."""
        out = dict(row)
        seen = parse_utc(str(row.get("lastSeenAt") or ""))
        age = (utc_now() - seen).total_seconds() if seen else 10**9
        stored = str(row.get("state") or "")
        if stored in TERMINAL_STATES:
            out["state"] = stored
        else:
            out["state"] = STATE_ONLINE if age <= ONLINE_GRACE_SECONDS else STATE_OFFLINE
        out["online"] = out["state"] == STATE_ONLINE
        out["ageSeconds"] = max(0.0, age) if age < 10**8 else None
        return out

    def close(self, endpoint_id: str, browser_epoch: str) -> dict[str, Any]:
        """The tab is gone. Terminal, and only for its own epoch."""
        return self._terminate(endpoint_id, browser_epoch, STATE_CLOSED)

    def expire_epoch(self, browser_epoch: str) -> list[str]:
        """A new browser epoch strands every endpoint of the previous one.

        Expiry follows a real change of owner, not any lease gap: a flapping
        lease under the same owner must not force new identities, because that
        would rebuild delivery targets for no reason.
        """
        body = self._load()
        rows = list(body.get("endpoints") or [])
        expired = []
        for idx, item in enumerate(rows):
            if str(item.get("browserEpoch") or "") == str(browser_epoch):
                continue
            if str(item.get("state") or "") in TERMINAL_STATES:
                continue
            row = dict(item)
            row["state"] = STATE_EXPIRED
            row["terminatedAt"] = utc_iso()
            rows[idx] = row
            expired.append(str(row.get("endpointId") or ""))
        if expired:
            body["endpoints"] = rows
            self._save(body)
        return expired

    def _terminate(self, endpoint_id: str, browser_epoch: str, state: str) -> dict[str, Any]:
        key = str(endpoint_id).strip()
        body = self._load()
        rows = list(body.get("endpoints") or [])
        for idx, item in enumerate(rows):
            if str(item.get("endpointId") or "") != key:
                continue
            if str(item.get("browserEpoch") or "") != str(browser_epoch):
                raise EndpointError("endpointId belongs to another browserEpoch")
            row = dict(item)
            if str(row.get("state") or "") in TERMINAL_STATES:
                return self._decorate(row)
            row["state"] = state
            row["terminatedAt"] = utc_iso()
            rows[idx] = row
            body["endpoints"] = rows
            self._save(body)
            return self._decorate(row)
        raise EndpointError("endpoint not found")

    def list(self) -> dict[str, Any]:
        """Observed browser state only.

        Selection policy is not returned here. OFFLINE endpoints are included:
        hiding them is a UI filter, and a server that hides them makes an absent
        tab and a policy decision look the same to every caller.
        """
        body = self._load()
        endpoints = [self._decorate(dict(x)) for x in body.get("endpoints") or []]
        order = {STATE_ONLINE: 0, STATE_OFFLINE: 1, STATE_CLOSED: 2, STATE_EXPIRED: 3}
        endpoints.sort(key=lambda x: (order.get(str(x.get("state")), 9), str(x.get("endpointId") or "")))
        return {"schemaVersion": 2, "onlineGraceSeconds": ONLINE_GRACE_SECONDS,
                "endpoints": endpoints}

    def endpoints_for_binding(self, binding: dict[str, Any], online_only: bool = True) -> list[dict[str, Any]]:
        rows = []
        for ep in self.list()["endpoints"]:
            if str(ep.get("chatType")) != str(binding.get("chatType")):
                continue
            if str(ep.get("conversationId") or "") != str(binding.get("conversationId") or ""):
                continue
            bp = str(binding.get("projectId") or "")
            ep_project = str(ep.get("projectId") or "")
            if bp and ep_project and bp != ep_project:
                continue
            if online_only and not ep.get("online"):
                continue
            rows.append(ep)
        return rows

    # pin/unpin removed in slice 2.
    #
    # Selection stopped being a property written onto an endpoint: it is a
    # relation between a session and a binding, established by selectEndpoint.
    # There is deliberately no way left to *create* a pin. pin_state and
    # pinned_tab survive only as read-side tails for callers that have not moved
    # yet; after the schema-2 invalidation there is physically nothing for them
    # to read, and they disappear with the selection rewrite.

    def pin_state(self, binding_id: str) -> dict[str, Any] | None:
        value = self._load().get("pins", {}).get(str(binding_id))
        if value is None:
            return None
        if isinstance(value, dict):
            try:
                return {**value, "tabId": int(value.get("tabId"))}
            except Exception:
                return None
        try:
            return {"tabId": int(value), "stale": False}
        except Exception:
            return None

    def pinned_tab(self, binding_id: str) -> int | None:
        pin = self.pin_state(binding_id)
        return int(pin["tabId"]) if pin else None

    def select_for_binding(self, binding: dict[str, Any]) -> dict[str, Any]:
        if str(binding.get("endpointPolicy") or "conversation") == "approved_endpoint":
            approved = str(binding.get("approvedEndpointId") or "")
            if not approved:
                return {"status": "ENDPOINT_NOT_APPROVED", "endpoint": None, "candidates": []}
            candidates = [x for x in self.endpoints_for_binding(binding, online_only=True) if str(x.get("endpointId") or "") == approved]
            if not candidates:
                return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": []}
            return {"status": "READY", "endpoint": candidates[0], "candidates": candidates}

        candidates = self.endpoints_for_binding(binding, online_only=True)
        pin = self.pin_state(str(binding.get("bindingId") or ""))
        if pin is not None:
            pinned = int(pin["tabId"])
            if pin.get("stale"):
                return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": candidates, "pinned": True, "pinnedTabId": pinned, "pinStale": True, "pinState": pin}
            chosen = next((x for x in candidates if int(x.get("tabId") or -1) == pinned), None)
            if chosen is not None:
                return {"status": "READY", "endpoint": chosen, "candidates": candidates, "pinned": True}
            return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": candidates, "pinned": True, "pinnedTabId": pinned}
        if not candidates:
            return {"status": "WAITING_FOR_ENDPOINT", "endpoint": None, "candidates": []}
        if len(candidates) > 1:
            return {"status": "ENDPOINT_AMBIGUOUS", "endpoint": None, "candidates": candidates}
        return {"status": "READY", "endpoint": candidates[0], "candidates": candidates}
```

### 6.2. `console_releases/4.5.0-s2/console_server.py` — фрагменты среза 2

Файл 1349 строк, приводятся изменённые и новые части. Остальное — код
основания 4.5.0-s1 без изменений.

#### Константы протокола

```python
VERSION = "4.5.0-s2"

# The extension half of slice 2 ships as its own release; server and extension
# are switched together, so the server names the one version it can speak to.
#
# The wire compatibility version is the numeric manifest version. The repo
# release directory carries the -s2 label; the protocol does not.
REQUIRED_EXTENSION_VERSION = "2.12.0"
POLL_KINDS = frozenset({"CONTROL_AGENT", "ENDPOINT"})
```

#### Устойчивая запись расхождения версий

```python
    # ---- version mismatch record -----------------------------------------
    #
    # One authoritative record, attached to the endpoint identity, never a
    # second copy on the profile: two copies drift the moment one is cleared.
    # It is a diagnostic fact, not a pause — the pause state does not exist
    # until slice 5, and showing one earlier would show a state the system
    # does not have.

    def _mismatch_path(self) -> Path:
        return self.root / "runtime" / "version-mismatch.json"

    def _record_version_mismatch(self, expected: str, observed: str | None,
                                 endpoint_id: str | None, browser_epoch: str | None) -> None:
        """One record per scope, never a second copy.

        A real 2.11.6 client sends neither endpointId nor browserEpoch, so it
        cannot be keyed by endpoint identity — and inventing one from the URL is
        exactly what the identity rules forbid. Such a client is recorded under
        LEGACY_AGENT: a single row is enough because 4.5 has one control agent.
        A client that already speaks slice-2 identity is recorded under
        ENDPOINT and keyed by it.
        """
        path = self._mismatch_path()
        try:
            body = json.loads(path.read_text("utf-8")) if path.is_file() else {}
        except Exception:
            body = {}
        rows = body.get("mismatches") if isinstance(body.get("mismatches"), dict) else {}
        scope = "ENDPOINT" if endpoint_id else "LEGACY_AGENT"
        key = f"ENDPOINT:{endpoint_id}" if endpoint_id else "LEGACY_AGENT"
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        row = rows.get(key) if isinstance(rows.get(key), dict) else {}
        rows[key] = {
            "scope": scope,
            "expected": expected,
            "observed": observed,
            "endpointId": endpoint_id,
            "browserEpoch": browser_epoch,
            # Repeated incompatible polls refresh lastSeenAt; they do not
            # multiply events.
            "firstSeenAt": row.get("firstSeenAt") or now,
            "lastSeenAt": now,
        }
        atomic_write_json(path, {"schemaVersion": 1, "mismatches": rows}, mode=0o640)

    def _clear_version_mismatch(self, browser_epoch: str | None, scope: str | None = None) -> None:
        """A compatible handshake clears the active record it proves obsolete.

        A successful CONTROL_AGENT proof clears the LEGACY_AGENT record: the
        agent that could not speak slice 2 has now spoken it. Without this the
        record from a real 2.11.6 client would survive the upgrade for ever,
        because it carries no epoch to match against.
        """
        path = self._mismatch_path()
        if not path.is_file():
            return
        try:
            body = json.loads(path.read_text("utf-8"))
        except Exception:
            return
        rows = body.get("mismatches") if isinstance(body.get("mismatches"), dict) else {}
        def obsolete(v: dict) -> bool:
            if scope:
                return str(v.get("scope") or "") == scope
            return bool(browser_epoch) and str(v.get("browserEpoch") or "") == str(browser_epoch)
        keep = {k: v for k, v in rows.items() if not obsolete(v)}
        if keep != rows:
            atomic_write_json(path, {"schemaVersion": 1, "mismatches": keep}, mode=0o640)

    def version_mismatches(self) -> list[dict[str, Any]]:
        path = self._mismatch_path()
        if not path.is_file():
            return []
        try:
            body = json.loads(path.read_text("utf-8"))
        except Exception:
            return []
        rows = body.get("mismatches") if isinstance(body.get("mismatches"), dict) else {}
        return sorted(rows.values(), key=lambda x: str(x.get("firstSeenAt") or ""))
```

#### Общий барьер браузерных маршрутов

```python
    # ---- browser protocol barrier ----------------------------------------

    def _browser_barrier(self, request: web.Request, *, require_endpoint: bool):
        """Settle version, epoch, ownership and endpoint state before mutation.

        Shared by every route the browser can reach. Duplicating the checks per
        route is how one of them ends up missing a check and becomes a way
        around all the others — the delivery event route was exactly that: no
        version gate, no epoch, no ownership, straight into delivery state.

        Returns a validated context, or a web.Response to send back untouched.
        """
        query = request.rel_url.query
        extension_version = str(query.get("extensionVersion") or "").strip()
        browser_epoch = str(query.get("browserEpoch") or "").strip()
        endpoint_id = str(query.get("endpointId") or "").strip()

        if extension_version != REQUIRED_EXTENSION_VERSION:
            self._record_version_mismatch(expected=REQUIRED_EXTENSION_VERSION,
                                          observed=extension_version or None,
                                          endpoint_id=endpoint_id or None,
                                          browser_epoch=browser_epoch or None)
            return None, web.json_response(
                {"ok": False, "code": "EXTENSION_VERSION_INCOMPATIBLE",
                 "expected": REQUIRED_EXTENSION_VERSION, "observed": extension_version or None},
                status=409)
        if not browser_epoch:
            return None, web.json_response({"ok": False, "code": "BROWSER_EPOCH_REQUIRED"}, status=400)

        control = self.endpoints.control_check(browser_epoch)
        if control.get("conflict"):
            return None, web.json_response({"ok": False, "code": "CONTROL_AGENT_CONFLICT",
                                            "browserEpoch": browser_epoch,
                                            "heldBy": control.get("heldBy")}, status=409)
        if not control.get("owner"):
            return None, web.json_response({"ok": False, "code": "NOT_CONTROL_OWNER",
                                            "browserEpoch": browser_epoch}, status=409)

        rollout = self.delivery.rollout_state()
        if not rollout.get("valid", True):
            # Rollout state that cannot be trusted is not a working mode. A
            # damaged file used to surface as a latched DRAIN, which still
            # permits events for claimed work — so damaging the persisted
            # BARRIER reopened the very plane it had closed.
            return None, web.json_response({"ok": False, "code": "DELIVERY_ROLLOUT_STATE_INVALID",
                                            "error": rollout.get("stateError")}, status=409)
        if rollout.get("mode") == "BARRIER":
            # A real refusal, not a label. Control and diagnostics stay
            # reachable; product delivery does not.
            return None, web.json_response({"ok": False, "code": "DELIVERY_BARRIER"}, status=409)

        if not require_endpoint:
            return {"browserEpoch": browser_epoch, "endpointId": endpoint_id or None}, None

        if not endpoint_id:
            return None, web.json_response({"ok": False, "code": "ENDPOINT_ID_REQUIRED"}, status=400)
        row = next((e for e in self.endpoints.list()["endpoints"]
                    if str(e.get("endpointId") or "") == endpoint_id), None)
        if row is None:
            return None, web.json_response({"ok": False, "code": "ENDPOINT_UNKNOWN",
                                            "endpointId": endpoint_id}, status=409)
        if str(row.get("browserEpoch") or "") != browser_epoch:
            return None, web.json_response({"ok": False, "code": "ENDPOINT_EPOCH_MISMATCH",
                                            "endpointId": endpoint_id}, status=409)
        if str(row.get("state") or "") in ("CLOSED", "EXPIRED"):
            # A terminal endpoint must not move delivery state. Its tab is gone;
            # accepting an event for it would attribute the outcome of a
            # delivery to a target that cannot have received it.
            return None, web.json_response({"ok": False, "code": "ENDPOINT_TERMINAL",
                                            "endpointId": endpoint_id,
                                            "state": row.get("state")}, status=409)
        return {"browserEpoch": browser_epoch, "endpointId": endpoint_id, "endpoint": row}, None
```

#### `api_delivery_poll`

```python
    async def api_delivery_poll(self, request: web.Request) -> web.Response:
        """Poll entry point. Every barrier runs before anything is recorded.

        Order matters more than it looks. In 4.4.0 `observe` sat inside a
        `try/except: pass`, so a client of an incompatible version reached the
        registry first and only then failed — and its failure was swallowed. A
        refusal that arrives after the state has already moved is not a refusal.
        Version, kind and ownership are therefore settled here, before observe,
        and outside any swallowing block.
        """
        self.require_auth(request)
        query = request.rel_url.query

        extension_version = str(query.get("extensionVersion") or "").strip()
        poll_kind = str(query.get("pollKind") or "").strip().upper()
        browser_epoch = str(query.get("browserEpoch") or "").strip()

        if extension_version != REQUIRED_EXTENSION_VERSION:
            # Recorded as a durable, single fact rather than an event per poll,
            # so the operator can see which tabs were never updated instead of
            # reading a repeating refusal in a log.
            self._record_version_mismatch(expected=REQUIRED_EXTENSION_VERSION,
                                          observed=extension_version or None,
                                          endpoint_id=str(query.get("endpointId") or "").strip() or None,
                                          browser_epoch=browser_epoch or None)
            return web.json_response(
                {"ok": False, "code": "EXTENSION_VERSION_INCOMPATIBLE",
                 "expected": REQUIRED_EXTENSION_VERSION, "observed": extension_version or None},
                status=409)
        if poll_kind not in POLL_KINDS:
            return web.json_response({"ok": False, "code": "POLL_KIND_INVALID",
                                      "expected": sorted(POLL_KINDS)}, status=400)
        if not browser_epoch:
            return web.json_response({"ok": False, "code": "BROWSER_EPOCH_REQUIRED"}, status=400)

        if poll_kind == "CONTROL_AGENT":
            state = self.endpoints.acquire_control(browser_epoch)
            if not state["owner"]:
                # The loser gets no plan and no delivery. Showing the conflict
                # while handing both epochs a plan would leave two reconcilers
                # competing, which is the situation the lease exists to avoid.
                return web.json_response({"ok": False, "code": "CONTROL_AGENT_CONFLICT",
                                          "browserEpoch": browser_epoch,
                                          "heldBy": state.get("heldBy")}, status=409)
            self._clear_version_mismatch(browser_epoch, scope="LEGACY_AGENT")
            self._clear_version_mismatch(browser_epoch)
            return web.json_response({"ok": True, "controlState": "OWNER",
                                      "browserEpoch": browser_epoch,
                                      "leaseUntil": state["leaseUntil"],
                                      "transferred": state["transferred"],
                                      "reacquired": state.get("reacquired", False),
                                      "expiredEndpoints": state["expiredEndpoints"]})

        # The first ENDPOINT poll is what creates the endpoint, so this branch
        # checks ownership but cannot require the endpoint to exist yet.
        _ctx, refusal = self._browser_barrier(request, require_endpoint=False)
        if refusal is not None:
            return refusal

        endpoint_id = str(query.get("endpointId") or "").strip()
        if not endpoint_id:
            return web.json_response({"ok": False, "code": "ENDPOINT_ID_REQUIRED"}, status=400)
        chat_type = str(query.get("chatType") or "").strip()
        conversation_id = str(query.get("conversationId") or "").strip()
        project_id = str(query.get("projectId") or "").strip() or None
        if not chat_type or not conversation_id:
            return web.json_response({"ok": False, "code": "ENDPOINT_IDENTITY_REQUIRED"}, status=400)
        try:
            tab_id = int(query.get("tabId") or -1)
        except Exception:
            return web.json_response({"ok": False, "error": "invalid tabId"}, status=400)
        page = str(query.get("page") or "")
        title = str(query.get("title") or "").strip() or None

        # Deliberately not swallowed. On the new protocol path a registry
        # refusal is the answer, not something to hide behind an empty 200 —
        # that combination is what let a broken call look healthy.
        try:
            self.endpoints.observe(tab_id, page, endpoint_id=endpoint_id,
                                   title=title, browser_epoch=browser_epoch,
                                   chat_type=chat_type, conversation_id=conversation_id,
                                   project_id=project_id)
        except EndpointError as exc:
            return web.json_response({"ok": False, "code": "ENDPOINT_REJECTED",
                                      "error": str(exc)}, status=409)

        self._clear_version_mismatch(browser_epoch)
        self._expire_endpoint_waits()
        job = self.delivery.poll_for_tab(tab_id, page)
        if job is not None:
            job = self._mark_profile_delivery_ready(job, tab_id, page)
            if not self._profile_job_poll_allowed(job, tab_id):
                job = None
        return web.json_response({"ok": True, "job": job})
```

#### `api_delivery_event`

```python
    async def api_delivery_event(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        ctx, refusal = self._browser_barrier(request, require_endpoint=True)
        if refusal is not None:
            return refusal
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        try:
            body = await request.json()
            if not isinstance(body, dict):
                body = {}
            # The tab is taken from the endpoint the barrier just validated,
            # never from the request body. Checking endpointId and then trusting
            # a client-supplied tabId made the endpoint identity decorative: an
            # endpoint belonging to one tab could claim and report on a delivery
            # addressed to another simply by naming it.
            body = dict(body)
            body["tabId"] = int(ctx["endpoint"].get("tabId"))
            job = self.delivery.update_from_client(run_id, job_id, body)
            await self.publish({"type": "delivery:update", "runId": run_id, "job": job})
            return web.json_response({"ok": True, "job": job})
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=409)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)
```

#### `api_delivery_chunk`

```python
    async def api_delivery_chunk(self, request: web.Request) -> web.Response:
        self.require_auth(request)
        # Attachment bytes are part of a delivery in progress, so the same
        # barrier applies: an incompatible or unowned client must not be able
        # to read them just because this route is not the poll route.
        ctx, refusal = self._browser_barrier(request, require_endpoint=True)
        if refusal is not None:
            return refusal
        run_id = request.match_info["run_id"]
        job_id = request.match_info["job_id"]
        attachment_id = request.match_info["attachment_id"]
        query = request.rel_url.query
        try:
            offset = int(query.get("offset") or 0)
            limit = int(query.get("limit") or 512 * 1024)
            # Reading a chunk is part of performing a delivery, so it needs the
            # same proof as reporting on one: the caller's own tab, and a live
            # lease it holds. Without this a drain still handed out fresh parts
            # of a delivery nobody had claimed.
            body = self.delivery.attachment_chunk(
                run_id, job_id, attachment_id, offset, limit,
                tab_id=int(ctx["endpoint"].get("tabId")),
                lease_token=str(query.get("leaseToken") or "").strip())
            return web.json_response(body)
        except DeliveryError as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=404)

    def _actor_name(self, request: web.Request) -> str:
        return str(request.headers.get("X-PAP-Operator") or "").strip() or "unknown"
```

### 6.3. `console_releases/4.5.0-s2/delivery_manager.py` — фрагменты среза 2

Файл 1965 строк, приводятся новые и изменённые части.

#### Режимы выката
```python
# Rollout modes for the breaking boundary.
#
#   OPEN    normal operation
#   DRAIN   no new work is handed out and no new claim may be taken; events for
#           work already claimed are still accepted so it can finish
#   BARRIER new delivery work is refused outright
#
# DRAIN is a pass with an identity of its own, not merely "there are no leases
# right now". A lease that existed and expired during the pass leaves an
# outcome nobody can report on, and an empty queue afterwards is not evidence
# that the outcome is known.
ROLLOUT_OPEN = 'OPEN'
ROLLOUT_DRAIN = 'DRAIN'
ROLLOUT_BARRIER = 'BARRIER'
ROLLOUT_MODES = (ROLLOUT_OPEN, ROLLOUT_DRAIN, ROLLOUT_BARRIER)
PAUSED_JOB_STATE = 'PAUSED_AFTER_RESTART'
CLAIM_LEASE_SECONDS = 15
MAX_AUTO_RECOVERIES = 3
SMART_ZIP_MAX_BYTES = 30 * 1024 * 1024
SMART_ZIP_SAFETY_BYTES = 64 * 1024
```

#### Состояние выката, слив, защёлка, барьер

```python
    # ---- rollout mode -----------------------------------------------------

    def _rollout_path(self) -> Path:
        path = self.data_dir.parent / 'runtime' / 'delivery-rollout.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    @staticmethod
    def _unsafe_state(reason: str) -> dict[str, Any]:
        """State that cannot be trusted at all, as distinct from a latched drain.

        These are different things and were conflated. A valid DRAIN with the
        latch set still permits events for already-claimed work, so presenting
        an unreadable file as a latched DRAIN reopened the delivery plane
        exactly when the persisted BARRIER had been damaged.
        """
        return {'mode': ROLLOUT_DRAIN, 'drainId': None, 'unsafe': True,
                'valid': False, 'stateError': reason,
                'unsafeReasons': [reason], 'startedAt': None}

    @staticmethod
    def _aware_ts(value: Any) -> bool:
        if not isinstance(value, str) or not value.strip():
            return False
        parsed = iso_dt(value)
        return bool(parsed and parsed.tzinfo is not None and parsed.utcoffset() is not None)

    def rollout_state(self) -> dict[str, Any]:
        """Read the rollout state, treating anything unexpected as unsafe.

        Filling in defaults for a partially written DRAIN would invent the very
        fact the latch exists to preserve: this writer always stores drainId,
        startedAt, unsafe and unsafeReasons together, so a DRAIN missing any of
        them was not written by it.
        """
        path = self._rollout_path()
        if not path.is_file():
            return {'mode': ROLLOUT_OPEN, 'drainId': None, 'unsafe': False,
                    'valid': True, 'unsafeReasons': [], 'startedAt': None}
        try:
            body = json.loads(path.read_text('utf-8'))
        except Exception:
            return self._unsafe_state('rollout state unreadable')
        if not isinstance(body, dict):
            return self._unsafe_state('rollout state is not an object')
        mode = body.get('mode')
        if mode not in ROLLOUT_MODES:
            return self._unsafe_state(f'unknown rollout mode {mode!r}')
        if mode == ROLLOUT_OPEN:
            # Absence of the file means OPEN; this writer never stores an OPEN
            # file. So a stored OPEN is not a canonical state, and accepting it
            # meant that damaging one field of a valid BARRIER — the word
            # BARRIER itself — reopened the delivery plane while the rest of the
            # record still said otherwise.
            return self._unsafe_state(
                'rollout state stores OPEN, which this writer never produces')
        if not isinstance(body.get('drainId'), str) or not body['drainId'].strip():
            return self._unsafe_state('rollout state has no drainId')
        if not self._aware_ts(body.get('startedAt')):
            return self._unsafe_state('rollout startedAt is not a timezone-aware timestamp')
        if not isinstance(body.get('unsafe'), bool):
            return self._unsafe_state('rollout state has no unsafe flag')
        reasons = body.get('unsafeReasons')
        if not isinstance(reasons, list) or not all(isinstance(r, str) for r in reasons):
            return self._unsafe_state('rollout unsafeReasons is not a list of strings')
        # This writer never stores one without the other. A cleared flag beside
        # recorded reasons is not a safe drain; it is a state nobody wrote.
        if bool(body['unsafe']) != bool(reasons):
            return self._unsafe_state(
                'rollout unsafe flag contradicts unsafeReasons')
        # Canonical shapes, symmetric on purpose: a BARRIER carries enteredAt
        # and a DRAIN does not. Without the second half, damaging one word of a
        # valid BARRIER turned it into an acceptable DRAIN with the barrier's
        # own timestamp still inside.
        if mode == ROLLOUT_BARRIER and not self._aware_ts(body.get('enteredAt')):
            return self._unsafe_state('barrier enteredAt is not a timezone-aware timestamp')
        if mode == ROLLOUT_DRAIN and body.get('enteredAt') is not None:
            return self._unsafe_state('drain state carries a barrier enteredAt')
        body['valid'] = True
        return body

    def _write_rollout(self, body: dict[str, Any]) -> None:
        atomic_write_json(self._rollout_path(), body)

    def begin_drain(self) -> dict[str, Any]:
        """Start a drain pass with its own identity.

        Restarting the pass is what clears the latch, and only an operator can
        do that: an automatic reset would turn "we lost track of an outcome"
        into "there is nothing outstanding".
        """
        state = {'mode': ROLLOUT_DRAIN, 'drainId': uuid.uuid4().hex,
                 'startedAt': utc_now(), 'unsafe': False, 'unsafeReasons': []}
        self._write_rollout(state)
        return state

    def mark_unsafe(self, reason: str) -> dict[str, Any]:
        """Latch the drain as unsafe. Monotonic within a pass."""
        state = self.rollout_state()
        if state.get('mode') != ROLLOUT_DRAIN:
            return state
        reasons = list(state.get('unsafeReasons') or [])
        if reason not in reasons:
            reasons.append(reason)
        state['unsafe'] = True
        state['unsafeReasons'] = reasons
        self._write_rollout(state)
        return state


    # ---- lease evidence during a drain ------------------------------------

    LEASE_NONE = 'NO_LEASE'
    LEASE_ACTIVE = 'ACTIVE'
    LEASE_EXPIRED = 'EXPIRED'
    LEASE_INVALID = 'INVALID'

    def classify_lease(self, job: dict[str, Any]) -> tuple[str, str]:
        """Classify the lease trace on disk, not merely whether it is live now.

        `_lease_is_active` answers False for a missing lease and for a
        contradictory one alike, and the drain read that as "nothing here".
        A half-written lease is an unknown outcome, not an absent one, so the
        two must be told apart before the boundary closes over them.
        """
        token = job.get('claimLeaseToken')
        expires_raw = job.get('claimExpiresAt')
        # CLAIM writes these four together and _clear_lease removes them
        # together, so any subset is a half-written trace, not an absent lease.
        # clientHeartbeatAt is deliberately excluded: it outlives _clear_lease.
        claimed_by = job.get('claimedBy')
        present = {
            'claimLeaseToken': isinstance(token, str) and token.strip() != '',
            'claimExpiresAt': isinstance(expires_raw, str) and expires_raw.strip() != '',
            'claimHeartbeatAt': isinstance(job.get('claimHeartbeatAt'), str)
                                and str(job.get('claimHeartbeatAt')).strip() != '',
            'claimedBy': isinstance(claimed_by, dict) and bool(claimed_by),
        }
        if not any(present.values()):
            return self.LEASE_NONE, ''
        missing = [name for name, ok in present.items() if not ok]
        if missing:
            return self.LEASE_INVALID, 'incomplete lease trace, missing ' + ', '.join(missing)
        if not self._aware_ts(job.get('claimHeartbeatAt')):
            return self.LEASE_INVALID, 'claimHeartbeatAt is not a timezone-aware timestamp'
        # claimedBy is the provenance CLAIM records: which tab took the lease,
        # where, when, and under which token. Validated against that shape
        # rather than a simpler one — a classifier that disagrees with the
        # writer rejects leases the server itself created.
        if not isinstance(claimed_by.get('tabId'), int) or isinstance(claimed_by.get('tabId'), bool):
            return self.LEASE_INVALID, 'claimedBy.tabId is not an integer'
        if not isinstance(claimed_by.get('url'), str):
            return self.LEASE_INVALID, 'claimedBy.url is not a string'
        if not self._aware_ts(claimed_by.get('at')):
            return self.LEASE_INVALID, 'claimedBy.at is not a timezone-aware timestamp'
        claimed_token = claimed_by.get('leaseToken')
        if not isinstance(claimed_token, str) or claimed_token.strip() != str(token).strip():
            return self.LEASE_INVALID, 'claimedBy.leaseToken disagrees with claimLeaseToken'
        has_token = True
        has_expiry = True
        expires = iso_dt(expires_raw)
        if expires is None:
            return self.LEASE_INVALID, f'unreadable claimExpiresAt {expires_raw!r}'
        if expires.tzinfo is None or expires.utcoffset() is None:
            return self.LEASE_INVALID, f'claimExpiresAt has no timezone: {expires_raw!r}'
        if expires > utc_now_dt():
            return self.LEASE_ACTIVE, ''
        return self.LEASE_EXPIRED, ''

    def _drain_reconcile(self) -> None:
        """Latch anything a drain cannot account for, across every process.

        Deliberately ignores dispatchEpoch. `recover_expired_leases` skips jobs
        of a previous epoch, so a console restarted mid-drain stopped seeing the
        lease it was waiting on: while alive it blocked the barrier, and the
        moment it expired it vanished from the check entirely and the barrier
        opened. Work outstanding from the old process is still outstanding.
        """
        if str(self.rollout_state().get('mode') or '') != ROLLOUT_DRAIN:
            return
        for job, error in self._iter_jobs_strict():
            if error is not None:
                self.mark_unsafe(f'unreadable delivery job during drain: {error}')
                continue
            if str(job.get('status') or '') in TERMINAL_JOB_STATES:
                continue
            kind, detail = self.classify_lease(job)
            if kind == self.LEASE_EXPIRED:
                self.mark_unsafe(
                    f"lease expired during drain: run={job.get('runId')} "
                    f"job={job.get('jobId')} status={job.get('status')}")
            elif kind == self.LEASE_INVALID:
                self.mark_unsafe(
                    f"invalid lease state during drain: run={job.get('runId')} "
                    f"job={job.get('jobId')}: {detail}")

    def drain_status(self) -> dict[str, Any]:
        """What still stands between this drain and the barrier."""
        state = self.rollout_state()
        outstanding: list[dict[str, Any]] = []
        for job, error in self._iter_jobs_strict():
            if error is not None:
                # A delivery job that cannot be read is an unknown outcome, not
                # an absent one. Tolerant loading turned it into {} and it
                # disappeared from the check entirely.
                outstanding.append({'runId': None, 'jobId': None,
                                    'reason': f'unreadable job: {error}'})
                continue
            status = str(job.get('status') or '')
            if status in TERMINAL_JOB_STATES:
                kind, detail = self.classify_lease(job)
                if kind != self.LEASE_NONE:
                    # A finished job still holding a lease is a contradiction,
                    # not silence: either the lease was never ended or the job
                    # was terminated under someone who still held it.
                    outstanding.append({**{'runId': job.get('runId'), 'jobId': job.get('jobId')},
                                        'reason': f'terminal job still holding a {kind} lease'})
                continue
            ref = {'runId': job.get('runId'), 'jobId': job.get('jobId')}
            # Browser quiet is not only about leases: an attachment still being
            # fetched or uploaded is a browser operation in flight, and closing
            # the boundary over it would cut the operation the design says must
            # finish first.
            for attachment in job.get('attachments') or []:
                state_name = str(attachment.get('state') or '')
                if state_name in ACTIVE_ATTACHMENT_STATES:
                    outstanding.append({**ref, 'reason': f'attachment {state_name}',
                                        'attachmentId': attachment.get('attachmentId')})
            kind, detail = self.classify_lease(job)
            if kind == self.LEASE_ACTIVE:
                outstanding.append({**ref, 'reason': 'claimed'})
            elif kind == self.LEASE_EXPIRED:
                outstanding.append({**ref, 'reason': 'lease expired, outcome unknown'})
            elif kind == self.LEASE_INVALID:
                outstanding.append({**ref, 'reason': f'invalid lease state: {detail}'})
            elif status == 'DISPATCHING':
                outstanding.append({**ref, 'reason': 'dispatching'})
        return {'mode': state.get('mode'), 'drainId': state.get('drainId'),
                'unsafe': bool(state.get('unsafe')),
                'unsafeReasons': list(state.get('unsafeReasons') or []),
                'outstanding': outstanding,
                'barrierAllowed': (state.get('mode') == ROLLOUT_DRAIN
                                   and not state.get('unsafe') and not outstanding)}

    def enter_barrier(self) -> dict[str, Any]:
        """Close the boundary, or refuse and say what is in the way.

        Recovery runs here rather than being expected beforehand. A lease that
        expired during the drain stops counting as active the moment it expires,
        so a barrier evaluated without recovery sees a quiet queue and closes
        over an outcome nobody recorded. Safety must not depend on the caller
        remembering the right order.
        """
        self.recover_expired_leases()
        # Across every process, not only this one's epoch.
        self._drain_reconcile()
        status = self.drain_status()
        if not status['barrierAllowed']:
            raise DeliveryError(
                'BARRIER_REFUSED: ' + json.dumps({'unsafe': status['unsafe'],
                                                  'unsafeReasons': status['unsafeReasons'],
                                                  'outstanding': status['outstanding']},
                                                 ensure_ascii=False))
        state = self.rollout_state()
        state['mode'] = ROLLOUT_BARRIER
        state['enteredAt'] = utc_now()
        self._write_rollout(state)
        return state

    def _iter_jobs(self):
        for job, error in self._iter_jobs_strict():
            if error is None:
                yield job

    def _iter_jobs_strict(self):
        """Every persisted delivery job, reporting the ones that cannot be read."""
        if not self.data_dir.is_dir():
            return
        for run_dir in sorted(self.data_dir.iterdir()):
            delivery_root = run_dir / 'executor' / 'delivery'
            if not delivery_root.is_dir():
                continue
            for job_dir in sorted(delivery_root.iterdir()):
                job_file = job_dir / 'job.json'
                if not job_file.is_file():
                    continue
                try:
                    job = json.loads(job_file.read_text('utf-8'))
                except Exception as exc:
                    yield None, f'{job_file}: {exc}'
                    continue
                if not isinstance(job, dict) or not job.get('jobId'):
                    yield None, f'{job_file}: not a delivery job'
                    continue
                # Only what browser quiet depends on, not the whole schema.
                attachments = job.get('attachments', [])
                if not isinstance(attachments, list):
                    yield None, f'{job_file}: attachments is not a list'
                    continue
                if any(not isinstance(a, dict) for a in attachments):
                    yield None, f'{job_file}: attachments contains a non-object'
                    continue
                if str(job.get('status') or '') in TERMINAL_JOB_STATES and any(
                        str(a.get('state') or '') in ACTIVE_ATTACHMENT_STATES for a in attachments):
                    # A finished job cannot still be uploading. Reading this as
                    # quiet would take a contradiction for proof of silence.
                    yield None, (f'{job_file}: terminal job with an attachment still in flight')
                    continue
                yield job, None
```

#### Обход заданий со строгой проверкой

```python
    def _iter_jobs(self):
        for job, error in self._iter_jobs_strict():
            if error is None:
                yield job

    def _iter_jobs_strict(self):
        """Every persisted delivery job, reporting the ones that cannot be read."""
        if not self.data_dir.is_dir():
            return
        for run_dir in sorted(self.data_dir.iterdir()):
            delivery_root = run_dir / 'executor' / 'delivery'
            if not delivery_root.is_dir():
                continue
            for job_dir in sorted(delivery_root.iterdir()):
                job_file = job_dir / 'job.json'
                if not job_file.is_file():
                    continue
                try:
                    job = json.loads(job_file.read_text('utf-8'))
                except Exception as exc:
                    yield None, f'{job_file}: {exc}'
                    continue
                if not isinstance(job, dict) or not job.get('jobId'):
                    yield None, f'{job_file}: not a delivery job'
                    continue
                # Only what browser quiet depends on, not the whole schema.
                attachments = job.get('attachments', [])
                if not isinstance(attachments, list):
                    yield None, f'{job_file}: attachments is not a list'
                    continue
                if any(not isinstance(a, dict) for a in attachments):
                    yield None, f'{job_file}: attachments contains a non-object'
                    continue
                if str(job.get('status') or '') in TERMINAL_JOB_STATES and any(
                        str(a.get('state') or '') in ACTIVE_ATTACHMENT_STATES for a in attachments):
                    # A finished job cannot still be uploading. Reading this as
                    # quiet would take a contradiction for proof of silence.
                    yield None, (f'{job_file}: terminal job with an attachment still in flight')
                    continue
                yield job, None
```

#### Классификация следа аренды

```python
    # ---- lease evidence during a drain ------------------------------------

    LEASE_NONE = 'NO_LEASE'
    LEASE_ACTIVE = 'ACTIVE'
    LEASE_EXPIRED = 'EXPIRED'
    LEASE_INVALID = 'INVALID'

    def classify_lease(self, job: dict[str, Any]) -> tuple[str, str]:
        """Classify the lease trace on disk, not merely whether it is live now.

        `_lease_is_active` answers False for a missing lease and for a
        contradictory one alike, and the drain read that as "nothing here".
        A half-written lease is an unknown outcome, not an absent one, so the
        two must be told apart before the boundary closes over them.
        """
        token = job.get('claimLeaseToken')
        expires_raw = job.get('claimExpiresAt')
        # CLAIM writes these four together and _clear_lease removes them
        # together, so any subset is a half-written trace, not an absent lease.
        # clientHeartbeatAt is deliberately excluded: it outlives _clear_lease.
        claimed_by = job.get('claimedBy')
        present = {
            'claimLeaseToken': isinstance(token, str) and token.strip() != '',
            'claimExpiresAt': isinstance(expires_raw, str) and expires_raw.strip() != '',
            'claimHeartbeatAt': isinstance(job.get('claimHeartbeatAt'), str)
                                and str(job.get('claimHeartbeatAt')).strip() != '',
            'claimedBy': isinstance(claimed_by, dict) and bool(claimed_by),
        }
        if not any(present.values()):
            return self.LEASE_NONE, ''
        missing = [name for name, ok in present.items() if not ok]
        if missing:
            return self.LEASE_INVALID, 'incomplete lease trace, missing ' + ', '.join(missing)
        if not self._aware_ts(job.get('claimHeartbeatAt')):
            return self.LEASE_INVALID, 'claimHeartbeatAt is not a timezone-aware timestamp'
        # claimedBy is the provenance CLAIM records: which tab took the lease,
        # where, when, and under which token. Validated against that shape
        # rather than a simpler one — a classifier that disagrees with the
        # writer rejects leases the server itself created.
        if not isinstance(claimed_by.get('tabId'), int) or isinstance(claimed_by.get('tabId'), bool):
            return self.LEASE_INVALID, 'claimedBy.tabId is not an integer'
        if not isinstance(claimed_by.get('url'), str):
            return self.LEASE_INVALID, 'claimedBy.url is not a string'
        if not self._aware_ts(claimed_by.get('at')):
            return self.LEASE_INVALID, 'claimedBy.at is not a timezone-aware timestamp'
        claimed_token = claimed_by.get('leaseToken')
        if not isinstance(claimed_token, str) or claimed_token.strip() != str(token).strip():
            return self.LEASE_INVALID, 'claimedBy.leaseToken disagrees with claimLeaseToken'
        has_token = True
        has_expiry = True
        expires = iso_dt(expires_raw)
        if expires is None:
            return self.LEASE_INVALID, f'unreadable claimExpiresAt {expires_raw!r}'
        if expires.tzinfo is None or expires.utcoffset() is None:
            return self.LEASE_INVALID, f'claimExpiresAt has no timezone: {expires_raw!r}'
        if expires > utc_now_dt():
            return self.LEASE_ACTIVE, ''
        return self.LEASE_EXPIRED, ''

    def _drain_reconcile(self) -> None:
        """Latch anything a drain cannot account for, across every process.

        Deliberately ignores dispatchEpoch. `recover_expired_leases` skips jobs
        of a previous epoch, so a console restarted mid-drain stopped seeing the
        lease it was waiting on: while alive it blocked the barrier, and the
        moment it expired it vanished from the check entirely and the barrier
        opened. Work outstanding from the old process is still outstanding.
        """
        if str(self.rollout_state().get('mode') or '') != ROLLOUT_DRAIN:
            return
        for job, error in self._iter_jobs_strict():
            if error is not None:
                self.mark_unsafe(f'unreadable delivery job during drain: {error}')
                continue
            if str(job.get('status') or '') in TERMINAL_JOB_STATES:
                continue
            kind, detail = self.classify_lease(job)
            if kind == self.LEASE_EXPIRED:
                self.mark_unsafe(
                    f"lease expired during drain: run={job.get('runId')} "
                    f"job={job.get('jobId')} status={job.get('status')}")
            elif kind == self.LEASE_INVALID:
                self.mark_unsafe(
                    f"invalid lease state during drain: run={job.get('runId')} "
                    f"job={job.get('jobId')}: {detail}")
```

#### Состояние слива

```python
    def drain_status(self) -> dict[str, Any]:
        """What still stands between this drain and the barrier."""
        state = self.rollout_state()
        outstanding: list[dict[str, Any]] = []
        for job, error in self._iter_jobs_strict():
            if error is not None:
                # A delivery job that cannot be read is an unknown outcome, not
                # an absent one. Tolerant loading turned it into {} and it
                # disappeared from the check entirely.
                outstanding.append({'runId': None, 'jobId': None,
                                    'reason': f'unreadable job: {error}'})
                continue
            status = str(job.get('status') or '')
            if status in TERMINAL_JOB_STATES:
                kind, detail = self.classify_lease(job)
                if kind != self.LEASE_NONE:
                    # A finished job still holding a lease is a contradiction,
                    # not silence: either the lease was never ended or the job
                    # was terminated under someone who still held it.
                    outstanding.append({**{'runId': job.get('runId'), 'jobId': job.get('jobId')},
                                        'reason': f'terminal job still holding a {kind} lease'})
                continue
            ref = {'runId': job.get('runId'), 'jobId': job.get('jobId')}
            # Browser quiet is not only about leases: an attachment still being
            # fetched or uploaded is a browser operation in flight, and closing
            # the boundary over it would cut the operation the design says must
            # finish first.
            for attachment in job.get('attachments') or []:
                state_name = str(attachment.get('state') or '')
                if state_name in ACTIVE_ATTACHMENT_STATES:
                    outstanding.append({**ref, 'reason': f'attachment {state_name}',
                                        'attachmentId': attachment.get('attachmentId')})
            kind, detail = self.classify_lease(job)
            if kind == self.LEASE_ACTIVE:
                outstanding.append({**ref, 'reason': 'claimed'})
            elif kind == self.LEASE_EXPIRED:
                outstanding.append({**ref, 'reason': 'lease expired, outcome unknown'})
            elif kind == self.LEASE_INVALID:
                outstanding.append({**ref, 'reason': f'invalid lease state: {detail}'})
            elif status == 'DISPATCHING':
                outstanding.append({**ref, 'reason': 'dispatching'})
        return {'mode': state.get('mode'), 'drainId': state.get('drainId'),
                'unsafe': bool(state.get('unsafe')),
                'unsafeReasons': list(state.get('unsafeReasons') or []),
                'outstanding': outstanding,
                'barrierAllowed': (state.get('mode') == ROLLOUT_DRAIN
                                   and not state.get('unsafe') and not outstanding)}

    def enter_barrier(self) -> dict[str, Any]:
        """Close the boundary, or refuse and say what is in the way.

        Recovery runs here rather than being expected beforehand. A lease that
        expired during the drain stops counting as active the moment it expires,
        so a barrier evaluated without recovery sees a quiet queue and closes
        over an outcome nobody recorded. Safety must not depend on the caller
        remembering the right order.
        """
        self.recover_expired_leases()
        # Across every process, not only this one's epoch.
        self._drain_reconcile()
        status = self.drain_status()
        if not status['barrierAllowed']:
            raise DeliveryError(
                'BARRIER_REFUSED: ' + json.dumps({'unsafe': status['unsafe'],
                                                  'unsafeReasons': status['unsafeReasons'],
                                                  'outstanding': status['outstanding']},
                                                 ensure_ascii=False))
        state = self.rollout_state()
        state['mode'] = ROLLOUT_BARRIER
        state['enteredAt'] = utc_now()
        self._write_rollout(state)
        return state
```

#### Проверка живости аренды и допуск события

```python
    def _lease_is_active(self, job: dict[str, Any]) -> bool:
        """One source of truth for lease liveness.

        Comparing the timestamp here as well left a second place that could meet
        a naive value and raise a bare TypeError, and a second definition of
        "active" that could drift from the classifier.
        """
        return self.classify_lease(job)[0] == self.LEASE_ACTIVE

    def _touch_lease(self, job: dict[str, Any], lease_token: str) -> None:
        """Every non-CLAIM event needs a live lease that this client holds.

        The old comparison matched an empty stored token against an empty
        requested one and, finding no expiry to object to, wrote a fresh one:
        a lease conjured out of nothing. During a drain that let unclaimed work
        keep moving, and RELEASE could erase a contradictory trace the latch was
        holding, opening the barrier over it.
        """
        kind, detail = self.classify_lease(job)
        if kind == self.LEASE_NONE:
            raise DeliveryError('DELIVERY_NOT_LEASED: job has no delivery lease')
        if kind == self.LEASE_EXPIRED:
            self._latch_if_draining_reason(
                job, f"event on an expired lease: run={job.get('runId')} job={job.get('jobId')}")
            raise DeliveryError('delivery lease expired')
        if kind == self.LEASE_INVALID:
            self._latch_if_draining_reason(
                job, f"event on an invalid lease state: run={job.get('runId')} "
                     f"job={job.get('jobId')}: {detail}")
            raise DeliveryError(f'DELIVERY_LEASE_INVALID: {detail}')
        requested = str(lease_token or '').strip()
        if not requested or str(job.get('claimLeaseToken') or '').strip() != requested:
            raise DeliveryError('delivery lease token mismatch')
        now = utc_now()
        job['claimHeartbeatAt'] = now
        job['clientHeartbeatAt'] = now
        job['claimExpiresAt'] = utc_after(CLAIM_LEASE_SECONDS)
```

#### Ветка `CLAIM` и завершение аренды успешной отправкой

```python
            event_type = str(body.get('event') or '')
            if event_type == 'CLAIM':
                # A new claim is new work. Refusing it only in poll_for_tab left
                # the event route as a way to take one anyway, which is how a
                # drain could still be handed fresh outstanding deliveries after
                # it started. Checked before any job-specific validation, so an
                # unrelated complaint cannot answer in its place.
                mode = str(self.rollout_state().get('mode') or ROLLOUT_OPEN)
                if mode != ROLLOUT_OPEN:
                    raise DeliveryError(f'DELIVERY_CLAIM_REFUSED: rollout mode is {mode}')
            now = utc_now()

            if event_type == 'CLAIM':
                requested_token = str(body.get('leaseToken') or '').strip()
                if not requested_token:
                    raise DeliveryError('missing delivery lease token')

                current_token = str(job.get('claimLeaseToken') or '')
                kind, detail = self.classify_lease(job)
                if kind == self.LEASE_ACTIVE and current_token != requested_token:
                    raise DeliveryError('delivery job is already leased')
                if kind == self.LEASE_INVALID:
                    # A fresh claim must not paper over a trace nobody could
                    # explain: overwriting it would destroy the only record that
                    # an outcome was lost.
                    raise DeliveryError(f'DELIVERY_LEASE_INVALID: {detail}')
                if kind == self.LEASE_EXPIRED:
                    # Recovery must run first. poll_for_tab does it before
                    # offering work, but a direct event call would otherwise
                    # overwrite the expired trace and the lease term would stop
                    # being a server-side boundary.
                    self._latch_if_draining_reason(
                        job, f"claim over an expired lease: run={job.get('runId')} "
                             f"job={job.get('jobId')}")
                    raise DeliveryError(
                        'DELIVERY_LEASE_EXPIRED: recover the expired lease before claiming')

                job['claimLeaseToken'] = requested_token
                job['claimHeartbeatAt'] = now
                job['claimExpiresAt'] = utc_after(CLAIM_LEASE_SECONDS)
                job['claimedBy'] = {
                    'tabId': int(body.get('tabId')),
                    'url': str(body.get('url') or ''),
                    'at': now,
                    'leaseToken': requested_token,
                }
                return self.save_job(job)
```

```python
            elif event_type == 'SEND_STATE':
                job['sendState'] = str(body.get('state') or 'SEND_ERROR')
                job['sendError'] = body.get('error')
                if job['sendState'] == 'SENT':
                    job['sentAt'] = now
                    # The outcome is known, so the lease ends here, in the same
                    # save. The browser sends RELEASE afterwards, but by then
                    # the job is terminal and the early return ignores it — so
                    # a perfectly ordinary successful send used to leave an
                    # ACTIVE lease behind for ever, and the drain read that
                    # terminal job as quiet.
                    self._clear_lease(job)
```

#### Чтение вложения с доказательством аренды

```python
    def attachment_chunk(self, run_id: str, job_id: str, attachment_id: str, offset: int, limit: int,
                         *, tab_id: int | None = None, lease_token: str = '') -> dict[str, Any]:
        job = self.get_job(run_id, job_id)
        if tab_id is not None:
            target = job.get('target') if isinstance(job.get('target'), dict) else {}
            if int(target.get('tabId') or -2) != int(tab_id):
                raise DeliveryError('wrong tabId for delivery job')
            # A live lease held by this caller. Reading bytes is work, and work
            # requires a claim — otherwise a drain that hands out no new jobs
            # still hands out new pieces of them.
            self._touch_lease(job, lease_token)
        attachment = next((x for x in job.get('attachments') or [] if x.get('attachmentId') == attachment_id), None)
        if attachment is None:
            raise DeliveryError('attachment not found')
        path = Path(str(attachment.get('path') or '')).resolve()
        job_files = (self.job_dir(run_id, job_id) / 'files').resolve()
        if job_files not in path.parents or not path.is_file():
            raise DeliveryError('attachment file not found')
        total = path.stat().st_size
        offset = max(0, int(offset))
        limit = min(max(64 * 1024, int(limit or 512 * 1024)), 1024 * 1024)
        if offset > total:
            raise DeliveryError('offset beyond file size')
        with path.open('rb') as fh:
            fh.seek(offset)
            chunk = fh.read(limit)
        return {
            'ok': True,
            'attachmentId': attachment_id,
            'name': attachment.get('name'),
            'mimeType': attachment.get('mimeType') or 'application/octet-stream',
            'offset': offset,
            'bytes': len(chunk),
            'totalBytes': total,
            'eof': offset + len(chunk) >= total,
            'dataBase64': base64.b64encode(chunk).decode('ascii'),
        }
```

### 6.4. `RUN_TESTS.sh` — целиком

```bash
#!/usr/bin/env bash
# Copyright (c) 2026 Kolobov Aleksei (@kilax9276)
# All rights reserved. See LICENSE at the repository root.
#
# Both suites must target the same console release in one process: each test
# file puts its release directory on sys.path and imports profile_store, and
# Python caches the module, so mixing releases in a single run silently tests
# whichever imported first. Slice 1 acceptance is deliberately re-run against
# the slice-2 release — that is the regression check.
set -euo pipefail
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
export PAP_CONSOLE_RELEASE="${PAP_CONSOLE_RELEASE:-4.5.0-s2}"
export PAP_RECEIVER_RELEASE="${PAP_RECEIVER_RELEASE:-2.11.0-s1}"
rm -rf console_releases/*/__pycache__ tests/__pycache__
echo "RET_VALUE::CONSOLE_RELEASE=${PAP_CONSOLE_RELEASE}"
echo "RET_VALUE::RECEIVER_RELEASE=${PAP_RECEIVER_RELEASE}"
python3 -m pytest tests/ -v -p no:cacheprovider
echo "RET_VALUE::TESTS_RC=$?"
```

### 6.5. `.gitignore` приложенного репозитория — целиком

```text
__pycache__/
*.py[cod]
.pytest_cache/
data/
runtime/
config/
logs/
```

### 6.6. Состав тестов

На момент тринадцатого раунда — четыре файла, 107 тестов; сейчас пятнадцать файлов, 235 тестов. Полные тексты — в приложенном архиве.
Ниже перечень по классам и именам, чтобы новый чат понимал покрытие без
чтения файлов.

**`tests/test_slice1.py`**

- `ReceiverHarness:`
- `Slice1Acceptance`
  - `test_receiver_stages_until_full_hash_and_deduplicates`
  - `test_binding_identity_changes_fingerprint_and_malformed_is_not_guessed`
  - `test_snapshot_atomic_secret_free_and_session_restart_generation`
  - `test_run_snapshot_is_immutable_and_live_profile_binding_gate_remains_live`
  - `test_binding_gate_is_live_and_tab_state_is_not_a_server_precondition`
  - `test_pinned_project_identity_change_revokes_execution`
  - `test_session_snapshot_survives_session_directory_deletion`
  - `test_server_side_profile_filter_and_repeat_as_new`
  - `test_context_creation_is_explicit_idempotent_and_get_never_writes`
  - `test_execution_readiness_does_not_depend_on_listing_or_ui`
  - `test_missing_context_is_fail_closed_and_never_masked_as_identity_failure`
  - `test_log_truncation_utf8_safe_and_full_source_unchanged`
  - `test_execute_business_gate_rejects_before_executor`
  - `test_execute_step_in_promotion_window_changes_no_step_state`
  - `test_presentation_log_shape_and_full_log_download_stays_complete`
  - `test_multi_file_hash_vector_is_ordered_and_duplicate_never_enters_repeat_path`
  - `test_ui_persists_profile_filter_selection`
  - `test_files_ui_is_explicit_not_ready_scaffold_and_filter_is_server_query`

**`tests/test_slice2_step1.py`**

- `ReceiverHarness:`
- `Slice2Step1TimeoutRename`
  - `test_five_states_decided_by_membership`
  - `test_explicit_falsy_is_rejected_not_defaulted`
  - `test_range_bounds_named_canonically`
  - `test_snapshot_freezes_only_the_canonical_name`
  - `test_authorization_and_console_use_the_canonical_name`
  - `test_ui_has_no_legacy_key_on_any_path`
- `Slice2Step1PersistedMigration`
  - `test_persisted_slice1_profile_migrates_and_then_loads`
  - `test_migration_is_idempotent`
  - `test_corrupt_profile_is_reported_not_rewritten`
  - `test_authorization_emits_only_the_canonical_name`
  - `test_set_with_one_bad_profile_writes_nothing`
  - `test_damaged_canonical_profile_is_failed_not_skipped`
  - `test_persisted_profile_without_either_key_gets_the_default`
  - `test_preflight_only_mode_writes_nothing`

**`tests/test_slice2_endpoint.py`**

- `Req:`
- `EndpointModel`
  - `test_page_reload_keeps_endpoint_id_within_the_epoch`
  - `test_late_pulse_after_closed_does_not_revive`
  - `test_late_pulse_of_previous_epoch_after_expired_does_not_revive`
  - `test_lease_gap_without_owner_change_keeps_endpoint_id`
  - `test_identity_comes_from_stated_fields_not_the_url`
  - `test_identity_is_required`
  - `test_second_live_epoch_is_refused_without_any_write`
  - `test_takeover_expires_previous_endpoints_in_one_write`
  - `test_expired_lease_means_not_owner`
  - `test_list_returns_observed_state_without_policy`
  - `test_offline_endpoints_are_not_hidden_by_the_server`
- `PollBarriers`
  - `test_compatible_owner_records_the_endpoint`
  - `test_wrong_version_is_refused_before_observe`
  - `test_foreign_live_epoch_gets_conflict_before_observe`
  - `test_expired_lease_gets_not_owner_before_observe`
  - `test_second_live_control_agent_gets_conflict_and_no_plan`
  - `test_takeover_after_expired_lease_expires_previous_endpoints`
  - `test_missing_epoch_or_endpoint_is_refused_before_observe`
  - `test_registry_refusal_is_answered_not_swallowed`
  - `test_real_legacy_client_is_recorded_and_cleared_after_upgrade`
  - `test_version_mismatch_is_recorded_once_and_cleared_on_handshake`
- `RegistrySchemaBoundary`
  - `test_legacy_registry_is_refused_until_invalidated`
  - `test_invalidation_discards_endpoints_and_pins_and_keeps_evidence`
  - `test_no_identity_is_synthesised_for_legacy_rows`
  - `test_corrupt_registry_is_refused_not_reset`
  - `test_registry_without_schema_version_is_refused`
  - `test_invalidation_refuses_an_unknown_registry`
  - `test_no_way_left_to_create_a_pin`
  - `test_damaged_schema2_registry_is_refused_not_coerced`
  - `test_timestamps_must_carry_an_offset_and_schema_version_is_not_coerced`
  - `test_a_foreign_integer_schema_is_migration_not_invalid`
  - `test_legacy_backup_keeps_the_original_bytes`
  - `test_invalidation_is_idempotent_on_a_current_registry`
- `PinApiRemoved`
  - `test_console_has_no_pin_route_or_handler`
  - `test_ui_offers_no_pin_action`
- `EventRouteBarriers`
  - `test_compatible_owner_reaches_delivery`
  - `test_incompatible_version_cannot_move_delivery_state`
  - `test_foreign_epoch_cannot_move_delivery_state`
  - `test_terminal_endpoint_cannot_move_delivery_state`
  - `test_unknown_endpoint_is_refused`
  - `test_missing_epoch_or_endpoint_is_refused`
  - `test_every_browser_route_goes_through_the_barrier`
- `ChunkRouteBarriers`
  - `test_compatible_owner_can_read_with_its_own_tab_and_lease`
  - `test_barriers_refuse_and_return_no_bytes`
  - `test_terminal_endpoint_cannot_read`
- `InvalidRolloutStateBlocksDeliveryPlane`
  - `test_unreadable_rollout_state_refuses_delivery_events`

**`tests/test_slice2_rollout.py`**

- `DrainBarrier`
  - `test_clean_drain_allows_barrier`
  - `test_active_claim_blocks_barrier`
  - `test_lease_expiring_during_drain_latches_unsafe_and_blocks_barrier`
  - `test_latch_is_monotonic_within_a_pass`
  - `test_only_a_new_drain_pass_clears_the_latch`
  - `test_drain_hands_out_no_new_work`
  - `test_claim_is_refused_outside_open`
  - `test_incomplete_rollout_state_is_unsafe`
  - `test_unreadable_job_blocks_the_barrier`
  - `test_outstanding_reports_the_real_job_id`
  - `test_restart_between_drain_start_and_expiry_still_latches`
  - `test_contradictory_lease_traces_are_unknown_not_absent`
  - `test_lease_classification_tells_the_four_cases_apart`
  - `test_non_claim_events_cannot_conjure_a_lease`
  - `test_release_cannot_erase_invalid_lease_evidence`
  - `test_claim_does_not_overwrite_invalid_evidence`
  - `test_naive_lease_timestamp_gives_a_lease_verdict_not_a_crash`
  - `test_rollout_state_values_are_validated`
  - `test_attachments_in_flight_block_the_barrier`
  - `test_claim_over_an_expired_lease_is_refused`
  - `test_real_claim_lifecycle_is_active_then_released`
  - `test_stored_open_is_not_a_canonical_state`
  - `test_contradictory_attachment_state_is_not_quiet`
  - `test_malformed_attachments_do_not_crash_the_drain`
  - `test_expiry_corruption_on_a_real_lease_is_invalid`
  - `test_successful_send_ends_the_lease`
  - `test_terminal_job_holding_a_lease_blocks_the_barrier`
  - `test_barrier_downgraded_to_drain_is_not_a_valid_drain`
  - `test_unreadable_rollout_state_is_treated_as_unsafe`


**`tests/test_slice2_review24.py`**

- `SameSourceCannotAcquireAnotherTarget`
  - `test_same_source_with_another_tab_is_corrupt_not_absent`
  - `test_same_source_with_another_page_is_corrupt_not_a_match`
  - `test_the_repeat_finds_the_replay_after_the_page_is_repaired`
- `ExistingFailClosedCasesStayClosed`
  - `test_a_missing_url_is_still_unprovable`
  - `test_the_canonical_pending_repeat_is_idempotent`
  - `test_a_replay_for_another_source_is_still_a_legal_skip`

**`tests/test_slice2_review25.py`**

- `ReplayMarkerIsPartOfTheProof`: отсутствующий marker, `1`, `"true"`, `False`, восстановимость после ремонта.
- `RecoveryOfIdentityIsStrict`: непригодные типы `runId/jobId` не превращаются в «другой source».
- `DispatchEpochMustMatchTheLifecycle`: чужая/пустая/нестроковая активная эпоха — отказ; канонический restart-pause остаётся существующим replay; после ремонта эпохи идемпотентность восстанавливается.
- `StatusCannotBeCoercedIntoAValidLifecycle`: `42` и неизвестный строковый статус — недоказуемость.
- `TheTwoProvenNonMatchesStayLegal`: обычный writer-job без обоих recovery-полей и replay другого source остаются законными non-match; канонический повтор идемпотентен.
- Каждый отрицательный сценарий сверяет число job-каталогов, прежний status и весь побайтный снимок delivery-tree до/после отказа.


### 6.7. Состав приложенного дерева

Дерево полное: его достаточно, чтобы прогнать тесты, проверить карту, поднять
платформу локально, выкатить и откатить срез 1 и прогнать живой smoke.

```
PAP2_S2_HANDOFF.md              этот документ
README_HANDOFF.md               раскладка дерева
ENVIRONMENT.md                  зависимости, запуск, выкат, smoke
requirements-dev.txt            точные версии, на которых идут тесты
requirements-console.txt        продуктовая зависимость (aiohttp)
RUN_TESTS.sh                    прогон обоих наборов против одного релиза

server.py                       receiver 2.10.0, замороженный корневой
platform_manager.py             менеджер платформы, с версионированием receiver
start_platform.sh               запуск и проверка готовности
activate_console_release.py     активатор консоли
activate_receiver_release.py    активатор receiver
activate_extension_release.py   активатор расширения (объявляет и раскладывает)
rollout_slice1.sh               атомарный выкат и откат среза 1
smoke_slice1.sh                 живой поведенческий smoke
install_platform_requirements.sh
VERSION-platform                4.3.5
console-current.json.example

console_releases/4.4.0/         замороженная историческая точка 830ab8c6
console_releases/4.5.0-s1/      закрытый срез 1, рабочее основание карты
console_releases/4.5.0-s2/      кандидат среза 2 — здесь идёт работа
receivers/2.10.0/               receiver до среза 1
receivers/2.11.0-s1/            receiver закрытого среза 1
extension_releases/2.11.6/      замороженный байтовый baseline расширения
extension_releases/2.11.7/      релиз с копирайтом, база для среза 2
packaging/                      установщик релиза и манифесты

tests/                          270 тестов, включая S4 delivery regressions
diff/                           три патча относительно коммита 8fc773c
docs/PAP2_4.5.0_DESIGN.md       дизайн, 2667 строк, журнал решений
PAP2_4.5.0_IMPLEMENTATION_MAP.md   карта точек врезки
tools/                          цепочка проверки карты, пути относительные

LICENSE, README.md, CHANGELOG.md, REPO_README.md
```

Проверено на распакованном архиве:

```
bash RUN_TESTS.sh              274 passed, 64 subtests passed
tools/verify_inventory.py      checks=177 failures=0
tools/verify_overlaps.py       checks=10  failures=0
tools/verify_map.py            checks=214 failures=0
```

Хэши поддеревьев в приложенном репозитории совпадают с объявленными в карте:

```
console_releases/4.5.0-s1     425bc1a8b77ab23b69997d98125f909f821b9a42
receivers/2.11.0-s1           f5ceaabab02513da2eafab9c593420918708fe63
extension_releases/2.11.6     65b0db4ed31d36f68bb3f6b832797d4e524edebc
```

То есть основание в архиве побайтно то же, что на сервере.

### 6.8. Что сокращено и почему

| Файл | Строк | Что сделано |
|---|---|---|
| `endpoint_registry.py` | 591 | **приведён целиком** |
| `console_server.py` | 1349 | приведены все изменённые срезом 2 части; остальное — неизменённый код 4.5.0-s1 |
| `delivery_manager.py` | 2443 | приведены все новые и изменённые части; остальное — неизменённый код 4.5.0-s1 |
| `profile_store.py` | 981 | не приводится: изменён только шагом 1, который **уже закоммичен** в `8fc773c`; ключевая часть — `migrate_persisted_profiles` и пятисостоянийная миграция |
| `static/app.js` | 1563 | не приводится: изменение среза 2 — удаление интерфейса закрепления и переход на `endpointWaitTimeoutSeconds` |
| `executor.py`, `protocol_engine.py`, `chat_bindings.py`, `profile_resolver.py`, `endpoint*` прочие | — | срезом 2 не изменялись |
| тесты, 13 файлов | 4713 | приведён полный перечень классов и методов; тексты в архиве |
| `PAP2_4.5.0_DESIGN.md` | 2645 | в архиве; ключевые решения из журнала перенесены в раздел 5 этого документа |
| `PAP2_4.5.0_IMPLEMENTATION_MAP.md` | — | в архиве; сводка в разделе 3 |
| три `.patch` относительно `8fc773c` | 1482 | в архиве, каталог `diff/` |
| `platform_manager.py`, `start_platform.sh`, активаторы, `rollout_slice1.sh`, `smoke_slice1.sh` | — | в архиве целиком; их поведение и порядок вызова описаны в `ENVIRONMENT.md` |

Всё сокращённое присутствует в приложенном архиве целиком.

**Единственное, чего нет ни здесь, ни в архиве:** каталог
`console_releases/4.3.5` — замороженный исторический релиз, существовавший
только на сервере. Он ничем не используется: активным релизом до среза 1 был
`4.4.0`, именно к нему привязаны HISTORICAL-строки карты, и он в архиве есть.
Также отсутствуют `data/`, `config/`, `runtime/`, `logs/` — состояние
конкретного развёртывания с содержимым чатов, профилями и секретами.

---

## 7. Нерешённые вопросы

### Открыто перед продолжением блока 2+5

Двадцать шестой независимый раунд был не чистым. Review 26 сделал lifecycle replay слишком строгим в одном product-written состоянии и слишком широким в другом. Во-первых, `pause_unfinished_jobs_after_restart` канонически пишет `PAUSED_AFTER_RESTART`, `dispatchEpoch=null`, `pausedFromDispatchEpoch=<old epoch>`, после чего обычный Prepare через `supersede_older_jobs_for_tab` может законно получить terminal `SUPERSEDED` с тем же null. Review 26 объявлял любой terminal-null противоречием и тем самым блокировал recovery даже для несвязанного source. Во-вторых, terminal `SUPERSEDED` replay с `messageState=PENDING`, `sendState=NOT_REQUESTED` возвращался как `FOUND`, хотя отправки не было и source навсегда терял возможность получить новый replay. Оба состояния воспроизведены на точных байтах review 26 (`delivery_manager.py=95651fd34cf00195cb47d5e4a81b89ea5c963fa308b86a434634a211327efa9b`) приложенным `test_slice2_review26_audit.py`: до правки `3 failed`, после review 27 `3 passed`. Review 27 принимает terminal-null только как доказуемое продолжение restart-pause writer-цепочки; bare null остаётся `UNPROVABLE`. Для `SUPERSEDED/CANCELLED` отдельно доказывается результат доставки: `SENT/MANUAL_SENT` сохраняют `FOUND`, `NOT_REQUESTED/SEND_ERROR` означают историческую недоставленную попытку и позволяют искать/создать следующий replay, а `SEND_REQUESTED` без подтверждённого исхода остаётся `UNPROVABLE`. Формулировки внесены в `MAP-087`, `ACC-S5-026` и журнал дизайна. Commit, выкат и шаг 3 не выполнялись. Ожидается независимая проверка пакета `PAP2_S2_BLOCK25_REVIEW27.tar.gz`.

Двадцать пятый независимый раунд был не чистым: writer создаёт recovery replay одной записью с `recoveryReplay: True`, `recoveryOf`, `target`, `status` и `dispatchEpoch`, но helper по-прежнему фильтровал эти доказательства по отдельности. Удалённый либо неканонический `recoveryReplay` и повреждённая `dispatchEpoch` превращали существующий replay в `ABSENT`, после чего писался второй job и прежний переходил в `SUPERSEDED`; `status=42` оставался последней снисходительной веткой. Review 26 закрывает writer-контракт целиком: обычный job доказан только одновременным отсутствием обоих recovery-полей; marker только ровно `True`; `recoveryOf.runId/jobId` только непустые строки; target пригодный; status канонический; активная нетерминальная эпоха текущая и непустая. Даже доказанно foreign-source replay разрешено пропустить только после проверки target/status/dispatchEpoch — ранний `recoveryOf != source` больше не скрывает повреждённую companion-часть writer-строки. Канонический `PAUSED_AFTER_RESTART` с `dispatchEpoch=null` остаётся существующим replay и не клонируется после рестарта; terminal replay тоже сохраняет факт существования. На точных байтах review 25 новый файл даёт `19 failed, 3 passed`, после исправления `22 passed`; каждый отказ дополнительно доказывает неизменность всего delivery-tree. Ожидается независимая проверка пакета `PAP2_S2_BLOCK25_REVIEW26.tar.gz`.

Двадцать четвёртый раунд был не чистым: `_existing_recovery_replay` после совпадения `recoveryOf` по-прежнему трактовал `TARGET_OTHER` как законный пропуск, хотя writer выводит цель повтора из самого источника. Повреждённый `tabId` позволял записать второй replay, а повреждённый `url` вообще не проверялся, потому что helper не принимал `page_url`, и чужая страница возвращалась как найденный повтор. Исправлено: helper принимает tab+page, общий `classify_target` проверяет обе координаты, а `TARGET_OTHER` после доказанного источника становится `REPLAY_UNPROVABLE`; отказ происходит до любой записи. На байтах review 24 новый файл даёт `3 failed, 3 passed`, после исправления `6 passed`. Пакет review 25 проверен независимо; следующий блокер закрывается review 26.

Двадцать третий раунд был не чистым: проверка идемпотентности повтора
восстановления оставалась двузначной, и повреждённый `recoveryOf` читался как
отсутствие повтора — на неполном доказательстве создавалась вторая доставка, а
прежняя переводилась в `SUPERSEDED`. Ответ сделан трёхзначным, отказ выдаётся до
любой записи; правка получила строку карты `MAP-087` и приёмку `ACC-S5-026`.
Числа в разделах «Что проверено» и «Передача» синхронизированы с текущей базой.
Находка воспроизведена на байтах пакета review 23. Пакет review 24 проверен; найденный дефект закрыт в review 25.

Двадцать второй раунд был не чистым: строгий классификатор цели использовался в
восстановлении, опросе и воротах аренды, но событие доставки и чтение вложения
по-прежнему решали принадлежность собственным `int()` — повреждённое значение
принималось за исправный номер вкладки (`int(True)` равен 1) либо уходило голым
исключением мимо отказа. Оба пути переведены на общий классификатор. Находки
воспроизведены на байтах пакета review 22. Ожидается проверка пакета
`PAP2_S2_BLOCK25_REVIEW23.tar.gz`.

Двадцать первый раунд был не чистым: внутри самого `classify_target`
отсутствующий `target.url` приравнивался к канонической пустой строке, то есть к
цели без страницы, и потому подходил к любой странице — доставка чужой страницы
объявлялась доказанным последним источником этой и могла быть выдана на неё же.
Устранено разделением отсутствия ключа и пустой строки; `outstanding_lease_for_tab`
переведён на тот же помощник. Находки воспроизведены на байтах пакета review 21.
Ожидается проверка пакета `PAP2_S2_BLOCK25_REVIEW22.tar.gz`.

Двадцатый раунд был не чистым: тот же класс — недоказуемость вместо отсутствия —
остался в доказательстве цели задания. Отсутствующая или повреждённая цель
читалась снисходительно, `{}` давало `tabId = -1`, и более новая доставка
объявлялась чужой, а непригодный `tabId` уходил голым `ValueError` мимо
трёхзначного ответа. Устранено общим помощником `classify_target`, которым
пользуются и обход, и явно названный источник, и решения плоскости доставки.
Находки воспроизведены на байтах пакета review 20. Ожидается проверка пакета
`PAP2_S2_BLOCK25_REVIEW21.tar.gz`.

Девятнадцатый раунд был не чистым: трёхзначный ответ появился, но три ветки
внутри поиска последнего отправленного задания по-прежнему превращали
недоказуемость в отсутствие кандидата — время отправки в будущем, нечитаемое
сохранённое задание и отправленное задание без единой метки времени. Устранено;
единственным законным пропуском остался доказанно вышедший за окно
восстановления. Находки воспроизведены на байтах пакета review 19. Ожидается
проверка пакета `PAP2_S2_BLOCK25_REVIEW20.tar.gz`.

Восемнадцатый раунд был не чистым: путь выбора источника восстановления терял
UNKNOWN — отказ и отсутствие отвечали одним `None`, и вызывающий брал названный
браузером более старый источник, — а равные метки отправки разрешались обходом
каталога. Устранено трёхзначным ответом и отказом при неоднозначности; правка
существующего символа получила строку карты `MAP-086` и приёмку `ACC-S2-037`.
Находки воспроизведены на байтах пакета review 18. Ожидается проверка пакета
`PAP2_S2_BLOCK25_REVIEW19.tar.gz`.

Семнадцатый раунд был не чистым: порядок Prepare выводился из строкового
сравнения `createdAt`, поэтому испорченная или неоднозначная метка делала
хранимым устаревшее задание и терминально вытесняла настоящее новое. Устранено
единым правилом для сохранённого времени, участвующего в порядке; находка
воспроизведена на байтах пакета review 17. Ожидается проверка пакета
`PAP2_S2_BLOCK25_REVIEW18.tar.gz`.

Шестнадцатый раунд был не чистым: подтверждён один блокирующий дефект
жизненного цикла — пропущенное вытеснение никогда не применялось позже, и старое
задание снова становилось кандидатом после успешной доставки нового. Устранено
отложенным вытеснением на месте решения о выдаче; находка воспроизведена на
байтах пакета review 16. Ожидается проверка пакета
`PAP2_S2_BLOCK25_REVIEW17.tar.gz`.

Пятнадцатый раунд был не чистым: найдены два продуктовых дефекта — гонка
`ACTIVE → EXPIRED` между восстановлением и решением опроса и обход авторизации
в `attachment_chunk` на уровне менеджера, — а также несоответствие фикстур
review 14 только что принятому инварианту и неэквивалентность `ACC-S2-036`
тексту карты и журнала. Все четыре устранены, находки воспроизведены на байтах
пакета review 15. Ожидается проверка пакета `PAP2_S2_BLOCK25_REVIEW16.tar.gz`;
если продуктовых дефектов в ней нет, серверная часть блока 2+5 считается
закрытой по коду.

`ACC-S2-036` остаётся `PLANNED` до расширения `2.12.0` — это не мешает считать
серверную реализацию контракта законченной, но мешает закрыть весь срез 2
раньше браузерной половины.

### Решено в четырнадцатом раунде

**Вытеснение захваченной работы — запрещено.** Задание с любым следом аренды в
`SUPERSEDED` не переводится. Доставка на вкладку односместна до известного
окончания текущей аренды: пока след не закрыт, новое задание вкладке не
выдаётся. Очищать аренду вместо этого нельзя — исход неизвестен. Это правило
безопасности среза 2 (`MAP-083`, `ACC-S2-033`). В срезе 4 вытеснение получает
более точную идентичность логической доставки (`MAP-036`), но отменить это
правило не вправе.

**Heartbeat во время забора вложения.** `chunk` доказывает `ACTIVE` аренду,
совпадение `leaseToken` и доверенный endpoint — оба доказательства обязательны
на уровне менеджера, — но аренду не продлевает. Продление персистится только
событиями доставки и `HEARTBEAT`. Расширение `2.12.0` шлёт `HEARTBEAT`
независимо от ожидания chunk с каденцией отправки не более 5 секунд: аренда
15 секунд, интервал — треть срока. Неуспешный `HEARTBEAT` продлением не
считается. Требование относится к каденции отправки, а не к разрыву между
сохранёнными на сервере продлениями: задержанный ответ не делает исправное
расширение нарушителем. Цикл прекращается только после терминального принятого
исхода, `RELEASE` или явного отказа сервера (`MAP-057`, `ACC-S2-036`).

**Односместность доставки на вкладку.** К выдаче допускается только `NO_LEASE`;
`ACTIVE`, `EXPIRED` и `INVALID` блокируют текущую итерацию опроса.
Восстановление, отложенное вытеснение и решение выполняются под одним замком,
потому что классификация берётся дважды и каждый раз читает часы заново.

**Отложенное вытеснение.** Вытеснение, пропущенное из-за живой аренды, не
отменяется, а применяется на первом же опросе, где вкладка доказанно свободна
от аренды. Иначе старое задание переживает новое и уходит в чат после него.

**Порядок Prepare.** Выводится только из разбираемого времени с часовым поясом.
Непригодная метка и две одинаковые метки означают, что новейшего доказать
нельзя: вкладка не выдаёт ничего и не вытесняет ничего до вмешательства
оператора. Обход каталога арбитром не является.

### Требует решения оператора

**Рассогласование при откате.** Если сервер откатился, а расширение нет —
браузер закрыт, вкладка неактивна, оператор ушёл. Симметричный откат по
кнопке этого не покрывает. Решение оператора получено для прямого
направления (пауза профиля), для обратного — нет.

### Отложено намеренно

| Что | Куда |
|---|---|
| `ACC-S2-008` PASS | после `MAP-049/050`, замена пути выбора |
| `ACC-MIG-003` PASS | шаг 8: нужны локальная тишина (`RUNNING` + живые `RunExecutor._processes`) и закрытый приём |
| `ACC-MIG-019` | срез 3a, панель доставки |
| `ACC-S2-032` | шаг 6, обратный забор в расширении |
| `ACC-LIVE-001/002/003` | живой прогон с браузером, обязателен до закрытия среза 2 |
| пауза профиля по расхождению версий | срез 5, общая модель паузы (`ACC-S5-024`) |
| сводка по профилям, удаление профиля | после среза 2 |
| `ACC-S2-036` | шаг 6/7, heartbeat-цикл в расширении 2.12.0 |

---

## 8. Следующий шаг

Порядок работ по срезу 2, с текущей позицией:

```
шаг 1   переименование timeout                    ЗАКРЫТ, коммит 8fc773c
шаг 2+5 модель endpoint, владение, барьеры,
        DRAIN/BARRIER                             ЗАКРЫТ ПО КОДУ, коммит d943c11
шаг 3   selectEndpoint, привязка сессии           ЗАКРЫТ, коммит b7d39e3
шаг 4   семантика доставки и слива                ← ЗДЕСЬ, независимый review
шаг 6   эпохи и управляющий агент в расширении
шаг 7   мост ENDPOINT и обратный забор
шаг 8   интеграция выката и миграции
```

**Немедленно:** независимо проверить текущий S4 Review 2 кандидат (`MAP-018`,
`MAP-034`, `MAP-035`, `MAP-036`) на точных байтах пакета. Review 1 получил
CHANGES REQUESTED не по продукту, а по доказательству: при адаптации старых
тестов к logical-delivery supersede были утрачены три fail-closed оси Review 27
и одна ось Review 26. В Review 2 они восстановлены через writer-produced
same-logical supersede; S4 production bytes не менялись. Причинный RED-before
для самого S4 по-прежнему выполняется тем же `test_slice4_delivery_semantics.py`
на MAP-028 Review 2.

**После CLEAN:** зафиксировать шаг 4 отдельным development-коммитом на ветке
`s2-block25` поверх `b7d39e350cf47f7b3ef6d6a34f63990f839257db`, без выката, затем
опубликовать только эту ветку. `main` и работающий стенд pro2 остаются на срезе 1.

**Затем:** перейти к следующей строке утверждённого порядка. `MAP-018`/`MAP-034`
входят в текущий шаг 4; не захватывать сюда `MAP-049`/`MAP-050`
(binding/resolver schema cleanup) и обязанности шагов 6–8.

---

## 9. Готовая инструкция для нового чата

Скопируйте текст ниже вместе с этим документом и архивом.

---

Ты продолжаешь разработку PAP2 4.5.0, срез 2, серверный блок 2+5. Весь
необходимый контекст в приложенном документе, исходный код в приложенном
архиве. Исходную переписку читать не нужно.

**Разверни архив и убедись, что база рабочая:**

```
tar -xzf PAP2_S2_HANDOFF_SOURCE.tar.gz
cd handoff-src
pip install -r requirements-dev.txt
bash RUN_TESTS.sh
cd tools && python3 verify_inventory.py && python3 verify_overlaps.py && python3 verify_map.py
```

Ожидается `274 passed, 64 subtests passed`; verify_inventory `177/0`, verify_overlaps `10/0`, verify_map `214/0 VERIFIED_CLEAN`.

Дерево полное: тесты, проверка карты, запуск платформы, выкат и откат среза 1,
живой smoke. Порядок команд для каждого — в `ENVIRONMENT.md`. В архиве
инициализирован git — работай поверх него, каждое изменение отдельным
коммитом.

**Прими правила, они не обсуждаются:**

1. Не выкатывать. Блок 2+5 и MAP-028 уже зафиксированы в `s2-block25`;
   текущий шаг 4 не коммитить до независимого CLEAN. Стенд работает на срезе 1.
2. Fail-closed везде. Неизвестное, повреждённое, противоречивое состояние —
   это UNKNOWN, а не отсутствие.
3. Отказ до мутации, никогда после.
4. Всякая сохранённая метка времени, участвующая в решении, обязана быть
   разбираемой и с часовым поясом.
5. Фикстура, описывающая сохранённое состояние, обязана порождаться настоящим
   writer, а не собираться вручную.
6. Проверяй результат правки, а не факт её применения: замена может не
   встать молча.
7. Прежде чем предположить форму данных — открой writer и прочитай.
8. Не переходи к следующему блоку без подтверждения ревьюера.
9. Свою ошибку называй прямо, без смягчения.

**Прочитай раздел 5a до первой правки.** Это каталог тридцати с лишним уже
закрытых дефектов с причинами. Многие проверки выглядят избыточными, пока не
знаешь, что они ловили; упростив их, ты вернёшь баг, на который ушёл раунд
проверки.

**Пользователь ведёт второй чат — независимого ревьюера.** Он воспроизводит
твои SHA и прогоны и ищет дефекты негативными проходами. Пакет для него должен
быть самодостаточным: изменённые файлы, тесты, отчёт о прогоне, диффы
относительно основания, точные SHA.

**Текущая задача:** независимый review шага 4. Проверить совместимость
ProfileSession при re-authorization, единую `evaluate/select` policy, sticky
OFFLINE и release только CLOSED/EXPIRED, immutable target/manifest, exact
files-as-sent и supersede по logical identity с сохранением S2 lease gate.
Особенно искать writer-produced состояния, где отказ происходит после мутации
или policy и poll расходятся. После CLEAN — отдельный development-коммит поверх
`b7d39e3` на `s2-block25`, без rollout.

**Формат ответа пользователю:** прямо, по делу, без похвал и лишних оговорок.
Русский язык. Хэши изменённых файлов и результат прогона тестов в каждом
пакете.

---

## 10. Краткое резюме

PAP2 — система исполнения директив из чатов ИИ на трёх процессах: расширение
браузера, receiver, консоль. Идёт релиз 4.5.0 из семи срезов.

Срез 1 закрыт и работает на стенде. Срез 2 — первая атомарная граница, где
сервер и расширение выкатываются только вместе. Шаг 1 закоммичен как `8fc773c`,
блок 2+5 прошёл review 27 CLEAN и опубликован отдельной веткой как `d943c11`,
без rollout. Шаг 3 `MAP-028` уже зафиксирован как `b7d39e3`; текущая работа —
шаг 4 с окончательной server-side delivery selection/manifest/supersede semantics.

Блок вводит идентичность endpoint вместо номера вкладки, владение
управляющим агентом на аренде, единый барьер протокола на всех браузерных
маршрутах и режимы выката DRAIN/BARRIER с защёлкой, которая не даёт закрыть
границу поверх исхода, о котором никто не отчитался.

Главный урок работы, стоящий дороже кода: **пустая очередь не есть
доказательство завершённости, а отсутствие следа не есть отсутствие события**.
Тринадцать раундов проверки нашли одну и ту же ошибку в разных обличьях —
подстановка умолчания вместо отказа. Дважды её прятала фикстура, которую я
собрал руками, не заглянув в writer.
