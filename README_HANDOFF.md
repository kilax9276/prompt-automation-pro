# PAP2 4.5.0 — срез 2, шаг 4 / S4 delivery semantics: review-кандидат

Полный контекст — в `PAP2_S2_HANDOFF.md`.

## Проверка

    bash RUN_TESTS.sh

Ожидается `274 passed, 64 subtests passed`.

    python tools/verify_inventory.py
    python tools/verify_overlaps.py
    python tools/verify_map.py

Ожидается соответственно `177/0`, `10/0`, `214/0 VERIFIED_CLEAN`.

## Основание

Ветка `s2-block25` опубликована до commit
`b7d39e350cf47f7b3ef6d6a34f63990f839257db` (MAP-028), parent `d943c11`.
`main` не сдвинут; rollout отсутствует; pro2 продолжает работать на slice 1.

Текущий S4 candidate поверх MAP-028 **не закоммичен и не выкачен**.

## Текущая дельта

Обязанности:

- `MAP-018` — re-authorization через совместимую current ProfileSession без
  переписывания Run provenance;
- `MAP-034` — `EndpointRegistry.evaluate/select`, session-owned sticky policy,
  явная ambiguity;
- `MAP-035` — endpoint-resolved immutable delivery manifest,
  logicalDeliveryId/sideEffectKey, exact outgoing bytes/names/artifact provenance;
- `MAP-036` — supersede только предыдущей попытки той же logical delivery с
  сохранением S2 lease/single-flight safety.

`tests/test_slice4_delivery_semantics.py`: 23 PASS на кандидате. Тот же файл
обязан быть RED на точных байтах MAP-028 Review 2; evidence лежит в каталоге
текущего review-пакета.

Review 2 восстанавливает четыре прежние recovery-provenance regression-оси,
которые Review 1 ошибочно заменил/удалил при адаптации tab-wide supersede к
logical-delivery supersede. Продуктовый S4-код при этом не меняется: terminal
состояние для этих проверок теперь создаётся настоящим writer-путём через новую
попытку с тем же `logicalDeliveryId`/`sideEffectKey`. `test_slice2_review27.py`
снова удерживает malformed `pausedAt`, unknown `sendState` и unresolved
`SEND_REQUESTED`; `test_slice2_review26_audit.py` снова удерживает правило, что
ретированный недоставленный replay не закрывает source.

`ACC-S4-001…008 = PASS`. Это development/code evidence, не live/browser
приёмка всего slice 2: rollout по-прежнему отсутствует.

## Что не входит

`MAP-049`/`MAP-050` (окончательная binding/resolver schema cleanup), extension
steps 6/7 и rollout integration step 8 не выполняются в этом review.
Evidence-каталог review не является commit-worthy product delta.
